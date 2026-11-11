"""Look of the program's own windows: settings, welcome, tray menu.

The windows follow the same colour choice as the suggestion window: by
default Telegram's own background (read from its message field), otherwise
the Windows light/dark mode or a fixed light/dark scheme. Shapes copy
Telegram Desktop: flat text buttons, a filled button for the main action,
toggle switches instead of check boxes, borderless panels.

Applied to the whole QApplication, so every dialog and message box shares it.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from PySide6.QtCore import QEasingCurve, QPropertyAnimation, QRectF, QSize, Qt, Property
from PySide6.QtGui import QColor, QFont, QPainter, QPalette
from PySide6.QtWidgets import QApplication, QCheckBox

from .theme import (DARK_BG, LIGHT_BG, RGB, hex_of, is_dark, mix, parse_hex,
                    windows_prefers_dark)

# Telegram Desktop: day theme / night theme
_ACCENT_LIGHT: RGB = (0x33, 0x90, 0xec)
_LINK_LIGHT: RGB = (0x16, 0x8a, 0xcd)
_ACCENT_DARK: RGB = (0x52, 0x88, 0xc1)
_LINK_DARK: RGB = (0x6a, 0xb3, 0xf3)
_DANGER_LIGHT: RGB = (0xe5, 0x39, 0x35)
_DANGER_DARK: RGB = (0xff, 0x6b, 0x6b)


@dataclass(frozen=True)
class WindowColors:
    dark: bool
    window: str         # page background
    surface: str        # panels, inputs, lists
    sidebar: str
    border: str
    text: str
    muted: str
    hover: str          # row / flat button under the mouse
    accent: str         # filled buttons, switches
    accent_hover: str
    accent_text: str    # links and flat buttons
    accent_soft: str    # selection, active sidebar item
    danger: str
    danger_soft: str


def colors_from_background(bg: RGB) -> WindowColors:
    """A whole window scheme around one background colour (Telegram's)."""
    dark = is_dark(bg)
    ink: RGB = (255, 255, 255) if dark else (0, 0, 0)
    accent = _ACCENT_DARK if dark else _ACCENT_LIGHT
    link = _LINK_DARK if dark else _LINK_LIGHT
    danger = _DANGER_DARK if dark else _DANGER_LIGHT
    text = mix(bg, ink, 0.93 if dark else 0.87)
    # Night: panels a shade lighter than the page, side column darker.
    # Day: white panels on a light grey page, as in Telegram's settings.
    window = bg if dark else mix(bg, ink, 0.05)
    surface = mix(bg, ink, 0.035) if dark else bg
    return WindowColors(
        dark=dark,
        window=hex_of(window),
        surface=hex_of(surface),
        sidebar=hex_of(mix(bg, (0, 0, 0), 0.22) if dark else bg),
        border=hex_of(mix(bg, ink, 0.12 if dark else 0.10)),
        text=hex_of(text),
        muted=hex_of(mix(bg, ink, 0.50 if dark else 0.48)),
        hover=hex_of(mix(bg, ink, 0.07 if dark else 0.045)),
        accent=hex_of(accent),
        accent_hover=hex_of(mix(accent, ink, 0.12)),
        accent_text=hex_of(link),
        accent_soft=hex_of(mix(bg, link, 0.17 if dark else 0.11)),
        danger=hex_of(danger),
        danger_soft=hex_of(mix(bg, danger, 0.16 if dark else 0.09)),
    )


LIGHT = colors_from_background(LIGHT_BG)
DARK = colors_from_background(DARK_BG)


def colors_for(theme: str, telegram_bg: Optional[RGB] = None) -> WindowColors:
    """Same rule as theme.palette_for, for the program's windows."""
    if theme == "dark":
        return DARK
    if theme == "light":
        return LIGHT
    if theme == "telegram" and telegram_bg is not None:
        return colors_from_background(telegram_bg)
    return DARK if windows_prefers_dark() else LIGHT


def current_colors() -> WindowColors:
    return DARK if windows_prefers_dark() else LIGHT


def stylesheet(c: WindowColors) -> str:
    return f"""
* {{ font-family: "Segoe UI Variable Text", "Segoe UI"; font-size: 13px; color: {c.text}; }}
QWidget#Root, QDialog, QMessageBox {{ background: {c.window}; }}
QScrollArea, QScrollArea > QWidget > QWidget, QStackedWidget {{ background: {c.window}; }}
QLabel {{ background: transparent; }}
QLabel[role="title"] {{ font-size: 20px; font-weight: 600; }}
QLabel[role="section"] {{ color: {c.accent_text}; font-size: 13px; font-weight: 600;
    padding-top: 2px; }}
QLabel[role="hint"] {{ color: {c.muted}; }}
QLabel[role="step"] {{ background: {c.accent}; color: white; border-radius: 11px;
    min-width: 22px; max-width: 22px; min-height: 22px; max-height: 22px;
    font-weight: 600; qproperty-alignment: AlignCenter; }}
QLabel[role="key"] {{ background: {c.hover}; border: none; border-radius: 6px;
    padding: 2px 8px; font-weight: 600; font-size: 12px; }}
QFrame[role="card"] {{ background: {c.surface}; border: none; border-radius: 12px; }}

QListWidget#Sidebar {{ background: {c.sidebar}; border: none; padding: 12px 8px; outline: 0; }}
QListWidget#Sidebar::item {{ padding: 10px 14px; border-radius: 8px; margin: 1px 0; }}
QListWidget#Sidebar::item:hover {{ background: {c.hover}; }}
QListWidget#Sidebar::item:selected {{ background: {c.accent_soft}; color: {c.accent_text};
    font-weight: 600; }}

QPushButton {{ background: transparent; border: none; border-radius: 8px;
    padding: 8px 16px; color: {c.accent_text}; font-weight: 600; }}
QPushButton:hover {{ background: {c.accent_soft}; }}
QPushButton:pressed {{ background: {c.border}; }}
QPushButton:disabled {{ color: {c.muted}; background: transparent; }}
QPushButton[role="primary"] {{ background: {c.accent}; color: white; padding: 8px 22px; }}
QPushButton[role="primary"]:hover {{ background: {c.accent_hover}; }}
QPushButton[role="primary"]:disabled {{ background: {c.border}; color: {c.muted}; }}
QPushButton[role="danger"] {{ color: {c.danger}; }}
QPushButton[role="danger"]:hover {{ background: {c.danger_soft}; }}
QPushButton[role="link"] {{ background: transparent; color: {c.accent_text};
    padding: 2px 0; text-align: left; font-weight: normal; }}
QPushButton[role="link"]:hover {{ text-decoration: underline; }}

QLineEdit, QSpinBox, QComboBox {{ background: {c.hover}; border: none;
    border-bottom: 2px solid {c.border}; border-radius: 6px;
    border-bottom-left-radius: 0; border-bottom-right-radius: 0;
    padding: 6px 9px; selection-background-color: {c.accent}; selection-color: white; }}
QLineEdit:focus, QSpinBox:focus, QComboBox:focus {{ border-bottom-color: {c.accent}; }}
QComboBox::drop-down {{ border: none; width: 22px; }}
QComboBox QAbstractItemView {{ background: {c.surface}; border: 1px solid {c.border};
    selection-background-color: {c.accent_soft}; selection-color: {c.text}; outline: 0;
    padding: 4px; }}
QSpinBox::up-button, QSpinBox::down-button {{ border: none; background: transparent;
    width: 16px; }}

QCheckBox {{ spacing: 12px; padding: 4px 0; }}

QTableWidget {{ background: {c.surface}; border: none; border-radius: 12px;
    gridline-color: transparent; selection-background-color: {c.accent_soft};
    selection-color: {c.text}; alternate-background-color: {c.window}; outline: 0; }}
QTableWidget::item {{ padding: 4px 8px; border: none; }}
QTableWidget::item:hover {{ background: {c.hover}; }}
QHeaderView::section {{ background: {c.surface}; color: {c.muted}; border: none;
    border-bottom: 1px solid {c.border}; padding: 8px 8px; font-weight: 600; }}
QTableCornerButton::section {{ background: {c.surface}; border: none; }}

QProgressBar {{ background: {c.border}; border: none; border-radius: 2px; height: 4px;
    max-height: 4px; text-align: center; color: transparent; }}
QProgressBar::chunk {{ background: {c.accent}; border-radius: 2px; }}

QScrollBar:vertical {{ background: transparent; width: 8px; margin: 2px; }}
QScrollBar::handle:vertical {{ background: {c.border}; border-radius: 3px; min-height: 30px; }}
QScrollBar::handle:vertical:hover {{ background: {c.muted}; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; width: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}

QMenu {{ background: {c.surface}; border: 1px solid {c.border}; border-radius: 8px;
    padding: 6px 0; }}
QMenu::item {{ padding: 8px 32px 8px 16px; }}
QMenu::item:selected {{ background: {c.hover}; color: {c.text}; }}
QMenu::item:disabled {{ color: {c.muted}; }}
QMenu::separator {{ height: 1px; background: {c.border}; margin: 6px 0; }}

QToolTip {{ background: {c.surface}; color: {c.text}; border: 1px solid {c.border};
    padding: 5px 8px; }}
"""


def qt_palette(c: WindowColors) -> QPalette:
    pal = QPalette()
    roles = {
        QPalette.ColorRole.Window: c.window,
        QPalette.ColorRole.WindowText: c.text,
        QPalette.ColorRole.Base: c.surface,
        QPalette.ColorRole.AlternateBase: c.window,
        QPalette.ColorRole.Text: c.text,
        QPalette.ColorRole.Button: c.surface,
        QPalette.ColorRole.ButtonText: c.text,
        QPalette.ColorRole.Highlight: c.accent,
        QPalette.ColorRole.HighlightedText: "#ffffff",
        QPalette.ColorRole.ToolTipBase: c.surface,
        QPalette.ColorRole.ToolTipText: c.text,
        QPalette.ColorRole.PlaceholderText: c.muted,
        QPalette.ColorRole.Link: c.accent_text,
        QPalette.ColorRole.Mid: c.border,
        QPalette.ColorRole.Accent: c.accent,
    }
    for role, color in roles.items():
        pal.setColor(role, QColor(color))
    pal.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Text, QColor(c.muted))
    pal.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.ButtonText, QColor(c.muted))
    pal.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.WindowText, QColor(c.muted))
    return pal


