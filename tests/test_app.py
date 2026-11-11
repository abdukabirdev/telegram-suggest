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


def test_program_windows_follow_the_telegram_colour(application, qt_app):
    from app import ui_style

    application._telegram_bg = (0x17, 0x21, 0x2b)
    application.settings.theme = "telegram"
    application.apply_palette()
    assert ui_style.applied_colors().dark
    assert ui_style.applied_colors().window == "#17212b"
    application._telegram_bg = (0xff, 0xff, 0xff)
    application.apply_palette()
    assert not ui_style.applied_colors().dark
    application.settings.theme = "dark"
    application.apply_palette()
    assert ui_style.applied_colors() == ui_style.DARK


def test_colour_is_sampled_even_without_ui_automation(application, monkeypatch):
    from app.positioning import Anchor

    guess = Anchor(400, 1000, 1800, 1028, "window")
    monkeypatch.setattr(application._fallback, "locate", lambda hwnd: guess)
    rect = application._sample_rect(123)
    # only the right part of the guessed row: it is inside the field in any layout
    assert rect is not None and rect[2] == 1800 and rect[0] > 400
    assert rect[1] == 1000 and rect[3] == 1028
    application._anchor = Anchor(500, 1000, 1700, 1030, "uia-search", is_password=True)
    application._anchor_hwnd = 123
    assert application._sample_rect(123) is None        # never read a password field


def test_second_launch_opens_the_running_window(application, qt_app):
    application.bridge.show_requested.emit()
    assert application.settings_window is not None
    assert application.settings_window.isVisible()
    application.open_settings("general")
    application.settings_window.hide()
    application.bridge.show_requested.emit()
    assert application.settings_window.current_page() == "general"
