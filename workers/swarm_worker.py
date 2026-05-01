"""
workers/swarm_worker.py
Worker de segmento Swarm — executado via ThreadPoolExecutor, sem herança de QThread.
Escreve diretamente no arquivo final pré-alocado usando buffer de 1 MB.
"""

import threading
import time
from typing import Callable, Optional

import requests

from core.constants import RETRY_LIMIT
from core.speed_calculator import AtomicCounter


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
            headers = {"Range": f"bytes={start_pos}-{end_pos}"}
            with session.get(url, headers=headers, stream=True, timeout=(5, 5)) as r:
                if response_tracker is not None:
                    response_tracker.add(r)
                try:
                    r.raise_for_status()

                    with open(output_path, "r+b") as f:
                        buffer = bytearray()
                        buffer_start = start_pos
                        logical_pos = start_pos

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
                            segment["current"] = logical_pos

                            if len(buffer) >= FLUSH_THRESHOLD:
                                with file_lock:
                                    f.seek(buffer_start)
                                    f.write(buffer)
                                flushed = len(buffer)
                                buffer_start += flushed
                                # Telemetria por flush — uma chamada por MB,
                                # baixa contenção do mp.Value entre 512 threads.
                                speed_counter.add(flushed)
                                buffer.clear()

                            if logical_pos > current_end:
                                break

                        # Flush do restante
                        if buffer:
                            with file_lock:
                                f.seek(buffer_start)
                                f.write(buffer)
                            speed_counter.add(len(buffer))
                            buffer.clear()
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
            attempt += 1
            if attempt > RETRY_LIMIT:
                segment["status"] = "free"
                if log_fn:
                    log_fn(f"Segmento falhou após {RETRY_LIMIT} tentativas: {e}", "warning")
                return False

            if stop_event.wait(min(1.5 ** attempt, 10)):
                return False

    segment["status"] = "free"
    return False
