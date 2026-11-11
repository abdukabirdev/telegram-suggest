"""Script detection, search-key folding and Uzbek Cyrillic <-> Latin transliteration."""

from __future__ import annotations

import unicodedata

APOSTROPHES = "'’‘ʻʼ`"
_APOS_OUT = "'"

# Uzbek letters that people routinely replace with plain Russian ones when
# typing on a Russian layout. Folding them makes "кил" find "қил" and back.
_FOLD_TABLE = {ord(a): b for a, b in zip("ўқғҳё", "укгхе")}
_FOLD_TABLE.update({ord(c): None for c in APOSTROPHES})

_CYR_VOWELS = "аеёиоуэюяўы"
_LAT_VOWELS = "aeiou"

_CYR_TO_LAT = {
    "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ё": "yo",
    "ж": "j", "з": "z", "и": "i", "й": "y", "к": "k", "л": "l", "м": "m",
    "н": "n", "о": "o", "п": "p", "р": "r", "с": "s", "т": "t", "у": "u",
    "ф": "f", "х": "x", "ц": "s", "ч": "ch", "ш": "sh", "щ": "sh",
    "ъ": _APOS_OUT, "ы": "i", "ь": "", "э": "e", "ю": "yu", "я": "ya",
    "ў": "o" + _APOS_OUT, "қ": "q", "ғ": "g" + _APOS_OUT, "ҳ": "h",
}

_LAT_DIGRAPHS = {
    "sh": "ш", "ch": "ч", "yo": "ё", "yu": "ю", "ya": "я", "ye": "е",
}
_LAT_TO_CYR = {
    "a": "а", "b": "б", "c": "с", "d": "д", "f": "ф", "g": "г", "h": "ҳ",
    "i": "и", "j": "ж", "k": "к", "l": "л", "m": "м", "n": "н", "o": "о",
    "p": "п", "q": "қ", "r": "р", "s": "с", "t": "т", "u": "у", "v": "в",
    "w": "в", "x": "х", "y": "й", "z": "з",
}


def nfc(text: str) -> str:
    return unicodedata.normalize("NFC", text)


def is_cyrillic(ch: str) -> bool:
    return "Ѐ" <= ch <= "ӿ"


def script_of(text: str) -> str:
    """Return 'cyr' or 'lat' judging by the first letter of the text."""
    for ch in text:
        if ch.isalpha():
            return "cyr" if is_cyrillic(ch) else "lat"
    return "lat"


def fold(text: str) -> str:
    """Search key: lowercase, Uzbek-specific letters folded, apostrophes dropped."""
    return nfc(text).lower().translate(_FOLD_TABLE)


def _recase(src: str, piece: str, all_upper: bool) -> str:
    if not piece or not src.isupper():
        return piece
    return piece.upper() if all_upper else piece[0].upper() + piece[1:]


def cyr_to_lat(word: str) -> str:
    word = nfc(word)
    all_upper = len(word) > 1 and word.isupper()
    out: list[str] = []
    prev = ""
    for ch in word:
        low = ch.lower()
        piece = _CYR_TO_LAT.get(low)
        if piece is None:
            out.append(ch)
        else:
            if low == "е" and (not prev or prev in _CYR_VOWELS or prev in "ъь"):
                piece = "ye"
            elif low == "ц" and prev and prev in _CYR_VOWELS:
                piece = "ts"
            out.append(_recase(ch, piece, all_upper))
        prev = low
    return "".join(out)


def lat_to_cyr(word: str) -> str:
    word = nfc(word)
    all_upper = len(word) > 1 and word.isupper()
    low = word.lower()
    n = len(word)
    out: list[str] = []
    prev = ""
    i = 0
    while i < n:
        ch = low[i]
        nxt = low[i + 1] if i + 1 < n else ""
        after = low[i + 2] if i + 2 < n else ""

        # o' -> ў, g' -> ғ
        if ch in "og" and nxt and nxt in APOSTROPHES:
            out.append(_recase(word[i], "ў" if ch == "o" else "ғ", all_upper))
            prev = ch
            i += 2
            continue

        pair = _LAT_DIGRAPHS.get(ch + nxt) if nxt else None
        # "yo'l" is й + ў + л, not ё + apostrophe
        if pair and not (nxt == "o" and after and after in APOSTROPHES):
            out.append(_recase(word[i], pair, all_upper))
            prev = nxt
            i += 2
            continue

        if ch in APOSTROPHES:
            # "Is'hoq": the apostrophe only separates s and h
            if not (prev == "s" and nxt == "h"):
                out.append("ъ")
        elif ch == "e":
            piece = "э" if (not prev or prev in _LAT_VOWELS) else "е"
            out.append(_recase(word[i], piece, all_upper))
        else:
            piece = _LAT_TO_CYR.get(ch)
            out.append(word[i] if piece is None else _recase(word[i], piece, all_upper))
        prev = ch
        i += 1
    return "".join(out)


def to_other_script(word: str) -> str:
    return cyr_to_lat(word) if script_of(word) == "cyr" else lat_to_cyr(word)


def to_script(word: str, script: str) -> str:
    """Transliterate the word into 'cyr' or 'lat' unless it is already there."""
    if script_of(word) == script:
        return word
    return cyr_to_lat(word) if script == "lat" else lat_to_cyr(word)
