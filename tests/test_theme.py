import pytest

from app import theme
from app.theme import (DARK_BG, LIGHT_BG, contrast, dominant_color, hex_of, is_dark, mix,
                       palette_for, palette_from_background, parse_hex)


def _pixels(*runs):
    """BGRA bytes from (rgb, count) runs."""
    out = bytearray()
    for (r, g, b), count in runs:
        out += bytes((b, g, r, 255)) * count
    return bytes(out)


def test_hex_round_trip():
    assert parse_hex("#17212b") == (0x17, 0x21, 0x2b)
    assert hex_of((0x17, 0x21, 0x2b)) == "#17212b"


def test_mix():
    assert mix((0, 0, 0), (255, 255, 255), 0.0) == (0, 0, 0)
    assert mix((0, 0, 0), (255, 255, 255), 1.0) == (255, 255, 255)
    assert mix((0, 0, 0), (200, 100, 50), 0.5) == (100, 50, 25)


@pytest.mark.parametrize("rgb, dark", [
    ((255, 255, 255), False),
    ((0xe6, 0xeb, 0xee), False),       # Telegram "Day" panel
    ((0x17, 0x21, 0x2b), True),        # Telegram "Night blue"
    ((0x21, 0x21, 0x21), True),        # Telegram "Night"
    ((0x80, 0x80, 0x80), False),
])
def test_is_dark(rgb, dark):
    assert is_dark(rgb) is dark


@pytest.mark.parametrize("bg", [(255, 255, 255), (0x17, 0x21, 0x2b), (0x21, 0x21, 0x21),
                                (0xe6, 0xeb, 0xee), (0x40, 0x10, 0x60), (0xff, 0xf3, 0xc0)])
def test_palette_text_is_readable(bg):
    p = palette_from_background(bg)
    surface = parse_hex(p.bg)
    assert contrast(surface, parse_hex(p.text)) >= 7.0
    assert contrast(surface, parse_hex(p.muted)) >= 2.5
    assert contrast(surface, parse_hex(p.accent)) >= 2.5
    # hover and border must be visible but quiet
    assert 1.03 < contrast(surface, parse_hex(p.hover)) < 2.0
    assert 1.1 < contrast(surface, parse_hex(p.border)) < 2.5


def test_palette_follows_background():
    night = palette_from_background((0x17, 0x21, 0x2b))
    assert night.dark
    # stays in Telegram's colour family: blueish, only slightly lifted
    r, g, b = parse_hex(night.bg)
    assert b > r and max(r, g, b) < 0x40
    day = palette_from_background((0xff, 0xff, 0xff))
    assert not day.dark and day.bg == "#ffffff"


def test_palette_for_fixed_themes(monkeypatch):
    monkeypatch.setattr(theme, "windows_prefers_dark", lambda: True)
    assert palette_for("dark") == palette_from_background(DARK_BG)
    assert palette_for("light") == palette_from_background(LIGHT_BG)
    assert palette_for("system").dark
    # nothing read from Telegram yet: Windows decides
    assert palette_for("telegram", None).dark
    monkeypatch.setattr(theme, "windows_prefers_dark", lambda: False)
    assert not palette_for("telegram", None).dark
    assert palette_for("telegram", (0x17, 0x21, 0x2b)).dark
    # an explicit choice wins over Telegram's colour
    assert not palette_for("light", (0x17, 0x21, 0x2b)).dark


def test_dominant_color_ignores_letters():
    data = _pixels(((0x17, 0x21, 0x2b), 900), ((0xff, 0xff, 0xff), 60), ((0x80, 0x80, 0x80), 40))
    assert dominant_color(data) == (0x17, 0x21, 0x2b)


def test_dominant_color_requires_a_clear_winner():
    runs = [((i, i, i), 20) for i in range(0, 250, 10)]   # a gradient, e.g. a wallpaper
    assert dominant_color(_pixels(*runs)) is None
    assert dominant_color(b"") is None


def test_windows_setting_is_readable():
    assert theme.windows_prefers_dark() in (True, False)


def test_screen_sample_does_not_crash():
    result = theme.sample_background((0, 0, 200, 40))
    assert result is None or (len(result) == 3 and all(0 <= c <= 255 for c in result))
    assert theme.sample_background((10, 10, 10, 10)) is None
