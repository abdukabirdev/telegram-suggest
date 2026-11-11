"""The suggestion window: a small strip of words above the text field.

It never takes keyboard focus (WS_EX_NOACTIVATE), so Telegram keeps the caret
while the user clicks a word with the mouse.

Look: a rounded panel with a soft shadow, words as chips. The first word,
the one Tab inserts, sits on an accent-tinted chip. Key numbers are not shown
all the time (they clutter the strip): they appear while Ctrl is held, the
way Windows shows Alt shortcuts. A right click on a word asks whether to
delete it from the dictionary; a second (left) click on it confirms.
"""

from __future__ import annotations

import ctypes
from ctypes import wintypes
from typing import Optional, Sequence

from PySide6.QtCore import QPoint, QPointF, QRect, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QWidget

from . import winapi as w
from .theme import Palette, palette_for

SHADOW = 8              # transparent margin around the panel for the shadow
_PANEL_PAD = 4          # between the panel edge and the chips
_ITEM_PAD = 16          # inside a chip, left and right
_ITEM_GAP = 2           # between chips
_ITEM_HEIGHT = 32
_MIN_ITEM_WIDTH = 44
_RADIUS = 11
_CHIP_RADIUS = 8
_MAX_WORD_WIDTH = 240
_CONFIRM_TIMEOUT_MS = 5000

HINT_MODES = ("ctrl", "always", "never")


def hint_for(index: int) -> str:
    """Key number shown on a chip: Ctrl+1 ... Ctrl+9."""
    return str(index + 1)


def confirm_text(word: str) -> str:
    return f"Удалить «{word}»?"


def _font(size: int, weight: QFont.Weight = QFont.Weight.Normal) -> QFont:
    font = QFont()
    font.setFamilies(["Segoe UI Variable Text", "Segoe UI"])
    font.setPixelSize(size)
    font.setWeight(weight)
    font.setHintingPreference(QFont.HintingPreference.PreferNoHinting)
    return font


