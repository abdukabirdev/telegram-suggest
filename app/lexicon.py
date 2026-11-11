"""In-memory dictionary with prefix search and ranking, persisted via Store.

Ranking uses an exponentially decayed use counter. For a word we keep
``score`` (decayed number of uses as of ``last_used``); its value at any later
moment is ``score * 0.5 ** ((now - last_used) / half_life)``. The ordering of
two words by that value does not depend on ``now``, so every entry carries a
time-invariant ``rank = log2(score) + last_used / half_life``. That lets the
prefix index return the top candidates without rescoring the whole range.
"""

from __future__ import annotations

import math
import threading
import time
from bisect import bisect_left, bisect_right
from dataclasses import dataclass
from heapq import nlargest
from operator import attrgetter
from typing import Callable, NamedTuple, Optional

from .settings import Settings
from .store import Store
from .textutil import is_learnable
from .translit import fold, nfc, script_of, to_other_script, to_script

_DAY = 86400.0
_TOP_K = 32
_CACHE_LIMIT = 4096
_RANK = attrgetter("rank")
_PREFIX_END = "\U0010ffff"


@dataclass(frozen=True)
class Suggestion:
    text: str            # what to insert
    word: str            # dictionary key (lowercase)
    score: float
    cross: bool = False  # transliterated from the other script


class WordInfo(NamedTuple):
    word: str
    display: str
    freq: int
    last_used: float


class WordEntry:
    __slots__ = (
        "word", "cased", "norm", "xnorm", "lang", "freq", "score",
        "last_used", "lower_count", "cased_count", "rank", "indexed",
    )

    def __init__(self, word, cased, norm, xnorm, lang, freq, score, last_used,
                 lower_count, cased_count):
        self.word: str = word
        self.cased: Optional[str] = cased
        self.norm: str = norm
        self.xnorm: str = xnorm
        self.lang: str = lang
        self.freq: int = freq
        self.score: float = score
        self.last_used: float = last_used
        self.lower_count: int = lower_count
        self.cased_count: int = cased_count
        self.rank: float = 0.0
        self.indexed: bool = False

    @property
    def display(self) -> str:
        """The form to offer: capitalised only if that is how it is written."""
        if self.cased and (self.lower_count == 0 or self.cased_count > self.lower_count):
            return self.cased
        return self.word

    def row(self) -> tuple:
        return (self.word, self.cased, self.norm, self.xnorm, self.lang, self.freq,
                self.score, self.last_used, self.lower_count, self.cased_count)


def apply_case(prefix: str, text: str) -> str:
    """Make the suggestion follow the capitalisation the user started with."""
    if not prefix or not text or not prefix[0].isupper():
        return text
    if len(prefix) >= 2 and prefix.isupper():
        return text.upper()
    return text[0].upper() + text[1:]


