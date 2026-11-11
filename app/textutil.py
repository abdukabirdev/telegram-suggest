"""Word boundaries, learnability rules and text tokenisation.

Shared by the live engine (typing) and the importer (Telegram export).
"""

from __future__ import annotations

import re

from .translit import APOSTROPHES, nfc

# Characters allowed inside a word, never at its edges.
JOINERS = APOSTROPHES + "-"
SENTENCE_END = ".!?…"
# Characters that mark the surrounding token as an address, handle or code.
GLUE = "/\\@_#&=%+~"
MAX_WORD_LEN = 40

_J = re.escape(JOINERS)
_WORD_RE = re.compile(rf"[^\W\d_]+(?:[{_J}][^\W\d_]+)*")
_EDGE_RE = re.compile(r"^\W+|\W+$")
_DOMAIN_RE = re.compile(r"[A-Za-z0-9-]\.[A-Za-z]{2,}")
_CLOSERS = "\"')]}»”’"

Chain = list[tuple[str, bool]]


def is_learnable(word: str, min_len: int = 2) -> bool:
    """A word worth remembering: letters only, long enough, not 'ааа'."""
    n = len(word)
    if n < min_len or n > MAX_WORD_LEN:
        return False
    if _WORD_RE.fullmatch(word) is None:
        return False
    letters = set()
    for ch in word.lower():
        if ch.isalpha():
            letters.add(ch)
        elif ch not in JOINERS:
            return False
    return len(letters) > 1


def _is_junk(chunk: str) -> bool:
    """Numbers, links, e-mails, @handles, #tags, file paths."""
    for ch in chunk:
        if ch.isdigit() or ch in GLUE:
            return True
    return _DOMAIN_RE.search(chunk) is not None


def tokenize(text: str, min_len: int = 2) -> list[Chain]:
    """Split text into chains of consecutive learnable words.

    Each chain item is ``(word, sentence_start)``. Bigrams are only valid
    between neighbours inside one chain: a chain ends at a sentence end, a
    line break or any skipped token (number, link, too short a word).
    """
    chains: list[Chain] = []
    cur: Chain = []

    def brk() -> None:
        nonlocal cur
        if cur:
            chains.append(cur)
            cur = []

    for line in nfc(text).splitlines():
        sent_start = True
        for chunk in line.split():
            core = _EDGE_RE.sub("", chunk)
            tail = chunk.rstrip(_CLOSERS)
            ends = bool(tail) and tail[-1] in SENTENCE_END
            if not core:
                if ends:
                    brk()
                    sent_start = True
                continue
            if _is_junk(chunk):
                brk()
                sent_start = ends
                continue
            pos = 0
            for m in _WORD_RE.finditer(core):
                between = core[pos:m.start()]
                if any(c in SENTENCE_END for c in between):
                    brk()
                    sent_start = True
                word = m.group()
                if is_learnable(word, min_len):
                    cur.append((word, sent_start))
                else:
                    brk()
                sent_start = False
                pos = m.end()
            if ends:
                brk()
                sent_start = True
        brk()
    return chains