class Overlay(QWidget):
    clicked = Signal(int)
    delete_requested = Signal(int)

    def __init__(self, theme: str = "system", key_hints: str = "ctrl") -> None:
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

        self._font = _font(14)
        self._primary_font = _font(14, QFont.Weight.DemiBold)
        self._hint_font = _font(9, QFont.Weight.DemiBold)

        self._palette: Palette = palette_for(theme)
        self._hint_mode = key_hints if key_hints in HINT_MODES else "ctrl"
        self._ctrl_held = False
        self._items: list[str] = []
        self._shown: list[str] = []         # possibly elided
        self._rects: list[QRect] = []
        self._hover = -1
        self._pressed = -1
        self._confirm = -1                  # chip asking "delete this word?"
        self._native_ready = False

        self._confirm_timer = QTimer(self)
        self._confirm_timer.setSingleShot(True)
        self._confirm_timer.timeout.connect(self.cancel_confirm)

    # ---- content -----------------------------------------------------------

    def items(self) -> list[str]:
        return list(self._items)

    def set_items(self, items: Sequence[str]) -> None:
        self._items = list(items)
        self._hover = -1
        self._pressed = -1
        self._confirm = -1
        self._confirm_timer.stop()
        self._layout()
        self.update()

    def palette_colors(self) -> Palette:
        return self._palette

    def set_palette(self, palette: Palette) -> None:
        if palette != self._palette:
            self._palette = palette
            self.update()

    def set_key_hints(self, mode: str) -> None:
        self._hint_mode = mode if mode in HINT_MODES else "ctrl"
        self.update()

    def set_ctrl_held(self, held: bool) -> None:
        if held != self._ctrl_held:
            self._ctrl_held = held
            if self._hint_mode == "ctrl":
                self.update()

    def hints_visible(self) -> bool:
        return self._hint_mode == "always" or (self._hint_mode == "ctrl" and self._ctrl_held)

    def confirming(self) -> int:
        return self._confirm

    def cancel_confirm(self) -> None:
        if self._confirm != -1:
            self._confirm = -1
            self._layout()
            self.update()

    def _label(self, index: int) -> str:
        shown = self._shown[index]
        return confirm_text(shown) if index == self._confirm else shown

    def _layout(self) -> None:
        metrics = QFontMetrics(self._font)
        primary = QFontMetrics(self._primary_font)
        self._rects = []
        self._shown = []
        x = SHADOW + _PANEL_PAD
        top = SHADOW + _PANEL_PAD
        for i, text in enumerate(self._items):
            fm = primary if i == 0 else metrics
            self._shown.append(fm.elidedText(text, Qt.TextElideMode.ElideRight, _MAX_WORD_WIDTH))
            label = self._label(i)
            width = max(_ITEM_PAD + fm.horizontalAdvance(label) + _ITEM_PAD, _MIN_ITEM_WIDTH)
            self._rects.append(QRect(x, top, width, _ITEM_HEIGHT))
            x += width + _ITEM_GAP
        if self._rects:
            x -= _ITEM_GAP
        width = max(x + _PANEL_PAD + SHADOW, 2 * (SHADOW + _PANEL_PAD) + 1)
        self.setFixedSize(width, _ITEM_HEIGHT + 2 * (_PANEL_PAD + SHADOW))

    def index_at(self, pos: QPoint) -> int:
        for i, rect in enumerate(self._rects):
            if rect.contains(pos):
                return i
        return -1

    def panel_rect(self) -> QRect:
        """The visible panel, without the shadow margin (widget coordinates)."""
        return self.rect().adjusted(SHADOW, SHADOW, -SHADOW, -SHADOW)

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

    def native_panel_rect(self) -> Optional[tuple[int, int, int, int]]:
        """The visible panel in physical screen pixels, None while hidden."""
        rect = self.native_rect()
        if rect is None:
            return None
        m = self.margin_physical()
        return (rect[0] + m, rect[1] + m, rect[2] - m, rect[3] - m)

    def margin_physical(self) -> int:
        return round(SHADOW * self.devicePixelRatioF())

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

    def _paint_shadow(self, painter: QPainter, panel: QRectF) -> None:
        strength = self._palette.shadow
        painter.setBrush(Qt.BrushStyle.NoBrush)
        for k in range(1, SHADOW + 1):
            alpha = round(strength * ((SHADOW + 1 - k) / (SHADOW + 1)) ** 2.4 / 2.2)
            if alpha <= 0:
                continue
            painter.setPen(QPen(QColor(0, 0, 0, alpha), 1))
            ring = panel.adjusted(-k + 0.5, -k + 0.5 + 1.5, k - 0.5, k - 0.5 + 1.5)
            painter.drawRoundedRect(ring, _RADIUS + k, _RADIUS + k)

    def paintEvent(self, _event) -> None:
        p = self._palette
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)

        panel = QRectF(self.panel_rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        self._paint_shadow(painter, panel)
        painter.setPen(QPen(QColor(p.border), 1))
        painter.setBrush(QColor(p.bg))
        painter.drawRoundedRect(panel, _RADIUS, _RADIUS)

        hints = self.hints_visible()
        highlighted = set()
        for i, rect in enumerate(self._rects):
            chip = QRectF(rect)
            fill: Optional[QColor] = None
            if i == self._confirm:
                fill = QColor(p.danger_bg)
            elif i == 0:
                fill = QColor(p.accent_bg)
            if i == self._hover or i == self._pressed:
                over = QColor(p.accent if i == 0 and i != self._confirm else p.text)
                over.setAlpha(40 if i == self._pressed else 22)
                if fill is None:
                    fill = QColor(p.pressed if i == self._pressed else p.hover)
                else:
                    path = QPainterPath()
                    path.addRoundedRect(chip, _CHIP_RADIUS, _CHIP_RADIUS)
                    painter.fillPath(path, fill)
                    fill = over
            if fill is not None:
                highlighted.add(i)
                path = QPainterPath()
                path.addRoundedRect(chip, _CHIP_RADIUS, _CHIP_RADIUS)
                painter.fillPath(path, fill)

        for i, rect in enumerate(self._rects):
            if i > 0 and i not in highlighted and i - 1 not in highlighted:
                x = rect.left() - _ITEM_GAP / 2
                painter.setPen(QPen(QColor(p.divider), 1))
                painter.drawLine(QPointF(x, rect.top() + 9), QPointF(x, rect.bottom() - 8))

            if i == self._confirm:
                color, font = p.danger, self._primary_font
            elif i == 0:
                color, font = p.accent, self._primary_font
            else:
                color, font = p.text, self._font
            painter.setFont(font)
            painter.setPen(QColor(color))
            painter.drawText(QRectF(rect), Qt.AlignmentFlag.AlignCenter, self._label(i))

            if hints and i < 9 and i != self._confirm:
                painter.setFont(self._hint_font)
                painter.setPen(QColor(p.accent if i == 0 else p.muted))
                painter.drawText(QRectF(rect.left() + 3, rect.top() + 3, 10, 11),
                                 Qt.AlignmentFlag.AlignCenter, hint_for(i))
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
        if event.button() in (Qt.MouseButton.LeftButton, Qt.MouseButton.RightButton):
            self._pressed = self.index_at(event.position().toPoint())
            self.update()

    def mouseReleaseEvent(self, event) -> None:
        button = event.button()
        if button not in (Qt.MouseButton.LeftButton, Qt.MouseButton.RightButton):
            return
        index = self.index_at(event.position().toPoint())
        pressed, self._pressed = self._pressed, -1
        self.update()
        if index < 0 or index != pressed:
            return
        if button == Qt.MouseButton.RightButton:
            self._confirm = index
            self._layout()
            self.update()
            self._confirm_timer.start(_CONFIRM_TIMEOUT_MS)
            return
        if index == self._confirm:
            self._confirm = -1
            self._confirm_timer.stop()
            self.delete_requested.emit(index)
            return
        self.cancel_confirm()
        self.clicked.emit(index)
