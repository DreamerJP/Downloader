"""
core/secret_store.py
Proteção de segredos gravados nas configurações (senha, proxy com senha) via
DPAPI do Windows: só o mesmo usuário do Windows consegue ler de volta.
Sem dependências de PyQt6.
"""

import base64
import ctypes
import sys
from ctypes import wintypes

_PREFIX = "dpapi:"
_CRYPTPROTECT_UI_FORBIDDEN = 0x1


class _Blob(ctypes.Structure):
    _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]


def _api():
    crypt32 = ctypes.WinDLL("crypt32")
    kernel32 = ctypes.WinDLL("kernel32")
    for fn in (crypt32.CryptProtectData, crypt32.CryptUnprotectData):
        fn.argtypes = [
            ctypes.POINTER(_Blob), ctypes.c_void_p, ctypes.POINTER(_Blob),
            ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(_Blob),
        ]
        fn.restype = wintypes.BOOL
    kernel32.LocalFree.argtypes = [ctypes.c_void_p]
    kernel32.LocalFree.restype = ctypes.c_void_p
    return crypt32, kernel32


def _run(fn_name: str, data: bytes) -> bytes | None:
    crypt32, kernel32 = _api()
    buf = ctypes.create_string_buffer(data, len(data))
    blob_in = _Blob(len(data), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char)))
    blob_out = _Blob()
    fn = getattr(crypt32, fn_name)
    if not fn(ctypes.byref(blob_in), None, None, None, None,
              _CRYPTPROTECT_UI_FORBIDDEN, ctypes.byref(blob_out)):
        return None
    try:
        return ctypes.string_at(blob_out.pbData, blob_out.cbData)
    finally:
        kernel32.LocalFree(ctypes.cast(blob_out.pbData, ctypes.c_void_p))


def is_protected(stored: str) -> bool:
    return bool(stored) and stored.startswith(_PREFIX)


def protect(text: str) -> str:
    """Cifra `text` para gravação. Vazio continua vazio."""
    if not text or sys.platform != "win32":
        return text or ""
    raw = _run("CryptProtectData", text.encode("utf-8"))
    if raw is None:
        raise OSError("Windows recusou cifrar o valor (CryptProtectData).")
    return _PREFIX + base64.b64encode(raw).decode("ascii")


def unprotect(stored: str) -> str:
    """
    Devolve o texto original. Valor sem o prefixo é de versão antiga (texto
    puro) e volta como está; valor que este usuário não consegue decifrar
    (ex.: registro copiado de outra conta) volta vazio.
    """
    if not stored:
        return ""
    if not is_protected(stored) or sys.platform != "win32":
        return stored
    try:
        raw = _run("CryptUnprotectData", base64.b64decode(stored[len(_PREFIX):]))
    except (ValueError, OSError):
        return ""
    return raw.decode("utf-8") if raw is not None else ""
