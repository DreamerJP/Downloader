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

    def segments_map(self, total: int, map_data: Any) -> None:
        now = time.time()
        if now - self._last_map_emit < 0.2:
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

    try:
        emitter.log("Preparando sessão HTTP...", "info")
        session = create_session(
            proxy=config.get("proxy"),
            auth=config.get("auth"),
            custom_headers=config.get("custom_headers"),
        )

        url = config["url"]
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

        if is_hls_url(url):
            success, final_path = _run_hls(
                url, final_path, session, config, counter_proxy,
                stop_event, pause_event, emitter, response_tracker,
            )
        else:
            connect_timeout = config.get("connect_timeout", 5)
            x3d_opt = config.get("x3d_opt", False)

            emitter.log("Consultando capacidades do servidor...", "info")
            accept_ranges, total_size, _enc = get_server_info(
                session, url, connect_timeout
            )
            expected_total_size = total_size
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
                    output_path=final_path,
                    session=session,
                    chunk_size=chunk_size,
                    stop_event=stop_event,
                    pause_event=pause_event,
                    speed_counter=counter_proxy,
                    log_fn=emitter.log,
                    total_size_fn=emitter.total_size,
                    response_tracker=response_tracker,
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
                    url, final_path, session, total_size, chunk_size,
                    num_threads, counter_proxy, stop_event, pause_event,
                    emitter, response_tracker,
                )

        if success and expected_total_size is not None:
            success = _verify_final_size(
                final_path, expected_total_size, emitter.log
            )

        if success and config.get("expected_checksum"):
            success = _verify_checksum(
                final_path, config["expected_checksum"],
                stop_event, emitter.log,
            )

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
                response_tracker,
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
    stop_event, pause_event, emitter, response_tracker,
) -> tuple[bool, str]:
    """
    Executa download HLS: parseia playlist, baixa segmentos .ts em paralelo,
    descriptografa AES-128 e concatena em arquivo final.
    """
    import shutil
    from core.constants import CHUNK_SIZE, PART_RECOVERY_LIMIT, TEMP_DIR

    try:
        import m3u8
    except ImportError:
        emitter.log("Módulo m3u8 não instalado. Execute: pip install m3u8", "error")
        return False, output_path

    emitter.log("Carregando playlist M3U8...", "info")
    try:
        r = session.get(url, timeout=(5, 30))
        r.raise_for_status()
        playlist = m3u8.loads(r.text, uri=url)
    except Exception as e:
        emitter.log(f"Erro ao carregar playlist: {e}", "error")
        return False, output_path

    if playlist.is_variant:
        emitter.log(
            f"Master Playlist com {len(playlist.playlists)} resoluções detectada.",
            "info",
        )
        valid = [p for p in playlist.playlists if p.stream_info and p.stream_info.bandwidth]
        if not valid:
            emitter.log("Nenhuma stream válida encontrada.", "error")
            return False, output_path
        best = max(valid, key=lambda p: p.stream_info.bandwidth)
        res = getattr(best.stream_info, "resolution", None)
        emitter.log(f"Resolução selecionada: {res or 'Máxima'}", "success")
        return _run_hls(
            best.absolute_uri, output_path, session, config, counter_proxy,
            stop_event, pause_event, emitter, response_tracker,
        )

    segments = playlist.segments
    if not segments:
        emitter.log("Nenhum segmento encontrado na playlist.", "error")
        return False, output_path

    import hashlib as _hl
    out_hash = _hl.md5(output_path.encode("utf-8")).hexdigest()[:12]
    part_dir = os.path.join(TEMP_DIR, f"hls_{out_hash}")
    os.makedirs(part_dir, exist_ok=True)
    emitter.send("part_dir", part_dir)

    emitter.log(
        f"Stream HLS com {len(segments)} segmentos .ts. Preparando download...",
        "info",
    )

    key_bytes = None
    key_info = None
    if hasattr(playlist, "keys") and playlist.keys and playlist.keys[0]:
        k = playlist.keys[0]
        if getattr(k, "method", None) == "AES-128":
            key_bytes, key_info = _fetch_aes_key(session, k, emitter)
            if key_bytes is None:
                return False, output_path

    base_sequence = int(getattr(playlist, "media_sequence", 0) or 0)
    emitter.total_size({"mode": "segments", "total": len(segments)})

    chunk_size = min(CHUNK_SIZE, 512 * 1024)
    max_workers = min(config.get("threads", 8), 256)

    parts = [(i, seg.absolute_uri) for i, seg in enumerate(segments)]
    failed = _hls_download_parts(
        parts, part_dir, session, chunk_size, max_workers,
        key_bytes, key_info, base_sequence,
        counter_proxy, stop_event, pause_event, emitter, response_tracker,
    )

    if failed and not stop_event.is_set():
        for recovery_round in range(1, PART_RECOVERY_LIMIT + 1):
            emitter.log(
                f"Repescagem HLS {recovery_round}/{PART_RECOVERY_LIMIT}: "
                f"{len(failed)} segmentos pendentes...",
                "warning",
            )
            retry_parts = [(i, u) for i, u in parts if i in failed]
            failed = _hls_download_parts(
                retry_parts, part_dir, session, chunk_size,
                max(1, min(len(retry_parts), 32)),
                key_bytes, key_info, base_sequence,
                counter_proxy, stop_event, pause_event, emitter, response_tracker,
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
            return False, output_path

    if stop_event.is_set():
        emitter.log("Download HLS cancelado.", "warning")
        return False, output_path

    missing = [
        i for i, _ in parts
        if not os.path.exists(os.path.join(part_dir, f"segment_{i}.ts"))
    ]
    if missing:
        preview = ", ".join(str(i) for i in missing[:10])
        if len(missing) > 10:
            preview += ", ..."
        emitter.log(f"Segmentos ausentes após o download: {preview}", "error")
        return False, output_path

    emitter.log("Unificando segmentos...", "info")
    try:
        with open(output_path, "wb") as out:
            for i, _ in parts:
                seg_path = os.path.join(part_dir, f"segment_{i}.ts")
                if not os.path.exists(seg_path):
                    emitter.log(f"Segmento {i} ausente: {seg_path}", "error")
                    return False, output_path
                with open(seg_path, "rb") as pf:
                    shutil.copyfileobj(pf, out, length=64 * 1024 * 1024)
        emitter.log("Unificação concluída!", "success")
    except OSError as e:
        emitter.log(f"Erro ao unificar segmentos: {e}", "error")
        return False, output_path

    if not output_path.lower().endswith(".ts"):
        from core.file_utils import make_unique_path as _mk_unique
        new_path = _mk_unique(os.path.splitext(output_path)[0] + ".ts")
        try:
            os.rename(output_path, new_path)
            # Avisa o pai que o arquivo final mudou de extensão — o histórico
            # precisa do caminho real para que cliques no item abram o arquivo.
            output_path = new_path
            emitter.send("resolved_path", new_path)
        except OSError as e:
            emitter.log(f"Aviso: não foi possível renomear para .ts: {e}", "warning")

    time.sleep(0.3)
    try:
        shutil.rmtree(part_dir, ignore_errors=True)
    except Exception:
        pass

    return True, output_path


def _hls_download_parts(
    parts, part_dir, session, chunk_size, max_workers,
    key_bytes, key_info, base_sequence,
    counter_proxy, stop_event, pause_event, emitter, response_tracker,
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
                idx, session, chunk_size, key_bytes, key_info,
                base_sequence, counter_proxy, stop_event, pause_event,
                response_tracker,
            ): idx
            for idx, url in parts
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
    url, filepath, index, session, chunk_size, key_bytes, key_info,
    base_sequence, counter_proxy, stop_event, pause_event, response_tracker,
) -> bool:
    from core.constants import CONNECT_TIMEOUT, READ_TIMEOUT, RETRY_LIMIT

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
            use_aes = key_bytes is not None and key_info is not None
            encrypted_buf = bytearray() if use_aes else None
            expected_len = None
            received = 0

            with session.get(
                url,
                headers={"Accept-Encoding": "identity"},
                stream=True,
                timeout=(CONNECT_TIMEOUT, READ_TIMEOUT),
            ) as r:
                if response_tracker is not None:
                    response_tracker.add(r)
                try:
                    r.raise_for_status()
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
                iv = _get_iv(key_info, base_sequence, index)
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


def _fetch_aes_key(session, key_info, emitter):
    try:
        import Crypto  # noqa: F401
    except ImportError:
        emitter.log(
            "pycryptodome não instalado. Execute: pip install pycryptodome",
            "error",
        )
        return None, None

    emitter.log("Criptografia AES-128 detectada. Buscando chave...", "warning")
    try:
        r = session.get(key_info.absolute_uri, timeout=10)
        r.raise_for_status()
        key = r.content
        if len(key) != 16:
            emitter.log(
                f"Chave AES inválida: {len(key)} bytes (esperado 16).",
                "error",
            )
            return None, None
        emitter.log("Chave de descriptografia obtida!", "success")
        return key, key_info
    except Exception as e:
        emitter.log(f"Erro ao obter chave AES: {e}", "error")
        return None, None


def _get_iv(key_info, base_sequence: int, index: int) -> bytes:
    if key_info and getattr(key_info, "iv", None):
        return bytes.fromhex(key_info.iv.replace("0x", "").replace("0X", ""))
    return (base_sequence + index).to_bytes(16, "big")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

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
