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

from core.constants import CONNECT_TIMEOUT, READ_TIMEOUT, RETRY_BACKOFF, RETRY_LIMIT
from core.speed_calculator import AtomicCounter


def _parse_content_range(value: str) -> tuple[int | None, int | None, int | None]:
    if not value:
        return None, None, None
    unit, _, rest = value.strip().partition(" ")
    if unit.lower() != "bytes" or "/" not in rest:
        return None, None, None
    bounds, _, total_raw = rest.partition("/")
    try:
        total = None if total_raw == "*" else int(total_raw)
    except ValueError:
        total = None
    if bounds == "*":
        return None, None, total
    start_raw, _, end_raw = bounds.partition("-")
    try:
        return int(start_raw), int(end_raw), total
    except ValueError:
        return None, None, total


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
        progress_at_attempt = 0
        try:
            headers: dict = {}
            existing = 0

            # Resume: verificar bytes já baixados
            if os.path.exists(output_path):
                existing = os.path.getsize(output_path)
                if existing > 0:
                    headers["Range"] = f"bytes={existing}-"
            headers["Accept-Encoding"] = "identity"
            progress_at_attempt = existing

            with session.get(
                url,
                headers=headers,
                stream=True,
                allow_redirects=True,
                timeout=(CONNECT_TIMEOUT, READ_TIMEOUT),
            ) as r:
                if response_tracker is not None:
                    response_tracker.add(r)
                try:
                    if existing and r.status_code == 416:
                        _start, _end, total = _parse_content_range(
                            r.headers.get("Content-Range", "")
                        )
                        if total is not None and existing == total:
                            if total_size_fn:
                                total_size_fn(total)
                            if log_fn:
                                log_fn("Arquivo local já está completo.", "success")
                            return True
                        if total is not None and existing > total:
                            if log_fn:
                                log_fn(
                                    "Arquivo parcial maior que o remoto; reiniciando do zero.",
                                    "warning",
                                )
                            try:
                                os.remove(output_path)
                            except OSError as exc:
                                raise IOError(
                                    f"não foi possível reiniciar arquivo parcial inválido: {exc}"
                                ) from exc
                            continue
                    r.raise_for_status()

                    # Informar tamanho total
                    expected_response_len = None
                    expected_total = None
                    raw_len = r.headers.get("Content-Length")
                    if raw_len:
                        try:
                            partial = int(raw_len)
                            expected_response_len = partial
                            expected_total = (partial + existing) if r.status_code == 206 else partial
                            if total_size_fn:
                                total_size_fn(expected_total)
                        except ValueError:
                            pass

                    # Modo de escrita
                    if existing and r.status_code == 206:
                        start, _end, total = _parse_content_range(
                            r.headers.get("Content-Range", "")
                        )
                        if start != existing:
                            raise IOError(
                                f"Content-Range inesperado para resume: inicio {start}, esperado {existing}"
                            )
                        if total is not None:
                            expected_total = total
                        mode = "ab"
                        if log_fn:
                            log_fn(
                                f"Retomando download ({existing / (1024*1024):.1f} MB já baixados)...",
                                "info",
                            )
                    else:
                        mode = "wb"
                        progress_at_attempt = 0
                        if existing and r.status_code == 200:
                            existing = 0
                            if log_fn:
                                log_fn("Servidor não suporta resume, reiniciando...", "warning")

                    encoding = (r.headers.get("Content-Encoding") or "").lower()
                    if encoding and encoding != "identity":
                        if mode == "ab":
                            raise IOError(
                                f"resume recusado: Content-Encoding={encoding} não é byte-a-byte confiável"
                            )
                        expected_response_len = None
                        expected_total = None

                    received = 0
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
                            received += len(chunk)
                            # Telemetria direta — sem debounce, sem Lock, sem sinal Qt
                            speed_counter.add(len(chunk))

                        f.flush()

                    if (
                        expected_response_len is not None
                        and received != expected_response_len
                    ):
                        raise IOError(
                            f"download truncado: {received} bytes recebidos, esperado {expected_response_len}"
                        )
                    if expected_total is not None:
                        final_size = os.path.getsize(output_path)
                        if final_size != expected_total:
                            raise IOError(
                                f"tamanho final inválido: {final_size} bytes, esperado {expected_total}"
                            )
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
            try:
                current_size = os.path.getsize(output_path) if os.path.exists(output_path) else 0
            except OSError:
                current_size = 0

            if current_size > progress_at_attempt:
                attempt = 0
                if log_fn:
                    log_fn("Conexão caiu, mas houve progresso. Retomando do último byte salvo...", "warning")
                if stop_event.wait(0.2):
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
