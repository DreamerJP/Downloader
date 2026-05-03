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
from concurrent.futures import ThreadPoolExecutor, as_completed
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
            success = _run_hls(
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

        if success and config.get("expected_checksum"):
            _verify_checksum(
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
    from core.constants import TEMP_DIR
    from core.file_utils import cleanup_temp_dir
    from core.segment_manager import DynamicSegmentManager
    from workers.swarm_worker import swarm_segment_worker

    # part_dir determinístico por output_path — pause→resume reaproveita
    # exatamente o mesmo state.json mesmo entre processos diferentes.
    out_hash = hashlib.md5(output_path.encode("utf-8")).hexdigest()[:12]
    part_dir = os.path.join(TEMP_DIR, f"swarm_{out_hash}")
    os.makedirs(part_dir, exist_ok=True)
    emitter.send("part_dir", part_dir)

    # Pula pré-alocação se o arquivo já existe com tamanho correto (caso de
    # retomada após pause).
    need_prealloc = True
    try:
        if os.path.isfile(output_path) and os.path.getsize(output_path) == total_size:
            need_prealloc = False
            emitter.log("Arquivo pré-alocado encontrado — pulando alocação.", "info")
    except OSError:
        pass

    if need_prealloc:
        try:
            emitter.log(f"Pré-alocando {_fmt_size(total_size)} no disco...", "info")
            with open(output_path, "wb") as f:
                f.seek(total_size - 1)
                f.write(b"\x00")
            emitter.log("Pré-alocação concluída.", "info")
        except OSError as e:
            emitter.log(f"Falha ao pré-alocar arquivo: {e}", "error")
            return False

    state_file = os.path.join(part_dir, "state.json")
    manager = DynamicSegmentManager.load_from_file(state_file, total_size)
    if manager:
        emitter.log("Estado anterior encontrado — retomando download...", "info")
    else:
        manager = DynamicSegmentManager(total_size)

    emitter.total_size(total_size)
    emitter.log(f"Disparando {num_threads} workers paralelos...", "info")
    file_lock = threading.Lock()
    failed = False

    try:
        with ThreadPoolExecutor(max_workers=num_threads, thread_name_prefix="Swarm") as executor:
            futures = []
            for _ in range(num_threads):
                seg = manager.get_work()
                if seg is None:
                    break
                futures.append(executor.submit(
                    swarm_segment_worker,
                    url, seg, file_lock, output_path, session,
                    chunk_size, stop_event, pause_event,
                    counter_proxy, emitter.log,
                    response_tracker,
                ))

            while not stop_event.is_set():
                seg = manager.get_work()
                if seg is None:
                    break
                futures.append(executor.submit(
                    swarm_segment_worker,
                    url, seg, file_lock, output_path, session,
                    chunk_size, stop_event, pause_event,
                    counter_proxy, emitter.log,
                    response_tracker,
                ))
                emitter.segments_map(total_size, manager.get_map_data())

            for future in as_completed(futures):
                if stop_event.is_set():
                    executor.shutdown(wait=False, cancel_futures=True)
                    break
                try:
                    if not future.result():
                        failed = True
                except Exception as e:
                    failed = True
                    emitter.log(f"Worker error: {e}", "warning")
                emitter.segments_map(total_size, manager.get_map_data())

    except Exception as e:
        emitter.log(f"Erro no Swarm: {e}", "error")
        manager.save_to_file(state_file)
        return False

    if stop_event.is_set():
        return False

    if failed or not manager.is_complete():
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
) -> bool:
    """
    Executa download HLS: parseia playlist, baixa segmentos .ts em paralelo,
    descriptografa AES-128 e concatena em arquivo final.
    """
    import shutil
    from core.constants import CHUNK_SIZE, TEMP_DIR

    try:
        import m3u8
    except ImportError:
        emitter.log("Módulo m3u8 não instalado. Execute: pip install m3u8", "error")
        return False

    emitter.log("Carregando playlist M3U8...", "info")
    try:
        r = session.get(url, timeout=(5, 30))
        r.raise_for_status()
        playlist = m3u8.loads(r.text, uri=url)
    except Exception as e:
        emitter.log(f"Erro ao carregar playlist: {e}", "error")
        return False

    if playlist.is_variant:
        emitter.log(
            f"Master Playlist com {len(playlist.playlists)} resoluções detectada.",
            "info",
        )
        valid = [p for p in playlist.playlists if p.stream_info and p.stream_info.bandwidth]
        if not valid:
            emitter.log("Nenhuma stream válida encontrada.", "error")
            return False
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
        return False

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
                return False

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
        emitter.log(f"Repescagem de {len(failed)} segmentos falhados...", "warning")
        retry_parts = [(i, u) for i, u in parts if i in failed]
        still_failed = _hls_download_parts(
            retry_parts, part_dir, session, chunk_size,
            min(len(retry_parts), 32),
            key_bytes, key_info, base_sequence,
            counter_proxy, stop_event, pause_event, emitter, response_tracker,
        )
        if not still_failed:
            emitter.log("Repescagem concluída com sucesso!", "success")
        else:
            emitter.log(
                f"{len(still_failed)} segmentos falharam permanentemente.",
                "error",
            )
            return False

    if stop_event.is_set():
        emitter.log("Download HLS cancelado.", "warning")
        return False

    missing = [
        i for i, _ in parts
        if not os.path.exists(os.path.join(part_dir, f"segment_{i}.ts"))
    ]
    if missing:
        preview = ", ".join(str(i) for i in missing[:10])
        if len(missing) > 10:
            preview += ", ..."
        emitter.log(f"Segmentos ausentes após o download: {preview}", "error")
        return False

    emitter.log("Unificando segmentos...", "info")
    try:
        with open(output_path, "wb") as out:
            for i, _ in parts:
                seg_path = os.path.join(part_dir, f"segment_{i}.ts")
                if not os.path.exists(seg_path):
                    emitter.log(f"Segmento {i} ausente: {seg_path}", "error")
                    return False
                with open(seg_path, "rb") as pf:
                    shutil.copyfileobj(pf, out, length=64 * 1024 * 1024)
        emitter.log("Unificação concluída!", "success")
    except OSError as e:
        emitter.log(f"Erro ao unificar segmentos: {e}", "error")
        return False

    if not output_path.lower().endswith(".ts"):
        from core.file_utils import make_unique_path as _mk_unique
        new_path = _mk_unique(os.path.splitext(output_path)[0] + ".ts")
        try:
            os.rename(output_path, new_path)
            # Avisa o pai que o arquivo final mudou de extensão — o histórico
            # precisa do caminho real para que cliques no item abram o arquivo.
            emitter.send("resolved_path", new_path)
        except OSError as e:
            emitter.log(f"Aviso: não foi possível renomear para .ts: {e}", "warning")

    time.sleep(0.3)
    try:
        shutil.rmtree(part_dir, ignore_errors=True)
    except Exception:
        pass

    return True


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
    from core.constants import RETRY_LIMIT

    if os.path.exists(filepath) and not key_bytes:
        if os.path.getsize(filepath) > 0:
            return True

    attempt = 0
    while attempt < RETRY_LIMIT and not stop_event.is_set():
        while pause_event.is_set() and not stop_event.is_set():
            time.sleep(0.05)

        try:
            use_aes = key_bytes is not None and key_info is not None
            encrypted_buf = bytearray() if use_aes else None

            with session.get(url, stream=True, timeout=(5, 10)) as r:
                response_tracker.add(r)
                try:
                    r.raise_for_status()

                    if encrypted_buf is None:
                        with open(filepath, "wb") as f:
                            for chunk in r.iter_content(chunk_size):
                                if stop_event.is_set():
                                    return False
                                if not chunk:
                                    continue
                                f.write(chunk)
                                counter_proxy.add(len(chunk))
                    else:
                        for chunk in r.iter_content(chunk_size):
                            if stop_event.is_set():
                                return False
                            if not chunk:
                                continue
                            encrypted_buf.extend(chunk)
                            counter_proxy.add(len(chunk))
                finally:
                    response_tracker.remove(r)

            if encrypted_buf is not None:
                from Crypto.Cipher import AES  # type: ignore
                iv = _get_iv(key_info, base_sequence, index)
                cipher = AES.new(key_bytes, AES.MODE_CBC, iv)
                data = cipher.decrypt(bytes(encrypted_buf))
                pad_len = data[-1] if data else 0
                if 0 < pad_len <= 16:
                    data = data[:-pad_len]
                with open(filepath, "wb") as f:
                    f.write(data)

            return True

        except Exception:
            try:
                if os.path.exists(filepath):
                    os.remove(filepath)
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

def _verify_checksum(path, expected, stop_event, log_fn):
    from core.file_utils import compute_sha256
    if not expected or not path or not os.path.exists(path):
        return
    log_fn("Verificando checksum SHA256...", "info")
    digest = compute_sha256(path, stop_event, log_fn)
    if digest is None:
        log_fn("Verificação cancelada.", "warning")
    elif digest.lower() == expected.lower():
        log_fn("✓ Checksum válido!", "success")
    else:
        log_fn(
            f"✗ Checksum INVÁLIDO!\n  Esperado: {expected}\n  Obtido  : {digest}",
            "error",
        )


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
