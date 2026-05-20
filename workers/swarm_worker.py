"""
workers/swarm_worker.py
Worker de segmento Swarm — executado via ThreadPoolExecutor, sem herança de QThread.
Escreve diretamente no arquivo final pré-alocado usando buffer de 1 MB.
"""

import threading
import time
from typing import Callable, Optional

import requests

from core.constants import CONNECT_TIMEOUT, READ_TIMEOUT, RETRY_LIMIT
from core.speed_calculator import AtomicCounter


def _parse_content_range(value: str) -> tuple[int, int, int | None] | None:
    if not value:
        return None
    unit, _, rest = value.strip().partition(" ")
    if unit.lower() != "bytes" or "-" not in rest or "/" not in rest:
        return None
    bounds, _, total_raw = rest.partition("/")
    start_raw, _, end_raw = bounds.partition("-")
    try:
        total = None if total_raw == "*" else int(total_raw)
        return int(start_raw), int(end_raw), total
    except ValueError:
        return None


def _validate_range_response(response: requests.Response, start: int, end: int) -> None:
    if response.status_code != 206:
        raise requests.HTTPError(
            f"servidor ignorou Range {start}-{end} (HTTP {response.status_code})",
            response=response,
        )

    encoding = (response.headers.get("Content-Encoding") or "").lower()
    if encoding and encoding != "identity":
        raise IOError(
            f"resposta com Content-Encoding={encoding}; range não é byte-a-byte confiável"
        )

    parsed = _parse_content_range(response.headers.get("Content-Range", ""))
    if parsed is None:
        raise IOError("resposta 206 sem Content-Range válido")
    returned_start, returned_end, _total = parsed
    if returned_start != start or returned_end != end:
        raise IOError(
            f"Content-Range inesperado: {returned_start}-{returned_end}, esperado {start}-{end}"
        )

    raw_len = response.headers.get("Content-Length")
    if raw_len:
        try:
            declared_len = int(raw_len)
        except ValueError:
            declared_len = None
        expected_len = end - start + 1
        if declared_len is not None and declared_len != expected_len:
            raise IOError(
                f"Content-Length do segmento inválido: {declared_len}, esperado {expected_len}"
            )


def swarm_segment_worker(
    url: str,
    segment: dict,
    file_lock: threading.Lock,
    output_path: str,
    session: requests.Session,
    chunk_size: int,
    stop_event: threading.Event,
    pause_event: threading.Event,
    speed_counter: AtomicCounter,
    log_fn: Optional[Callable[[str, str], None]] = None,
    response_tracker=None,
) -> bool:
    """
    Baixa um segmento e escreve diretamente no arquivo final.

    Telemetria: speed_counter.add(bytes) é chamado a cada flush de 1 MB,
    minimizando contenção no mp.Value entre dezenas/centenas de workers.
    """
    FLUSH_THRESHOLD = 1024 * 1024  # 1 MB

    attempt = 0
    while attempt <= RETRY_LIMIT and not stop_event.is_set():
        while pause_event.is_set() and not stop_event.is_set():
            time.sleep(0.02)
        if stop_event.is_set():
            return False

        start_pos = segment["current"]
        end_pos = segment["end"]

        if start_pos > end_pos:
            segment["status"] = "done"
            return True

        try:
            progress_at_attempt = start_pos
            headers = {
                "Range": f"bytes={start_pos}-{end_pos}",
                "Accept-Encoding": "identity",
            }
            with session.get(
                url,
                headers=headers,
                stream=True,
                timeout=(CONNECT_TIMEOUT, READ_TIMEOUT),
            ) as r:
                if response_tracker is not None:
                    response_tracker.add(r)
                try:
                    r.raise_for_status()
                    _validate_range_response(r, start_pos, end_pos)

                    with open(output_path, "r+b") as f:
                        buffer = bytearray()
                        buffer_start = start_pos
                        logical_pos = start_pos

                        def flush_buffer() -> None:
                            nonlocal buffer_start
                            if not buffer:
                                return
                            with file_lock:
                                f.seek(buffer_start)
                                f.write(buffer)
                                f.flush()
                            flushed = len(buffer)
                            buffer_start += flushed
                            # current só avança depois que os bytes foram
                            # entregues ao arquivo. Em crash/pause, o resume
                            # pode rebaixar um pouco, mas não pula bytes.
                            segment["current"] = max(segment["current"], buffer_start)
                            speed_counter.add(flushed)
                            buffer.clear()

                        for chunk in r.iter_content(chunk_size):
                            if stop_event.is_set():
                                return False

                            while pause_event.is_set() and not stop_event.is_set():
                                time.sleep(0.02)
                            if stop_event.is_set():
                                return False

                            if not chunk:
                                continue

                            chunk_len = len(chunk)

                            current_end = segment["end"]
                            if logical_pos + chunk_len > current_end + 1:
                                allowed = (current_end + 1) - logical_pos
                                if allowed <= 0:
                                    break
                                chunk = chunk[:allowed]
                                chunk_len = len(chunk)

                            buffer.extend(chunk)
                            logical_pos += chunk_len

                            if len(buffer) >= FLUSH_THRESHOLD:
                                flush_buffer()

                            if logical_pos > current_end:
                                break

                        # Flush do restante
                        flush_buffer()

                    if segment["current"] <= segment["end"]:
                        remaining = segment["end"] - segment["current"] + 1
                        raise IOError(f"segmento incompleto; faltam {remaining} bytes")
                finally:
                    if response_tracker is not None:
                        response_tracker.remove(r)

            segment["status"] = "done"
            return True

        except Exception as e:
            if stop_event.is_set():
                return False
            # Pause acionado fecha a Response e gera exceção. Espera o resume
            # e retoma do segment["current"] sem queimar tentativa.
            if pause_event.is_set():
                while pause_event.is_set() and not stop_event.is_set():
                    time.sleep(0.02)
                if stop_event.is_set():
                    return False
                continue
            if segment.get("current", progress_at_attempt) > progress_at_attempt:
                attempt = 0
                if stop_event.wait(0.2):
                    return False
                continue

            attempt += 1
            if attempt > RETRY_LIMIT:
                segment["status"] = "free"
                if log_fn:
                    log_fn(
                        f"Segmento falhou após {RETRY_LIMIT} tentativas sem progresso: {e}",
                        "warning",
                    )
                return False

            if stop_event.wait(min(1.5 ** attempt, 10)):
                return False

    segment["status"] = "free"
    return False
