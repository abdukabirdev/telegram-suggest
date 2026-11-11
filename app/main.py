"""Entry point: wires the hook, the worker, the locator and the UI together.

Threads:
    kbd-hook       keyboard hook + its message loop (app.hook)
    engine-worker  engine, dictionary, typing the accepted word (app.worker)
    locator        finds Telegram's text field via UI Automation (app.positioning)
    main           Qt: suggestion window, tray icon, timers
"""

from __future__ import annotations

import argparse
import ctypes
import gc
import logging
import signal
import sys
import time
from ctypes import wintypes
from typing import Optional

from PySide6.QtCore import QObject, QTimer, Signal
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QApplication, QMessageBox, QSystemTrayIcon

from . import inserter
from . import winapi as w
from .engine import Engine
from .hook import KeyboardHook
from .keymap import KeyTranslator
from .lexicon import Lexicon
from .logsetup import setup_logging
from .overlay import Overlay
from .paths import database_path
from .positioning import Anchor, Locator, WindowStrategy, monitor_work_area, place
from .settings import Settings
from .store import Store
from .theme import palette_for, sample_background
from .tray import APP_TITLE, Tray
from .window_watch import WindowWatch
from .worker import EngineWorker

log = logging.getLogger(__name__)

_POLL_ACTIVE_MS = 40
_POLL_IDLE_MS = 250
_HOOK_SILENCE_S = 20.0
_GAP = 6                    # between the text field and the suggestion panel
_SAMPLE_EVERY_S = 2.0       # how often Telegram's colours are re-read
_HINT_DELAY_S = 0.3         # Ctrl held this long shows the key numbers
_MUTEX_NAME = "Local\\TelegramSuggest.SingleInstance"


class Bridge(QObject):
    """Carries events from the background threads into the Qt thread."""
    suggestions = Signal(object)
    anchor = Signal(object, object)
    pause_hotkey = Signal()
    diag = Signal(object)


