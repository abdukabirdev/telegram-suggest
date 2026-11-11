"""Tray icon: the only always-visible part of the program."""

from __future__ import annotations

from PySide6.QtCore import QObject, QRectF, Qt, Signal
from PySide6.QtGui import QAction, QColor, QCursor, QFont, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import QMenu, QSystemTrayIcon

APP_TITLE = "Подсказки для Telegram"


def icon_pixmap(size: int, paused: bool = False) -> QPixmap:
    """Rounded square with the letter "А": blue when working, grey when paused."""
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
    painter.drawText(QRectF(0, -size * 0.04, size, size), Qt.AlignmentFlag.AlignCenter, "А")
    painter.end()
    return pixmap


def make_icon(paused: bool = False) -> QIcon:
    icon = QIcon()
    for size in (16, 20, 24, 32, 48, 64):
        icon.addPixmap(icon_pixmap(size, paused))
    return icon


class Tray(QObject):
    pause_toggled = Signal()
    quit_requested = Signal()
    page_requested = Signal(str)        # a page of the settings window
    help_requested = Signal()
    autostart_toggled = Signal(bool)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._paused = False
        self._icon = QSystemTrayIcon(make_icon(False), self)
        self._menu = QMenu()

        self._status = self._add("")
        self._status.setEnabled(False)
        self._menu.addSeparator()
        self._pause_action = self._add("", self.pause_toggled.emit)
        self._menu.addSeparator()
        self._add("Мои слова…", lambda: self.page_requested.emit("words"))
        self._add("Загрузить историю из Telegram…", lambda: self.page_requested.emit("import"))
        self._add("Настройки…", lambda: self.page_requested.emit("suggest"))
        self._autostart = self._add("Запускать вместе с Windows")
        self._autostart.setCheckable(True)
        self._autostart.toggled.connect(self.autostart_toggled)
        self._add("Как пользоваться", self.help_requested.emit)
        self._menu.addSeparator()
        self._add("Выход", self.quit_requested.emit)

        self._icon.setContextMenu(self._menu)
        self._icon.activated.connect(self._on_activated)
        self.set_paused(False)

    def _add(self, text: str, slot=None) -> QAction:
        action = QAction(text, self._menu)
        if slot is not None:
            action.triggered.connect(lambda _checked=False: slot())
        self._menu.addAction(action)
        return action

    def set_autostart(self, enabled: bool) -> None:
        self._autostart.blockSignals(True)
        self._autostart.setChecked(enabled)
        self._autostart.blockSignals(False)

    def set_word_count(self, text: str) -> None:
        """A greyed first line of the menu, e.g. "В словаре 1 234 слова"."""
        self._status.setText(text)

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

    def menu(self) -> QMenu:
        return self._menu

    def _on_activated(self, reason) -> None:
        # a plain left click opens the same menu: easier than a right click
        if reason == QSystemTrayIcon.ActivationReason.Trigger:
            self._menu.popup(QCursor.pos())
