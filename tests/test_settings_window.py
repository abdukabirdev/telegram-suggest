import json
import time

import pytest
from PySide6.QtWidgets import QApplication

from app import settings_window as sw
from app.lexicon import Lexicon
from app.settings import Settings
from app.settings_window import SettingsWindow
from app.theme import palette_from_background
from app.welcome import WelcomeWindow


@pytest.fixture(scope="module")
def qt_app():
    app = QApplication.instance() or QApplication([])
    yield app


@pytest.fixture
def window(qt_app, store, clock):
    settings = Settings()
    lexicon = Lexicon(store, settings, clock=clock)
    for word, n in (("салом", 5), ("рахмат", 3), ("ака", 1)):
        for _ in range(n):
            lexicon.learn(word)
    win = SettingsWindow(settings, store, lexicon, lambda: palette_from_background((255, 255, 255)))
    changes, words = [], []
    win.settings_changed.connect(changes.append)
    win.words_changed.connect(lambda: words.append(1))
    win.changes, win.word_events = changes, words
    yield win
    win.hide()
    win.deleteLater()


def _wait(qt_app, condition, seconds=10.0):
    deadline = time.monotonic() + seconds
    while not condition():
        qt_app.processEvents()
        if time.monotonic() > deadline:
            raise AssertionError("timed out")
        time.sleep(0.01)


def test_pages_open(window):
    for page in sw.PAGES:
        window.show_page(page)
        assert window.current_page() == page


def test_setting_is_saved_and_reported(window, store):
    window._set("max_suggestions", 3)
    assert window.settings.max_suggestions == 3
    assert store.get_setting("max_suggestions") == 3
    assert window.changes == ["max_suggestions"]
    window._set("max_suggestions", 3)             # no change: no signal
    assert window.changes == ["max_suggestions"]


def test_theme_combo_updates_preview(window):
    window.show_page("suggest")
    before = window._preview.pixmap().toImage()
    window._set("key_hints", "always")
    after = window._preview.pixmap().toImage()
    assert before != after


def test_words_list_and_search(window):
    window.show_page("words")
    assert window._table.rowCount() == 3
    assert window._table.item(0, 0).text() == "салом"
    window._search.setText("рах")
    window.reload_words()
    assert window._table.rowCount() == 1


def test_delete_selected_words(window, monkeypatch):
    monkeypatch.setattr(SettingsWindow, "_confirm", lambda self, q, d: True)
    window.show_page("words")
    window._table.selectRow(1)
    assert window._delete.isEnabled()
    window._delete_selected()
    assert "рахмат" not in window.lexicon
    assert window._table.rowCount() == 2
    assert window.word_events == [1]


def test_clear_all_asks_first(window, monkeypatch):
    monkeypatch.setattr(SettingsWindow, "_confirm", lambda self, q, d: False)
    window._clear_all()
    assert len(window.lexicon) == 3
    monkeypatch.setattr(SettingsWindow, "_confirm", lambda self, q, d: True)
    window.settings.import_marks = {"json:1": 5}
    window._clear_all()
    assert len(window.lexicon) == 0
    assert window.settings.import_marks == {}


def test_import_flow(window, qt_app, tmp_path, store):
    export = {"name": "Кабир", "type": "personal_chat", "id": 42, "messages": [
        {"id": i, "type": "message", "date_unixtime": str(1_700_000_000 + i),
         "from": name, "from_id": sender, "text": text}
        for i, (sender, name, text) in enumerate([
            ("user1", "Абдукабир", "Ассалому алейкум дорогой"),
            ("user2", "Кабир", "Ваалейкум ассалом"),
            ("user1", "Абдукабир", "дорогой друг"),
        ], 1)
    ]}
    (tmp_path / "result.json").write_text(json.dumps(export, ensure_ascii=False), encoding="utf-8")
    window.show_page("import")
    window.start_scan(tmp_path)
    _wait(qt_app, lambda: window._state != "scanning")
    assert window._state == "ready"
    assert window._who.count() == 2                 # one chat: the user picks themself
    window._who.setCurrentIndex(0)                  # the most active sender comes first
    window._start_learning()
    _wait(qt_app, lambda: window._state != "learning")
    assert window._state == "done"
    assert "дорогой" in window.lexicon and "ваалейкум" not in window.lexicon
    assert window.settings.import_marks == {"json:42": 3}
    assert store.get_setting("import_marks") == {"json:42": 3}
    assert window.word_events
    assert "Готово" in window._import_status.text()


def test_import_of_a_wrong_folder_explains(window, qt_app, tmp_path):
    window.start_scan(tmp_path)
    _wait(qt_app, lambda: window._state != "scanning")
    assert window._state == "failed"
    assert "нет экспорта" in window._import_status.text()


def test_welcome_window(qt_app):
    welcome = WelcomeWindow(palette_from_background((255, 255, 255)), True, True)
    seen = []
    welcome.autostart_changed.connect(seen.append)
    welcome._autostart.setChecked(False)
    assert seen == [False]
    welcome.set_autostart_checked(True)
    assert seen == [False]                          # programmatic change is silent
    asked = []
    welcome.import_requested.connect(lambda: asked.append(1))
    welcome._import()
    assert asked == [1]
    welcome.deleteLater()


def test_switches_behave_like_check_boxes(window):
    from app.ui_style import Toggle

    window.show_page("general")
    switch = window._autostart
    assert isinstance(switch, Toggle)
    switch.click()
    assert switch.isChecked() and window.settings.autostart
    switch.click()
    assert not switch.isChecked() and not window.settings.autostart
    assert switch.heightForWidth(200) >= switch.heightForWidth(2000)
