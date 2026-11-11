"""Colours of the suggestion window and of the program's own windows.

The suggestion window dresses like Telegram: the background of Telegram's
message field is read from the screen and the whole palette is built around
that one colour. Only the dominant colour is computed; the captured pixels
are dropped at once and never stored or logged. If Telegram cannot be read,
the Windows light/dark setting decides.
"""

from __future__ import annotations

import ctypes
import logging
from collections import Counter
from dataclasses import dataclass
from typing import Optional

from . import winapi as w

log = logging.getLogger(__name__)

RGB = tuple[int, int, int]

THEMES = ("telegram", "system", "dark", "light")
DARK_BG: RGB = (0x21, 0x25, 0x2b)
LIGHT_BG: RGB = (0xff, 0xff, 0xff)

# Telegram's own blues: day theme and night theme
_ACCENT_LIGHT: RGB = (0x33, 0x90, 0xec)
_ACCENT_DARK: RGB = (0x6a, 0xb3, 0xf3)
_DANGER_LIGHT: RGB = (0xe5, 0x39, 0x35)
_DANGER_DARK: RGB = (0xff, 0x6b, 0x6b)

_MAX_SAMPLE_W = 800
_MAX_SAMPLE_H = 48
_MIN_SHARE = 0.30       # the dominant colour must cover this much of the field


@dataclass(frozen=True)
class Palette:
    dark: bool
    bg: str
    text: str
    muted: str
    border: str
    hover: str
    pressed: str
    divider: str
    accent: str
    accent_bg: str
    accent_text: str        # text drawn on top of the accent colour
    danger: str
    danger_bg: str
    shadow: int             # alpha (0..255) of the densest shadow ring


# ---- colour arithmetic -------------------------------------------------------


def parse_hex(text: str) -> RGB:
    text = text.lstrip("#")
    return int(text[0:2], 16), int(text[2:4], 16), int(text[4:6], 16)


def hex_of(rgb: RGB) -> str:
    return "#{:02x}{:02x}{:02x}".format(*rgb)


def mix(a: RGB, b: RGB, t: float) -> RGB:
    """``a`` moved towards ``b`` by the share ``t`` (0..1)."""
    return tuple(round(x + (y - x) * t) for x, y in zip(a, b))  # type: ignore[return-value]


def luminance(rgb: RGB) -> float:
    """Relative luminance (WCAG 2)."""
    def channel(c: int) -> float:
        c = c / 255.0
        return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4

    r, g, b = (channel(c) for c in rgb)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast(a: RGB, b: RGB) -> float:
    la, lb = luminance(a), luminance(b)
    hi, lo = max(la, lb), min(la, lb)
    return (hi + 0.05) / (lo + 0.05)


def is_dark(rgb: RGB) -> bool:
    """True when white text reads better on this colour than black text."""
    return contrast(rgb, (255, 255, 255)) > contrast(rgb, (0, 0, 0))


# ---- palettes ----------------------------------------------------------------


def palette_from_background(bg: RGB) -> Palette:
    dark = is_dark(bg)
    ink: RGB = (255, 255, 255) if dark else (0, 0, 0)
    text = mix(bg, ink, 0.92 if dark else 0.86)
    accent = _ACCENT_DARK if dark else _ACCENT_LIGHT
    danger = _DANGER_DARK if dark else _DANGER_LIGHT
    # Seen next to Telegram's own panel, a slightly lifted surface reads as
    # "a layer above", the same way Telegram draws its popups.
    surface = mix(bg, ink, 0.05) if dark else bg
    return Palette(
        dark=dark,
        bg=hex_of(surface),
        text=hex_of(text),
        muted=hex_of(mix(surface, text, 0.55)),
        border=hex_of(mix(surface, text, 0.16 if dark else 0.13)),
        hover=hex_of(mix(surface, text, 0.08)),
        pressed=hex_of(mix(surface, text, 0.15)),
        divider=hex_of(mix(surface, text, 0.12)),
        accent=hex_of(accent),
        accent_bg=hex_of(mix(surface, accent, 0.16 if dark else 0.11)),
        accent_text="#ffffff",
        danger=hex_of(danger),
        danger_bg=hex_of(mix(surface, danger, 0.16 if dark else 0.10)),
        shadow=110 if dark else 44,
    )