class _PrefixIndex:
    """Sorted array of search keys with a cache of top entries per prefix."""

    __slots__ = ("keys", "ents", "_cache")

    def __init__(self) -> None:
        self.keys: list[str] = []
        self.ents: list[WordEntry] = []
        self._cache: dict[str, list[WordEntry]] = {}

    def build(self, pairs: list[tuple[str, WordEntry]]) -> None:
        pairs.sort(key=lambda p: p[0])
        self.keys = [p[0] for p in pairs]
        self.ents = [p[1] for p in pairs]
        self._cache.clear()
        self._warm_up()

    def _warm_up(self) -> None:
        """Precompute one-letter prefixes: the widest and most used ranges."""
        keys = self.keys
        i = 0
        while i < len(keys):
            first = keys[i][:1]
            if not first:
                i += 1
                continue
            self.top(first)
            i = bisect_left(keys, first + _PREFIX_END, i)

    def add(self, key: str, ent: WordEntry) -> None:
        i = bisect_right(self.keys, key)
        self.keys.insert(i, key)
        self.ents.insert(i, ent)
        self.touch(key, ent)

    def remove(self, key: str, ent: WordEntry) -> None:
        i = bisect_left(self.keys, key)
        while i < len(self.keys) and self.keys[i] == key:
            if self.ents[i] is ent:
                del self.keys[i]
                del self.ents[i]
                break
            i += 1
        cache = self._cache
        for n in range(1, len(key) + 1):
            cache.pop(key[:n], None)

    def touch(self, key: str, ent: WordEntry) -> None:
        """Keep cached tops exact after ``ent`` was added or its rank grew.

        A rank only ever grows (a use is never taken back), so an entry that
        is already in a cached top stays there, and one that is not may only
        push out the current weakest member.
        """
        cache = self._cache
        if not cache:
            return
        for n in range(1, len(key) + 1):
            top = cache.get(key[:n])
            if top is None or ent in top:
                continue
            if len(top) < _TOP_K:
                # a short list is the whole range, so ent is a new word
                top.append(ent)
                continue
            weakest = min(range(len(top)), key=lambda j: top[j].rank)
            if ent.rank > top[weakest].rank:
                top[weakest] = ent

    def top(self, prefix: str) -> list[WordEntry]:
        """Up to _TOP_K best entries for the prefix, in no particular order."""
        hit = self._cache.get(prefix)
        if hit is not None:
            return hit
        lo = bisect_left(self.keys, prefix)
        hi = bisect_left(self.keys, prefix + _PREFIX_END, lo)
        if hi - lo <= _TOP_K:
            result = self.ents[lo:hi]
        else:
            result = nlargest(_TOP_K, self.ents[lo:hi], key=_RANK)
        if len(self._cache) >= _CACHE_LIMIT:
            self._cache.clear()
        self._cache[prefix] = result
        return result


