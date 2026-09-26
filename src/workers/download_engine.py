"""
workers/download_engine.py

Função top-level executada em processo filho via multiprocessing. Encapsula
toda a orquestração de download (Swarm / Single / HLS) sem depender de PyQt.

Comunicação com o processo pai:
- msg_send (Pipe end): mensagens de progresso/log/finalização
- cmd_recv (Pipe end): comandos de pause/resume vindos do parent
- counter (multiprocessing.Value): bytes baixados, lido pelo SpeedCalculator

Cancelamento é feito via terminate() do parent — não há graceful shutdown
nem stop_event externo. Tudo morre quando o processo é encerrado.
"""

import os
import sys
import threading
import time
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, as_completed, wait
from typing import Any
from urllib.parse import urlparse


# ---------------------------------------------------------------------------
# Adapter expondo a API esperada pelos workers (add/read) sobre mp.Value.
# Os workers existentes em swarm/single/hls esperam um objeto com .add(n).
# ---------------------------------------------------------------------------

class _CounterProxy:
    __slots__ = ("_value",)

    def __init__(self, mp_value):
        self._value = mp_value

    def add(self, delta: int) -> None:
        with self._value.get_lock():
            self._value.value += delta

    def read(self) -> int:
        with self._value.get_lock():
            return self._value.value


# ---------------------------------------------------------------------------
# Registry de Responses ativas — permite ao listener de pause fechar todos
# os sockets em uso, fazendo `iter_content()` em andamento abortar.
# ---------------------------------------------------------------------------

class _ResponseTracker:
    def __init__(self):
        self._lock = threading.Lock()
        self._set: set = set()

    def add(self, r) -> None:
        with self._lock:
            self._set.add(r)

    def remove(self, r) -> None:
        with self._lock:
            self._set.discard(r)

    def close_all(self) -> None:
        with self._lock:
            active = list(self._set)
            self._set.clear()
        for r in active:
            try:
                r.close()
            except Exception:
                pass


# ---------------------------------------------------------------------------
# Adapter para emitir mensagens via Pipe sem causar exceções no caller
# ---------------------------------------------------------------------------

class _MessageEmitter:
    def __init__(self, pipe):
        self._pipe = pipe
        self._lock = threading.Lock()
        self._last_map_emit = 0.0

    def send(self, *parts) -> None:
        try:
            with self._lock:
                self._pipe.send(parts)
        except (BrokenPipeError, EOFError, OSError):
            pass

    def log(self, message: str, level: str = "info") -> None:
        self.send("log", message, level)

    def total_size(self, total: Any) -> None:
        self.send("total_size", total)

    def segment_done(self) -> None:
        self.send("segment_done")

    def segments_map(self, total: int, map_data: Any, force: bool = False) -> None:
        # `force`: o último desenho não pode cair no limite de 0,2 s, senão a
        # barra fica com pedaços "em andamento" depois do fim.
        now = time.time()
        if not force and now - self._last_map_emit < 0.2:
            return
        self._last_map_emit = now
        self.send("segments_map", total, map_data)

    def finished(self, success: bool, message: str) -> None:
        self.send("finished", success, message)


# ---------------------------------------------------------------------------
# Listener de comandos do parent (pause/resume)
# ---------------------------------------------------------------------------

def _start_command_listener(
    cmd_recv,
    pause_event: threading.Event,
    response_tracker: "_ResponseTracker",
) -> threading.Thread:
    def loop():
        while True:
            try:
                if cmd_recv.poll(0.2):
                    cmd = cmd_recv.recv()
                else:
                    continue
            except (EOFError, BrokenPipeError, OSError):
                return
            if cmd == "pause":
                pause_event.set()
                # Fecha as Responses ativas para abortar `iter_content` em
                # andamento — sem isso a pause só efetiva entre chunks, o que
                # com chunk de 6MB pode levar dezenas de segundos.
                response_tracker.close_all()
            elif cmd == "resume":
                pause_event.clear()

    t = threading.Thread(target=loop, name="EngineCmdListener", daemon=True)
    t.start()
    return t


# ---------------------------------------------------------------------------
# Entry point — chamado por multiprocessing.Process(target=engine_main, ...)
# ---------------------------------------------------------------------------

