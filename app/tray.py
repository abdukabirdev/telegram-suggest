"""Tray icon: the only always-visible part of the program."""

from __future__ import annotations

from PySide6.QtCore import QObject, QRectF, Qt, Signal
from PySide6.QtGui import QAction, QColor, QFont, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import QMenu, QSystemTrayIcon

APP_TITLE = "Подсказки для Telegram"


def make_icon(paused: bool = False) -> QIcon:
    """Rounded square with the letter "А": blue when working, grey when paused."""
    icon = QIcon()
    for size in (16, 20, 24, 32, 48, 64):
        pixmap = QPixmap(size, size)
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor("#8a9099" if paused else "#2a9ef0"))
        radius = size * 0.24
        painter.drawRoundedRect(QRectF(0.5, 0.5, size - 1, size - 1), radius, radius)
        font = QFont("Segoe UI")
        font.setBold(True)
        font.setPixelSize(int(size * 0.68))
        painter.setFont(font)
        painter.setPen(QColor("#ffffff"))
        painter.drawText(QRectF(0, -size * 0.04, size, size),
                         Qt.AlignmentFlag.AlignCenter, "А")
        painter.end()
        icon.addPixmap(pixmap)
    return icon


class Tray(QObject):
    pause_toggled = Signal()
    quit_requested = Signal()

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._paused = False
        self._icon = QSystemTrayIcon(make_icon(False), self)
        self._menu = QMenu()
        self._pause_action = QAction(self._menu)
        self._pause_action.triggered.connect(self.pause_toggled)
        self._menu.addAction(self._pause_action)
        self._menu.addSeparator()
        quit_action = QAction("Выход", self._menu)
        quit_action.triggered.connect(self.quit_requested)
        self._menu.addAction(quit_action)
        self._icon.setContextMenu(self._menu)
        self._icon.activated.connect(self._on_activated)
        self.set_paused(False)

    def show(self) -> None:
        self._icon.show()

    def hide(self) -> None:
        self._icon.hide()

    def set_paused(self, paused: bool) -> None:
        self._paused = paused
        self._icon.setIcon(make_icon(paused))
        if paused:
            self._pause_action.setText("Включить подсказки\tCtrl+Alt+P")
            self._icon.setToolTip(f"{APP_TITLE}: выключены (пауза)")
        else:
            self._pause_action.setText("Выключить на время (пауза)\tCtrl+Alt+P")
            self._icon.setToolTip(f"{APP_TITLE}: работают")

    def notify(self, text: str) -> None:
        self._icon.showMessage(APP_TITLE, text, make_icon(self._paused), 4000)

    def _on_activated(self, reason) -> None:
        # a plain left click opens the same menu: easier than a right click
        if reason == QSystemTrayIcon.ActivationReason.Trigger:
            from PySide6.QtGui import QCursor

            self._menu.popup(QCursor.pos())
