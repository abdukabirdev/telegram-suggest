"""Low-level keyboard hook (WH_KEYBOARD_LL) in its own thread.

The callback runs inside the system input path, so it does the bare minimum:
decide whether the key concerns us, put a small tuple into a queue and
return. All real work happens in the worker thread.

Privacy: while the foreground window is not Telegram the callback returns
before looking at which key was pressed (the only exception is Caps Lock,
whose on/off state has to be tracked to know the letter case later).
"""

from __future__ import annotations

import ctypes
import logging
import threading
import time
from ctypes import wintypes
from typing import Callable, Optional

from . import winapi as w

log = logging.getLogger(__name__)

_MODIFIER_VKS = frozenset({
    w.VK_SHIFT, w.VK_CONTROL, w.VK_MENU,
    w.VK_LSHIFT, w.VK_RSHIFT, w.VK_LCONTROL, w.VK_RCONTROL,
    w.VK_LMENU, w.VK_RMENU, w.VK_LWIN, w.VK_RWIN,
})
_VK_1 = 0x31
_WM_REINSTALL = w.WM_APP + 1
_HOTKEY_PAUSE = 1

# Event tuples put into the sink:
#   ("key", vk, scan, shift, ctrl, alt, win, caps, action, hwnd)
#       action: None | ("accept", index) | ("dismiss",)
#   ("focus", active, hwnd)
Sink = Callable[[tuple], None]


class KeyboardHook(threading.Thread):
    def __init__(
        self,
        sink: Sink,
        is_target: Callable[[Optional[int]], bool],
        on_pause_hotkey: Optional[Callable[[], None]] = None,
        foreground: Callable[[], Optional[int]] = w.GetForegroundWindow,
        key_down: Callable[[int], bool] = w.key_down,
    ) -> None:
        super().__init__(name="kbd-hook", daemon=True)
        self._sink = sink
        self._is_target = is_target
        self._on_pause_hotkey = on_pause_hotkey
        self._foreground = foreground
        self._key_down = key_down

        # Written by other threads, read by the callback (plain attribute
        # reads and writes are atomic under the GIL).
        self.visible_count = 0      # how many suggestions are on screen now
        self.paused = False

        self.last_callback = 0.0    # time.monotonic() of the last callback
        self.installed = threading.Event()
        self.hotkey_ok = False

        self._fg: Optional[int] = None
        self._active = False
        self._caps = False
        self._caps_held = False
        self._swallowed: set[int] = set()
        self._hook = None
        self._thread_id = 0
        self._proc = w.HOOKPROC(self._callback)   # keep a reference alive
        self._errors = 0

    # ---- thread ------------------------------------------------------------

    def run(self) -> None:
        self._thread_id = w.GetCurrentThreadId()
        self._caps = bool(w.GetKeyState(w.VK_CAPITAL) & 1)
        self._install()
        if self._on_pause_hotkey is not None:
            self.hotkey_ok = bool(w.RegisterHotKey(
                None, _HOTKEY_PAUSE, w.MOD_CONTROL | w.MOD_ALT | w.MOD_NOREPEAT, ord("P")
            ))
            if not self.hotkey_ok:
                log.warning("pause hotkey is taken by another program")
        self.installed.set()
        msg = wintypes.MSG()
        try:
            while True:
                result = w.GetMessageW(ctypes.byref(msg), None, 0, 0)
                if result in (0, -1):
                    break
                if msg.message == w.WM_HOTKEY and msg.wParam == _HOTKEY_PAUSE:
                    try:
                        self._on_pause_hotkey()
                    except Exception:
                        log.exception("pause hotkey handler failed")
                elif msg.message == _WM_REINSTALL:
                    self._uninstall()
                    self._install()
        finally:
            if self.hotkey_ok:
                w.UnregisterHotKey(None, _HOTKEY_PAUSE)
            self._uninstall()

    def stop(self) -> None:
        if self._thread_id:
            w.PostThreadMessageW(self._thread_id, w.WM_QUIT, 0, 0)

    def reinstall(self) -> None:
        """Windows silently drops a hook that once answered too slowly."""
        if self._thread_id:
            w.PostThreadMessageW(self._thread_id, _WM_REINSTALL, 0, 0)

    def _install(self) -> None:
        self._hook = w.SetWindowsHookExW(
            w.WH_KEYBOARD_LL, self._proc, w.GetModuleHandleW(None), 0
        )
        if not self._hook:
            log.error("SetWindowsHookExW failed: %s", ctypes.get_last_error())
        self.last_callback = time.monotonic()

    def _uninstall(self) -> None:
        if self._hook:
            w.UnhookWindowsHookEx(self._hook)
            self._hook = None

    # ---- callback ----------------------------------------------------------

    def _callback(self, n_code: int, w_param: int, l_param: int) -> int:
        try:
            if n_code == w.HC_ACTION:
                self.last_callback = time.monotonic()
                kb = w.KBDLLHOOKSTRUCT.from_address(l_param)
                if kb.dwExtraInfo != w.INJECT_TAG:
                    down = w_param == w.WM_KEYDOWN or w_param == w.WM_SYSKEYDOWN
                    if self.handle(kb.vkCode, kb.scanCode, down):
                        return 1
        except Exception:
            # Never let an exception escape into the system input path.
            self._errors += 1
            if self._errors <= 5:
                log.exception("hook callback failed")
        return w.CallNextHookEx(None, n_code, w_param, l_param)

    def handle(self, vk: int, scan: int, down: bool) -> bool:
        """Process one physical key event. True means: swallow it."""
        if vk == w.VK_CAPITAL:
            if not down:
                self._caps_held = False
            elif not self._caps_held:
                self._caps_held = True
                self._caps = not self._caps
            return False

        if not down:
            if vk in self._swallowed:
                self._swallowed.discard(vk)
                return True
            return False
        if vk in self._swallowed:
            return True                    # auto-repeat of a key we took
        if self.paused or vk in _MODIFIER_VKS:
            return False

        hwnd = self._foreground()
        if hwnd != self._fg:
            self._fg = hwnd
            active = self._is_target(hwnd)
            if active != self._active:
                self._active = active
                self._sink(("focus", active, hwnd))
        if not self._active:
            return False

        key_down = self._key_down
        shift = key_down(w.VK_SHIFT)
        ctrl = key_down(w.VK_CONTROL)
        alt = key_down(w.VK_MENU)
        win = key_down(w.VK_LWIN) or key_down(w.VK_RWIN)

        action = None
        count = self.visible_count
        if count and not alt and not win and not shift:
            if ctrl:
                index = vk - _VK_1
                if 0 <= index < min(count, 9):
                    action = ("accept", index)
            elif vk == w.VK_TAB:
                action = ("accept", 0)
            elif vk == w.VK_ESCAPE:
                action = ("dismiss",)
        if action is not None:
            self._swallowed.add(vk)

        self._sink(("key", vk, scan, shift, ctrl, alt, win, self._caps, action, hwnd))
        return action is not None
