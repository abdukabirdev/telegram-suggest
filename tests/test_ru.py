import pytest

from app.ru import MESSAGES, WORDS, date, plural


@pytest.mark.parametrize("n, text", [
    (0, "0 слов"), (1, "1 слово"), (2, "2 слова"), (4, "4 слова"), (5, "5 слов"),
    (11, "11 слов"), (12, "12 слов"), (14, "14 слов"), (21, "21 слово"), (22, "22 слова"),
    (101, "101 слово"), (111, "111 слов"),
])
def test_plural(n, text):
    assert plural(n, WORDS) == text


def test_plural_groups_thousands():
    assert plural(12345, MESSAGES) == "12 345 сообщений"


def test_date():
    assert date(0) == "—"
    assert len(date(1_700_000_000)) == 10
