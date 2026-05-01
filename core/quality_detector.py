"""
core/quality_detector.py
Detecção automática de melhor qualidade de vídeo disponível em uma URL.
Sem dependências de PyQt6.
"""

import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Callable, Optional
from urllib.parse import urlparse

import requests

from core.constants import (
    CHUNK_SIZE,
    LARGE_CHUNK_SIZE,
    SMALL_CHUNK_SIZE,
    VIDEO_EXTENSIONS,
    VIDEO_QUALITIES,
)


# ---------------------------------------------------------------------------
# Helpers de URL
# ---------------------------------------------------------------------------

def is_video_url(url: str) -> bool:
    """Retorna True se a extensão do path da URL é um formato de vídeo suportado."""
    path = urlparse(url).path.lower()
    return any(path.endswith(ext) for ext in VIDEO_EXTENSIONS)


def is_hls_url(url: str) -> bool:
    """Retorna True se a URL aponta para uma playlist HLS/M3U8."""
    url_lower = url.lower()
    return ".m3u8" in url_lower or "playlist" in url_lower or "master" in url_lower


# ---------------------------------------------------------------------------
# Otimização de chunk e threads
# ---------------------------------------------------------------------------

def get_optimal_chunk_size(file_size: int, x3d_opt: bool = False) -> int:
    """
    Retorna o tamanho de chunk adequado ao tamanho do arquivo.

    x3d_opt=True ativa chunk de 32 MB para maximizar uso do L3 Cache 3D (AMD X3D).
    """
    if x3d_opt:
        return 32 * 1024 * 1024
    if file_size < 1024 * 1024:
        return SMALL_CHUNK_SIZE
    if file_size < 100 * 1024 * 1024:
        return CHUNK_SIZE
    return LARGE_CHUNK_SIZE


def get_optimal_thread_count(file_size: int, max_threads: int) -> int:
    """
    Calcula o número ideal de threads baseado no tamanho do arquivo.
    Nunca excede max_threads nem cria partes menores que o mínimo por faixa.
    """
    if file_size < 10 * 1024 * 1024:
        ideal = max_threads
        min_part = 256 * 1024
    elif file_size < 100 * 1024 * 1024:
        ideal = max_threads
        min_part = 512 * 1024
    elif file_size < 1024 * 1024 * 1024:
        ideal = max(256, max_threads // 2)
        min_part = 1024 * 1024
    else:
        ideal = max(512, max_threads // 2)
        min_part = 2 * 1024 * 1024

    # Nunca criar partes menores que min_part
    max_by_size = file_size // min_part
    return max(1, min(ideal, max_threads, max_by_size))


# ---------------------------------------------------------------------------
# Detecção de melhor qualidade
# ---------------------------------------------------------------------------

def _check_url_exists(session: requests.Session, url: str, timeout: float = 2.0) -> bool:
    """Verifica existência de uma URL com HEAD request rápido."""
    try:
        r = session.head(url, timeout=timeout, allow_redirects=True)
        return r.status_code == 200
    except Exception:
        return False


def _generate_quality_variations(url: str) -> list[str]:
    """
    Gera variações de URL substituindo indicadores de qualidade conhecidos.
    Retorna lista com a URL original + variações únicas.
    """
    variations: list[str] = [url]

    # Padrões: 360p, 1080p, 4K, etc.
    pattern = re.compile(r"(\d{3,4}p|4K)", re.IGNORECASE)

    if not pattern.search(url):
        return variations  # URL sem indicador de qualidade detectável

    for quality in VIDEO_QUALITIES:
        candidate = pattern.sub(quality, url)
        if candidate != url and candidate not in variations:
            variations.append(candidate)

    return variations


def find_best_quality_url(
    session: requests.Session,
    original_url: str,
    stop_event=None,
    log_fn: Optional[Callable] = None,
) -> str:
    """
    Encontra a melhor qualidade de vídeo disponível a partir da URL original.

    Fluxo:
    1. Verifica se é URL de vídeo; se não for → retorna original.
    2. Gera variações de qualidade.
    3. Verifica existência em paralelo (max 12 workers, timeout global 15s).
    4. Retorna a URL com maior qualidade disponível.
    5. Em qualquer falha (timeout, erro de rede) → retorna original silenciosamente.

    Parâmetros:
        session      : sessão HTTP configurada
        original_url : URL base
        stop_event   : threading.Event para cancelamento (opcional)
        log_fn       : callback(msg, level) para feedback (opcional)
    """
    if not is_video_url(original_url):
        return original_url

    if log_fn:
        log_fn("Procurando melhor qualidade disponível...", "info")

    variations = _generate_quality_variations(original_url)
    if len(variations) <= 1:
        return original_url

    if log_fn:
        log_fn(f"Verificando {len(variations)} variações de qualidade...", "info")

    available: list[str] = []
    max_workers = min(12, len(variations))

    try:
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {
                executor.submit(_check_url_exists, session, url): url
                for url in variations
            }
            for future in as_completed(futures, timeout=15):
                if stop_event and stop_event.is_set():
                    break
                url = futures[future]
                try:
                    if future.result():
                        available.append(url)
                except Exception:
                    pass
    except Exception:
        return original_url  # Timeout ou erro geral → fallback silencioso

    if not available:
        if log_fn:
            log_fn("Nenhuma variação encontrada, usando URL original.", "warning")
        return original_url

    # Encontrar maior qualidade disponível pela posição em VIDEO_QUALITIES
    best_url = original_url
    best_idx = -1

    for url in available:
        url_lower = url.lower()
        for i, quality in enumerate(VIDEO_QUALITIES):
            if quality.lower() in url_lower and i > best_idx:
                best_idx = i
                best_url = url
                break

    if best_url != original_url and log_fn:
        log_fn(f"Melhor qualidade encontrada: {VIDEO_QUALITIES[best_idx]}", "success")

    return best_url
