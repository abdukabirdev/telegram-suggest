"""One running copy of the program, and what a second launch does.

A second launch does not show "already running": it asks the running copy to
open its window and quits. If the second launch is a newer version (the user
downloaded a new .exe), it asks the old copy to close and takes its place;
the dictionary and settings live in %APPDATA% and stay as they are.

Everything goes through named kernel objects of the current session:

    <name>          mutex: exists while a copy runs
    <name>.Info     shared memory: process id and version of the running copy
    <name>.Show     event: "open your window"
    <name>.Quit     event: "close, a newer version is starting"
"""

from __future__ import annotations

import ctypes
import logging
import os
import threading
from ctypes import wintypes
from dataclasses import dataclass
from typing import Callable, Optional

log = logging.getLogger(__name__)

_k32 = ctypes.WinDLL("kernel32", use_last_error=True)

ERROR_ALREADY_EXISTS = 183
INVALID_HANDLE_VALUE = wintypes.HANDLE(-1).value
PAGE_READWRITE = 0x04
FILE_MAP_ALL_ACCESS = 0x000F001F
SYNCHRONIZE = 0x00100000
WAIT_OBJECT_0 = 0
WAIT_TIMEOUT = 0x102
INFINITE = 0xFFFFFFFF
_INFO_SIZE = 256


def _proto(func, restype, *argtypes):
    func.restype = restype
    func.argtypes = argtypes
    return func


_CreateMutexW = _proto(_k32.CreateMutexW, wintypes.HANDLE,
                       wintypes.LPVOID, wintypes.BOOL, wintypes.LPCWSTR)
_CreateEventW = _proto(_k32.CreateEventW, wintypes.HANDLE,
                       wintypes.LPVOID, wintypes.BOOL, wintypes.BOOL, wintypes.LPCWSTR)
_SetEvent = _proto(_k32.SetEvent, wintypes.BOOL, wintypes.HANDLE)
_CreateFileMappingW = _proto(_k32.CreateFileMappingW, wintypes.HANDLE,
                             wintypes.HANDLE, wintypes.LPVOID, wintypes.DWORD,
                             wintypes.DWORD, wintypes.DWORD, wintypes.LPCWSTR)
_MapViewOfFile = _proto(_k32.MapViewOfFile, wintypes.LPVOID, wintypes.HANDLE,
                        wintypes.DWORD, wintypes.DWORD, wintypes.DWORD, ctypes.c_size_t)
_UnmapViewOfFile = _proto(_k32.UnmapViewOfFile, wintypes.BOOL, wintypes.LPCVOID)
_OpenProcess = _proto(_k32.OpenProcess, wintypes.HANDLE,
                      wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
_WaitForSingleObject = _proto(_k32.WaitForSingleObject, wintypes.DWORD,
                              wintypes.HANDLE, wintypes.DWORD)
_WaitForMultipleObjects = _proto(_k32.WaitForMultipleObjects, wintypes.DWORD,
                                 wintypes.DWORD, ctypes.POINTER(wintypes.HANDLE),
                                 wintypes.BOOL, wintypes.DWORD)
_CloseHandle = _proto(_k32.CloseHandle, wintypes.BOOL, wintypes.HANDLE)


def parse_version(text: str) -> tuple[int, ...]:
    """"0.10.2" -> (0, 10, 2); anything unreadable counts as the oldest."""
    parts = []
    for piece in str(text).strip().split("."):
        digits = "".join(ch for ch in piece if ch.isdigit())
        if not digits:
            break
        parts.append(int(digits))
    return tuple(parts) or (0,)


def is_newer(mine: str, theirs: str) -> bool:
    return parse_version(mine) > parse_version(theirs)


@dataclass(frozen=True)
class Running:
    pid: int
    version: str


class SingleInstance:
    """Create once at start-up and keep until the process ends."""

    def __init__(self, name: str) -> None:
        self.name = name
        self._mutex = _CreateMutexW(None, False, name)
        self.first = ctypes.get_last_error() != ERROR_ALREADY_EXISTS
        self._show = _CreateEventW(None, False, False, name + ".Show")
        self._quit = _CreateEventW(None, False, False, name + ".Quit")
        self._mapping = _CreateFileMappingW(INVALID_HANDLE_VALUE, None, PAGE_READWRITE,
                                            0, _INFO_SIZE, name + ".Info")
        self._stop = _CreateEventW(None, True, False, None)
        self._thread: Optional[threading.Thread] = None

    # ---- shared info ---------------------------------------------------------

    def _view(self):
        if not self._mapping:
            return None
        return _MapViewOfFile(self._mapping, FILE_MAP_ALL_ACCESS, 0, 0, _INFO_SIZE)

    def publish(self, version: str) -> None:
        """Tell later launches who is running."""
        view = self._view()
        if not view:
            return
        try:
            data = f"{os.getpid()} {version}".encode("ascii", "replace")[:_INFO_SIZE - 1]
            ctypes.memset(view, 0, _INFO_SIZE)
            ctypes.memmove(view, data, len(data))
        finally:
            _UnmapViewOfFile(view)

    def running(self) -> Optional[Running]:
        view = self._view()
        if not view:
            return None
        try:
            text = ctypes.string_at(view, _INFO_SIZE).split(b"\0", 1)[0].decode("ascii", "replace")
        finally:
            _UnmapViewOfFile(view)
        pid, _, version = text.partition(" ")
        if not pid.isdigit():
            return None             # an older copy that does not publish itself
        return Running(int(pid), version)

    # ---- second launch -------------------------------------------------------

    def ask_show(self) -> None:
        if self._show:
            _SetEvent(self._show)

    def replace_running(self, timeout_s: float = 15.0) -> bool:
        """Ask the running copy to close and wait for it. True when it is gone."""
        other = self.running()
        if other is None or not self._quit:
            return False
        process = _OpenProcess(SYNCHRONIZE, False, other.pid)
        if not process:
            return False
        try:
            _SetEvent(self._quit)
            gone = _WaitForSingleObject(process, int(timeout_s * 1000)) == WAIT_OBJECT_0
        finally:
            _CloseHandle(process)
        if gone:
            self.first = True       # our handles keep the mutex and the info alive
        return gone

    # ---- the running copy ----------------------------------------------------

    def listen(self, on_show: Callable[[], None], on_quit: Callable[[], None]) -> None:
        """Call ``on_show``/``on_quit`` (from a background thread) on requests."""
        if not (self._show and self._quit and self._stop):
            return
        handles = (wintypes.HANDLE * 3)(self._stop, self._show, self._quit)

        def run() -> None:
            while True:
                result = _WaitForMultipleObjects(3, handles, False, INFINITE)
                if result == WAIT_OBJECT_0 + 1:
                    on_show()
                elif result == WAIT_OBJECT_0 + 2:
                    on_quit()
                else:
                    return

        self._thread = threading.Thread(target=run, name="instance", daemon=True)
        self._thread.start()

    def close(self) -> None:
        if self._stop:
            _SetEvent(self._stop)
        if self._thread is not None:
            self._thread.join(1.0)
        for handle in (self._stop, self._show, self._quit, self._mapping, self._mutex):
            if handle:
                _CloseHandle(handle)
        self._stop = self._show = self._quit = self._mapping = self._mutex = None
