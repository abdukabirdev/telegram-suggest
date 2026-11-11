"""Typing a word into the foreground window with SendInput.

The whole replacement (release held modifiers, Backspace x N, the word,
press the modifiers back) goes in a single SendInput call: Windows inserts
such a batch into the input stream as one piece, so physical keystrokes
cannot land in the middle of it. Every event carries INJECT_TAG, which makes
the hook skip our own keystrokes.
"""

from __future__ import annotations

import ctypes
import logging
from typing import Callable, Iterable

from . import winapi as w

log = logging.getLogger(__name__)

# Held Ctrl or Shift would turn our Backspace into "delete word" and our
# letters into shortcuts, so they are released for the time of typing.
_HELD_CANDIDATES = (w.VK_LCONTROL, w.VK_RCONTROL, w.VK_LSHIFT, w.VK_RSHIFT)
_EXTENDED = frozenset({w.VK_RCONTROL})


def _key(vk: int, scan: int, flags: int) -> w.INPUT:
    item = w.INPUT()
    item.type = w.INPUT_KEYBOARD
    item.ki = w.KEYBDINPUT(vk, scan, flags, 0, w.INJECT_TAG)
    return item


def _vk_event(vk: int, up: bool) -> w.INPUT:
    flags = w.KEYEVENTF_KEYUP if up else 0
    if vk in _EXTENDED:
        flags |= w.KEYEVENTF_EXTENDEDKEY
    return _key(vk, 0, flags)


def build_inputs(backspaces: int, text: str, held: Iterable[int] = ()) -> list[w.INPUT]:
    held = list(held)
    events: list[w.INPUT] = []
    for vk in held:
        events.append(_vk_event(vk, up=True))
    for _ in range(max(0, backspaces)):
        events.append(_vk_event(w.VK_BACK, up=False))
        events.append(_vk_event(w.VK_BACK, up=True))
    # KEYEVENTF_UNICODE takes UTF-16 code units, one event pair per unit
    data = text.encode("utf-16-le")
    for i in range(0, len(data), 2):
        unit = data[i] | (data[i + 1] << 8)
        events.append(_key(0, unit, w.KEYEVENTF_UNICODE))
        events.append(_key(0, unit, w.KEYEVENTF_UNICODE | w.KEYEVENTF_KEYUP))
    for vk in reversed(held):
        events.append(_vk_event(vk, up=False))
    return events


def held_modifiers(key_down: Callable[[int], bool] = w.key_down) -> list[int]:
    return [vk for vk in _HELD_CANDIDATES if key_down(vk)]


def send(backspaces: int, text: str) -> bool:
    """Erase ``backspaces`` characters and type ``text``. True on success."""
    events = build_inputs(backspaces, text, held_modifiers())
    if not events:
        return True
    array = (w.INPUT * len(events))(*events)
    sent = w.SendInput(len(events), array, ctypes.sizeof(w.INPUT))
    if sent != len(events):
        # Typically UIPI: the target window runs as administrator and we do not.
        log.warning("SendInput inserted %d of %d events (error %d)",
                    sent, len(events), ctypes.get_last_error())
        return False
    return True
