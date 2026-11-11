"""Application wiring of windows and settings. Threads and the hook are not started."""

import pytest
from PySide6.QtWidgets import QApplication

from app import main as main_module
from app.lexicon import Lexicon
from app.main import Application, _mutex_name
from app.settings import Settings


@pytest.fixture(scope="module")
def qt_app():
    app = QApplication.instance() or QApplication([])
    yield app


@pytest.fixture
def registry(monkeypatch):
    state = {"enabled": False, "ok": True}

    def sync(enabled, key_path=None):
        if state["ok"]:
            state["enabled"] = enabled
        return state["ok"]

    monkeypatch.setattr(main_module.autostart, "sync", sync)
    monkeypatch.setattr(main_module.autostart, "is_enabled", lambda key_path=None: state["enabled"])
    monkeypatch.setattr(main_module.QMessageBox, "warning", lambda *a, **k: None)
    return state


@pytest.fixture
def application(qt_app, store, clock, registry):
    settings = Settings()
    lexicon = Lexicon(store, settings, clock=clock)
    lexicon.learn("салом")
    app = Application(store, settings, lexicon)
    posted = []
    app.worker.post = lambda *event: posted.append(event)
    app.posted = posted
    yield app
    app.overlay.hide()
    for window in (app.settings_window, app.welcome):
        if window is not None:
            window.hide()


def test_settings_changes_reach_the_worker(application):
    application._on_setting_changed("min_suggest_len")
    application._on_setting_changed("max_suggestions")
    assert application.posted == [("settings",), ("refresh",)]


def test_key_hints_and_theme_reach_the_overlay(application):
    application.settings.key_hints = "always"
    application._on_setting_changed("key_hints")
    assert application.overlay.hints_visible()
    application.settings.theme = "dark"
    application._on_setting_changed("theme")
    assert application.overlay.palette_colors().dark
    application.settings.theme = "light"
    application._on_setting_changed("theme")
    assert not application.overlay.palette_colors().dark


def test_telegram_colour_is_used_only_in_telegram_mode(application):
    application._telegram_bg = (0x17, 0x21, 0x2b)
    application.settings.theme = "telegram"
    application.apply_palette()
    assert application.overlay.palette_colors().dark
    application.settings.theme = "light"
    application.apply_palette()
    assert not application.overlay.palette_colors().dark


def test_autostart_from_tray_is_saved_and_mirrored(application, registry, store):
    application.open_settings("general")
    application.set_autostart(True)
    assert registry["enabled"] is True
    assert store.get_setting("autostart") is True
    assert application.settings_window._autostart.isChecked()
    application.set_autostart(False)
    assert registry["enabled"] is False
    assert not application.settings_window._autostart.isChecked()


def test_autostart_failure_is_rolled_back(application, registry):
    registry["ok"] = False
    application.set_autostart(True)
    assert application.settings.autostart is False


def test_first_run_shows_welcome_once(application, store):
    application._first_run()
    assert application.welcome is not None and application.welcome.isVisible()
    assert store.get_setting("welcome_shown") is True
    application.show_welcome(first_run=False)       # replaces the old one
    assert application.welcome.isVisible()


def test_words_change_refreshes(application):
    application._on_words_changed()
    assert application.posted == [("refresh",)]
    assert "1 слово" in application.tray._status.text()


def test_overlay_right_click_deletes_through_worker(application):
    application._on_overlay_delete(2)
    assert application.posted == [("forget", 2)]


def test_test_copy_never_touches_autostart(qt_app, store, clock, registry):
    settings = Settings()
    app = Application(store, settings, Lexicon(store, settings, clock=clock), test_copy=True)
    app.set_autostart(True)
    assert registry["enabled"] is False
    app.overlay.hide()


def test_mutex_name_per_dictionary(tmp_path):
    assert _mutex_name(None) == main_module._MUTEX_NAME
    a = _mutex_name(str(tmp_path / "a.db"))
    assert a != _mutex_name(str(tmp_path / "b.db"))
    assert a == _mutex_name(str(tmp_path / "A.db"))
