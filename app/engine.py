"""Word buffer state machine.

Turns a stream of typed characters into suggestions and learning events.
Pure logic: no WinAPI, no UI, no threads. The caller (hook worker) feeds it
characters and control events and asks for suggestions.

A finished word is not learned at once: it stays *pending* until the next
word starts. If the user deletes the separator and keeps typing, the pending
word goes back into the buffer, so "Абду" + space + backspace + "кабир" is
learned as one word, not as a fragment.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from .lexicon import Lexicon, Suggestion
from .settings import Settings
from .textutil import GLUE, JOINERS, SENTENCE_END
from .translit import script_of


@dataclass(frozen=True)
class Insertion:
    """What to send to the target window to accept a suggestion."""
    backspaces: int
    text: str


@dataclass
class _Pending:
    raw: str                    # the word exactly as typed
    prev: Optional[str]
    sentence_start: bool


class Engine:
    def __init__(self, lexicon: Lexicon, settings: Settings) -> None:
        self.lexicon = lexicon
        self.settings = settings
        self.buffer = ""
        self._prev: Optional[str] = None
        self._sentence_start = True
        self._pending: Optional[_Pending] = None
        self._after = ""            # separators typed after the pending word
        self._tainted = False       # inside a link/handle/path: stay silent
        self._taint_len = 0
        self._dismissed = False
        self._last_char = ""
        self._shown: Optional[list[Suggestion]] = None

    # ---- input events ------------------------------------------------------

    def feed(self, text: str) -> None:
        """Characters produced by the keyboard, Enter being '\\r' or '\\n'."""
        for ch in text:
            self._feed_char(ch)

    def backspace(self) -> None:
        self._shown = None
        self._last_char = ""
        if self._tainted:
            self._taint_len -= 1
            if self._taint_len <= 0:
                self._tainted = False
            return
        if self.buffer:
            self.buffer = self.buffer[:-1]
            return
        pending = self._pending
        if pending is not None and self._after:
            self._after = self._after[:-1]
            if not self._after:
                # The separator is gone: the word is being edited again
                self._pending = None
                self.buffer = pending.raw
                self._prev = pending.prev
                self._sentence_start = pending.sentence_start
                self._dismissed = False
            return
        # Deleting text we know nothing about
        self.reset()

    def reset(self) -> None:
        """Caret moved, text pasted, selection changed, focus lost..."""
        self._shown = None
        self._last_char = ""
        word = self.buffer.strip(JOINERS)
        if word and word in self.lexicon:
            # An unfinished buffer is dropped, unless it is a word we already
            # know (e.g. the message was sent with a mouse click).
            self._flush_pending()
            self.lexicon.learn(word, self._prev, self._sentence_start)
        self.buffer = ""
        self._flush_pending()
        self._prev = None
        self._sentence_start = True
        self._tainted = False
        self._taint_len = 0
        self._dismissed = False

    def discard(self) -> None:
        """Forget everything typed so far without learning any of it.

        For password fields: nothing typed there may reach the dictionary.
        """
        self.buffer = ""
        self._pending = None
        self._after = ""
        self.reset()

    def dismiss(self) -> None:
        """Esc: hide suggestions until the next word."""
        self._shown = None
        self._dismissed = True

    # ---- suggestions -------------------------------------------------------

    @property
    def prefix(self) -> str:
        return self.buffer

    def suggestions(self) -> list[Suggestion]:
        if self._shown is None:
            self._shown = self._compute()
        return self._shown

    def accept(self, index: int = 0) -> Optional[Insertion]:
        """Accept the suggestion number ``index`` of those last shown."""
        items = self.suggestions()
        if not 0 <= index < len(items):
            return None
        chosen = items[index]
        typed = self.buffer
        self._flush_pending()
        # A capital that came from the dictionary, not from the user's fingers,
        # is no evidence about how the word is written.
        neutral = chosen.text != chosen.text.lower() and typed == typed.lower()
        self._pending = _Pending(chosen.text, self._prev, self._sentence_start or neutral)
        self._after = " "
        self.buffer = ""
        self._dismissed = False
        self._shown = None
        return Insertion(len(typed), chosen.text + " ")

    # ---- internals ---------------------------------------------------------

    def _compute(self) -> list[Suggestion]:
        if self._tainted or self._dismissed:
            return []
        buf = self.buffer
        if not buf:
            pending = self._pending
            if (
                self.settings.predict_next_word
                and pending is not None
                and self._after
                and self._after.strip(" ") == ""
            ):
                return self.lexicon.predict_next(pending.raw.strip(JOINERS))
            return []
        if len(buf) < self.settings.min_prefix_len:
            return []
        if any(ch.isdigit() for ch in buf):
            return []
        return self.lexicon.suggest(buf, self._prev)

    def _feed_char(self, ch: str) -> None:
        self._shown = None
        before, self._last_char = self._last_char, ch
        if before == ":" and ch.isalpha() and not self.buffer and not self._tainted:
            # ":smile" is Telegram's own emoji search with its own Tab/Enter
            self._taint()
            return
        if ch in "\r\n":
            self._enter()
            return
        if ch.isspace():
            self._boundary(ch)
            self._tainted = False
            self._taint_len = 0
            return
        if self._tainted:
            self._taint_len += 1
            return
        if ch.isalpha() or ch.isdigit():
            if not self.buffer:
                self._begin_word()
                if self._tainted:
                    return
            self.buffer += ch
        elif ch in JOINERS and self.buffer:
            self.buffer += ch
        elif ch in GLUE:
            self._taint()
        else:
            self._boundary(ch)

    def _begin_word(self) -> None:
        self._dismissed = False
        pending = self._pending
        if pending is not None and self._after == "." and script_of(pending.raw) == "lat":
            # "google.com": a dot glued to Latin letters is a domain, not a sentence
            self._pending = None
            self._after = ""
            self._prev = None
            self._sentence_start = False
            self._tainted = True
            self._taint_len = 1
            return
        self._flush_pending()

    def _boundary(self, ch: str) -> None:
        if self.buffer:
            self._flush_pending()
            self._pending = _Pending(self.buffer, self._prev, self._sentence_start)
            self._after = ch
            self.buffer = ""
        elif self._pending is not None:
            self._after += ch
        elif ch in SENTENCE_END:
            self._prev = None
            self._sentence_start = True

    def _enter(self) -> None:
        self._boundary("\n")
        self._flush_pending()
        self._prev = None
        self._sentence_start = True
        self._tainted = False
        self._taint_len = 0
        self._dismissed = False

    def _taint(self) -> None:
        if self._pending is not None:
            if any(ch.isspace() for ch in self._after):
                self._flush_pending()
            else:
                # "https" + ":" + "/": the pending word was part of the link
                self._pending = None
                self._after = ""
        self.buffer = ""
        self._prev = None
        self._sentence_start = False
        self._tainted = True
        self._taint_len = 1

    def _flush_pending(self) -> None:
        pending = self._pending
        if pending is None:
            return
        after = self._after
        self._pending = None
        self._after = ""
        word = pending.raw.strip(JOINERS)
        learned = self.lexicon.learn(word, pending.prev, pending.sentence_start)
        if any(ch in SENTENCE_END or ch == "\n" for ch in after):
            self._prev = None
            self._sentence_start = True
        else:
            self._prev = word if learned else None
            self._sentence_start = False
