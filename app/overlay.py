"""The suggestion window: a small strip of words above the text field.

It never takes keyboard focus (WS_EX_NOACTIVATE), so Telegram keeps the caret
while the user clicks a word with the mouse.
"""

from __future__ import annotations

import ctypes
from ctypes import wintypes
from typing import Optional, Sequence

from PySide6.QtCore import QPoint, QRect, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFont, QFontMetrics, QGuiApplication, QPainter, QPen
from PySide6.QtWidgets import QWidget

from . import winapi as w

_THEMES = {
    "dark": {
        "bg": "#24272c", "border": "#3b4048", "text": "#e9ebee", "muted": "#8d949e",
        "hover": "#343941", "accent": "#6ab3f3", "divider": "#353a42",
    },
    "light": {
        "bg": "#ffffff", "border": "#cfd4da", "text": "#1c1e21", "muted": "#8a9099",
        "hover": "#edf1f5", "accent": "#168acd", "divider": "#e3e6ea",
    },
}

_PANEL_PAD = 4          # around the row of items
_ITEM_PAD = 10          # inside an item, left and right
_HINT_GAP = 6           # between the key hint and the word
_ITEM_HEIGHT = 28
_RADIUS = 9
_MAX_WORD_WIDTH = 240


def hint_for(index: int) -> str:
    return "Tab" if index == 0 else f"Ctrl+{index + 1}"


def system_theme() -> str:
    try:
        scheme = QGuiApplication.styleHints().colorScheme()
        return "dark" if scheme == Qt.ColorScheme.Dark else "light"
    except AttributeError:          # Qt older than 6.5
        return "light"


