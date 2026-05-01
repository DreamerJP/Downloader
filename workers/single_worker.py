"""
workers/single_worker.py
Download single-thread com suporte a resume e retry.
Usado quando o servidor não suporta range requests ou o arquivo é pequeno (< 1 MB).
"""

import os
import threading
import time
from typing import Callable, Optional

import requests

from core.constants import RETRY_BACKOFF, RETRY_LIMIT
from core.speed_calculator import AtomicCounter


def single_stream_download(
    url: str,
    output_path: str,
    session: requests.Session,
    chunk_size: int,
    stop_event: threading.Event,
    pause_event: threading.Event,
    speed_counter: AtomicCounter,
    log_fn: Optional[Callable[[str, str], None]] = None,
    total_size_fn: Optional[Callable[[int], None]] = None,
    response_tracker=None,
) -> bool:
    """
    Baixa um arquivo em stream único com suporte a resume e retry automático.

    Telemetria: chama speed_counter.add(delta) a cada chunk — sem Lock, sem
    sinal Qt. O SpeedCalculator lê o acumulador no tick do timer da UI.
    """
    attempt = 0

    while attempt <= RETRY_LIMIT and not stop_event.is_set():
        try:
            headers: dict = {}
            existing = 0

            # Resume: verificar bytes já baixados
            if os.path.exists(output_path):
                existing = os.path.getsize(output_path)
                if existing > 0:
                    headers["Range"] = f"bytes={existing}-"

            with session.get(
                url,
                headers=headers,
                stream=True,
                allow_redirects=True,
                timeout=(5, 5),
            ) as r:
                if response_tracker is not None:
                    response_tracker.add(r)
                try:
                    r.raise_for_status()

                    # Informar tamanho total
                    raw_len = r.headers.get("Content-Length")
                    if raw_len and total_size_fn:
                        try:
                            partial = int(raw_len)
                            total = (partial + existing) if r.status_code == 206 else partial
                            total_size_fn(total)
                        except ValueError:
                            pass

                    # Modo de escrita
                    if existing and r.status_code == 206:
                        mode = "ab"
                        if log_fn:
                            log_fn(
                                f"Retomando download ({existing / (1024*1024):.1f} MB já baixados)...",
                                "info",
                            )
                    else:
                        mode = "wb"
                        if existing and r.status_code == 200:
                            existing = 0
                            if log_fn:
                                log_fn("Servidor não suporta resume, reiniciando...", "warning")

                    with open(output_path, mode) as f:
                        for chunk in r.iter_content(chunk_size):
                            if stop_event.is_set():
                                return False

                            while pause_event.is_set() and not stop_event.is_set():
                                time.sleep(0.02)
                            if stop_event.is_set():
                                return False

                            if not chunk:
                                continue

                            f.write(chunk)
                            # Telemetria direta — sem debounce, sem Lock, sem sinal Qt
                            speed_counter.add(len(chunk))

                        f.flush()
                finally:
                    if response_tracker is not None:
                        response_tracker.remove(r)

            return True

        except Exception as e:
            if stop_event.is_set():
                return False
            # Pause acionado durante iter_content fecha a Response e gera
            # exceção. Espera o resume e tenta de novo sem queimar tentativa.
            if pause_event.is_set():
                while pause_event.is_set() and not stop_event.is_set():
                    time.sleep(0.02)
                if stop_event.is_set():
                    return False
                continue
            attempt += 1
            if attempt <= RETRY_LIMIT:
                wait = RETRY_BACKOFF ** attempt
                if log_fn:
                    log_fn(
                        f"Erro no download (tentativa {attempt}/{RETRY_LIMIT}): {e}. "
                        f"Aguardando {wait:.1f}s...",
                        "warning",
                    )
                if stop_event.wait(wait):
                    return False
            else:
                if log_fn:
                    log_fn(f"Falha definitiva após {RETRY_LIMIT} tentativas: {e}", "error")
                return False

    return False