_applied: Optional[WindowColors] = None


def apply(app: QApplication, colors: Optional[WindowColors] = None) -> WindowColors:
    """Style the whole application; without ``colors`` after the Windows mode.

    Calling it again with the same colours does nothing, so it is cheap to
    call whenever the colours might have changed.
    """
    global _applied
    colors = colors or current_colors()
    if colors == _applied:
        return colors
    first = _applied is None
    _applied = colors
    if first:
        app.setStyle("Fusion")
        font = QFont()
        font.setFamilies(["Segoe UI Variable Text", "Segoe UI"])
        font.setPointSize(10)
        app.setFont(font)
    app.setPalette(qt_palette(colors))
    app.setStyleSheet(stylesheet(colors))
    return colors


def applied_colors() -> WindowColors:
    return _applied or current_colors()


# ---- toggle switch -----------------------------------------------------------


class Toggle(QCheckBox):
    """A check box drawn as Telegram's on/off switch, text on the left.

    Keeps the QCheckBox interface (isChecked, setChecked, toggled), so it is
    a drop-in replacement.
    """

    _TRACK_W = 36
    _TRACK_H = 16
    _KNOB = 20
    _GAP = 16

    def __init__(self, text: str = "", parent=None) -> None:
        super().__init__(text, parent)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        policy = self.sizePolicy()
        policy.setHeightForWidth(True)
        self.setSizePolicy(policy)
        self._pos = 0.0
        self._anim = QPropertyAnimation(self, b"knob", self)
        self._anim.setDuration(120)
        self._anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self.toggled.connect(self._animate)

    def _get_knob(self) -> float:
        return self._pos

    def _set_knob(self, value: float) -> None:
        self._pos = value
        self.update()

    knob = Property(float, _get_knob, _set_knob)

    def setChecked(self, value: bool) -> None:  # noqa: N802 (Qt name)
        super().setChecked(value)
        self._anim.stop()
        self._pos = 1.0 if value else 0.0
        self.update()

    def _animate(self, value: bool) -> None:
        if not self.isVisible():
            self._pos = 1.0 if value else 0.0
            return
        self._anim.stop()
        self._anim.setStartValue(self._pos)
        self._anim.setEndValue(1.0 if value else 0.0)
        self._anim.start()

    def _switch_width(self) -> int:
        return self._TRACK_W + (self._KNOB - self._TRACK_H)

    def sizeHint(self) -> QSize:
        metrics = self.fontMetrics()
        width = self._switch_width() + self._GAP
        if self.text():
            width += metrics.horizontalAdvance(self.text())
        return QSize(width, max(self._KNOB + 8, metrics.height() + 8))

    def minimumSizeHint(self) -> QSize:
        return QSize(self._switch_width() + self._GAP + 120, self.sizeHint().height())

    def hitButton(self, pos) -> bool:  # noqa: N802 (Qt name)
        return self.rect().contains(pos)

    def hasHeightForWidth(self) -> bool:  # noqa: N802 (Qt name)
        return True

    def heightForWidth(self, width: int) -> int:  # noqa: N802 (Qt name)
        text_w = max(40, width - self._switch_width() - self._GAP)
        box = self.fontMetrics().boundingRect(0, 0, text_w, 10000,
                                              int(Qt.TextFlag.TextWordWrap), self.text())
        return max(self._KNOB + 8, box.height() + 8)

    def paintEvent(self, _event) -> None:  # noqa: N802 (Qt name)
        c = applied_colors()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = self.rect()
        switch_w = self._switch_width()
        text_rect = rect.adjusted(0, 0, -(switch_w + self._GAP), 0)
        painter.setPen(QColor(c.text if self.isEnabled() else c.muted))
        painter.setFont(self.font())
        painter.drawText(text_rect, int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
                                        | Qt.TextFlag.TextWordWrap), self.text())

        on = parse_hex(c.accent)
        off = mix(parse_hex(c.window), parse_hex(c.muted), 0.6) if c.dark else parse_hex(c.muted)
        t = self._pos
        track = QColor(hex_of(mix(off, on, t)))
        if not self.isEnabled():
            track.setAlphaF(0.5)
        inset = (self._KNOB - self._TRACK_H) / 2
        left = rect.right() - switch_w + 1
        top = rect.center().y() - self._KNOB / 2 + 0.5
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(track)
        painter.drawRoundedRect(QRectF(left + inset, top + inset, self._TRACK_W, self._TRACK_H),
                                self._TRACK_H / 2, self._TRACK_H / 2)
        knob_x = left + t * (switch_w - self._KNOB)
        knob = QRectF(knob_x, top, self._KNOB, self._KNOB)
        painter.setBrush(QColor(c.surface if c.dark else "#ffffff"))
        painter.setPen(QColor(hex_of(mix(off, on, t))))
        painter.drawEllipse(knob.adjusted(1, 1, -1, -1))
        painter.end()
