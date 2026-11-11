"""Look of the program's own windows: settings, welcome, tray menu.

Light or dark after the Windows "app mode", in Telegram's blue. Applied to the
whole QApplication, so every dialog and message box shares it.
"""

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtGui import QColor, QFont, QPalette
from PySide6.QtWidgets import QApplication

from .theme import windows_prefers_dark


@dataclass(frozen=True)
class WindowColors:
    dark: bool
    window: str         # page background
    surface: str        # cards, inputs, lists
    sidebar: str
    border: str
    text: str
    muted: str
    accent: str         # buttons
    accent_hover: str
    accent_text: str    # links and accent-coloured text
    accent_soft: str    # selection, active sidebar item
    danger: str
    danger_soft: str


LIGHT = WindowColors(
    dark=False, window="#f4f6f8", surface="#ffffff", sidebar="#eceff3", border="#dde2e8",
    text="#1f2328", muted="#6b7480", accent="#3390ec", accent_hover="#2a7fd6",
    accent_text="#2a7fd6", accent_soft="#dcebfb", danger="#e53935", danger_soft="#fdeceb",
)
DARK = WindowColors(
    dark=True, window="#17191d", surface="#212429", sidebar="#1c1f23", border="#30353c",
    text="#e8eaed", muted="#9aa1ab", accent="#3390ec", accent_hover="#4a9ef0",
    accent_text="#6ab3f3", accent_soft="#1f3a57", danger="#ff6b6b", danger_soft="#3d2224",
)


def current_colors() -> WindowColors:
    return DARK if windows_prefers_dark() else LIGHT


def stylesheet(c: WindowColors) -> str:
    return f"""
* {{ font-family: "Segoe UI Variable Text", "Segoe UI"; font-size: 13px; color: {c.text}; }}
QWidget#Root, QDialog, QMessageBox {{ background: {c.window}; }}
QLabel {{ background: transparent; }}
QLabel[role="title"] {{ font-size: 20px; font-weight: 600; }}
QLabel[role="section"] {{ font-size: 14px; font-weight: 600; padding-top: 6px; }}
QLabel[role="hint"] {{ color: {c.muted}; }}
QLabel[role="step"] {{ background: {c.accent}; color: white; border-radius: 11px;
    min-width: 22px; max-width: 22px; min-height: 22px; max-height: 22px;
    font-weight: 600; qproperty-alignment: AlignCenter; }}
QFrame[role="card"] {{ background: {c.surface}; border: 1px solid {c.border}; border-radius: 10px; }}

QListWidget#Sidebar {{ background: {c.sidebar}; border: none; border-right: 1px solid {c.border};
    padding: 10px 8px; outline: 0; }}
QListWidget#Sidebar::item {{ padding: 9px 12px; border-radius: 7px; margin: 1px 0; }}
QListWidget#Sidebar::item:hover {{ background: {c.surface}; }}
QListWidget#Sidebar::item:selected {{ background: {c.accent_soft}; color: {c.accent_text};
    font-weight: 600; }}

QPushButton {{ background: {c.surface}; border: 1px solid {c.border}; border-radius: 7px;
    padding: 7px 16px; }}
QPushButton:hover {{ border-color: {c.accent}; }}
QPushButton:pressed {{ background: {c.accent_soft}; }}
QPushButton:disabled {{ color: {c.muted}; background: {c.window}; }}
QPushButton[role="primary"] {{ background: {c.accent}; border: 1px solid {c.accent};
    color: white; font-weight: 600; }}
QPushButton[role="primary"]:hover {{ background: {c.accent_hover}; border-color: {c.accent_hover}; }}
QPushButton[role="primary"]:disabled {{ background: {c.border}; border-color: {c.border};
    color: {c.muted}; }}
QPushButton[role="danger"] {{ color: {c.danger}; }}
QPushButton[role="danger"]:hover {{ background: {c.danger_soft}; border-color: {c.danger}; }}
QPushButton[role="link"] {{ background: transparent; border: none; color: {c.accent_text};
    padding: 2px 0; text-align: left; }}
QPushButton[role="link"]:hover {{ text-decoration: underline; }}

QLineEdit, QSpinBox, QComboBox {{ background: {c.surface}; border: 1px solid {c.border};
    border-radius: 7px; padding: 6px 9px; selection-background-color: {c.accent};
    selection-color: white; }}
QLineEdit:focus, QSpinBox:focus, QComboBox:focus {{ border-color: {c.accent}; }}
QComboBox::drop-down {{ border: none; width: 22px; }}
QComboBox QAbstractItemView {{ background: {c.surface}; border: 1px solid {c.border};
    selection-background-color: {c.accent_soft}; selection-color: {c.text}; outline: 0;
    padding: 4px; }}
QSpinBox::up-button, QSpinBox::down-button {{ width: 18px; border: none; }}

QCheckBox {{ spacing: 9px; padding: 3px 0; }}

QTableWidget {{ background: {c.surface}; border: 1px solid {c.border}; border-radius: 10px;
    gridline-color: transparent; selection-background-color: {c.accent_soft};
    selection-color: {c.text}; alternate-background-color: {c.window}; outline: 0; }}
QTableWidget::item {{ padding: 4px 8px; border: none; }}
QHeaderView::section {{ background: {c.surface}; color: {c.muted}; border: none;
    border-bottom: 1px solid {c.border}; padding: 7px 8px; font-weight: 600; }}
QTableCornerButton::section {{ background: {c.surface}; border: none; }}

QProgressBar {{ background: {c.border}; border: none; border-radius: 4px; height: 8px;
    max-height: 8px; text-align: center; color: transparent; }}
QProgressBar::chunk {{ background: {c.accent}; border-radius: 4px; }}

QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
QScrollBar::handle:vertical {{ background: {c.border}; border-radius: 3px; min-height: 30px; }}
QScrollBar::handle:vertical:hover {{ background: {c.muted}; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; width: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}

QMenu {{ background: {c.surface}; border: 1px solid {c.border}; padding: 5px; }}
QMenu::item {{ padding: 7px 28px 7px 14px; border-radius: 5px; }}
QMenu::item:selected {{ background: {c.accent_soft}; color: {c.text}; }}
QMenu::item:disabled {{ color: {c.muted}; }}
QMenu::separator {{ height: 1px; background: {c.border}; margin: 5px 8px; }}

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
    }
    for role, color in roles.items():
        pal.setColor(role, QColor(color))
    pal.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Text, QColor(c.muted))
    pal.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.ButtonText, QColor(c.muted))
    pal.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.WindowText, QColor(c.muted))
    return pal


def apply(app: QApplication) -> WindowColors:
    """Style the whole application after the current Windows mode."""
    colors = current_colors()
    app.setStyle("Fusion")
    app.setPalette(qt_palette(colors))
    font = QFont()
    font.setFamilies(["Segoe UI Variable Text", "Segoe UI"])
    font.setPointSize(10)
    app.setFont(font)
    app.setStyleSheet(stylesheet(colors))
    return colors
