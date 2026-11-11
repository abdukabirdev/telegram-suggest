"""Where to put the suggestion window.

Telegram Desktop draws its own text field: there is no system caret and UI
Automation gives no caret position either. What it does expose (Telegram 5+/
Qt 6) is the rectangle of the input field, so the window is anchored to the
field: right above its left edge, like the suggestion strip of a phone
keyboard.

Strategies are tried in order, the first that returns an Anchor wins:

    CaretStrategy   system caret (GetGUIThreadInfo): classic Win32 controls
    UiaStrategy     UI Automation: the focused text field of Telegram
    WindowStrategy  geometry of the Telegram window: bottom row, by guess

UI Automation calls take tens of milliseconds, so the first two run in the
Locator thread; WindowStrategy is instant and serves until a result arrives.
"""

from __future__ import annotations

import ctypes
import logging
import threading
import time
from ctypes import wintypes
from dataclasses import dataclass
from typing import Callable, Optional, Sequence

from . import winapi as w
from .window_watch import window_ids, window_rect

log = logging.getLogger(__name__)

Rect = tuple[int, int, int, int]


@dataclass(frozen=True)
class Anchor:
    """Rectangle of the text field (or caret), physical screen pixels."""
    left: int
    top: int
    right: int
    bottom: int
    source: str
    is_password: bool = False


def place(anchor: Anchor, size: tuple[int, int], work: Rect,
          offset: tuple[int, int] = (0, 0), gap: int = 6) -> tuple[int, int]:
    """Top-left corner for a window of ``size``: above the anchor, on screen."""
    width, height = size
    x = anchor.left + offset[0]
    y = anchor.top - gap - height + offset[1]
    if y < work[1]:
        y = anchor.bottom + gap             # no room above: go below
    x = max(work[0], min(x, work[2] - width))
    y = max(work[1], min(y, work[3] - height))
    return x, y


def guess_anchor(client: Rect, scale: float = 1.0) -> Anchor:
    """Message field of Telegram judging by the window alone.

    Numbers measured on Telegram Desktop 7.4 at 100% scale: the input row is
    46 px high, the field sits 9 px above the bottom and 46 px to the right
    of the chat column. The width of the chat list is the user's choice, so
    the horizontal position is only an estimate.
    """
    left, top, right, bottom = client
    width = right - left
    if width < 640 * scale:
        column = left                        # narrow window: one column
    else:
        column = left + int(min(max(width * 0.30, 260 * scale), 430 * scale))
    field_left = column + int(46 * scale)
    return Anchor(
        min(field_left, right - 1), bottom - int(37 * scale),
        max(field_left + 1, right - int(90 * scale)), bottom - int(9 * scale),
        "window",
    )


def monitor_work_area(x: int, y: int) -> Rect:
    monitor = w.MonitorFromPoint(wintypes.POINT(x, y), w.MONITOR_DEFAULTTONEAREST)
    info = w.MONITORINFO()
    info.cbSize = ctypes.sizeof(w.MONITORINFO)
    if monitor and w.GetMonitorInfoW(monitor, ctypes.byref(info)):
        r = info.rcWork
        return (r.left, r.top, r.right, r.bottom)
    return (0, 0, 1920, 1080)


def window_scale(hwnd: Optional[int]) -> float:
    try:
        dpi = w.GetDpiForWindow(hwnd) if hwnd else 0
    except OSError:
        dpi = 0
    return dpi / 96.0 if dpi else 1.0


# ---- strategies --------------------------------------------------------------


class WindowStrategy:
    name = "window"

    def locate(self, hwnd: int) -> Optional[Anchor]:
        rect = window_rect(hwnd)
        if rect is None or rect[2] <= rect[0] or rect[3] <= rect[1]:
            return None
        return guess_anchor(rect, window_scale(hwnd))


class CaretStrategy:
    name = "caret"

    def locate(self, hwnd: int) -> Optional[Anchor]:
        tid, _ = window_ids(hwnd)
        info = w.GUITHREADINFO()
        info.cbSize = ctypes.sizeof(w.GUITHREADINFO)
        if not tid or not w.GetGUIThreadInfo(tid, ctypes.byref(info)) or not info.hwndCaret:
            return None
        rc = info.rcCaret
        if rc.bottom <= rc.top:
            return None
        top_left = wintypes.POINT(rc.left, rc.top)
        bottom_right = wintypes.POINT(max(rc.right, rc.left + 1), rc.bottom)
        if not (w.ClientToScreen(info.hwndCaret, ctypes.byref(top_left))
                and w.ClientToScreen(info.hwndCaret, ctypes.byref(bottom_right))):
            return None
        return Anchor(top_left.x, top_left.y, bottom_right.x, bottom_right.y, "caret")


