"""Which window is in the foreground, and is it Telegram (Desktop or Web)."""

from __future__ import annotations

import ctypes
from ctypes import wintypes
from typing import Iterable, Optional

from . import winapi as w

# Telegram Desktop and its forks: same Qt text field, same theme colours
DEFAULT_TARGETS = ("telegram.exe", "ayugram.exe", "kotatogram.exe", "64gram.exe")
# Browsers that may show Telegram Web; "browser.exe" is Yandex Browser
BROWSERS = ("chrome.exe", "msedge.exe", "firefox.exe", "browser.exe", "opera.exe",
            "brave.exe", "vivaldi.exe")
# Addresses of Telegram Web: the only pages where keys are used
WEB_HOSTS = ("web.telegram.org", "webk.telegram.org", "webz.telegram.org")


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


def window_title(hwnd: Optional[int]) -> str:
    if not hwnd:
        return ""
    buf = ctypes.create_unicode_buffer(512)
    return buf.value if w.GetWindowTextW(hwnd, buf, len(buf)) > 0 else ""


def is_web_title(title: str) -> bool:
    """Could the browser be showing Telegram Web? Only a first, cheap filter:
    the page address is checked later through UI Automation (positioning)."""
    return "telegram" in title.lower()


class WindowWatch:
    """Answers "is this window Telegram?" and remembers the last answer.

    A Telegram Desktop window always is. A browser window is when Telegram Web
    is allowed (``web``) and the title of its open tab mentions Telegram; the
    title is read on every call because switching tabs keeps the window.

    Not thread-safe: every thread that needs it keeps its own instance.
    """

    def __init__(self, targets: Iterable[str] = DEFAULT_TARGETS,
                 browsers: Iterable[str] = BROWSERS, web: bool = True) -> None:
        self._targets = frozenset(t.lower() for t in targets)
        self._browsers = frozenset(b.lower() for b in browsers)
        # Written by the Qt thread when the setting changes, read here: a
        # plain attribute, atomic under the GIL.
        self.web = web
        self._hwnd: Optional[int] = None
        self._pid = 0
        self._kind = ""

    def kind(self, hwnd: Optional[int]) -> str:
        """"app" (Telegram Desktop), "browser" or "" for anything else."""
        if not hwnd:
            return ""
        _, pid = window_ids(hwnd)
        if hwnd != self._hwnd or pid != self._pid:
            self._hwnd = hwnd
            self._pid = pid
            name = process_name(pid)
            self._kind = ("app" if name in self._targets
                          else "browser" if name in self._browsers else "")
        return self._kind

    def is_browser(self, hwnd: Optional[int]) -> bool:
        return self.web and self.kind(hwnd) == "browser"

    def is_target(self, hwnd: Optional[int]) -> bool:
        kind = self.kind(hwnd)
        if kind == "app":
            return True
        return kind == "browser" and self.web and is_web_title(window_title(hwnd))

    def check(self) -> tuple[Optional[int], bool]:
        """(foreground window, is it Telegram)."""
        hwnd = w.GetForegroundWindow()
        return hwnd, self.is_target(hwnd)
