"""Key code -> character, honouring the keyboard layout of the target window.

The hook reports virtual key codes. What character a key produces depends on
the layout active in the thread that owns the Telegram window, so we ask
Windows (ToUnicodeEx) with that thread's layout instead of guessing.
"""

from __future__ import annotations

import ctypes
from typing import Optional

from . import winapi as w

# ToUnicodeEx flag (Windows 10 1607+): do not touch the kernel keyboard state,
# otherwise dead keys typed by the user would be eaten by our lookup.
_NO_STATE_CHANGE = 0x4


def installed_layouts() -> list[int]:
    count = w.GetKeyboardLayoutList(0, None)
    if count <= 0:
        return []
    arr = (w.HKL * count)()
    count = w.GetKeyboardLayoutList(count, arr)
    return [int(h or 0) for h in arr[:count]]


def layout_name(hkl: int) -> str:
    """Human-readable layout tag such as 'ru-RU', 'en-US', 'uz-Cyrl-UZ'."""
    lang = int(hkl or 0) & 0xFFFF
    if not lang:
        return "?"
    buf = ctypes.create_unicode_buffer(85)
    if w.LCIDToLocaleName(lang, buf, len(buf), 0) > 0:
        return buf.value
    return f"0x{lang:04x}"


class KeyTranslator:
    """Not thread-safe: owned by the worker thread."""

    def __init__(self) -> None:
        self._state = (ctypes.c_ubyte * 256)()
        self._buf = ctypes.create_unicode_buffer(16)
        self.last_layout = 0

    def layout_of_window(self, hwnd: Optional[int]) -> int:
        tid = w.GetWindowThreadProcessId(hwnd, None) if hwnd else 0
        hkl = int(w.GetKeyboardLayout(tid) or 0)
        self.last_layout = hkl
        return hkl

    def translate(self, vk: int, scan: int, shift: bool, caps: bool,
                  altgr: bool, hkl: int) -> str:
        """Characters the key types, '' for keys that type nothing."""
        state = self._state
        state[w.VK_SHIFT] = 0x80 if shift else 0
        state[w.VK_CAPITAL] = 0x01 if caps else 0
        mod = 0x80 if altgr else 0
        state[w.VK_CONTROL] = mod
        state[w.VK_MENU] = mod
        n = w.ToUnicodeEx(vk, scan, state, self._buf, len(self._buf),
                          _NO_STATE_CHANGE, hkl)
        if n <= 0:
            return ""          # no character, or a dead key
        text = self._buf[:n]
        for ch in text:
            if ch < " " or ch == "\x7f":
                return ""      # control characters are not text
        return text
