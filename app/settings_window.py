"""Settings window: suggestions, the user's words, history import, general.

Every change applies at once and is saved at once: there is no "Save" button
to forget. The window reports changes with ``settings_changed(name)`` and
``words_changed()``; the application reacts to them.
"""

from __future__ import annotations

import logging
import os
import threading
from pathlib import Path
from typing import Callable, Optional

from PySide6.QtCore import QObject, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QComboBox, QFileDialog, QFrame,
                               QGridLayout, QHBoxLayout, QHeaderView, QLabel, QLineEdit,
                               QListWidget, QMessageBox, QProgressBar, QPushButton, QScrollArea,
                               QSpinBox, QStackedWidget, QTableWidget, QTableWidgetItem,
                               QVBoxLayout, QWidget)

from . import importer, ru
from .overlay import Overlay
from .paths import data_dir
from .settings import Settings
from .theme import Palette
from .tray import APP_TITLE, make_icon

log = logging.getLogger(__name__)

PAGES = ("suggest", "words", "import", "general")
_PAGE_TITLES = {
    "suggest": "Подсказки",
    "words": "Мои слова",
    "import": "Загрузить историю",
    "general": "Общие",
}
_WORDS_LIMIT = 500
_PREVIEW_WORDS = ["Ассалому", "алейкум", "ака", "ассалом"]


# ---- small building blocks ---------------------------------------------------


def label(text: str, role: str = "", wrap: bool = True) -> QLabel:
    widget = QLabel(text)
    widget.setWordWrap(wrap)
    widget.setTextFormat(Qt.TextFormat.PlainText)
    if role:
        widget.setProperty("role", role)
    return widget


def button(text: str, role: str = "") -> QPushButton:
    widget = QPushButton(text)
    widget.setCursor(Qt.CursorShape.PointingHandCursor)
    if role:
        widget.setProperty("role", role)
    return widget


def card() -> tuple[QFrame, QVBoxLayout]:
    frame = QFrame()
    frame.setProperty("role", "card")
    layout = QVBoxLayout(frame)
    layout.setContentsMargins(18, 14, 18, 16)
    layout.setSpacing(8)
    return frame, layout


def page_layout(title: str, subtitle: str = "") -> tuple[QWidget, QVBoxLayout]:
    page = QWidget()
    layout = QVBoxLayout(page)
    layout.setContentsMargins(28, 22, 28, 22)
    layout.setSpacing(12)
    layout.addWidget(label(title, "title"))
    if subtitle:
        layout.addWidget(label(subtitle, "hint"))
    return page, layout


def scrollable(page: QWidget) -> QScrollArea:
    area = QScrollArea()
    area.setWidget(page)
    area.setWidgetResizable(True)
    area.setFrameShape(QFrame.Shape.NoFrame)
    area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    return area


def downloads_folder() -> str:
    home = Path(os.environ.get("USERPROFILE") or Path.home())
    for candidate in (home / "Downloads" / "Telegram Desktop", home / "Downloads", home):
        if candidate.is_dir():
            return str(candidate)
    return str(home)


# ---- import in the background ------------------------------------------------


