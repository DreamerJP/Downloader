"""
core/windows_taskbar.py
Integração opcional com a barra de tarefas do Windows.
"""

import ctypes
import sys
import uuid
from ctypes import wintypes


class _GUID(ctypes.Structure):
    _fields_ = [
        ("Data1", wintypes.DWORD),
        ("Data2", wintypes.WORD),
        ("Data3", wintypes.WORD),
        ("Data4", ctypes.c_ubyte * 8),
    ]


def _guid(value: str) -> _GUID:
    return _GUID.from_buffer_copy(uuid.UUID(value).bytes_le)


class WindowsTaskbarProgress:
    """Wrapper mínimo de ITaskbarList3 para progresso no ícone da taskbar."""

    TBPF_NOPROGRESS = 0
    TBPF_INDETERMINATE = 1
    TBPF_NORMAL = 2
    TBPF_ERROR = 4
    TBPF_PAUSED = 8

    CLSCTX_INPROC_SERVER = 1

    CLSID_TASKBAR_LIST = _guid("56FDF344-FD6D-11D0-958A-006097C9A090")
    IID_ITASKBAR_LIST3 = _guid("EA1AFB91-9E28-4B86-90E9-9E9F8A5EEFAF")

    def __init__(self) -> None:
        self._hwnd = 0
        self._taskbar = ctypes.c_void_p()
        self._available = False

    def initialize(self, hwnd: int) -> None:
        if sys.platform != "win32" or not hwnd:
            return

        self._hwnd = int(hwnd)
        try:
            ole32 = ctypes.WinDLL("ole32")
            ole32.CoCreateInstance.restype = ctypes.c_long
            ole32.CoCreateInstance.argtypes = [
                ctypes.POINTER(_GUID),
                ctypes.c_void_p,
                wintypes.DWORD,
                ctypes.POINTER(_GUID),
                ctypes.POINTER(ctypes.c_void_p),
            ]
            ole32.CoInitialize(None)
            hr = ole32.CoCreateInstance(
                ctypes.byref(self.CLSID_TASKBAR_LIST),
                None,
                self.CLSCTX_INPROC_SERVER,
                ctypes.byref(self.IID_ITASKBAR_LIST3),
                ctypes.byref(self._taskbar),
            )
            if hr != 0 or not self._taskbar:
                return

            self._call(3, ctypes.c_long)
            self._available = True
        except Exception:
            self._available = False

    def set_progress(self, ratio: float, paused: bool = False) -> None:
        if not self._available:
            return
        value = max(0, min(int(float(ratio) * 1000), 1000))
        state = self.TBPF_PAUSED if paused else self.TBPF_NORMAL
        try:
            self._call(
                9,
                ctypes.c_long,
                wintypes.HWND,
                ctypes.c_ulonglong,
                ctypes.c_ulonglong,
                self._hwnd,
                value,
                1000,
            )
            self._set_state(state)
        except Exception:
            self._available = False

    def set_indeterminate(self) -> None:
        self._set_state(self.TBPF_INDETERMINATE)

    def set_error(self) -> None:
        self._set_state(self.TBPF_ERROR)

    def clear(self) -> None:
        self._set_state(self.TBPF_NOPROGRESS)

    def _set_state(self, state: int) -> None:
        if not self._available:
            return
        try:
            self._call(10, ctypes.c_long, wintypes.HWND, ctypes.c_int, self._hwnd, state)
        except Exception:
            self._available = False

    def _call(self, index: int, restype, *argtypes_and_values):
        argtypes = argtypes_and_values[: len(argtypes_and_values) // 2]
        values = argtypes_and_values[len(argtypes_and_values) // 2 :]
        vtable = ctypes.cast(
            self._taskbar, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))
        ).contents
        prototype = getattr(ctypes, "WINFUNCTYPE", ctypes.CFUNCTYPE)
        method = prototype(restype, ctypes.c_void_p, *argtypes)(vtable[index])
        return method(self._taskbar, *values)
