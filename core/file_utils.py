"""
core/file_utils.py
Utilitários de sistema de arquivos: merge de partes, checksum, limpeza de temporários.
Sem dependências de PyQt6.
"""

import hashlib
import mmap
import os
import shutil
import stat
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from typing import Callable, Optional
from urllib.parse import urlparse

from core.constants import TEMP_DIR, VIDEO_EXTENSIONS


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
        base = os.path.abspath(".")
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


# ---------------------------------------------------------------------------
# Merge de partes
# ---------------------------------------------------------------------------

def merge_parts(
    output_path: str,
    parts_count: int,
    part_dir: str,
    stop_event: threading.Event,
    log_fn: Optional[Callable] = None,
) -> bool:
    """
    Une partes sequenciais (part.0, part.1, …) em um arquivo final.

    Estratégia:
    - Usa mmap para partes > 10 MB (reduz syscalls).
    - Buffer de escrita de 64 MB para minimizar operações de disco.
    - Verifica stop_event entre cada parte.

    Retorna True em sucesso, False se alguma parte está ausente ou em erro.
    """
    if log_fn:
        log_fn("Unindo partes do arquivo...", "info")

    part_files: list[tuple[str, int]] = []
    for i in range(parts_count):
        path = os.path.join(part_dir, f"part.{i}")
        if not os.path.exists(path):
            if log_fn:
                log_fn(f"Parte {i} não encontrada: {path}", "error")
            return False
        part_files.append((path, os.path.getsize(path)))

    read_chunk = 64 * 1024 * 1024  # 64 MB
    total_written = 0

    try:
        with open(output_path, "wb") as out:
            for part_path, part_size in part_files:
                if stop_event.is_set():
                    return False
                with open(part_path, "rb") as pf:
                    if part_size > 10 * 1024 * 1024:
                        try:
                            with mmap.mmap(pf.fileno(), 0, access=mmap.ACCESS_READ) as mm:
                                remaining = part_size
                                while remaining > 0 and not stop_event.is_set():
                                    chunk = mm.read(min(read_chunk, remaining))
                                    if not chunk:
                                        break
                                    out.write(chunk)
                                    total_written += len(chunk)
                                    remaining -= len(chunk)
                        except (mmap.error, OSError):
                            # Fallback sem mmap
                            pf.seek(0)
                            shutil.copyfileobj(pf, out, length=read_chunk)
                    else:
                        shutil.copyfileobj(pf, out, length=read_chunk)

            out.flush()
            os.fsync(out.fileno())

        if log_fn:
            mb = total_written / (1024 * 1024)
            log_fn(f"União completa: {mb:.1f} MB", "success")
        return True

    except OSError as e:
        if log_fn:
            log_fn(f"Erro ao unir partes: {e}", "error")
        return False


def merge_parts_smart(
    output_path: str,
    parts_count: int,
    part_dir: str,
    stop_event: threading.Event,
    log_fn: Optional[Callable] = None,
    memory_limit_mb: int = 500,
) -> bool:
    """
    Escolhe entre merge em memória (rápido) ou sequencial (conservador).

    Para arquivos pequenos (< memory_limit_mb), carrega tudo em RAM e escreve
    de uma vez — elimina o tempo de merge. Para arquivos grandes, usa merge
    sequencial com mmap.
    """
    total = sum(
        os.path.getsize(os.path.join(part_dir, f"part.{i}"))
        for i in range(parts_count)
        if os.path.exists(os.path.join(part_dir, f"part.{i}"))
    )

    if total <= memory_limit_mb * 1024 * 1024:
        return _merge_in_memory(output_path, parts_count, part_dir, stop_event, log_fn)

    return merge_parts(output_path, parts_count, part_dir, stop_event, log_fn)


def _merge_in_memory(
    output_path: str,
    parts_count: int,
    part_dir: str,
    stop_event: threading.Event,
    log_fn: Optional[Callable] = None,
) -> bool:
    """Carrega todas as partes em RAM e escreve em uma operação."""
    if log_fn:
        log_fn(f"Carregando {parts_count} partes na memória...", "info")
    try:
        parts_data: list[bytes] = []
        for i in range(parts_count):
            if stop_event.is_set():
                return False
            path = os.path.join(part_dir, f"part.{i}")
            with open(path, "rb") as f:
                parts_data.append(f.read())

        if log_fn:
            log_fn("Escrevendo arquivo final...", "info")
        with open(output_path, "wb") as out:
            for data in parts_data:
                out.write(data)
            out.flush()
            os.fsync(out.fileno())

        total_mb = sum(len(d) for d in parts_data) / (1024 * 1024)
        if log_fn:
            log_fn(f"Merge em memória concluído: {total_mb:.1f} MB", "success")
        return True
    except OSError as e:
        if log_fn:
            log_fn(f"Erro no merge em memória: {e}", "error")
        return False