class Application(QObject):
    def __init__(self, store: Store, settings: Settings, lexicon: Lexicon,
                 diag: bool = False) -> None:
        super().__init__()
        self.store = store
        self.settings = settings
        self.lexicon = lexicon
        self.diag = diag

        self.bridge = Bridge()
        self.overlay = Overlay(settings.theme, settings.key_hints)
        self.tray = Tray(self)
        self.watch = WindowWatch()
        self._fallback = WindowStrategy()

        hook_watch = WindowWatch()
        worker_watch = WindowWatch()
        self.locator = Locator(self.bridge.anchor.emit)
        self.hook = KeyboardHook(
            sink=self._sink,
            is_target=hook_watch.is_target,
            on_pause_hotkey=self.bridge.pause_hotkey.emit,
        )
        self.worker = EngineWorker(
            Engine(lexicon, settings),
            lexicon,
            KeyTranslator(),
            insert=inserter.send,
            foreground_is_target=lambda: worker_watch.check()[1],
            set_visible=self._set_visible,
            on_update=self.bridge.suggestions.emit,
            on_word_start=self.locator.request,
            on_diag=self.bridge.diag.emit if diag else None,
        )

        self._paused = False
        self._blocked = False
        self._active = False
        self._target_hwnd: Optional[int] = None
        self._anchor: Optional[Anchor] = None
        self._anchor_hwnd: Optional[int] = None
        self._mouse_was_down = False
        self._overlay_click_time = 0.0
        self._last_reinstall = time.monotonic()
        self._last_diag = None
        self._telegram_bg = None
        self._last_sample = 0.0
        self._ctrl_since: Optional[float] = None

        self.bridge.suggestions.connect(self._on_suggestions)
        self.bridge.anchor.connect(self._on_anchor)
        self.bridge.pause_hotkey.connect(lambda: self.toggle_pause(notify=True))
        self.bridge.diag.connect(self._on_diag)
        self.overlay.clicked.connect(self._on_overlay_clicked)
        self.overlay.delete_requested.connect(self._on_overlay_delete)
        try:
            QGuiApplication.styleHints().colorSchemeChanged.connect(self.apply_palette)
        except AttributeError:          # Qt older than 6.5
            pass
        self.tray.pause_toggled.connect(self.toggle_pause)
        self.tray.quit_requested.connect(QApplication.quit)

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._poll)

    # ---- lifecycle ---------------------------------------------------------

    def start(self) -> None:
        self.worker.start()
        self.locator.start()
        self.hook.start()
        self.hook.installed.wait(3.0)
        self.tray.show()
        self._timer.start(_POLL_IDLE_MS)
        self.tray.notify(
            "Программа работает. Печатайте в Telegram: подсказки появятся над полем "
            "сообщения. Tab вставляет первое слово, можно выбрать и мышью."
        )
        if self.diag:
            self._print("Диагностика включена. Откройте Telegram и печатайте в поле сообщения.")
            self._print("Здесь видно то, что видит программа. Выход: Ctrl+C или значок возле часов.")
            if not self.hook.hotkey_ok:
                self._print("Внимание: Ctrl+Alt+P занята другой программой, пауза только через значок.")

    def shutdown(self) -> None:
        self._timer.stop()
        self.overlay.hide()
        self.tray.hide()
        self.hook.stop()
        self.hook.join(2.0)
        self.worker.stop()
        self.worker.join(5.0)
        self.locator.stop()
        self.locator.join(2.0)
        try:
            self.lexicon.flush()
        except Exception:
            log.exception("final save failed")

    # ---- callbacks from other threads --------------------------------------

    def _sink(self, event: tuple) -> None:
        self.worker.post(*event)            # runs in the hook thread: keep it tiny

    def _set_visible(self, count: int) -> None:
        self.hook.visible_count = count     # runs in the worker thread

    # ---- Qt thread ---------------------------------------------------------

    def toggle_pause(self, notify: bool = False) -> None:
        self._paused = not self._paused
        self.hook.paused = self._paused
        self.worker.post("pause", self._paused)
        self.tray.set_paused(self._paused)
        if self._paused:
            self.overlay.hide()
        if notify:
            self.tray.notify(
                "Подсказки выключены. Включить снова: Ctrl+Alt+P." if self._paused
                else "Подсказки включены."
            )

    def _on_overlay_clicked(self, index: int) -> None:
        # Remember the moment: this click must not be taken for a click
        # elsewhere in Telegram, which would reset the word context.
        self._overlay_click_time = time.monotonic()
        self.worker.post("accept", index)

    def _on_overlay_delete(self, index: int) -> None:
        self._overlay_click_time = time.monotonic()
        self.worker.post("forget", index)

    # ---- colours -----------------------------------------------------------

    def apply_palette(self, *_args) -> None:
        self.overlay.set_palette(palette_for(self.settings.theme, self._telegram_bg))

    def _sample_telegram(self, anchor: Optional[Anchor]) -> None:
        """Read the background of Telegram's message field, now and then.

        Only one colour is computed from the pixels; they are not kept.
        """
        if (self.settings.theme != "telegram" or anchor is None
                or anchor.source == "window" or anchor.is_password):
            return
        now = time.monotonic()
        if now - self._last_sample < _SAMPLE_EVERY_S:
            return
        if w.GetForegroundWindow() != self._target_hwnd:
            return
        field = (anchor.left, anchor.top, anchor.right, anchor.bottom)
        ours = self.overlay.native_rect()
        if ours is not None and not (ours[2] <= field[0] or field[2] <= ours[0]
                                     or ours[3] <= field[1] or field[3] <= ours[1]):
            return                      # our own window covers the field
        self._last_sample = now
        color = sample_background(field)
        if color is not None and color != self._telegram_bg:
            self._telegram_bg = color
            self.apply_palette()

    def _on_suggestions(self, texts: list) -> None:
        if texts and not self._active:
            self._poll()            # typing started before the timer noticed Telegram
        if not texts or self._paused or not self._active:
            self.overlay.hide()
            return
        self.overlay.set_items(texts)
        self._reposition()

    def _on_anchor(self, hwnd, anchor) -> None:
        self._anchor = anchor
        self._anchor_hwnd = hwnd
        blocked = bool(anchor is not None and anchor.is_password)
        if blocked != self._blocked:
            self._blocked = blocked
            self.worker.post("blocked", blocked)
        if self._active and hwnd == self._target_hwnd:
            self._sample_telegram(anchor)
        if self.overlay.isVisible():
            self._reposition()
        if self.diag:
            source = anchor.source if anchor is not None else "нет (запасной вариант по окну)"
            self._print_diag({"position": source, "password": blocked})

    def _reposition(self) -> None:
        hwnd = self._target_hwnd
        anchor = self._anchor if self._anchor_hwnd == hwnd else None
        if anchor is None and hwnd:
            anchor = self._fallback.locate(hwnd)
        if anchor is None:
            self.overlay.hide()
            return
        work = monitor_work_area(anchor.left, anchor.top)
        x, y = self._place(anchor, self.overlay.physical_size(), work)
        self.overlay.show_at(x, y)
        actual = self.overlay.native_rect()
        if actual is not None:
            size = (actual[2] - actual[0], actual[3] - actual[1])
            if size != self.overlay.physical_size():
                # the window landed on a monitor with another scale
                x, y = self._place(anchor, size, work)
                self.overlay.show_at(x, y)

    def _place(self, anchor: Anchor, size, work) -> tuple[int, int]:
        # The window is larger than the visible panel by the shadow margin:
        # line up the panel, not the window, with the text field.
        margin = self.overlay.margin_physical()
        offset = (self.settings.overlay_offset_x - margin, self.settings.overlay_offset_y)
        return place(anchor, size, work, offset, _GAP - margin)

    def _cursor_over_overlay(self) -> bool:
        rect = self.overlay.native_panel_rect()
        if rect is None:
            return False
        point = wintypes.POINT()
        if not w.GetCursorPos(ctypes.byref(point)):
            return False
        return rect[0] <= point.x < rect[2] and rect[1] <= point.y < rect[3]

    def _poll(self) -> None:
        hwnd, active = self.watch.check()
        if active != self._active or (active and hwnd != self._target_hwnd):
            self._active = active
            if active:
                self._target_hwnd = hwnd
                self.locator.request(hwnd)
            else:
                self.overlay.hide()
            self.worker.post("focus", active, hwnd)
            self._timer.setInterval(_POLL_ACTIVE_MS if active else _POLL_IDLE_MS)
            if self.diag:
                self._print_diag({"active": active})
        if not active:
            return

        # A mouse click moves the caret: the word being typed is no longer known.
        # 0x8000 = held now, 0x0001 = was pressed since the previous check
        # (catches clicks shorter than the timer interval).
        pressed = False
        for button in (w.VK_LBUTTON, w.VK_RBUTTON, w.VK_MBUTTON):
            if w.GetAsyncKeyState(button) & 0x8001:
                pressed = True
        if pressed and not self._mouse_was_down:
            on_overlay = (self._cursor_over_overlay()
                          or time.monotonic() - self._overlay_click_time < 0.4)
            if not on_overlay:
                self.worker.post("reset")
                QTimer.singleShot(150, lambda: self.locator.request(self._target_hwnd))
        self._mouse_was_down = pressed
        self._update_key_numbers()

        # Windows drops a low-level hook that was once too slow, without telling.
        now = time.monotonic()
        if (not self._paused and now - self.hook.last_callback > _HOOK_SILENCE_S
                and now - self._last_reinstall > _HOOK_SILENCE_S):
            self._last_reinstall = now
            self.hook.reinstall()

    def _update_key_numbers(self) -> None:
        """Key numbers on the words appear while Ctrl alone is held a moment."""
        held = (self.overlay.isVisible() and w.key_down(w.VK_CONTROL)
                and not w.key_down(w.VK_MENU) and not w.key_down(w.VK_SHIFT))
        if not held:
            self._ctrl_since = None
            self.overlay.set_ctrl_held(False)
            return
        now = time.monotonic()
        if self._ctrl_since is None:
            self._ctrl_since = now
        self.overlay.set_ctrl_held(now - self._ctrl_since >= _HINT_DELAY_S)

    # ---- diagnostics (console only, never written to the log) ---------------

    def _on_diag(self, info: dict) -> None:
        self._print_diag(info)

    def _print_diag(self, info: dict) -> None:
        state = dict(self._last_diag or {})
        state.update(info)
        if state == self._last_diag:
            return
        self._last_diag = state
        parts = [
            "Telegram: " + ("АКТИВЕН" if state.get("active") else "не активен"),
            "раскладка: " + str(state.get("layout", "?")),
            "префикс: «" + str(state.get("prefix", "")) + "»",
            "подсказки: " + (", ".join(state.get("suggestions") or []) or "нет"),
            "позиция: " + str(state.get("position", "?")),
        ]
        if state.get("paused"):
            parts.append("ПАУЗА")
        if state.get("password") or state.get("blocked"):
            parts.append("ПОЛЕ ПАРОЛЯ (ничего не читаем)")
        self._print(" | ".join(parts))

    @staticmethod
    def _print(text: str) -> None:
        if sys.stdout is None:
            return
        try:
            print(time.strftime("[%H:%M:%S] ") + text, flush=True)
        except (OSError, ValueError, UnicodeError):
            pass