class ImportJob(QObject):
    """Reads and learns an export in a plain thread; reports through signals."""

    scanned = Signal(object)            # ExportScan
    progress = Signal(int, int)
    finished = Signal(object, object)   # ImportResult, marks
    failed = Signal(str)

    def __init__(self) -> None:
        super().__init__()
        self._cancel = threading.Event()
        self._thread: Optional[threading.Thread] = None

    def busy(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def cancel(self) -> None:
        self._cancel.set()

    def _start(self, target, *args) -> None:
        # every run has its own flag: a cancelled run can never report back
        self._cancel = cancel = threading.Event()
        self._thread = threading.Thread(target=target, args=(cancel, *args),
                                        name="import", daemon=True)
        self._thread.start()

    def scan(self, path: Path) -> None:
        self._start(self._scan, path)

    def _scan(self, cancel: threading.Event, path: Path) -> None:
        try:
            export = importer.scan(path)
        except importer.ExportError as e:
            if not cancel.is_set():
                self.failed.emit(str(e))
            return
        except Exception:
            log.exception("reading the export failed")
            if not cancel.is_set():
                self.failed.emit("Не удалось прочитать экспорт. Попробуйте выгрузить его "
                                 "из Telegram ещё раз.")
            return
        if not cancel.is_set():
            self.scanned.emit(export)

    def learn(self, lexicon, export, own: set, marks: dict) -> None:
        self._start(self._learn, lexicon, export, own, dict(marks))

    def _learn(self, cancel: threading.Event, lexicon, export, own, marks) -> None:
        try:
            result = importer.learn_messages(
                lexicon, export, own, marks,
                progress=self.progress.emit, cancelled=cancel.is_set,
            )
        except Exception:
            log.exception("import failed")
            self.failed.emit("Во время загрузки произошла ошибка. То, что успело "
                             "загрузиться, сохранено.")
            return
        self.finished.emit(result, marks)


# ---- the window --------------------------------------------------------------


class SettingsWindow(QWidget):
    settings_changed = Signal(str)
    words_changed = Signal()
    welcome_requested = Signal()

    def __init__(self, settings: Settings, store, lexicon,
                 palette_for_preview: Callable[[], Palette]) -> None:
        super().__init__(None, Qt.WindowType.Window)
        self.settings = settings
        self.store = store
        self.lexicon = lexicon
        self._preview_palette = palette_for_preview
        self.setObjectName("Root")
        self.setWindowTitle(f"{APP_TITLE}: настройки")
        self.setWindowIcon(make_icon())
        self.resize(820, 580)
        self.setMinimumSize(680, 460)

        self._sidebar = QListWidget()
        self._sidebar.setObjectName("Sidebar")
        self._sidebar.setFixedWidth(200)
        self._sidebar.setCursor(Qt.CursorShape.PointingHandCursor)
        self._stack = QStackedWidget()
        for name in PAGES:
            self._sidebar.addItem(_PAGE_TITLES[name])
        self._stack.addWidget(scrollable(self._build_suggest_page()))
        self._stack.addWidget(self._build_words_page())
        self._stack.addWidget(scrollable(self._build_import_page()))
        self._stack.addWidget(scrollable(self._build_general_page()))
        self._sidebar.currentRowChanged.connect(self._on_page)
        self._sidebar.setCurrentRow(0)

        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        root.addWidget(self._sidebar)
        root.addWidget(self._stack, 1)

        self._search_timer = QTimer(self)
        self._search_timer.setSingleShot(True)
        self._search_timer.setInterval(200)
        self._search_timer.timeout.connect(self.reload_words)

    # ---- navigation --------------------------------------------------------

    def show_page(self, name: str) -> None:
        self._sidebar.setCurrentRow(PAGES.index(name) if name in PAGES else 0)
        if self.isMinimized():
            self.showNormal()
        self.show()
        self.raise_()
        self.activateWindow()

    def current_page(self) -> str:
        return PAGES[self._stack.currentIndex()]

    def _on_page(self, row: int) -> None:
        self._stack.setCurrentIndex(row)
        if PAGES[row] == "words":
            self.reload_words()
        elif PAGES[row] == "suggest":
            self.refresh_preview()

    def closeEvent(self, event) -> None:
        if self.importing():
            # keep importing in the background; the window can come back
            event.ignore()
            self.hide()
            return
        event.accept()

    # ---- saving ------------------------------------------------------------

    def _set(self, name: str, value) -> None:
        if getattr(self.settings, name) == value:
            return
        setattr(self.settings, name, value)
        self.store.set_setting(name, value)
        self.settings_changed.emit(name)

    def _check(self, name: str, text: str) -> QCheckBox:
        box = QCheckBox(text)
        box.setChecked(bool(getattr(self.settings, name)))
        box.toggled.connect(lambda value: self._set(name, bool(value)))
        return box

    def _spin(self, name: str, low: int, high: int, suffix: str = "") -> QSpinBox:
        box = QSpinBox()
        box.setRange(low, high)
        box.setValue(int(getattr(self.settings, name)))
        if suffix:
            box.setSuffix(suffix)
        box.setFixedWidth(110)
        box.valueChanged.connect(lambda value: self._set(name, int(value)))
        return box

    def _combo(self, name: str, choices: list[tuple[str, str]]) -> QComboBox:
        box = QComboBox()
        for value, text in choices:
            box.addItem(text, value)
        values = [value for value, _ in choices]
        current = getattr(self.settings, name)
        box.setCurrentIndex(values.index(current) if current in values else 0)
        box.currentIndexChanged.connect(lambda _i: self._set(name, box.currentData()))
        box.setMinimumWidth(240)
        return box

    # ---- page: suggestions -------------------------------------------------

    def _build_suggest_page(self) -> QWidget:
        page, layout = page_layout(
            "Подсказки", "Как выглядят и какие слова предлагаются. Изменения действуют сразу.")

        frame, box = card()
        box.addWidget(label("Так выглядит окно подсказок", "section"))
        self._preview = QLabel()
        self._preview.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        self._preview.setMinimumHeight(60)
        box.addWidget(self._preview)
        self._preview_hint = label("", "hint")
        box.addWidget(self._preview_hint)
        layout.addWidget(frame)
        self._preview_overlay = Overlay(self.settings.theme, self.settings.key_hints)
        self._preview_overlay.set_items(_PREVIEW_WORDS)

        frame, box = card()
        box.addWidget(label("Оформление", "section"))
        grid = QGridLayout()
        grid.setHorizontalSpacing(16)
        grid.setVerticalSpacing(10)
        grid.addWidget(label("Цвета окна", wrap=False), 0, 0)
        grid.addWidget(self._combo("theme", [
            ("telegram", "Как в Telegram"),
            ("system", "Как в Windows"),
            ("dark", "Тёмные"),
            ("light", "Светлые"),
        ]), 0, 1)
        grid.addWidget(label("Номера клавиш на словах", wrap=False), 1, 0)
        grid.addWidget(self._combo("key_hints", [
            ("ctrl", "Только пока зажат Ctrl"),
            ("always", "Всегда"),
            ("never", "Никогда"),
        ]), 1, 1)
        grid.setColumnStretch(2, 1)
        box.addLayout(grid)
        layout.addWidget(frame)

        frame, box = card()
        box.addWidget(label("Какие слова предлагать", "section"))
        grid = QGridLayout()
        grid.setHorizontalSpacing(16)
        grid.setVerticalSpacing(10)
        grid.addWidget(label("Сколько слов показывать", wrap=False), 0, 0)
        grid.addWidget(self._spin("max_suggestions", 1, 6), 0, 1)
        grid.addWidget(label("Предлагать слова длиной от", wrap=False), 1, 0)
        grid.addWidget(self._spin("min_suggest_len", 2, 6, " букв"), 1, 1)
        grid.setColumnStretch(2, 1)
        box.addLayout(grid)
        box.addWidget(self._check(
            "predict_next_word",
            "Предлагать следующее слово сразу после пробела (по вашим частым сочетаниям)"))
        box.addWidget(self._check(
            "cross_script",
            "Узбекский: предлагать слово и в другой письменности (кириллица ↔ латиница)"))
        layout.addWidget(frame)

        frame, box = card()
        box.addWidget(label("Положение окна", "section"))
        box.addWidget(label("Обычно окно стоит прямо над полем сообщения. Если оно мешает, "
                            "его можно сдвинуть.", "hint"))
        row = QHBoxLayout()
        row.setSpacing(10)
        row.addWidget(label("Вправо на", wrap=False))
        self._offset_x = self._spin("overlay_offset_x", -400, 400, " пикс.")
        row.addWidget(self._offset_x)
        row.addSpacing(12)
        row.addWidget(label("Вниз на", wrap=False))
        self._offset_y = self._spin("overlay_offset_y", -400, 400, " пикс.")
        row.addWidget(self._offset_y)
        row.addSpacing(12)
        reset = button("Как было", "link")
        reset.clicked.connect(lambda: (self._offset_x.setValue(0), self._offset_y.setValue(0)))
        row.addWidget(reset)
        row.addStretch(1)
        box.addLayout(row)
        layout.addWidget(frame)
        layout.addStretch(1)
        self.settings_changed.connect(self._on_own_change)
        return page

    def _on_own_change(self, name: str) -> None:
        if name in ("theme", "key_hints"):
            self.refresh_preview()

    def refresh_preview(self) -> None:
        overlay = self._preview_overlay
        overlay.set_palette(self._preview_palette())
        overlay.set_key_hints(self.settings.key_hints)
        overlay.set_ctrl_held(False)
        self._preview.setPixmap(overlay.grab())
        hints = {
            "ctrl": "Tab вставляет первое (выделенное) слово. Номера 1, 2, 3… появляются "
                    "на словах, пока зажат Ctrl: Ctrl+2 вставит второе слово.",
            "always": "Tab вставляет первое (выделенное) слово, Ctrl+2 — второе и так далее.",
            "never": "Tab вставляет первое (выделенное) слово, Ctrl+2 — второе и так далее. "
                     "Любое слово можно выбрать мышью.",
        }
        theme_note = {
            "telegram": " Цвета подстраиваются под тему Telegram, когда вы печатаете.",
        }
        self._preview_hint.setText(hints.get(self.settings.key_hints, "")
                                   + theme_note.get(self.settings.theme, ""))

    # ---- page: words -------------------------------------------------------

    def _build_words_page(self) -> QWidget:
        page, layout = page_layout(
            "Мои слова",
            "Слова, которые программа запомнила из вашего набора. Ненужное слово можно удалить: "
            "здесь или правым щелчком по нему в окне подсказок.")
        top = QHBoxLayout()
        self._search = QLineEdit()
        self._search.setPlaceholderText("Найти слово…")
        self._search.setClearButtonEnabled(True)
        self._search.textChanged.connect(lambda _t: self._search_timer.start())
        top.addWidget(self._search, 1)
        self._count = label("", "hint", wrap=False)
        top.addWidget(self._count)
        layout.addLayout(top)

        table = QTableWidget(0, 3)
        table.setHorizontalHeaderLabels(["Слово", "Сколько раз", "Последний раз"])
        table.verticalHeader().setVisible(False)
        table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        table.setShowGrid(False)
        table.setAlternatingRowColors(True)
        table.verticalHeader().setDefaultSectionSize(32)
        header = table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        header.setDefaultAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        table.itemSelectionChanged.connect(self._on_selection)
        self._table = table
        layout.addWidget(table, 1)

        bottom = QHBoxLayout()
        self._delete = button("Удалить выбранные", "danger")
        self._delete.setEnabled(False)
        self._delete.clicked.connect(self._delete_selected)
        bottom.addWidget(self._delete)
        bottom.addStretch(1)
        clear = button("Очистить весь словарь…", "danger")
        clear.clicked.connect(self._clear_all)
        bottom.addWidget(clear)
        layout.addLayout(bottom)
        return page

    def reload_words(self) -> None:
        query = self._search.text()
        found = self.lexicon.search(query, limit=_WORDS_LIMIT)
        table = self._table
        table.setRowCount(len(found))
        for row, info in enumerate(found):
            word = QTableWidgetItem(info.display)
            word.setData(Qt.ItemDataRole.UserRole, info.word)
            uses = QTableWidgetItem(ru.plural(info.freq, ru.TIMES))
            last = QTableWidgetItem(ru.date(info.last_used))
            table.setItem(row, 0, word)
            table.setItem(row, 1, uses)
            table.setItem(row, 2, last)
        total = len(self.lexicon)
        if query.strip():
            text = f"найдено: {len(found)}" + (" (первые)" if len(found) >= _WORDS_LIMIT else "")
        elif total > len(found):
            text = f"всего {ru.plural(total, ru.WORDS)}, показаны {len(found)} самых частых"
        else:
            text = f"всего {ru.plural(total, ru.WORDS)}"
        self._count.setText(text)
        self._on_selection()

    def _selected_words(self) -> list[str]:
        rows = sorted({index.row() for index in self._table.selectedIndexes()})
        return [self._table.item(r, 0).data(Qt.ItemDataRole.UserRole) for r in rows]

    def _on_selection(self) -> None:
        count = len(self._selected_words())
        self._delete.setEnabled(count > 0)
        self._delete.setText(f"Удалить: {ru.plural(count, ru.WORDS)}" if count
                             else "Удалить выбранные")

    def _delete_selected(self) -> None:
        words = self._selected_words()
        if not words:
            return
        question = (f"Удалить слово «{words[0]}» из словаря?" if len(words) == 1
                    else f"Удалить {ru.plural(len(words), ru.WORDS)} из словаря?")
        if not self._confirm(question, "Программа забудет их. Если вы снова наберёте "
                                       "такое слово, оно запомнится заново."):
            return
        for word in words:
            self.lexicon.delete(word)
        self.words_changed.emit()
        self.reload_words()

    def _clear_all(self) -> None:
        total = len(self.lexicon)
        if total == 0:
            return
        if not self._confirm(f"Удалить все {ru.plural(total, ru.WORDS)}?",
                             "Словарь станет пустым, подсказки начнут копиться заново. "
                             "Отменить это нельзя."):
            return
        self.lexicon.clear()
        self.settings.import_marks = {}
        self.store.set_setting("import_marks", {})
        self.words_changed.emit()
        self.reload_words()

    def _confirm(self, question: str, details: str) -> bool:
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Question)
        box.setWindowTitle(APP_TITLE)
        box.setText(question)
        box.setInformativeText(details)
        yes = box.addButton("Удалить", QMessageBox.ButtonRole.DestructiveRole)
        box.addButton("Отмена", QMessageBox.ButtonRole.RejectRole)
        box.exec()
        return box.clickedButton() is yes

    # ---- page: import ------------------------------------------------------

    def _build_import_page(self) -> QWidget:
        page, layout = page_layout(
            "Загрузить историю из Telegram",
            "Программа может сразу выучить слова из ваших старых сообщений, и подсказки "
            "будут полезны с первого дня. Учатся только ваши собственные сообщения; "
            "переписка никуда не отправляется и целиком не сохраняется.")

        frame, box = card()
        box.addWidget(label("Как выгрузить историю", "section"))
        steps = [
            "В Telegram Desktop откройте нужный чат, нажмите ⋮ (три точки вверху справа) → "
            "«Экспорт истории чата». Чтобы взять все чаты сразу: Настройки → Продвинутые "
            "настройки → «Экспорт данных из Telegram».",
            "Снимите галочки с фото, видео, файлов: нужны только сообщения. Формат можно "
            "оставить любой.",
            "Нажмите «Экспортировать» и дождитесь конца. Telegram сохранит папку, обычно "
            "в «Загрузки\\Telegram Desktop».",
            "Нажмите кнопку ниже и выберите эту папку.",
        ]
        for i, text in enumerate(steps, 1):
            row = QHBoxLayout()
            row.setSpacing(12)
            number = label(str(i), "step", wrap=False)
            row.addWidget(number, 0, Qt.AlignmentFlag.AlignTop)
            row.addWidget(label(text), 1)
            box.addLayout(row)
        layout.addWidget(frame)

        frame, box = card()
        self._import_status = label("", "")
        self._import_status.setVisible(False)
        box.addWidget(self._import_status)

        self._who_row = QWidget()
        who = QHBoxLayout(self._who_row)
        who.setContentsMargins(0, 0, 0, 0)
        who.addWidget(label("Кто из них вы?", wrap=False))
        self._who = QComboBox()
        self._who.setMinimumWidth(280)
        who.addWidget(self._who)
        who.addStretch(1)
        self._who_row.setVisible(False)
        box.addWidget(self._who_row)

        self._progress = QProgressBar()
        self._progress.setVisible(False)
        box.addWidget(self._progress)

        buttons = QHBoxLayout()
        self._pick_folder = button("Выбрать папку экспорта…", "primary")
        self._pick_folder.clicked.connect(self._choose_folder)
        self._pick_file = button("Выбрать файл…")
        self._pick_file.clicked.connect(self._choose_file)
        self._start = button("Загрузить мои слова", "primary")
        self._start.clicked.connect(self._start_learning)
        self._cancel = button("Отмена")
        self._cancel.clicked.connect(self._cancel_import)
        for widget in (self._pick_folder, self._pick_file, self._start, self._cancel):
            buttons.addWidget(widget)
        buttons.addStretch(1)
        box.addLayout(buttons)
        layout.addWidget(frame)
        layout.addStretch(1)

        self._job = ImportJob()
        self._job.scanned.connect(self._on_scanned)
        self._job.progress.connect(self._on_progress)
        self._job.finished.connect(self._on_learned)
        self._job.failed.connect(self._on_import_failed)
        self._export = None
        self._import_state("idle")
        return page

    def _import_state(self, state: str, text: str = "") -> None:
        self._state = state
        picking = state in ("idle", "done", "failed")
        self._pick_folder.setVisible(picking)
        self._pick_file.setVisible(picking)
        self._pick_folder.setText("Выбрать другую папку…" if state == "done"
                                  else "Выбрать папку экспорта…")
        self._start.setVisible(state == "ready")
        self._cancel.setVisible(state in ("ready", "scanning", "learning"))
        self._who_row.setVisible(state == "ready" and self._who.count() > 1)
        self._progress.setVisible(state in ("scanning", "learning"))
        if state == "scanning":
            self._progress.setRange(0, 0)
        self._import_status.setVisible(bool(text))
        self._import_status.setText(text)

    def _choose_folder(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "Папка экспорта Telegram",
                                                downloads_folder())
        if path:
            self.start_scan(Path(path))

    def _choose_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Файл экспорта Telegram", downloads_folder(),
            "Экспорт Telegram (result.json messages*.html);;Все файлы (*)")
        if path:
            self.start_scan(Path(path))

    def start_scan(self, path: Path) -> None:
        if self.importing():
            return
        self._import_state("scanning", "Читаю экспорт…")
        self._job.scan(path)

    def _on_scanned(self, export) -> None:
        self._export = export
        self._who.clear()
        candidates = export.candidates()
        own = export.own
        if own is None and len(candidates) == 1:
            own = candidates[0][0]
        if own is not None:
            name = export.names.get(own, "вы")
            self._who.addItem(name, own)
            mine = export.senders[own]
            text = (f"Найдено: {ru.plural(len(export.chats), ru.CHATS)}, ваших сообщений: "
                    f"{mine:,}.".replace(",", " "))
        else:
            for key, name, count in candidates[:30]:
                self._who.addItem(f"{name}  ({ru.plural(count, ru.MESSAGES)})", key)
            text = ("Найдено: " + ru.plural(len(export.messages), ru.MESSAGES)
                    + ". Telegram не указывает в этом экспорте, кто вы: выберите себя в списке.")
        self._import_state("ready", text)

    def _start_learning(self) -> None:
        if self._export is None or self._who.count() == 0:
            return
        own = {self._who.currentData()}
        self._progress.setRange(0, 1)
        self._progress.setValue(0)
        self._import_state("learning", "Учу слова из ваших сообщений…")
        self._job.learn(self.lexicon, self._export, own, self.settings.import_marks)

    def _on_progress(self, done: int, total: int) -> None:
        if self._state != "learning":
            return
        self._progress.setRange(0, max(total, 1))
        self._progress.setValue(done)
        self._import_status.setText(
            f"Учу слова из ваших сообщений… {done:,} из {total:,}".replace(",", " "))

    def _on_learned(self, result, marks: dict) -> None:
        self._export = None
        self.settings.import_marks = marks
        self.store.set_setting("import_marks", marks)
        self.words_changed.emit()
        parts = []
        if result.cancelled:
            parts.append("Загрузка остановлена. То, что успело загрузиться, сохранено; "
                         "при следующей загрузке программа продолжит с того же места.")
        else:
            parts.append("Готово!")
        parts.append(f"Изучено {ru.plural(result.messages, ru.MESSAGES)}, "
                     f"в них {ru.plural(result.words, ru.WORDS)}.")
        if result.skipped:
            parts.append(f"Ещё {ru.plural(result.skipped, ru.MESSAGES)} уже были загружены "
                         "раньше и второй раз не считались.")
        parts.append(f"Сейчас в словаре {ru.plural(len(self.lexicon), ru.WORDS)}.")
        self._import_state("done", " ".join(parts))

    def _on_import_failed(self, message: str) -> None:
        self._export = None
        self._import_state("failed", message)

    def _cancel_import(self) -> None:
        if self._state == "learning":
            self._job.cancel()
            self._import_status.setText("Останавливаю…")
        else:
            self._job.cancel()          # a scan still running will not report back
            self._export = None
            self._import_state("idle")

    def importing(self) -> bool:
        return self._state == "learning" and self._job.busy()

    def stop_import(self, timeout: float = 5.0) -> None:
        """On exit: stop a running import; what was learned so far is kept."""
        self._job.cancel()
        thread = self._job._thread
        if thread is not None:
            thread.join(timeout)

    # ---- page: general -----------------------------------------------------

    def _build_general_page(self) -> QWidget:
        page, layout = page_layout("Общие")

        frame, box = card()
        box.addWidget(label("Запуск", "section"))
        self._autostart = self._check("autostart", "Запускать вместе с Windows")
        box.addWidget(self._autostart)
        box.addWidget(label("Программа будет тихо запускаться при входе в Windows; "
                            "её значок «А» появится возле часов.", "hint"))
        layout.addWidget(frame)

        frame, box = card()
        box.addWidget(label("Ваши данные", "section"))
        box.addWidget(label(
            "Словарь хранится только на этом компьютере и никуда не отправляется. "
            "Сохраняются отдельные слова и пары слов, но не ваши сообщения.", ""))
        path = label(str(data_dir()), "hint")
        path.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        box.addWidget(path)
        open_folder = button("Открыть папку", "link")
        open_folder.clicked.connect(self._open_data_folder)
        box.addWidget(open_folder, 0, Qt.AlignmentFlag.AlignLeft)
        layout.addWidget(frame)

        frame, box = card()
        box.addWidget(label("Помощь", "section"))
        box.addWidget(label("Короткая памятка: как вставлять слова, как удалять "
                            "ненужные, где выключить.", ""))
        help_button = button("Как пользоваться")
        help_button.clicked.connect(self.welcome_requested)
        box.addWidget(help_button, 0, Qt.AlignmentFlag.AlignLeft)
        layout.addWidget(frame)
        layout.addStretch(1)
        return page

    def set_autostart_checked(self, value: bool) -> None:
        self._autostart.blockSignals(True)
        self._autostart.setChecked(value)
        self._autostart.blockSignals(False)

    @staticmethod
    def _open_data_folder() -> None:
        folder = data_dir()
        folder.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder)))
