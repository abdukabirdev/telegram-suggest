"""Small helpers for Russian interface text."""

from __future__ import annotations

import time


def plural(n: int, forms: tuple[str, str, str]) -> str:
    """``forms`` for 1, 2 and 5: plural(3, ("слово", "слова", "слов")) == "3 слова"."""
    n_abs = abs(n)
    if n_abs % 10 == 1 and n_abs % 100 != 11:
        form = forms[0]
    elif 2 <= n_abs % 10 <= 4 and not 12 <= n_abs % 100 <= 14:
        form = forms[1]
    else:
        form = forms[2]
    return f"{n:,}".replace(",", " ") + " " + form


WORDS = ("слово", "слова", "слов")
MESSAGES = ("сообщение", "сообщения", "сообщений")
CHATS = ("чат", "чата", "чатов")
TIMES = ("раз", "раза", "раз")


def date(ts: float) -> str:
    if ts <= 0:
        return "—"
    return time.strftime("%d.%m.%Y", time.localtime(ts))
