"""The worker thread: key events -> engine -> suggestions and insertion.

Everything that touches the Engine and the Lexicon during normal work runs
here, one event at a time, so the engine needs no locking of its own and the
keyboard hook never waits for anything.
"""

from __future__ import annotations

import logging
import queue
import threading
import time
from typing import Callable, Optional

from . import winapi as w
from .engine import Engine
from .keymap import layout_name
from .lexicon import Lexicon

log = logging.getLogger(__name__)

# Keys that move the caret or change the text in ways we cannot follow.
_RESET_VKS = frozenset({
    w.VK_TAB, w.VK_ESCAPE, w.VK_LEFT, w.VK_RIGHT, w.VK_UP, w.VK_DOWN,
    w.VK_HOME, w.VK_END, w.VK_PRIOR, w.VK_NEXT, w.VK_DELETE, w.VK_INSERT,
    w.VK_APPS,
})
_VK_C = 0x43
_BULLET = "•"      # stands for one non-letter character (an emoji)


class EngineWorker(threading.Thread):
    def __init__(
        self,
        engine: Engine,
        lexicon: Lexicon,
        translator,
        *,
        insert: Callable[[int, str], bool],
        foreground_is_target: Callable[[], bool],
        set_visible: Callable[[int], None],
        on_update: Callable[[list], None],
        on_word_start: Optional[Callable[[Optional[int]], None]] = None,
        on_diag: Optional[Callable[[dict], None]] = None,
        idle_flush: float = 2.0,
        max_dirty: float = 15.0,
    ) -> None:
        super().__init__(name="engine-worker", daemon=True)
        self.engine = engine
        self.lexicon = lexicon
        self.translator = translator
        self._insert = insert
        self._foreground_is_target = foreground_is_target
        self._set_visible = set_visible
        self._on_update = on_update
        self._on_word_start = on_word_start
        self._on_diag = on_diag
        self._idle_flush = idle_flush
        self._max_dirty = max_dirty
        self._q: queue.SimpleQueue = queue.SimpleQueue()
        self._paused = False
        self._blocked = False       # focus is in a password field
        self._active = False        # Telegram is in the foreground
        self._hwnd: Optional[int] = None
        self._last_texts: list = []
        self._last_flush = time.monotonic()

    # ---- called from other threads -----------------------------------------

    def post(self, *event) -> None:
        """Queue an event. Safe to call from the hook callback."""
        self._q.put(event)

    def stop(self) -> None:
        self._q.put(("stop",))

    # ---- thread ------------------------------------------------------------

    def run(self) -> None:
        while True:
            try:
                event = self._q.get(timeout=self._idle_flush)
            except queue.Empty:
                self._flush()
                continue
            if event[0] == "stop":
                break
            self.process(event)
            if time.monotonic() - self._last_flush > self._max_dirty:
                self._flush()
        self._flush()

    def process(self, event: tuple) -> None:
        """Handle one event (public so tests can drive it without a thread)."""
        try:
            self._dispatch(event)
            self._publish()
        except Exception:
            # The event itself is never logged: it may contain a typed key.
            log.exception("worker failed on a %r event", event[0])

    def _flush(self) -> None:
        self._last_flush = time.monotonic()
        try:
            self.lexicon.flush()
        except Exception:
            log.exception("saving the dictionary failed")

    # ---- events ------------------------------------------------------------

    def _dispatch(self, event: tuple) -> None:
        kind = event[0]
        if kind == "key":
            if self._paused:
                return
            if self._blocked:
                if event[1] in (w.VK_TAB, w.VK_RETURN, w.VK_ESCAPE) and self._on_word_start:
                    self._on_word_start(event[9])      # maybe the password field was left
                return
            self._set_focus(True, event[9])
            self._on_key(event)
        elif kind == "accept":
            if not self._paused and not self._blocked:
                self._accept(event[1])
        elif kind == "reset":
            self.engine.reset()
        elif kind == "focus":
            self._set_focus(bool(event[1]), event[2] if len(event) > 2 else None)
        elif kind == "pause":
            self._paused = bool(event[1])
            self.engine.reset()
        elif kind == "blocked":
            flag = bool(event[1])
            if flag and not self._blocked:
                self.engine.discard()
            self._blocked = flag
        elif kind == "forget":
            if not self._paused and not self._blocked:
                self.engine.forget(event[1])
        elif kind == "refresh":
            self.engine.invalidate()
        elif kind == "settings":
            self.lexicon.refresh_settings()
            self.engine.invalidate()
        elif kind == "call":
            event[1]()

    def _set_focus(self, active: bool, hwnd: Optional[int]) -> None:
        """Both the hook and the UI timer report focus; act only on a change.

        Otherwise the later of the two reports would wipe a word the user has
        already started typing right after switching to Telegram.
        """
        if not active:
            hwnd = None
        if active == self._active and hwnd == self._hwnd:
            return
        self._active = active
        self._hwnd = hwnd
        self.engine.reset()

    def _on_key(self, event: tuple) -> None:
        _, vk, scan, shift, ctrl, alt, win, caps, action, hwnd = event
        engine = self.engine
        if action is not None:
            if action[0] == "accept":
                self._accept(action[1])
            else:
                engine.dismiss()
            return
        if win or (alt and not ctrl):
            engine.reset()
            return
        if ctrl and not alt:
            if vk != _VK_C:               # copying changes nothing
                engine.reset()            # Ctrl+A/V/X/Z, Ctrl+Backspace, Ctrl+arrows...
            return
        if vk == w.VK_BACK:
            engine.backspace()
            return
        if vk == w.VK_RETURN:
            engine.feed("\n")
            return
        if vk in _RESET_VKS:
            engine.reset()
            return
        if vk == w.VK_PACKET:
            # Unicode character injected by another program (emoji panel,
            # on-screen keyboard); the scan code carries a UTF-16 code unit.
            if 0xDC00 <= scan <= 0xDFFF:
                return                    # second half of a surrogate pair
            text = _BULLET if 0xD800 <= scan <= 0xDBFF else chr(scan)
            if text < " ":
                return
        else:
            hkl = self.translator.layout_of_window(hwnd)
            text = self.translator.translate(vk, scan, shift, caps, ctrl and alt, hkl)
        if not text:
            return
        was_empty = not engine.buffer
        engine.feed(text)
        if was_empty and engine.buffer and self._on_word_start is not None:
            self._on_word_start(hwnd)

    def _accept(self, index: int) -> None:
        if not self._foreground_is_target():
            self.engine.reset()
            return
        insertion = self.engine.accept(index)
        if insertion is None:
            return
        if not self._insert(insertion.backspaces, insertion.text):
            self.engine.discard()         # nothing was typed: do not learn it

    def _publish(self) -> None:
        if self._paused or self._blocked or not self._active:
            texts: list = []
        else:
            texts = [s.text for s in self.engine.suggestions()]
        self._set_visible(len(texts))
        if texts != self._last_texts:
            self._last_texts = texts
            self._on_update(texts)
        if self._on_diag is not None:
            self._on_diag(self.snapshot(texts))

    def snapshot(self, texts: Optional[list] = None) -> dict:
        """State for the diagnostic mode. Never goes to the log file."""
        return {
            "active": self._active,
            "paused": self._paused,
            "blocked": self._blocked,
            "layout": layout_name(getattr(self.translator, "last_layout", 0)),
            "prefix": self.engine.buffer,
            "suggestions": list(self._last_texts if texts is None else texts),
        }
