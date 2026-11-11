"""First-run greeting, also the "How to use" window from the tray menu."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from .overlay import Overlay
from .settings_window import button, label
from .theme import Palette
from .tray import APP_TITLE, make_icon
from .ui_style import Toggle

# (keys, what they do); keys are shown as keyboard "caps"
TIPS = [
    (["Tab"], "вставить первое, выделенное слово"),
    (["Ctrl", "2"], "вставить второе слово (номера видны, пока зажат Ctrl)"),
    (["щелчок"], "мышью по любому слову: вставить его"),
    (["правый щелчок"], "по слову: удалить его из словаря"),
    (["Esc"], "скрыть подсказки до следующего слова"),
    (["Ctrl", "Alt", "P"], "выключить на время или включить снова"),
]


def key_cap(text: str) -> QLabel:
    cap = QLabel(text)
    cap.setProperty("role", "key")
    cap.setAlignment(Qt.AlignmentFlag.AlignCenter)
    return cap


class WelcomeWindow(QWidget):
    import_requested = Signal()
    autostart_changed = Signal(bool)

    def __init__(self, palette: Palette, autostart: bool, first_run: bool) -> None:
        super().__init__(None, Qt.WindowType.Window)
        self.setObjectName("Root")
        self.setWindowTitle(APP_TITLE)
        self.setWindowIcon(make_icon())
        self.setMinimumWidth(560)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(32, 28, 32, 24)
        layout.setSpacing(14)

        layout.addWidget(label("Подсказки для Telegram" if first_run else "Как пользоваться",
                               "title"))
        layout.addWidget(label(
            "Печатайте в Telegram как обычно: над полем сообщения появятся слова, "
            "как на клавиатуре телефона. Программа учится на вашем наборе, поэтому "
            "с каждым днём подсказки точнее.", "hint"))

        preview = Overlay("light")
        preview.set_palette(palette)
        preview.set_items(["Ассалому", "алейкум", "ака"])
        picture = QLabel()
        picture.setPixmap(preview.grab())
        preview.deleteLater()
        layout.addWidget(picture, 0, Qt.AlignmentFlag.AlignLeft)

        tips = QFrame()
        tips.setProperty("role", "card")
        tips_layout = QVBoxLayout(tips)
        tips_layout.setContentsMargins(18, 14, 18, 14)
        tips_layout.setSpacing(9)
        for keys, text in TIPS:
            row = QHBoxLayout()
            row.setSpacing(5)
            keys_box = QWidget()
            keys_box.setFixedWidth(170)
            keys_row = QHBoxLayout(keys_box)
            keys_row.setContentsMargins(0, 0, 0, 0)
            keys_row.setSpacing(4)
            for i, key in enumerate(keys):
                if i:
                    keys_row.addWidget(label("+", "hint", wrap=False))
                keys_row.addWidget(key_cap(key))
            keys_row.addStretch(1)
            row.addWidget(keys_box)
            row.addWidget(label(text), 1)
            tips_layout.addLayout(row)
        layout.addWidget(tips)

        layout.addWidget(label(
            "Значок «А» возле часов (справа внизу) открывает настройки, список ваших слов "
            "и выход. Если значка не видно, нажмите стрелку ^ возле часов.", "hint"))

        self._autostart = Toggle("Запускать вместе с Windows")
        self._autostart.setChecked(autostart)
        self._autostart.toggled.connect(self.autostart_changed)
        layout.addWidget(self._autostart)

        buttons = QHBoxLayout()
        history = button("Загрузить историю из Telegram…")
        history.setToolTip("Программа выучит слова из ваших прошлых сообщений")
        history.clicked.connect(self._import)
        buttons.addWidget(history)
        buttons.addStretch(1)
        start = button("Начать" if first_run else "Понятно", "primary")
        start.setDefault(True)
        start.clicked.connect(self.close)
        buttons.addWidget(start)
        layout.addLayout(buttons)

    def set_autostart_checked(self, value: bool) -> None:
        self._autostart.blockSignals(True)
        self._autostart.setChecked(value)
        self._autostart.blockSignals(False)

    def _import(self) -> None:
        self.import_requested.emit()
        self.close()