def engine_main(config: dict, counter, msg_send, cmd_recv) -> None:
    """
    Executa o download completo no processo filho.

    Parâmetros:
        config   : dict com chaves url, output_path, threads, proxy, auth,
                   custom_headers, x3d_opt, auto_detect_quality,
                   connect_timeout, expected_checksum
        counter  : multiprocessing.Value('q', 0) compartilhado
        msg_send : Pipe end para enviar mensagens ao parent
        cmd_recv : Pipe end para receber comandos do parent
    """
    from core.constants import CONNECT_TIMEOUT, PARTIAL_SUFFIX
    from core.file_utils import make_unique_path, resolve_output_path
    from core.http_session import (
        apply_streaming_compat_headers,
        create_session,
        get_server_info,
    )
    from core.quality_detector import (
        find_best_quality_url,
        get_optimal_chunk_size,
        get_optimal_thread_count,
        is_dash_url,
        is_hls_url,
        is_video_url,
    )
    from workers.single_worker import single_stream_download

    emitter = _MessageEmitter(msg_send)
    counter_proxy = _CounterProxy(counter)
    stop_event = threading.Event()
    pause_event = threading.Event()
    response_tracker = _ResponseTracker()

    # Reporta o _MEIPASS para o parent fazer cleanup do bundle PyInstaller
    # após terminate() — o bootloader não roda seu próprio cleanup quando o
    # processo é morto à força.
    if getattr(sys, "frozen", False):
        meipass = getattr(sys, "_MEIPASS", None)
        if meipass:
            emitter.send("meipass", meipass)

    _start_command_listener(cmd_recv, pause_event, response_tracker)

    success = False
    final_path = ""
    expected_total_size = None
    session = None
    # (arquivo em andamento, nome final, rótulo) de cada arquivo produzido.
    outputs: list = []

    try:
        url = config["url"]
        if is_dash_url(url):
            _log_dash_unsupported(emitter)
            return

        emitter.log("Preparando sessão HTTP...", "info")
        session = create_session(
            proxy=config.get("proxy"),
            auth=config.get("auth"),
            custom_headers=config.get("custom_headers"),
        )
        connect_timeout = config.get("connect_timeout") or CONNECT_TIMEOUT

        apply_streaming_compat_headers(session, url)
        if (
            config.get("auto_detect_quality", True)
            and is_video_url(url)
            and not is_hls_url(url)
        ):
            url = find_best_quality_url(session, url, stop_event, emitter.log)
            apply_streaming_compat_headers(session, url)

        emitter.log("Resolvendo caminho de destino...", "info")
        resolved = resolve_output_path(config.get("output_path") or "", url)
        os.makedirs(os.path.dirname(os.path.abspath(resolved)), exist_ok=True)
        if config.get("is_resume"):
            # Retomada de pause: mantém o caminho exato e usa os arquivos
            # de estado/parciais que já estão em disco.
            final_path = resolved
            emitter.log(
                f"Retomando download anterior em '{os.path.basename(final_path)}'.",
                "info",
            )
        else:
            # Evita sobrescrever arquivo existente — adiciona sufixo (1), (2)...
            unique = make_unique_path(resolved)
            if unique != resolved:
                emitter.log(
                    f"Arquivo já existe; salvando como '{os.path.basename(unique)}'.",
                    "info",
                )
            final_path = unique
        emitter.send("resolved_path", final_path)
        emitter.log(f"Destino: {final_path}", "info")

        is_playlist = is_hls_url(url)
        if not is_playlist:
            emitter.log("Consultando capacidades do servidor...", "info")
            accept_ranges, total_size, _enc, content_type = get_server_info(
                session, url, connect_timeout
            )
            if "dash+xml" in content_type:
                _log_dash_unsupported(emitter)
                return
            # Playlist servida em link sem ".m3u8"/"master"/"playlist": o tipo
            # do servidor ou o começo do arquivo denunciam.
            if "mpegurl" in content_type or _looks_like_hls_playlist(
                session, url, total_size, content_type, connect_timeout
            ):
                emitter.log("O link é uma playlist .m3u8; baixando as partes do vídeo.", "info")
                is_playlist = True

        if is_playlist:
            success, outputs = _run_hls(
                url, final_path, session, config, counter_proxy,
                stop_event, pause_event, emitter, response_tracker,
                connect_timeout,
            )
        else:
            x3d_opt = config.get("x3d_opt", False)
            work_path = final_path + PARTIAL_SUFFIX
            outputs = [(work_path, final_path, "")]
            expected_total_size = total_size
            emitter.send("work_path", work_path)
            emitter.log(
                f"Servidor: ranges={'sim' if accept_ranges == 'bytes' else 'não'}, "
                f"tamanho={_fmt_size(total_size)}",
                "info",
            )

            small = total_size is not None and total_size < 1024 * 1024
            if small or accept_ranges != "bytes" or total_size is None:
                if not small and accept_ranges != "bytes":
                    emitter.log(
                        "Servidor não suporta download paralelo — modo single stream.",
                        "warning",
                    )
                chunk_size = get_optimal_chunk_size(total_size or 0, x3d_opt)
                if total_size:
                    emitter.total_size(total_size)
                success = single_stream_download(
                    url=url,
                    output_path=work_path,
                    session=session,
                    chunk_size=chunk_size,
                    stop_event=stop_event,
                    pause_event=pause_event,
                    speed_counter=counter_proxy,
                    log_fn=emitter.log,
                    total_size_fn=emitter.total_size,
                    response_tracker=response_tracker,
                    connect_timeout=connect_timeout,
                )
            else:
                chunk_size = get_optimal_chunk_size(total_size, x3d_opt)
                num_threads = get_optimal_thread_count(
                    total_size, config.get("threads", 8)
                )
                emitter.log(
                    f"Modo Swarm: {num_threads} threads, "
                    f"arquivo {_fmt_size(total_size)}",
                    "info",
                )
                success = _run_swarm(
                    url, work_path, session, total_size, chunk_size,
                    num_threads, counter_proxy, stop_event, pause_event,
                    emitter, response_tracker, connect_timeout,
                )

        if success and expected_total_size is not None:
            success = _verify_final_size(
                outputs[0][0], expected_total_size, emitter.log
            )

        if success and config.get("expected_checksum"):
            success = _verify_checksum(
                outputs[0][0], config["expected_checksum"],
                stop_event, emitter.log,
            )

        if success:
            _finalize_outputs(outputs, emitter)

    except Exception as e:
        emitter.log(f"Erro inesperado: {e}", "error")
        success = False
    finally:
        if session is not None:
            try:
                session.close()
            except Exception:
                pass

        msg = "Download concluído!" if success else "Falha no download."
        emitter.finished(success, msg)
        try:
            msg_send.close()
        except Exception:
            pass
        try:
            cmd_recv.close()
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Sub-fluxos
# ---------------------------------------------------------------------------