def windows_prefers_dark() -> bool:
    """The "app mode" switch in Windows settings (Personalisation > Colours)."""
    try:
        import winreg

        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize",
        ) as key:
            value, _ = winreg.QueryValueEx(key, "AppsUseLightTheme")
            return int(value) == 0
    except OSError:
        return False


def palette_for(theme: str, telegram_bg: Optional[RGB] = None) -> Palette:
    """Palette for a theme setting; ``telegram_bg`` is the colour read from Telegram."""
    if theme == "dark":
        return palette_from_background(DARK_BG)
    if theme == "light":
        return palette_from_background(LIGHT_BG)
    if theme == "telegram" and telegram_bg is not None:
        return palette_from_background(telegram_bg)
    return palette_from_background(DARK_BG if windows_prefers_dark() else LIGHT_BG)


# ---- reading the colour from the screen --------------------------------------


def dominant_color(bgra: bytes, min_share: float = _MIN_SHARE) -> Optional[RGB]:
    """Most frequent colour of 32-bit BGRA pixels, None if no colour dominates.

    Letters and icons inside the field are a minority; the background is the
    colour that covers most of it.
    """
    total = len(bgra) // 8          # every second pixel is plenty
    if total == 0:
        return None
    data = bgra[:total * 8]
    counts = Counter(zip(data[0::8], data[1::8], data[2::8]))
    (b, g, r), n = counts.most_common(1)[0]
    if n / total < min_share:
        return None
    return r, g, b


def capture_bgra(rect: tuple[int, int, int, int]) -> Optional[bytes]:
    """Pixels of a screen rectangle (physical coordinates) as BGRA bytes."""
    left, top, right, bottom = rect
    width = min(right - left, _MAX_SAMPLE_W)
    height = min(bottom - top, _MAX_SAMPLE_H)
    if width <= 0 or height <= 0:
        return None
    screen = w.GetDC(None)
    if not screen:
        return None
    memory = bitmap = old = None
    try:
        memory = w.CreateCompatibleDC(screen)
        bitmap = w.CreateCompatibleBitmap(screen, width, height)
        if not memory or not bitmap:
            return None
        old = w.SelectObject(memory, bitmap)
        if not w.BitBlt(memory, 0, 0, width, height, screen, left, top, w.SRCCOPY):
            return None
        header = w.BITMAPINFOHEADER()
        header.biSize = ctypes.sizeof(w.BITMAPINFOHEADER)
        header.biWidth = width
        header.biHeight = -height           # top-down rows
        header.biPlanes = 1
        header.biBitCount = 32
        header.biCompression = w.BI_RGB
        buffer = ctypes.create_string_buffer(width * height * 4)
        w.SelectObject(memory, old)
        old = None
        lines = w.GetDIBits(memory, bitmap, 0, height, buffer, ctypes.byref(header),
                            w.DIB_RGB_COLORS)
        if lines != height:
            return None
        return buffer.raw
    finally:
        if old:
            w.SelectObject(memory, old)
        if bitmap:
            w.DeleteObject(bitmap)
        if memory:
            w.DeleteDC(memory)
        w.ReleaseDC(None, screen)


def sample_background(rect: tuple[int, int, int, int]) -> Optional[RGB]:
    """Background colour of a screen area (Telegram's message field)."""
    try:
        pixels = capture_bgra(rect)
    except OSError:
        log.exception("reading the screen colour failed")
        return None
    if pixels is None:
        return None
    return dominant_color(pixels)
