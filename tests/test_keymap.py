"""Real ToUnicodeEx against the layouts installed on this computer."""

import pytest

from app import winapi as w
from app.keymap import KeyTranslator, installed_layouts, layout_name

LAYOUTS = {hkl & 0xFFFF: hkl for hkl in installed_layouts()}
EN = LAYOUTS.get(0x0409)
RU = LAYOUTS.get(0x0419)

needs_en = pytest.mark.skipif(EN is None, reason="English (US) layout is not installed")
needs_ru = pytest.mark.skipif(RU is None, reason="Russian layout is not installed")


@pytest.fixture
def tr():
    return KeyTranslator()


def test_some_layout_is_installed():
    assert installed_layouts()


@needs_en
def test_english_letters_and_case(tr):
    assert tr.translate(0x41, 0x1E, False, False, False, EN) == "a"
    assert tr.translate(0x41, 0x1E, True, False, False, EN) == "A"
    assert tr.translate(0x41, 0x1E, False, True, False, EN) == "A"      # Caps Lock
    assert tr.translate(0x41, 0x1E, True, True, False, EN) == "a"       # Caps + Shift


@needs_en
def test_english_digits_and_punctuation(tr):
    assert tr.translate(0x31, 0x02, False, False, False, EN) == "1"
    assert tr.translate(0x31, 0x02, True, False, False, EN) == "!"
    assert tr.translate(w.VK_SPACE, 0x39, False, False, False, EN) == " "
    assert tr.translate(0xBC, 0x33, False, False, False, EN) == ","
    assert tr.translate(0xDE, 0x28, False, False, False, EN) == "'"


@needs_ru
def test_russian_letters_on_the_same_keys(tr):
    assert tr.translate(0x46, 0x21, False, False, False, RU) == "а"     # the F key
    assert tr.translate(0x46, 0x21, True, False, False, RU) == "А"
    assert tr.translate(0x46, 0x21, False, True, False, RU) == "А"
    assert tr.translate(0x41, 0x1E, False, False, False, RU) == "ф"     # the A key
    assert tr.translate(0xBC, 0x33, False, False, False, RU) == "б"     # the comma key
    assert tr.translate(0xDE, 0x28, False, False, False, RU) == "э"


@needs_ru
def test_russian_punctuation(tr):
    assert tr.translate(0x37, 0x08, True, False, False, RU) == "?"
    assert tr.translate(0xBF, 0x35, False, False, False, RU) == "."
    assert tr.translate(0xBF, 0x35, True, False, False, RU) == ","


@needs_en
@pytest.mark.parametrize("vk", [
    w.VK_BACK, w.VK_TAB, w.VK_RETURN, w.VK_ESCAPE, w.VK_LEFT, w.VK_F1,
    w.VK_DELETE, w.VK_LSHIFT, w.VK_CAPITAL, 0xAF,
])
def test_keys_that_type_nothing(tr, vk):
    assert tr.translate(vk, 0, False, False, False, EN) == ""


@needs_en
def test_translation_does_not_depend_on_previous_call(tr):
    assert tr.translate(0x41, 0x1E, True, True, True, EN) is not None
    assert tr.translate(0x41, 0x1E, False, False, False, EN) == "a"


def test_layout_names():
    assert layout_name(0x04190419) == "ru-RU"
    assert layout_name(0x04090409) == "en-US"
    assert layout_name(0x08430843).startswith("uz-Cyrl")
    assert layout_name(0x04430443).startswith("uz-Latn")
    assert layout_name(0) == "?"


def test_layout_of_missing_window(tr):
    # no window: Windows answers with the layout of the calling thread
    assert tr.layout_of_window(None) == tr.last_layout