def _parse_args(argv) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="telegram-suggest", description=APP_TITLE)
    parser.add_argument("--diag", action="store_true",
                        help="печатать в консоль состояние программы (для проверки)")
    parser.add_argument("--db", default=None,
                        help="путь к файлу базы (по умолчанию в %%APPDATA%%\\TelegramSuggest)")
    parser.add_argument("--exit-after", type=float, default=0.0, help=argparse.SUPPRESS)
    return parser.parse_args(argv)


def main(argv=None) -> int:
    args = _parse_args(sys.argv[1:] if argv is None else argv)

    mutex = w.CreateMutexW(None, False, _MUTEX_NAME)
    already_running = ctypes.get_last_error() == w.ERROR_ALREADY_EXISTS

    qt_app = QApplication(sys.argv[:1])
    qt_app.setApplicationName("TelegramSuggest")
    qt_app.setApplicationDisplayName(APP_TITLE)
    qt_app.setQuitOnLastWindowClosed(False)

    if already_running:
        QMessageBox.information(
            None, APP_TITLE,
            "Программа уже запущена.\n\n"
            "Её значок (синяя буква «А») находится возле часов, "
            "в правом нижнем углу экрана.",
        )
        return 0

    store = None
    app = None
    try:
        store = Store(args.db or database_path())
        settings = Settings.load(store)
        setup_logging(settings.log_level)
        log.info("starting, words in dictionary: %d", store.counts()[0])
        lexicon = Lexicon(store, settings, autoflush=False)
        # The dictionary lives as long as the process: take it out of the
        # garbage collector's sight so that collections stay short.
        gc.collect()
        gc.freeze()
        if not QSystemTrayIcon.isSystemTrayAvailable():
            log.warning("system tray is not available")
        app = Application(store, settings, lexicon, diag=args.diag)
        app.start()
    except Exception:
        log.exception("startup failed")
        QMessageBox.critical(
            None, APP_TITLE,
            "Не удалось запустить программу.\n\n"
            "Попробуйте перезагрузить компьютер и запустить её снова.",
        )
        if app is not None:
            app.shutdown()
        if store is not None:
            store.close()
        return 1

    signal.signal(signal.SIGINT, lambda *_: qt_app.quit())
    if args.exit_after > 0:                 # automated smoke test
        QTimer.singleShot(int(args.exit_after * 1000), qt_app.quit)
    code = qt_app.exec()
    app.shutdown()
    store.close()
    log.info("stopped")
    del mutex
    return code


if __name__ == "__main__":
    sys.exit(main())
