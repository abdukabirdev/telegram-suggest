"""SQLite persistence: words, bigrams, settings. One local file, no network."""

from __future__ import annotations

import json
import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterable, Iterator

SCHEMA_VERSION = 1

# (word, cased, norm, xnorm, lang, freq, score, last_used, lower_count, cased_count)
WordRow = tuple
# (prev, next, freq, score, last_used)
BigramRow = tuple

_SCHEMA = """
CREATE TABLE IF NOT EXISTS words (
    word        TEXT PRIMARY KEY,           -- lowercase form
    cased       TEXT,                       -- form with capitals, if ever seen
    norm        TEXT NOT NULL,              -- search key (folded)
    xnorm       TEXT NOT NULL,              -- search key in the other script
    lang        TEXT NOT NULL,              -- 'cyr' or 'lat'
    freq        INTEGER NOT NULL DEFAULT 0, -- raw number of uses
    score       REAL NOT NULL DEFAULT 0,    -- decayed number of uses as of last_used
    last_used   REAL NOT NULL DEFAULT 0,    -- unix time
    lower_count INTEGER NOT NULL DEFAULT 0,
    cased_count INTEGER NOT NULL DEFAULT 0
) WITHOUT ROWID;
CREATE INDEX IF NOT EXISTS idx_words_norm ON words(norm);
CREATE INDEX IF NOT EXISTS idx_words_xnorm ON words(xnorm);

CREATE TABLE IF NOT EXISTS bigrams (
    prev      TEXT NOT NULL,
    next      TEXT NOT NULL,
    freq      INTEGER NOT NULL DEFAULT 0,
    score     REAL NOT NULL DEFAULT 0,
    last_used REAL NOT NULL DEFAULT 0,
    PRIMARY KEY (prev, next)
) WITHOUT ROWID;
CREATE INDEX IF NOT EXISTS idx_bigrams_next ON bigrams(next);

CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
) WITHOUT ROWID;
"""


class Store:
    """Thread-safe wrapper around a single SQLite connection."""

    def __init__(self, path: str | Path = ":memory:") -> None:
        self.path = str(path)
        self._memory = self.path == ":memory:"
        if not self._memory:
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._depth = 0
        # isolation_level=None: transactions are managed explicitly in bulk()
        self._conn = sqlite3.connect(
            self.path, isolation_level=None, check_same_thread=False
        )
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA synchronous=NORMAL")
        # Deleted words must really disappear from the file
        self._conn.execute("PRAGMA secure_delete=ON")
        self._conn.executescript(_SCHEMA)
        self._conn.execute(f"PRAGMA user_version={SCHEMA_VERSION}")

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    @contextmanager
    def bulk(self) -> Iterator[None]:
        """Group writes into one transaction. Re-entrant."""
        with self._lock:
            outer = self._depth == 0
            if outer:
                self._conn.execute("BEGIN")
            self._depth += 1
            try:
                yield
            except BaseException:
                self._depth -= 1
                if outer:
                    self._conn.execute("ROLLBACK")
                raise
            else:
                self._depth -= 1
                if outer:
                    self._conn.execute("COMMIT")

    # ---- words and bigrams -------------------------------------------------

    def load_words(self) -> list[WordRow]:
        with self._lock:
            return self._conn.execute(
                "SELECT word, cased, norm, xnorm, lang, freq, score, last_used,"
                " lower_count, cased_count FROM words"
            ).fetchall()

    def load_bigrams(self) -> list[BigramRow]:
        with self._lock:
            return self._conn.execute(
                "SELECT prev, next, freq, score, last_used FROM bigrams"
            ).fetchall()

    def save_words(self, rows: Iterable[WordRow]) -> None:
        with self.bulk():
            self._conn.executemany(
                "INSERT OR REPLACE INTO words (word, cased, norm, xnorm, lang, freq,"
                " score, last_used, lower_count, cased_count)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                rows,
            )

    def save_bigrams(self, rows: Iterable[BigramRow]) -> None:
        with self.bulk():
            self._conn.executemany(
                "INSERT OR REPLACE INTO bigrams (prev, next, freq, score, last_used)"
                " VALUES (?, ?, ?, ?, ?)",
                rows,
            )

    def delete_word(self, word: str) -> None:
        with self.bulk():
            self._conn.execute("DELETE FROM words WHERE word = ?", (word,))
            self._conn.execute(
                "DELETE FROM bigrams WHERE prev = ? OR next = ?", (word, word)
            )

    def clear(self) -> None:
        """Remove every learned word and bigram. Settings are kept."""
        with self._lock:
            with self.bulk():
                self._conn.execute("DELETE FROM words")
                self._conn.execute("DELETE FROM bigrams")
            if self._depth == 0 and not self._memory:
                self._conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
                self._conn.execute("VACUUM")

    def counts(self) -> tuple[int, int]:
        with self._lock:
            words = self._conn.execute("SELECT COUNT(*) FROM words").fetchone()[0]
            bigrams = self._conn.execute("SELECT COUNT(*) FROM bigrams").fetchone()[0]
            return words, bigrams

    # ---- settings ----------------------------------------------------------

    def get_setting(self, key: str, default: Any = None) -> Any:
        with self._lock:
            row = self._conn.execute(
                "SELECT value FROM settings WHERE key = ?", (key,)
            ).fetchone()
        if row is None:
            return default
        try:
            return json.loads(row[0])
        except ValueError:
            return default

    def set_setting(self, key: str, value: Any) -> None:
        with self.bulk():
            self._conn.execute(
                "INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)",
                (key, json.dumps(value, ensure_ascii=False)),
            )

    def all_settings(self) -> dict[str, Any]:
        with self._lock:
            rows = self._conn.execute("SELECT key, value FROM settings").fetchall()
        result: dict[str, Any] = {}
        for key, value in rows:
            try:
                result[key] = json.loads(value)
            except ValueError:
                continue
        return result