class UiaStrategy:
    """Focused text field via UI Automation. Create and use in one thread."""

    name = "uia"
    _EDIT = 50004
    _DOCUMENT = 50030
    _CONTROL_TYPE_PROPERTY = 30003
    _DESCENDANTS = 4

    def __init__(self) -> None:
        import comtypes.client

        comtypes.client.GetModule("UIAutomationCore.dll")
        from comtypes.gen import UIAutomationClient as uia_module

        self._uia = comtypes.client.CreateObject(
            uia_module.CUIAutomation, interface=uia_module.IUIAutomation
        )
        self._edit_condition = self._uia.CreatePropertyCondition(
            self._CONTROL_TYPE_PROPERTY, self._EDIT
        )

    @staticmethod
    def _anchor(element, source: str) -> Optional[Anchor]:
        r = element.CurrentBoundingRectangle
        if r.right <= r.left or r.bottom <= r.top:
            return None
        return Anchor(r.left, r.top, r.right, r.bottom, source,
                      bool(element.CurrentIsPassword))

    def locate(self, hwnd: int) -> Optional[Anchor]:
        _, pid = window_ids(hwnd)
        if not pid:
            return None
        # 1. The element that has keyboard focus, if it is a text field of ours
        try:
            focused = self._uia.GetFocusedElement()
            if (focused is not None and focused.CurrentProcessId == pid
                    and focused.CurrentControlType in (self._EDIT, self._DOCUMENT)):
                anchor = self._anchor(focused, "uia-focus")
                if anchor is not None:
                    return anchor
        except OSError:
            pass
        # 2. Search the window: a focused field, else the lowest one (message box)
        root = self._uia.ElementFromHandle(hwnd)
        found = root.FindAll(self._DESCENDANTS, self._edit_condition)
        lowest: Optional[Anchor] = None
        for i in range(found.Length):
            element = found.GetElement(i)
            if element.CurrentIsOffscreen:
                continue
            if element.CurrentHasKeyboardFocus:
                anchor = self._anchor(element, "uia-focus")
                if anchor is not None:
                    return anchor
            anchor = self._anchor(element, "uia-search")
            if anchor is not None and (lowest is None or anchor.bottom > lowest.bottom):
                lowest = anchor
        if lowest is not None and lowest.is_password:
            # not known to be focused: do not block typing because of it
            lowest = Anchor(lowest.left, lowest.top, lowest.right, lowest.bottom,
                            lowest.source, False)
        return lowest


# ---- background locator ------------------------------------------------------


class Locator(threading.Thread):
    """Runs the slow strategies off the UI thread.

    ``on_result(hwnd, anchor_or_None)`` is called from this thread.
    """

    def __init__(
        self,
        on_result: Callable[[int, Optional[Anchor]], None],
        strategies: Optional[Sequence] = None,
        min_interval: float = 0.08,
    ) -> None:
        super().__init__(name="locator", daemon=True)
        self._on_result = on_result
        self._strategies = strategies
        self._min_interval = min_interval
        self._event = threading.Event()
        self._hwnd: Optional[int] = None
        self._stopping = False
        self.strategy_names: list[str] = []

    def request(self, hwnd: Optional[int]) -> None:
        if hwnd:
            self._hwnd = hwnd
            self._event.set()

    def stop(self) -> None:
        self._stopping = True
        self._event.set()

    def _build(self) -> list:
        strategies: list = [CaretStrategy()]
        try:
            strategies.append(UiaStrategy())
        except Exception:
            log.exception("UI Automation is not available; using window geometry only")
        return strategies

    def run(self) -> None:
        com = None
        if self._strategies is None:
            try:
                import sys

                if "comtypes" not in sys.modules:
                    # comtypes initialises COM for the thread that imports it
                    # first; make that a multithreaded apartment (no message
                    # loop is needed for UI Automation client calls there).
                    sys.coinit_flags = 0
                import comtypes

                comtypes.CoInitializeEx(comtypes.COINIT_MULTITHREADED)
                com = comtypes
            except Exception:
                log.exception("COM initialisation failed")
        strategies = list(self._strategies) if self._strategies is not None else self._build()
        self.strategy_names = [s.name for s in strategies]
        failures = 0
        try:
            while True:
                self._event.wait()
                if self._stopping:
                    break
                self._event.clear()
                hwnd = self._hwnd
                anchor = None
                for strategy in strategies:
                    try:
                        anchor = strategy.locate(hwnd)
                    except Exception:
                        failures += 1
                        if failures <= 3:
                            log.exception("strategy %s failed", strategy.name)
                        anchor = None
                    if anchor is not None:
                        break
                try:
                    self._on_result(hwnd, anchor)
                except Exception:
                    log.exception("locator callback failed")
                time.sleep(self._min_interval)
        finally:
            strategies.clear()
            if com is not None:
                com.CoUninitialize()