class Overlay(QWidget):
    clicked = Signal(int)

    def __init__(self, theme: str = "system") -> None:
        super().__init__(
            None,
            Qt.WindowType.Tool
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.WindowDoesNotAcceptFocus
            | Qt.WindowType.NoDropShadowWindowHint,
        )
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setMouseTracking(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

        self._font = QFont("Segoe UI")
        self._font.setPixelSize(14)
        self._hint_font = QFont("Segoe UI")
        self._hint_font.setPixelSize(10)

        self._theme_setting = theme
        self._colors = _THEMES[self._resolve_theme()]
        self._items: list[str] = []
        self._shown: list[str] = []         # possibly elided
        self._rects: list[QRect] = []
        self._hover = -1
        self._pressed = -1
        self._native_ready = False

        try:
            QGuiApplication.styleHints().colorSchemeChanged.connect(self._on_scheme_changed)
        except AttributeError:
            pass

    # ---- content -----------------------------------------------------------

    def items(self) -> list[str]:
        return list(self._items)

    def set_items(self, items: Sequence[str]) -> None:
        self._items = list(items)
        self._hover = -1
        self._pressed = -1
        self._layout()
        self.update()

    def set_theme(self, theme: str) -> None:
        self._theme_setting = theme
        self._colors = _THEMES[self._resolve_theme()]
        self.update()

    def _resolve_theme(self) -> str:
        return self._theme_setting if self._theme_setting in _THEMES else system_theme()

    def _on_scheme_changed(self, *_args) -> None:
        self.set_theme(self._theme_setting)

    def _layout(self) -> None:
        metrics = QFontMetrics(self._font)
        hint_metrics = QFontMetrics(self._hint_font)
        self._rects = []
        self._shown = []
        x = _PANEL_PAD
        for i, text in enumerate(self._items):
            shown = metrics.elidedText(text, Qt.TextElideMode.ElideRight, _MAX_WORD_WIDTH)
            width = (_ITEM_PAD + hint_metrics.horizontalAdvance(hint_for(i)) + _HINT_GAP
                     + metrics.horizontalAdvance(shown) + _ITEM_PAD)
            self._rects.append(QRect(x, _PANEL_PAD, width, _ITEM_HEIGHT))
            self._shown.append(shown)
            x += width
        self.setFixedSize(max(x + _PANEL_PAD, 2 * _PANEL_PAD + 1),
                          _ITEM_HEIGHT + 2 * _PANEL_PAD)

    def index_at(self, pos: QPoint) -> int:
        for i, rect in enumerate(self._rects):
            if rect.contains(pos):
                return i
        return -1

    # ---- native window -----------------------------------------------------

    def native_handle(self) -> int:
        hwnd = int(self.winId())
        if not self._native_ready:
            self._native_ready = True
            style = w.GetWindowLongPtrW(hwnd, w.GWL_EXSTYLE)
            w.SetWindowLongPtrW(
                hwnd, w.GWL_EXSTYLE,
                style | w.WS_EX_NOACTIVATE | w.WS_EX_TOOLWINDOW | w.WS_EX_TOPMOST,
            )
        return hwnd

    def native_rect(self) -> Optional[tuple[int, int, int, int]]:
        """Window rectangle in physical screen pixels, None while hidden."""
        if not self.isVisible():
            return None
        rect = wintypes.RECT()
        if not w.GetWindowRect(self.native_handle(), ctypes.byref(rect)):
            return None
        return (rect.left, rect.top, rect.right, rect.bottom)

    def physical_size(self) -> tuple[int, int]:
        ratio = self.devicePixelRatioF()
        return round(self.width() * ratio), round(self.height() * ratio)

    def show_at(self, x: int, y: int) -> None:
        """Show (or move) the window with its top-left at physical (x, y)."""
        hwnd = self.native_handle()
        w.SetWindowPos(hwnd, w.HWND_TOPMOST, int(x), int(y), 0, 0,
                       w.SWP_NOSIZE | w.SWP_NOACTIVATE | w.SWP_NOOWNERZORDER)
        if not self.isVisible():
            self.show()
            # Qt may place a freshly shown window itself: put it back
            w.SetWindowPos(hwnd, w.HWND_TOPMOST, int(x), int(y), 0, 0,
                           w.SWP_NOSIZE | w.SWP_NOACTIVATE | w.SWP_NOOWNERZORDER)

    # ---- painting ----------------------------------------------------------

    def paintEvent(self, _event) -> None:
        colors = self._colors
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)

        panel = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        painter.setPen(QPen(QColor(colors["border"]), 1))
        painter.setBrush(QColor(colors["bg"]))
        painter.drawRoundedRect(panel, _RADIUS, _RADIUS)

        metrics = QFontMetrics(self._font)
        hint_metrics = QFontMetrics(self._hint_font)
        for i, rect in enumerate(self._rects):
            if i == self._hover:
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(QColor(colors["hover"]))
                painter.drawRoundedRect(QRectF(rect), _RADIUS - 3, _RADIUS - 3)
            elif i > 0 and i - 1 != self._hover:
                painter.setPen(QPen(QColor(colors["divider"]), 1))
                painter.drawLine(rect.left(), rect.top() + 7, rect.left(), rect.bottom() - 7)

            hint = hint_for(i)
            x = rect.left() + _ITEM_PAD
            baseline = rect.top() + (rect.height() + metrics.ascent() - metrics.descent()) // 2
            painter.setFont(self._hint_font)
            painter.setPen(QColor(colors["muted"]))
            painter.drawText(x, baseline - 1, hint)
            x += hint_metrics.horizontalAdvance(hint) + _HINT_GAP

            painter.setFont(self._font)
            painter.setPen(QColor(colors["accent"] if i == 0 else colors["text"]))
            painter.drawText(x, baseline, self._shown[i])
        painter.end()

    # ---- mouse -------------------------------------------------------------

    def mouseMoveEvent(self, event) -> None:
        index = self.index_at(event.position().toPoint())
        if index != self._hover:
            self._hover = index
            self.update()

    def leaveEvent(self, _event) -> None:
        if self._hover != -1:
            self._hover = -1
            self.update()

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._pressed = self.index_at(event.position().toPoint())

    def mouseReleaseEvent(self, event) -> None:
        if event.button() != Qt.MouseButton.LeftButton:
            return
        index = self.index_at(event.position().toPoint())
        pressed, self._pressed = self._pressed, -1
        if index >= 0 and index == pressed:
            self.clicked.emit(index)
