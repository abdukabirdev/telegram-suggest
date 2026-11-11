import pytest

from app.settings import Settings
from app.store import Store

WORD = ("салом", "Салом", "салом", "salom", "cyr", 3, 2.5, 1000.0, 1, 2)
WORD2 = ("алейкум", None, "алейкум", "aleykum", "cyr", 1, 1.0, 1000.0, 1, 0)


def test_words_and_bigrams_roundtrip(store):
    store.save_words([WORD, WORD2])
    store.save_bigrams([("салом", "алейкум", 2, 1.5, 1000.0)])
    assert sorted(store.load_words()) == sorted([WORD, WORD2])
    assert store.load_bigrams() == [("салом", "алейкум", 2, 1.5, 1000.0)]
    assert store.counts() == (2, 1)


def test_save_replaces_existing_row(store):
    store.save_words([WORD])
    updated = WORD[:5] + (4,) + WORD[6:]
    store.save_words([updated])
    assert store.load_words() == [updated]


def test_delete_word_removes_its_bigrams(store):
    store.save_words([WORD, WORD2])
    store.save_bigrams([
        ("салом", "алейкум", 1, 1.0, 1.0),
        ("алейкум", "салом", 1, 1.0, 1.0),
    ])
    store.delete_word("салом")
    assert store.load_words() == [WORD2]
    assert store.load_bigrams() == []


def test_clear_keeps_settings(store):
    store.save_words([WORD])
    store.save_bigrams([("салом", "алейкум", 1, 1.0, 1.0)])
    store.set_setting("max_suggestions", 5)
    store.clear()
    assert store.counts() == (0, 0)
    assert store.get_setting("max_suggestions") == 5


def test_settings_values(store):
    assert store.get_setting("missing") is None
    assert store.get_setting("missing", 7) == 7
    store.set_setting("flag", True)
    store.set_setting("name", "Абдукабир")
    store.set_setting("offset", [10, -20])
    assert store.all_settings() == {
        "flag": True, "name": "Абдукабир", "offset": [10, -20],
    }


def test_bulk_rolls_back_on_error(store):
    with pytest.raises(RuntimeError):
        with store.bulk():
            store.save_words([WORD])
            raise RuntimeError("boom")
    assert store.load_words() == []
    # the store is still usable afterwards
    store.save_words([WORD])
    assert store.counts() == (1, 0)


def test_data_survives_reopen(tmp_path):
    path = tmp_path / "sub" / "data.db"
    s = Store(path)
    s.save_words([WORD])
    s.set_setting("cross_script", True)
    s.close()
    s = Store(path)
    assert s.load_words() == [WORD]
    assert s.get_setting("cross_script") is True
    s.clear()
    assert s.counts() == (0, 0)
    s.close()


def test_settings_load_and_save(store):
    settings = Settings()
    settings.max_suggestions = 5
    settings.cross_script = True
    settings.half_life_days = 14
    settings.save(store)
    loaded = Settings.load(store)
    assert loaded.max_suggestions == 5
    assert loaded.cross_script is True
    assert loaded.half_life_days == 14.0
    assert isinstance(loaded.half_life_days, float)


def test_settings_ignore_garbage(store):
    store.set_setting("max_suggestions", "many")
    store.set_setting("cross_script", 1)
    store.set_setting("unknown_key", 123)
    loaded = Settings.load(store)
    assert loaded.max_suggestions == Settings().max_suggestions
    assert loaded.cross_script is False


def test_settings_new_fields_round_trip(store):
    settings = Settings()
    settings.theme = "dark"
    settings.key_hints = "never"
    settings.autostart = True
    settings.import_marks = {"json:123": 456}
    settings.save(store)
    loaded = Settings.load(store)
    assert loaded.theme == "dark"
    assert loaded.key_hints == "never"
    assert loaded.autostart is True
    assert loaded.import_marks == {"json:123": 456}


def test_settings_reject_unknown_choices(store):
    store.set_setting("theme", "purple")
    store.set_setting("key_hints", "sometimes")
    store.set_setting("import_marks", [1, 2])
    loaded = Settings.load(store)
    assert loaded.theme == "telegram"
    assert loaded.key_hints == "ctrl"
    assert loaded.import_marks == {}


def test_default_import_marks_are_not_shared():
    a, b = Settings(), Settings()
    a.import_marks["x"] = 1
    assert b.import_marks == {}