class Lexicon:
    def __init__(
        self,
        store: Store,
        settings: Settings,
        clock: Callable[[], float] = time.time,
        autoflush: bool = True,
    ) -> None:
        self.store = store
        self.settings = settings
        self._clock = clock
        self.autoflush = autoflush
        self._lock = threading.RLock()
        self._words: dict[str, WordEntry] = {}
        # prev -> {next: [freq, score, last_used]}
        self._bigrams: dict[str, dict[str, list]] = {}
        self._main = _PrefixIndex()
        self._cross = _PrefixIndex()
        self._dirty_words: set[str] = set()
        self._dirty_bigrams: set[tuple[str, str]] = set()
        self._half_life = 0.0
        self._min_suggest_len = 0
        self.load()

    # ---- decay arithmetic --------------------------------------------------

    def _decayed(self, score: float, last: float, now: float) -> float:
        dt = now - last
        if dt <= 0:
            return score
        return score * 0.5 ** (dt / self._half_life)

    def _bump(self, score: float, last: float, ts: float) -> tuple[float, float]:
        """Register one more use at time ``ts``; returns (score, last_used)."""
        if ts >= last:
            return self._decayed(score, last, ts) + 1.0, ts
        # An older use (import of history): add it already decayed to ``last``
        return score + 0.5 ** ((last - ts) / self._half_life), last

    def _rank_of(self, score: float, last: float) -> float:
        return math.log2(score) + last / self._half_life if score > 0 else -math.inf

    # ---- loading -----------------------------------------------------------

    def load(self) -> None:
        with self._lock:
            self._words.clear()
            self._bigrams.clear()
            self._dirty_words.clear()
            self._dirty_bigrams.clear()
            for row in self.store.load_words():
                entry = WordEntry(*row)
                self._words[entry.word] = entry
            for prev, nxt, freq, score, last in self.store.load_bigrams():
                if prev in self._words and nxt in self._words:
                    self._bigrams.setdefault(prev, {})[nxt] = [freq, score, last]
            self.refresh_settings()

    def refresh_settings(self) -> None:
        """Recompute ranks and indexes; call after ranking settings change."""
        with self._lock:
            self._half_life = max(float(self.settings.half_life_days), 0.01) * _DAY
            self._min_suggest_len = int(self.settings.min_suggest_len)
            main: list[tuple[str, WordEntry]] = []
            cross: list[tuple[str, WordEntry]] = []
            for entry in self._words.values():
                entry.rank = self._rank_of(entry.score, entry.last_used)
                entry.indexed = len(entry.word) >= self._min_suggest_len
                if entry.indexed:
                    main.append((entry.norm, entry))
                    cross.append((entry.xnorm, entry))
            self._main.build(main)
            self._cross.build(cross)

    # ---- learning ----------------------------------------------------------

    def learn(
        self,
        token: str,
        prev: Optional[str] = None,
        sentence_start: bool = False,
        ts: Optional[float] = None,
    ) -> Optional[str]:
        """Register one use of a word. Returns its key, or None if ignored.

        ``sentence_start`` tells that a capital first letter proves nothing
        about how the word is normally written.
        """
        token = nfc(token)
        if not is_learnable(token, self.settings.min_word_len):
            return None
        if ts is None:
            ts = self._clock()
        lower = token.lower()
        with self._lock:
            entry = self._words.get(lower)
            if entry is None:
                entry = WordEntry(
                    lower, None, fold(lower), fold(to_other_script(lower)),
                    script_of(lower), 0, 0.0, ts, 0, 0,
                )
                self._words[lower] = entry
            entry.freq += 1
            entry.score, entry.last_used = self._bump(entry.score, entry.last_used, ts)
            entry.rank = self._rank_of(entry.score, entry.last_used)

            if token == lower:
                entry.lower_count += 1
            elif not sentence_start:
                entry.cased = token
                entry.cased_count += 1
            elif entry.cased is None:
                entry.cased = token

            if entry.indexed:
                self._main.touch(entry.norm, entry)
                self._cross.touch(entry.xnorm, entry)
            elif len(lower) >= self._min_suggest_len:
                entry.indexed = True
                self._main.add(entry.norm, entry)
                self._cross.add(entry.xnorm, entry)
            self._dirty_words.add(lower)

            if prev:
                prev_key = nfc(prev).lower()
                if prev_key in self._words:
                    followers = self._bigrams.setdefault(prev_key, {})
                    rec = followers.get(lower)
                    if rec is None:
                        rec = followers[lower] = [0, 0.0, ts]
                    rec[0] += 1
                    rec[1], rec[2] = self._bump(rec[1], rec[2], ts)
                    self._dirty_bigrams.add((prev_key, lower))

            if self.autoflush:
                self.flush()
        return lower

    def flush(self) -> None:
        """Write pending changes to the database."""
        with self._lock:
            if not self._dirty_words and not self._dirty_bigrams:
                return
            word_rows = [
                self._words[w].row() for w in self._dirty_words if w in self._words
            ]
            bigram_rows = []
            for prev, nxt in self._dirty_bigrams:
                rec = self._bigrams.get(prev, {}).get(nxt)
                if rec is not None:
                    bigram_rows.append((prev, nxt, rec[0], rec[1], rec[2]))
            self._dirty_words.clear()
            self._dirty_bigrams.clear()
            with self.store.bulk():
                self.store.save_words(word_rows)
                self.store.save_bigrams(bigram_rows)

    # ---- lookup ------------------------------------------------------------

    def suggest(
        self,
        prefix: str,
        prev: Optional[str] = None,
        now: Optional[float] = None,
        limit: Optional[int] = None,
    ) -> list[Suggestion]:
        prefix = nfc(prefix)
        key = fold(prefix)
        if not key:
            return []
        settings = self.settings
        if limit is None:
            limit = settings.max_suggestions
        if now is None:
            now = self._clock()
        script = script_of(prefix)
        use_cross = settings.cross_script
        penalty = settings.cross_script_penalty
        weight = settings.bigram_weight
        best: dict[str, Suggestion] = {}

        with self._lock:
            followers = self._bigrams.get(nfc(prev).lower()) if prev else None

            def consider(entry: WordEntry, cross: bool) -> None:
                text = entry.display
                if cross:
                    text = to_script(text, script)
                text = apply_case(prefix, text)
                if text == prefix:
                    return
                score = self._decayed(entry.score, entry.last_used, now)
                if followers:
                    rec = followers.get(entry.word)
                    if rec is not None:
                        score += weight * self._decayed(rec[1], rec[2], now)
                if cross:
                    score *= penalty
                current = best.get(text)
                if current is None or score > current.score:
                    best[text] = Suggestion(text, entry.word, score, cross)

            seen: set[str] = set()
            for entry in self._main.top(key):
                seen.add(entry.word)
                consider(entry, False)
            if use_cross:
                for entry in self._cross.top(key):
                    if entry.lang != script and entry.word not in seen:
                        seen.add(entry.word)
                        consider(entry, True)
            if followers:
                # Words that follow the previous one may rank below the top-K
                # of their prefix; the bigram bonus can still lift them up.
                for nxt in followers:
                    if nxt in seen:
                        continue
                    entry = self._words.get(nxt)
                    if entry is None or not entry.indexed:
                        continue
                    if entry.norm.startswith(key):
                        consider(entry, False)
                    elif use_cross and entry.lang != script and entry.xnorm.startswith(key):
                        consider(entry, True)

        ranked = sorted(best.values(), key=lambda s: (-s.score, s.text))
        return ranked[:limit]

    def predict_next(
        self,
        prev: str,
        now: Optional[float] = None,
        limit: Optional[int] = None,
    ) -> list[Suggestion]:
        """Most likely words after ``prev`` (no letters typed yet)."""
        if limit is None:
            limit = self.settings.max_suggestions
        if now is None:
            now = self._clock()
        result: list[Suggestion] = []
        with self._lock:
            followers = self._bigrams.get(nfc(prev).lower())
            if not followers:
                return []
            for nxt, rec in followers.items():
                entry = self._words.get(nxt)
                if entry is None or not entry.indexed:
                    continue
                result.append(
                    Suggestion(entry.display, nxt, self._decayed(rec[1], rec[2], now))
                )
        result.sort(key=lambda s: (-s.score, s.text))
        return result[:limit]

    def __contains__(self, word: str) -> bool:
        return nfc(word).lower() in self._words

    def __len__(self) -> int:
        return len(self._words)

    def get(self, word: str) -> Optional[WordInfo]:
        with self._lock:
            entry = self._words.get(nfc(word).lower())
            if entry is None:
                return None
            return WordInfo(entry.word, entry.display, entry.freq, entry.last_used)

    def bigram_count(self) -> int:
        with self._lock:
            return sum(len(f) for f in self._bigrams.values())

    def search(self, query: str = "", limit: int = 500) -> list[WordInfo]:
        """Words containing the query, most used first (for the settings UI)."""
        key = fold(query.strip())
        with self._lock:
            if key:
                found = [e for e in self._words.values() if key in e.norm or key in e.xnorm]
            else:
                found = list(self._words.values())
            found = nlargest(limit, found, key=lambda e: (e.freq, e.last_used))
            return [WordInfo(e.word, e.display, e.freq, e.last_used) for e in found]

    # ---- removal -----------------------------------------------------------

    def delete(self, word: str) -> bool:
        key = nfc(word).lower()
        with self._lock:
            entry = self._words.pop(key, None)
            if entry is None:
                return False
            if entry.indexed:
                self._main.remove(entry.norm, entry)
                self._cross.remove(entry.xnorm, entry)
            self._bigrams.pop(key, None)
            for prev in [p for p, f in self._bigrams.items() if key in f]:
                followers = self._bigrams[prev]
                del followers[key]
                if not followers:
                    del self._bigrams[prev]
            self._dirty_words.discard(key)
            self._dirty_bigrams = {
                pair for pair in self._dirty_bigrams if key not in pair
            }
            self.store.delete_word(key)
            return True

    def clear(self) -> None:
        with self._lock:
            self._words.clear()
            self._bigrams.clear()
            self._dirty_words.clear()
            self._dirty_bigrams.clear()
            self._main.build([])
            self._cross.build([])
            self.store.clear()