def _run_swarm(
    url, output_path, session, total_size, chunk_size, num_threads,
    counter_proxy, stop_event, pause_event, emitter, response_tracker,
    connect_timeout,
) -> bool:
    import hashlib
    from core.constants import (
        MIN_SWARM_THREADS,
        PART_RECOVERY_LIMIT,
        SWARM_STALL_TIMEOUT,
        TEMP_DIR,
        THROTTLE_COOLDOWN,
    )
    from core.file_utils import cleanup_temp_dir
    from core.segment_manager import DynamicSegmentManager
    from workers.swarm_worker import swarm_segment_worker

    # part_dir determinístico por output_path — pause→resume reaproveita
    # exatamente o mesmo state.json mesmo entre processos diferentes.
    out_hash = hashlib.md5(output_path.encode("utf-8")).hexdigest()[:12]
    part_dir = os.path.join(TEMP_DIR, f"swarm_{out_hash}")
    os.makedirs(part_dir, exist_ok=True)
    emitter.send("part_dir", part_dir)

    state_file = os.path.join(part_dir, "state.json")
    resume_file_ok = False
    try:
        if os.path.isfile(output_path) and os.path.getsize(output_path) == total_size:
            resume_file_ok = True
            emitter.log("Arquivo pré-alocado encontrado — pulando alocação.", "info")
    except OSError:
        pass

    manager = None
    if resume_file_ok:
        manager = DynamicSegmentManager.load_from_file(state_file, total_size)
        if manager:
            emitter.log("Estado anterior encontrado — retomando download...", "info")
    elif os.path.exists(state_file):
        emitter.log(
            "Estado anterior ignorado: arquivo parcial ausente ou com tamanho incompatível.",
            "warning",
        )

    if not resume_file_ok:
        try:
            emitter.log(f"Pré-alocando {_fmt_size(total_size)} no disco...", "info")
            with open(output_path, "wb") as f:
                f.seek(total_size - 1)
                f.write(b"\x00")
            emitter.log("Pré-alocação concluída.", "info")
        except OSError as e:
            emitter.log(f"Falha ao pré-alocar arquivo: {e}", "error")
            return False

    if manager is None:
        manager = DynamicSegmentManager(total_size)
        manager.save_to_file(state_file)

    emitter.total_size(total_size)
    emitter.log(f"Disparando {num_threads} workers paralelos...", "info")
    file_lock = threading.Lock()
    hard_failed = 0
    last_state_save = 0.0

    # Paralelismo adaptativo: começa em num_threads (rápido para servidores
    # normais) e cai pela metade sempre que o servidor recusa conexões em massa
    # (ex.: googlevideo devolvendo 401). Assim o download se ajusta ao limite do
    # host em vez de martelar e travar.
    effective_threads = num_threads
    throttle_until = 0.0           # enquanto now < isto, não submete trabalho novo
    refusals_since_backoff = 0     # recusas acumuladas desde o último recuo

    def persist_state(force: bool = False) -> None:
        nonlocal last_state_save
        now = time.time()
        if force or now - last_state_save >= 1.0:
            manager.save_to_file(state_file)
            last_state_save = now

    def submit_available(executor, inflight: dict) -> int:
        submitted = 0
        while len(inflight) < effective_threads and not stop_event.is_set():
            seg = manager.get_work()
            if seg is None:
                break
            future = executor.submit(
                swarm_segment_worker,
                url, seg, file_lock, output_path, session,
                chunk_size, stop_event, pause_event,
                counter_proxy, emitter.log,
                response_tracker, connect_timeout,
            )
            inflight[future] = seg
            submitted += 1
        if submitted:
            emitter.segments_map(total_size, manager.get_map_data())
        return submitted

    stalled = False
    last_bytes = 0
    last_progress_time = time.time()

    try:
        with ThreadPoolExecutor(max_workers=num_threads, thread_name_prefix="Swarm") as executor:
            inflight: dict = {}
            submit_available(executor, inflight)
            persist_state(force=True)

            while not stop_event.is_set() and not manager.is_complete():
                now = time.time()

                # Guarda de estagnação: medimos PROGRESSO POR BYTES, não por
                # segmento concluído (em paralelismo baixo um segmento pode levar
                # mais de 60s e não é estagnação). Se nenhum byte novo chega em
                # SWARM_STALL_TIMEOUT, o link provavelmente expirou — aborta limpo.
                cur_bytes = counter_proxy.read()
                if cur_bytes > last_bytes:
                    last_bytes = cur_bytes
                    last_progress_time = now
                elif now - last_progress_time > SWARM_STALL_TIMEOUT:
                    stalled = True
                    break

                # Fora do cooldown, mantém o pool cheio até o limite efetivo.
                if now >= throttle_until:
                    submit_available(executor, inflight)

                if not inflight:
                    if now < throttle_until:
                        # Em cooldown e nada em voo: espera a pausa terminar.
                        if stop_event.wait(min(throttle_until - now, 0.25)):
                            break
                        continue
                    # Sem trabalho em voo nem disponível => acabou.
                    break

                done, _pending = wait(
                    tuple(inflight.keys()),
                    timeout=0.25,
                    return_when=FIRST_COMPLETED,
                )
                if not done:
                    persist_state()
                    emitter.segments_map(total_size, manager.get_map_data())
                    continue

                for future in done:
                    seg = inflight.pop(future, None)
                    if seg is None:
                        continue

                    ok = False
                    err = None
                    try:
                        ok = bool(future.result())
                    except Exception as e:
                        err = e

                    reason = seg.pop("fail_reason", None)
                    seg.pop("fail_status", None)

                    if ok or seg.get("current", seg["start"]) > seg["end"]:
                        seg["status"] = "done"
                        seg.pop("failures", None)
                    elif reason == "refusal":
                        # Servidor recusou (não é culpa do segmento). Volta para a
                        # fila SEM gastar orçamento de repescagem — fim do "martelar
                        # 24×". Só contamos para decidir se reduzimos o paralelismo;
                        # recusas durante o cooldown são da rajada antiga e ignoradas.
                        seg["status"] = "free"
                        if time.time() >= throttle_until:
                            refusals_since_backoff += 1
                    else:
                        failures = int(seg.get("failures", 0)) + 1
                        seg["failures"] = failures
                        if failures <= PART_RECOVERY_LIMIT:
                            seg["status"] = "free"
                            detail = f": {err}" if err else ""
                            emitter.log(
                                f"Repescando segmento ({failures}/{PART_RECOVERY_LIMIT}){detail}",
                                "warning",
                            )
                        else:
                            if seg.get("status") != "failed":
                                hard_failed += 1
                            seg["status"] = "failed"
                            detail = f": {err}" if err else ""
                            emitter.log(
                                f"Segmento abandonado após repescagens{detail}",
                                "error",
                            )

                    persist_state(force=True)
                    emitter.segments_map(total_size, manager.get_map_data())

                # Recuo de paralelismo se o servidor recusa em massa. Gatilho baixo
                # para reagir cedo, mas > 1 para não recuar por um azar isolado. Só
                # recua fora do cooldown — o recuo anterior ainda não foi "testado".
                if (
                    refusals_since_backoff >= max(2, effective_threads // 8)
                    and time.time() >= throttle_until
                ):
                    if effective_threads > MIN_SWARM_THREADS:
                        effective_threads = max(MIN_SWARM_THREADS, effective_threads // 2)
                        emitter.log(
                            f"Servidor recusando conexões (HTTP 401/403/429). "
                            f"Reduzindo paralelismo para {effective_threads} conexões e "
                            f"aguardando {THROTTLE_COOLDOWN:.0f}s...",
                            "warning",
                        )
                    else:
                        emitter.log(
                            f"Servidor ainda recusa no mínimo de {MIN_SWARM_THREADS} "
                            f"conexões; aguardando {THROTTLE_COOLDOWN:.0f}s...",
                            "warning",
                        )
                    throttle_until = time.time() + THROTTLE_COOLDOWN
                    refusals_since_backoff = 0

                if time.time() >= throttle_until:
                    submit_available(executor, inflight)

            if stop_event.is_set():
                executor.shutdown(wait=False, cancel_futures=True)

    except Exception as e:
        emitter.log(f"Erro no Swarm: {e}", "error")
        manager.save_to_file(state_file)
        return False

    emitter.segments_map(total_size, manager.get_map_data(), force=True)

    if stop_event.is_set():
        return False

    if stalled:
        manager.save_to_file(state_file)
        emitter.log(
            "Sem progresso por tempo demais — o servidor recusou as conexões mesmo "
            "no paralelismo mínimo. O link provavelmente expirou; gere um novo e "
            "tente novamente.",
            "error",
        )
        return False

    if hard_failed or not manager.is_complete():
        manager.save_to_file(state_file)
        emitter.log(
            "Download Swarm incompleto. O arquivo final não será marcado como concluído.",
            "error",
        )
        return False

    cleanup_temp_dir(part_dir)
    return True


def _run_hls(
    url, output_path, session, config, counter_proxy,
    stop_event, pause_event, emitter, response_tracker, connect_timeout,
) -> tuple[bool, list]:
    """
    Executa download HLS: resolve a master playlist, baixa os segmentos em
    paralelo (AES-128 descriptografado em tempo real) e concatena cada faixa.

    Retorna (sucesso, [(arquivo em andamento, nome final, rótulo), ...]).
    A primeira faixa é o vídeo; a segunda, se existir, é o áudio que a
    playlist serve separado.
    """
    import hashlib
    import shutil
    from core.constants import PARTIAL_SUFFIX, TEMP_DIR

    try:
        import m3u8
    except ImportError:
        emitter.log("Módulo m3u8 não instalado. Execute: pip install m3u8", "error")
        return False, []

    playlist = _load_playlist(m3u8, session, url, connect_timeout, emitter)
    if playlist is None:
        return False, []

    audio_url = None
    if playlist.is_variant:
        emitter.log(
            f"Master Playlist com {len(playlist.playlists)} resoluções detectada.",
            "info",
        )
        valid = [p for p in playlist.playlists if p.stream_info and p.stream_info.bandwidth]
        if not valid:
            emitter.log("Nenhuma stream válida encontrada.", "error")
            return False, []
        best = max(valid, key=lambda p: p.stream_info.bandwidth)
        res = getattr(best.stream_info, "resolution", None)
        emitter.log(f"Resolução selecionada: {res or 'Máxima'}", "success")
        audio_url = _separate_audio_uri(best)
        playlist = _load_playlist(m3u8, session, best.absolute_uri, connect_timeout, emitter)
        if playlist is None:
            return False, []
        if playlist.is_variant:
            emitter.log("A resolução escolhida aponta para outra master playlist; formato não suportado.", "error")
            return False, []

    base = os.path.splitext(output_path)[0]
    tracks = [("video", playlist, base)]
    if audio_url:
        audio_playlist = _load_playlist(m3u8, session, audio_url, connect_timeout, emitter)
        if audio_playlist is None:
            return False, []
        emitter.log(
            "O áudio deste vídeo vem em faixa separada: ele será salvo em um "
            "segundo arquivo ao lado do vídeo (juntar os dois exige um programa "
            "como o ffmpeg).",
            "warning",
        )
        tracks.append(("audio", audio_playlist, f"{base} (áudio)"))

    plans = []
    total_segments = 0
    already_done = 0
    for label, pl, name_base in tracks:
        if not pl.segments:
            emitter.log("Nenhum segmento encontrado na playlist.", "error")
            return False, []
        key = f"{output_path}|{label}".encode("utf-8")
        part_dir = os.path.join(TEMP_DIR, f"hls_{hashlib.md5(key).hexdigest()[:12]}")
        os.makedirs(part_dir, exist_ok=True)
        emitter.send("part_dir", part_dir)
        total_segments += len(pl.segments)
        already_done += sum(
            1 for i in range(len(pl.segments)) if _hls_segment_ready(part_dir, i)
        )
        plans.append((label, pl, name_base, part_dir))

    # Segmentos já em disco (retomada) entram no progresso como feitos, para
    # a barra não contá-los de novo.
    emitter.total_size(
        {"mode": "segments", "total": total_segments, "done": already_done}
    )

    prepared = []
    for label, pl, name_base, part_dir in plans:
        track = _download_hls_track(
            label, pl, name_base, part_dir, session, config, counter_proxy,
            stop_event, pause_event, emitter, response_tracker, connect_timeout,
        )
        if track is None:
            return False, []
        prepared.append(track)

    outputs = []
    for (label, pl, name_base, part_dir), (final_path, inits) in zip(plans, prepared):
        partial = final_path + PARTIAL_SUFFIX
        emitter.send("work_path", partial)
        if not _concat_hls_track(pl.segments, part_dir, inits, partial, emitter):
            return False, []
        outputs.append((partial, final_path, label))

    time.sleep(0.3)
    for _label, _pl, _name_base, part_dir in plans:
        shutil.rmtree(part_dir, ignore_errors=True)

    return True, outputs


def _load_playlist(m3u8, session, url, connect_timeout, emitter):
    emitter.log("Carregando playlist M3U8...", "info")
    try:
        r = session.get(url, timeout=(connect_timeout, 30))
        r.raise_for_status()
        return m3u8.loads(r.text, uri=url)
    except Exception as e:
        emitter.log(f"Erro ao carregar playlist: {e}", "error")
        return None


def _separate_audio_uri(variant):
    """URI da faixa de áudio separada da variante escolhida, ou None se o áudio vem junto."""
    medias = [
        m for m in (getattr(variant, "media", None) or [])
        if (getattr(m, "type", "") or "").upper() == "AUDIO" and getattr(m, "uri", None)
    ]
    if not medias:
        return None
    chosen = next(
        (m for m in medias if (getattr(m, "default", "") or "").upper() == "YES"),
        medias[0],
    )
    return chosen.absolute_uri


def _hls_segment_ready(part_dir, index) -> bool:
    path = os.path.join(part_dir, f"segment_{index}.ts")
    try:
        return os.path.getsize(path) > 0
    except OSError:
        return False


def _init_section_key(segment):
    init = getattr(segment, "init_section", None)
    if init is None or not getattr(init, "uri", None):
        return None
    return (init.absolute_uri, getattr(init, "byterange", None) or "")


def _download_hls_track(
    label, playlist, name_base, part_dir, session, config, counter_proxy,
    stop_event, pause_event, emitter, response_tracker, connect_timeout,
):
    """
    Baixa todos os segmentos (e seções de inicialização) de uma faixa.
    Retorna (nome_final, {chave_init: caminho}) ou None em falha.
    """
    from core.constants import CHUNK_SIZE, PART_RECOVERY_LIMIT

    segments = playlist.segments
    track_name = "áudio" if label == "audio" else "vídeo"
    emitter.log(
        f"Faixa de {track_name} com {len(segments)} segmentos. Preparando download...",
        "info",
    )

    base_sequence = int(getattr(playlist, "media_sequence", 0) or 0)
    # Chave por segmento: a playlist pode trocar de chave no meio (EXT-X-KEY
    # repetido) ou alternar trechos cifrados e abertos.
    seg_crypto = _hls_segment_crypto(segments, base_sequence, session, emitter)
    if seg_crypto is None:
        return None
    seg_ranges = _hls_segment_ranges(segments)
    if seg_ranges is None:
        emitter.log(f"Trecho de segmento inválido na playlist da faixa de {track_name}.", "error")
        return None

    # fMP4: sem a seção de inicialização (EXT-X-MAP) os segmentos não abrem.
    inits: dict = {}
    for seg in segments:
        key = _init_section_key(seg)
        if key is None or key in inits:
            continue
        init_path = os.path.join(part_dir, f"init_{len(inits)}.mp4")
        if not _fetch_init_section(session, key, init_path, connect_timeout, stop_event):
            emitter.log(f"Falha ao baixar a seção de inicialização da faixa de {track_name}.", "error")
            return None
        inits[key] = init_path

    if inits:
        ext = ".m4a" if label == "audio" else ".mp4"
    elif label == "audio" and urlparse(segments[0].absolute_uri).path.lower().endswith(".aac"):
        ext = ".aac"
    else:
        ext = ".ts"
    final_path = name_base + ext

    chunk_size = min(CHUNK_SIZE, 512 * 1024)
    max_workers = min(config.get("threads", 8), 256)

    parts = [
        (i, seg.absolute_uri, seg_ranges[i], seg_crypto[i])
        for i, seg in enumerate(segments)
    ]
    pending = [p for p in parts if not _hls_segment_ready(part_dir, p[0])]
    failed = set()
    if pending:
        failed = _hls_download_parts(
            pending, part_dir, session, chunk_size, max_workers,
            counter_proxy, stop_event, pause_event, emitter, response_tracker,
            connect_timeout,
        )

    if failed and not stop_event.is_set():
        for recovery_round in range(1, PART_RECOVERY_LIMIT + 1):
            emitter.log(
                f"Repescagem HLS {recovery_round}/{PART_RECOVERY_LIMIT}: "
                f"{len(failed)} segmentos pendentes...",
                "warning",
            )
            retry_parts = [p for p in parts if p[0] in failed]
            failed = _hls_download_parts(
                retry_parts, part_dir, session, chunk_size,
                max(1, min(len(retry_parts), 32)),
                counter_proxy, stop_event, pause_event, emitter, response_tracker,
                connect_timeout,
            )
            if not failed:
                emitter.log("Repescagem concluída com sucesso!", "success")
                break
            if stop_event.wait(min(1.5 ** recovery_round, 10)):
                break

        if failed and not stop_event.is_set():
            emitter.log(
                f"{len(failed)} segmentos falharam permanentemente.",
                "error",
            )
            return None

    if stop_event.is_set():
        emitter.log("Download HLS cancelado.", "warning")
        return None

    missing = [p[0] for p in parts if not _hls_segment_ready(part_dir, p[0])]
    if missing:
        preview = ", ".join(str(i) for i in missing[:10])
        if len(missing) > 10:
            preview += ", ..."
        emitter.log(f"Segmentos ausentes após o download: {preview}", "error")
        return None

    return final_path, inits


def _concat_hls_track(segments, part_dir, inits, out_path, emitter) -> bool:
    import shutil

    emitter.log("Unificando segmentos...", "info")
    try:
        with open(out_path, "wb") as out:
            current_init = None
            for i, seg in enumerate(segments):
                key = _init_section_key(seg)
                # A seção de inicialização vai antes do primeiro segmento que a
                # usa e de novo sempre que a playlist troca de seção.
                if key is not None and key != current_init:
                    with open(inits[key], "rb") as f:
                        shutil.copyfileobj(f, out, length=64 * 1024 * 1024)
                    current_init = key
                seg_path = os.path.join(part_dir, f"segment_{i}.ts")
                if not os.path.exists(seg_path):
                    emitter.log(f"Segmento {i} ausente: {seg_path}", "error")
                    return False
                with open(seg_path, "rb") as pf:
                    shutil.copyfileobj(pf, out, length=64 * 1024 * 1024)
        emitter.log("Unificação concluída!", "success")
        return True
    except OSError as e:
        emitter.log(f"Erro ao unificar segmentos: {e}", "error")
        return False


def _fetch_init_section(session, key, path, connect_timeout, stop_event) -> bool:
    from core.constants import READ_TIMEOUT, RETRY_LIMIT

    uri, byterange = key
    headers = {"Accept-Encoding": "identity"}
    if byterange:
        length_raw, _, offset_raw = byterange.partition("@")
        try:
            length = int(length_raw)
            offset = int(offset_raw) if offset_raw else 0
        except ValueError:
            return False
        headers["Range"] = f"bytes={offset}-{offset + length - 1}"

    for attempt in range(RETRY_LIMIT):
        if stop_event.is_set():
            return False
        try:
            r = session.get(uri, headers=headers, timeout=(connect_timeout, READ_TIMEOUT))
            r.raise_for_status()
            if r.status_code not in (200, 206) or not r.content:
                raise IOError(f"HTTP {r.status_code} sem conteúdo")
            data = r.content
            if byterange and r.status_code == 200:
                # Servidor ignorou o Range: recorta o trecho pedido.
                data = data[offset:offset + length]
            tmp = f"{path}.part"
            with open(tmp, "wb") as f:
                f.write(data)
            os.replace(tmp, path)
            return True
        except Exception:
            if stop_event.wait(1):
                return False
    return False


def _hls_segment_crypto(segments, base_sequence, session, emitter):
    """
    Lista, por segmento, (chave, IV) para AES-128 ou None se o segmento é
    aberto. Retorna None (com log) se a proteção não é suportada ou uma
    chave não pôde ser obtida.
    """
    keys: dict = {}
    result = []
    for index, seg in enumerate(segments):
        key = getattr(seg, "key", None)
        method = ((getattr(key, "method", None) or "NONE") if key else "NONE").upper()
        if method == "NONE":
            result.append(None)
            continue
        keyformat = (getattr(key, "keyformat", None) or "identity").lower()
        if method != "AES-128" or keyformat != "identity":
            # SAMPLE-AES e DRM (FairPlay/Widevine) cifram por dentro do vídeo;
            # "decifrar" como AES-128 geraria um arquivo ilegível.
            emitter.log(
                f"Este vídeo usa proteção {method} ({keyformat}), que o Downloader "
                "não consegue abrir. O download foi interrompido.",
                "error",
            )
            return None
        uri = key.absolute_uri
        if uri not in keys:
            key_bytes = _fetch_aes_key(session, uri, emitter, quiet=bool(keys))
            if key_bytes is None:
                return None
            keys[uri] = key_bytes
        result.append((keys[uri], _get_iv(key, base_sequence, index)))
    return result


def _hls_segment_ranges(segments):
    """
    Lista, por segmento, o header Range (EXT-X-BYTERANGE) ou None.
    Sem offset explícito, o trecho começa onde terminou o anterior do mesmo
    arquivo. Retorna None se algum trecho for inválido.
    """
    next_offset: dict = {}
    result = []
    for seg in segments:
        byterange = getattr(seg, "byterange", None)
        if not byterange:
            result.append(None)
            continue
        uri = seg.absolute_uri
        length_raw, _, offset_raw = str(byterange).partition("@")
        try:
            length = int(length_raw)
            start = int(offset_raw) if offset_raw else next_offset.get(uri, 0)
        except ValueError:
            return None
        if length <= 0:
            return None
        result.append(f"bytes={start}-{start + length - 1}")
        next_offset[uri] = start + length
    return result


def _hls_download_parts(
    parts, part_dir, session, chunk_size, max_workers,
    counter_proxy, stop_event, pause_event, emitter, response_tracker,
    connect_timeout,
):
    failed: set = set()
    completed = 0
    last_log_pct = -1

    with ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="HLS") as executor:
        futures = {
            executor.submit(
                _hls_download_segment,
                url,
                os.path.join(part_dir, f"segment_{idx}.ts"),
                session, chunk_size, range_header, crypto,
                counter_proxy, stop_event, pause_event,
                response_tracker, connect_timeout,
            ): idx
            for idx, url, range_header, crypto in parts
        }

        for future in as_completed(futures):
            if stop_event.is_set():
                executor.shutdown(wait=False, cancel_futures=True)
                break
            idx = futures[future]
            completed += 1
            try:
                if future.result():
                    emitter.segment_done()
                else:
                    failed.add(idx)
            except Exception:
                failed.add(idx)

            pct = int((completed / len(parts)) * 100) if parts else 0
            if pct >= last_log_pct + 10 or completed == 1:
                emitter.log(
                    f"Segmentos: {completed - len(failed)}/{len(parts)} ({pct}%)",
                    "info",
                )
                last_log_pct = pct

    return failed


def _hls_download_segment(
    url, filepath, session, chunk_size, range_header, crypto,
    counter_proxy, stop_event, pause_event, response_tracker,
    connect_timeout,
) -> bool:
    """
    Baixa um segmento para `filepath`. `range_header` recorta o segmento de
    um arquivo maior (EXT-X-BYTERANGE); `crypto` é (chave, IV) para AES-128.
    """
    from core.constants import READ_TIMEOUT, RETRY_LIMIT

    headers = {"Accept-Encoding": "identity"}
    if range_header:
        headers["Range"] = range_header

    if os.path.exists(filepath):
        try:
            complete_size = os.path.getsize(filepath)
        except OSError:
            complete_size = 0
        if complete_size > 0:
            return True

    tmp_path = f"{filepath}.part"
    try:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
    except OSError:
        pass

    attempt = 0
    while attempt < RETRY_LIMIT and not stop_event.is_set():
        while pause_event.is_set() and not stop_event.is_set():
            time.sleep(0.05)

        try:
            encrypted_buf = bytearray() if crypto is not None else None
            expected_len = None
            received = 0

            with session.get(
                url,
                headers=headers,
                stream=True,
                timeout=(connect_timeout, READ_TIMEOUT),
            ) as r:
                if response_tracker is not None:
                    response_tracker.add(r)
                try:
                    r.raise_for_status()
                    if r.status_code not in (200, 206):
                        raise IOError(f"segmento HLS sem conteúdo (HTTP {r.status_code})")
                    if range_header and r.status_code != 206:
                        # Sem 206 o servidor mandaria o arquivo inteiro, não o trecho.
                        raise IOError("servidor ignorou o trecho do segmento (sem HTTP 206)")
                    raw_len = r.headers.get("Content-Length")
                    if raw_len:
                        try:
                            expected_len = int(raw_len)
                        except ValueError:
                            expected_len = None

                    if encrypted_buf is None:
                        with open(tmp_path, "wb") as f:
                            for chunk in r.iter_content(chunk_size):
                                if stop_event.is_set():
                                    try:
                                        os.remove(tmp_path)
                                    except OSError:
                                        pass
                                    return False
                                if not chunk:
                                    continue
                                f.write(chunk)
                                received += len(chunk)
                                counter_proxy.add(len(chunk))
                            f.flush()
                    else:
                        for chunk in r.iter_content(chunk_size):
                            if stop_event.is_set():
                                return False
                            if not chunk:
                                continue
                            encrypted_buf.extend(chunk)
                            received += len(chunk)
                            counter_proxy.add(len(chunk))
                finally:
                    if response_tracker is not None:
                        response_tracker.remove(r)

            if expected_len is not None and received != expected_len:
                raise IOError(
                    f"segmento HLS truncado: {received} bytes, esperado {expected_len}"
                )

            if encrypted_buf is not None:
                from Crypto.Cipher import AES  # type: ignore
                key_bytes, iv = crypto
                cipher = AES.new(key_bytes, AES.MODE_CBC, iv)
                data = cipher.decrypt(bytes(encrypted_buf))
                pad_len = data[-1] if data else 0
                if 0 < pad_len <= 16:
                    data = data[:-pad_len]
                with open(tmp_path, "wb") as f:
                    f.write(data)
                    f.flush()

            os.replace(tmp_path, filepath)

            return True

        except Exception:
            try:
                if os.path.exists(tmp_path):
                    os.remove(tmp_path)
            except OSError:
                pass
            if stop_event.is_set():
                return False
            # Se pause foi acionado, a exceção é do close externo da Response.
            # Espera o resume e tenta de novo sem queimar tentativa.
            if pause_event.is_set():
                while pause_event.is_set() and not stop_event.is_set():
                    time.sleep(0.05)
                if stop_event.is_set():
                    return False
                continue
            attempt += 1
            if attempt < RETRY_LIMIT:
                if stop_event.wait(1):
                    return False

    return False


def _fetch_aes_key(session, key_uri, emitter, quiet=False):
    """Baixa a chave AES-128 (16 bytes). `quiet` evita repetir o log a cada troca de chave."""
    try:
        import Crypto  # noqa: F401
    except ImportError:
        emitter.log(
            "pycryptodome não instalado. Execute: pip install pycryptodome",
            "error",
        )
        return None

    if not quiet:
        emitter.log("Criptografia AES-128 detectada. Buscando chave...", "warning")
    try:
        r = session.get(key_uri, timeout=10)
        r.raise_for_status()
        key = r.content
        if len(key) != 16:
            emitter.log(
                f"Chave AES inválida: {len(key)} bytes (esperado 16).",
                "error",
            )
            return None
        if not quiet:
            emitter.log("Chave de descriptografia obtida!", "success")
        return key
    except Exception as e:
        emitter.log(f"Erro ao obter chave AES: {e}", "error")
        return None


def _get_iv(key_info, base_sequence: int, index: int) -> bytes:
    if key_info and getattr(key_info, "iv", None):
        return bytes.fromhex(key_info.iv.replace("0x", "").replace("0X", ""))
    return (base_sequence + index).to_bytes(16, "big")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _looks_like_hls_playlist(session, url, total_size, content_type, connect_timeout) -> bool:
    """
    Lê o começo de arquivos pequenos de tipo genérico procurando "#EXTM3U".
    Vídeo/áudio declarado ou arquivo grande não é consultado (playlist tem KBs).
    """
    if content_type.startswith(("video/", "audio/")):
        return False
    if total_size is not None and total_size >= 1024 * 1024:
        return False
    try:
        with session.get(
            url, headers={"Range": "bytes=0-63"}, stream=True,
            timeout=(connect_timeout, 10),
        ) as r:
            if r.status_code not in (200, 206):
                return False
            head = r.raw.read(64, decode_content=True) or b""
    except Exception:
        return False
    return head.lstrip(b"\xef\xbb\xbf \t\r\n").startswith(b"#EXTM3U")


def _log_dash_unsupported(emitter) -> None:
    emitter.log(
        "Links DASH (.mpd) não são suportados: esse arquivo é só a lista das "
        "partes do vídeo, não o vídeo. Use um link .m3u8 ou .mp4 da mesma página.",
        "error",
    )


def _finalize_outputs(outputs, emitter) -> None:
    """Dá o nome final a cada arquivo verificado e informa o caminho real ao pai."""
    from core.file_utils import finalize_partial

    for index, (partial, final, label) in enumerate(outputs):
        saved = finalize_partial(partial, final)
        if saved != final:
            emitter.log(
                f"'{os.path.basename(final)}' passou a existir durante o download; "
                f"salvo como '{os.path.basename(saved)}'.",
                "warning",
            )
        if index == 0:
            emitter.send("resolved_path", saved)
        elif label == "audio":
            emitter.log(f"Áudio salvo separado em: {saved}", "warning")


def _verify_final_size(path, expected_size, log_fn) -> bool:
    if expected_size is None:
        return True
    if not path or not os.path.exists(path):
        log_fn("Arquivo final ausente após o download.", "error")
        return False
    try:
        actual = os.path.getsize(path)
    except OSError as e:
        log_fn(f"Não foi possível validar tamanho final: {e}", "error")
        return False
    if actual == expected_size:
        return True
    log_fn(
        f"Tamanho final inválido: esperado {_fmt_size(expected_size)}, obtido {_fmt_size(actual)}.",
        "error",
    )
    return False


def _verify_checksum(path, expected, stop_event, log_fn) -> bool:
    from core.file_utils import compute_sha256
    if not expected:
        return True
    if not path or not os.path.exists(path):
        log_fn("Checksum não verificado: arquivo final ausente.", "error")
        return False
    log_fn("Verificando checksum SHA256...", "info")
    digest = compute_sha256(path, stop_event, log_fn)
    if digest is None:
        log_fn("Verificação cancelada.", "warning")
        return False
    elif digest.lower() == expected.lower():
        log_fn("✓ Checksum válido!", "success")
        return True
    else:
        log_fn(
            f"✗ Checksum INVÁLIDO!\n  Esperado: {expected}\n  Obtido  : {digest}",
            "error",
        )
        return False


def _fmt_size(size) -> str:
    if size is None:
        return "desconhecido"
    if size < 1024:
        return f"{size} B"
    if size < 1024 ** 2:
        return f"{size / 1024:.1f} KB"
    if size < 1024 ** 3:
        return f"{size / (1024 ** 2):.1f} MB"
    return f"{size / (1024 ** 3):.2f} GB"
