"""
core/file_utils.py
Utilitários de sistema de arquivos: checksum, limpeza de temporários,
resolução de caminhos de saída.
Sem dependências de PyQt6.
"""

import hashlib
import os
import shutil
import stat
import sys
import threading
from typing import Callable, Optional
from urllib.parse import urlparse

from core.constants import TEMP_DIR


# ---------------------------------------------------------------------------
# Caminhos e recursos
# ---------------------------------------------------------------------------

def get_resource_path(relative_path: str) -> str:
    """
    Resolve o caminho de um recurso tanto em modo desenvolvimento quanto em
    executável PyInstaller (sys._MEIPASS).
    """
    if getattr(sys, "frozen", False):
        base = sys._MEIPASS  # type: ignore[attr-defined]
    else:
        # Raiz do repositório: este arquivo é <raiz>/src/core/file_utils.py,
        # então subimos três níveis (core → src → raiz). Independe do CWD.
        base = os.path.dirname(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        )
    return os.path.join(base, relative_path)


def get_default_download_dir() -> str:
    """
    Retorna a pasta Downloads do usuário.
    Fallback: Documents → home directory.
    """
    for folder in ("Downloads", "Documents"):
        path = os.path.join(os.path.expanduser("~"), folder)
        if os.path.isdir(path):
            return path
    return os.path.expanduser("~")


def ensure_file_extension(filepath: str, url: str) -> str:
    """
    Garante que o caminho de destino tenha uma extensão de arquivo.

    Regras:
    - Se filepath já possui extensão → retorna como está.
    - Extrai extensão do path da URL.
    - URLs de HLS (contêm .m3u8, 'playlist', 'master') → força extensão .ts.
    - Se nenhuma extensão encontrada → retorna filepath sem modificar.
    """
    if not filepath:
        return filepath

    if os.path.splitext(os.path.basename(filepath))[1]:
        return filepath  # Já tem extensão

    url_path = urlparse(url).path.lower()
    url_ext = os.path.splitext(url_path)[1]

    # HLS → .ts para compatibilidade de seek/rewind
    hls_indicators = (".m3u8", "playlist", "master")
    if any(ind in url_path for ind in hls_indicators):
        url_ext = ".ts"
    elif url_ext in (".m3u8", ".txt"):
        url_ext = ".ts"

    if url_ext:
        return filepath + url_ext
    return filepath


def resolve_output_path(output_input: str, url: str) -> str:
    """
    Resolve o caminho final de saída do arquivo.

    - Se output_input fornecido e tem extensão → usa diretamente.
    - Se output_input fornecido sem extensão → adiciona extensão da URL.
    - Se output_input vazio → pasta Downloads + nome inferido da URL.
    """
    if output_input:
        return ensure_file_extension(output_input, url)

    # Inferir nome da URL
    name = os.path.basename(urlparse(url).path) or "download.bin"
    full = os.path.join(get_default_download_dir(), name)
    return ensure_file_extension(full, url)


def make_unique_path(path: str) -> str:
    """
    Se `path` já existe, retorna uma variante com sufixo numerado
    (ex.: `arquivo.ext` → `arquivo (1).ext`, `arquivo (2).ext`, ...).
    Caso contrário retorna `path` inalterado.
    """
    if not os.path.exists(path):
        return path
    base, ext = os.path.splitext(path)
    n = 1
    while True:
        candidate = f"{base} ({n}){ext}"
        if not os.path.exists(candidate):
            return candidate
        n += 1


# ---------------------------------------------------------------------------
# Limpeza de temporários PyInstaller
# ---------------------------------------------------------------------------

def _handle_rmtree_error(func: Callable, path: str, exc_info: object) -> None:
    """Callback para shutil.rmtree: ajusta permissões e tenta novamente."""
    if not os.access(path, os.W_OK):
        os.chmod(path, stat.S_IWUSR)
        func(path)


def cleanup_old_temp_dirs() -> None:
    """
    Remove pastas _MEI* antigas no diretório do executável e no TEMP do SO.
    Só executa quando empacotado com PyInstaller (sys.frozen).
    Previne acúmulo de pastas temporárias após atualizações ou ciclos de
    pause/resume (que matam subprocessos sem o cleanup do bootloader rodar).

    Usa rename+rmtree para não tocar em bundles de outros processos
    PyInstaller ainda ativos — se algum arquivo interno estiver aberto por
    outro processo, o rename falha e a pasta é deixada intacta.
    """
    if not getattr(sys, "frozen", False):
        return

    current_meipass = getattr(sys, "_MEIPASS", None)
    current_meipass_norm = (
        os.path.normpath(current_meipass) if current_meipass else None
    )

    candidates_dirs = [os.path.dirname(sys.executable)]
    try:
        import tempfile
        candidates_dirs.append(tempfile.gettempdir())
    except Exception:
        pass

    for parent in candidates_dirs:
        if not parent or not os.path.isdir(parent):
            continue
        try:
            entries = os.listdir(parent)
        except OSError:
            continue
        for entry in entries:
            if not entry.startswith("_MEI"):
                continue
            entry_path = os.path.join(parent, entry)
            if not os.path.isdir(entry_path):
                continue
            if (
                current_meipass_norm
                and os.path.normpath(entry_path) == current_meipass_norm
            ):
                continue
            # rename → rmtree: rename falha se algum arquivo dentro estiver
            # aberto por outro processo, evitando corromper bundles ativos.
            purge_path = entry_path + ".purge"
            try:
                os.rename(entry_path, purge_path)
            except OSError:
                continue
            try:
                shutil.rmtree(purge_path, onexc=_handle_rmtree_error)
            except Exception:
                pass


def cleanup_temp_dir(part_dir: str) -> None:
    """Remove diretório temporário de partes. Silencioso em caso de erro."""
    try:
        if os.path.exists(part_dir):
            shutil.rmtree(part_dir, ignore_errors=True)
        # Remover TEMP_DIR pai se ficou vazio
        if os.path.exists(TEMP_DIR) and not os.listdir(TEMP_DIR):
            os.rmdir(TEMP_DIR)
    except OSError:
        pass


# ---------------------------------------------------------------------------
# Checksum
# ---------------------------------------------------------------------------

def compute_sha256(
    path: str,
    stop_event: threading.Event,
    log_fn: Optional[Callable] = None,
) -> Optional[str]:
    """
    Calcula o hash SHA-256 de um arquivo com reporte de progresso.

    Parâmetros:
        path       : caminho do arquivo
        stop_event : sinaliza cancelamento
        log_fn     : callback(msg, level) para progresso; opcional

    Retorna:
        hexdigest em minúsculas, ou None se cancelado/erro.
    """
    chunk_size = 4 * 1024 * 1024  # 4 MB por leitura
    h = hashlib.sha256()
    try:
        file_size = os.path.getsize(path)
        processed = 0
        last_pct = 0

        with open(path, "rb") as f:
            while True:
                if stop_event.is_set():
                    return None
                chunk = f.read(chunk_size)
                if not chunk:
                    break
                h.update(chunk)
                processed += len(chunk)

                # Ceder tempo para outras threads (evita micro-stuttering em IO pesado)
                import time
                time.sleep(0.001)

                if file_size > 0 and log_fn:
                    pct = int((processed / file_size) * 100)
                    if pct >= last_pct + 5:
                        log_fn(f"Verificando checksum: {pct}%", "info")
                        last_pct = pct

        return h.hexdigest()
    except OSError as e:
        if log_fn:
            log_fn(f"Erro ao calcular checksum: {e}", "error")
        return None
