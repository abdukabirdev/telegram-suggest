"""Lookup must stay well under 5 ms even on a big dictionary."""

import random
import time

import pytest

from app.engine import Engine
from app.lexicon import Lexicon
from app.settings import Settings
from app.store import Store
from app.textutil import is_learnable

ALPHABET = "абвгдежзийклмнопрстуфхцчшэюяўқғҳ"
WORDS = 60_000


@pytest.fixture(scope="module")
def big_lexicon():
    rng = random.Random(42)
    settings = Settings()
    settings.cross_script = True
    lexicon = Lexicon(Store(":memory:"), settings, autoflush=False)
    now = time.time()
    words = set()
    while len(words) < WORDS:
        word = "".join(rng.choice(ALPHABET) for _ in range(rng.randint(3, 10)))
        if is_learnable(word):
            words.add(word)
    words = sorted(words)
    prev = None
    for word in words:
        ts = now - rng.random() * 200 * 86400
        for _ in range(rng.choice((1, 1, 1, 2, 3, 8))):
            lexicon.learn(word, prev=prev, ts=ts)
        prev = word
    lexicon.flush()
    return lexicon, words


def _worst_ms(lexicon, prefixes, prev=None, repeat=3):
    """Worst prefix, each measured as the best of a few uncached runs."""
    worst = 0.0
    for prefix in prefixes:
        best = float("inf")
        for _ in range(repeat):
            lexicon.refresh_settings()            # drops the prefix cache
            t0 = time.perf_counter()
            lexicon.suggest(prefix, prev)
            best = min(best, time.perf_counter() - t0)
        worst = max(worst, best)
    return worst * 1000


def test_uncached_lookup_under_5ms(big_lexicon):
    lexicon, words = big_lexicon
    assert len(lexicon) == WORDS
    one_letter = list(ALPHABET) + list("abcdefghijklmnopqrstuvwxyz")
    two_letters = [a + b for a in "аксў" for b in "аиу"]
    # refresh_settings() rebuilds the whole index, so time only suggest()
    assert _worst_ms(lexicon, one_letter[:8] + two_letters[:4], repeat=2) < 5.0


def test_cached_lookup_is_fast(big_lexicon):
    lexicon, words = big_lexicon
    prefixes = list(ALPHABET) + [w[:2] for w in words[::2000]] + [w[:4] for w in words[::2000]]
    for prefix in prefixes:
        lexicon.suggest(prefix)
    t0 = time.perf_counter()
    for prefix in prefixes:
        lexicon.suggest(prefix)
    per_call_ms = (time.perf_counter() - t0) * 1000 / len(prefixes)
    assert per_call_ms < 1.0


def test_lookup_with_bigram_context_under_5ms(big_lexicon):
    lexicon, words = big_lexicon
    worst = 0.0
    for i in range(0, len(words) - 1, 1500):
        prev, nxt = words[i], words[i + 1]
        # Three fresh uses of the pair: 3 + 5 * 3 = 18 points, more than any
        # single word of the synthetic dictionary can have (8 uses at most).
        for _ in range(3):
            lexicon.learn(nxt, prev=prev)
        best = float("inf")
        for _ in range(3):                        # best of 3: ignore OS hiccups
            t0 = time.perf_counter()
            result = lexicon.suggest(nxt[:1], prev)
            best = min(best, time.perf_counter() - t0)
        worst = max(worst, best)
        assert result[0].text == nxt
    assert worst * 1000 < 5.0


def test_keystroke_cycle_under_5ms(big_lexicon):
    """One keystroke = feed a char + compute suggestions, including learning.

    Percentiles, not the maximum: a single slow sample is the OS preempting
    the thread, which no algorithm can prevent.
    """
    lexicon, words = big_lexicon
    lexicon.flush()
    lexicon.autoflush = True                      # worst case: db write per word
    engine = Engine(lexicon, lexicon.settings)
    sample = " ".join(words[::300]) + "\n"
    times = []
    for ch in sample:
        t0 = time.perf_counter()
        engine.feed(ch)
        engine.suggestions()
        times.append((time.perf_counter() - t0) * 1000)
    lexicon.autoflush = False
    times.sort()
    assert len(times) > 1000
    assert times[len(times) // 2] < 0.5           # median
    assert times[int(len(times) * 0.99)] < 5.0    # p99


def test_load_time_is_reasonable(big_lexicon):
    lexicon, _ = big_lexicon
    t0 = time.perf_counter()
    fresh = Lexicon(lexicon.store, lexicon.settings)
    elapsed = time.perf_counter() - t0
    assert len(fresh) == WORDS
    assert elapsed < 5.0
