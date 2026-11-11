"""Which window is in the foreground, and does it belong to Telegram Desktop."""

from __future__ import annotations

import ctypes
from ctypes import wintypes
from typing import Iterable, Optional

from . import winapi as w

DEFAULT_TARGETS = ("telegram.exe",)


def window_ids(hwnd: Optional[int]) -> tuple[int, int]:
    """(thread id, process id) of the window, zeros if it is gone."""
    if not hwnd:
        return 0, 0
    pid = wintypes.DWORD(0)
    tid = w.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    return tid, pid.value


def process_name(pid: int) -> str:
    """Lowercase file name of the process executable, '' if not accessible."""
    if not pid:
        return ""
    handle = w.OpenProcess(w.PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not handle:
        return ""
    try:
        size = wintypes.DWORD(1024)
        buf = ctypes.create_unicode_buffer(size.value)
        if not w.QueryFullProcessImageNameW(handle, 0, buf, ctypes.byref(size)):
            return ""
        return buf.value.rsplit("\\", 1)[-1].lower()
    finally:
        w.CloseHandle(handle)


def window_rect(hwnd: int) -> Optional[tuple[int, int, int, int]]:
    """Client area of the window in screen pixels: (left, top, right, bottom)."""
    rect = wintypes.RECT()
    if not hwnd or not w.GetClientRect(hwnd, ctypes.byref(rect)):
        return None
    origin = wintypes.POINT(0, 0)
    if not w.ClientToScreen(hwnd, ctypes.byref(origin)):
        return None
    return (origin.x, origin.y, origin.x + rect.right, origin.y + rect.bottom)


class WindowWatch:
    """Answers "is this window Telegram?" and remembers the last answer.

    Not thread-safe: every thread that needs it keeps its own instance.
    """

    def __init__(self, targets: Iterable[str] = DEFAULT_TARGETS) -> None:
        self._targets = frozenset(t.lower() for t in targets)
        self._hwnd: Optional[int] = None
        self._pid = 0
        self._result = False

    def is_target(self, hwnd: Optional[int]) -> bool:
        if not hwnd:
            return False
        _, pid = window_ids(hwnd)
        if hwnd == self._hwnd and pid == self._pid:
            return self._result
        self._hwnd = hwnd
        self._pid = pid
        self._result = process_name(pid) in self._targets
        return self._result

    def check(self) -> tuple[Optional[int], bool]:
        """(foreground window, is it Telegram)."""
        hwnd = w.GetForegroundWindow()
        return hwnd, self.is_target(hwnd)
