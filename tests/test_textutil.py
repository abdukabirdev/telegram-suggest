import pytest

from app.textutil import is_learnable, tokenize


def words(text):
    return [[w for w, _ in chain] for chain in tokenize(text)]


@pytest.mark.parametrize("word", [
    "салом", "Абдукабир", "ўзбек", "қилдим", "ғалаба", "ҳаво", "да", "ok",
    "o'zbek", "o\u02bbzbek", "кто-то", "ma'no",
])
def test_learnable(word):
    assert is_learnable(word)


@pytest.mark.parametrize("word", [
    "", "я", "a", "аа", "ааа", "ммм", "123", "abc123", "2024", "t.me",
    "user@mail", "#tag", "-да", "да-", "'a", "a_b", "x" * 41, "½",
])
def test_not_learnable(word):
    assert not is_learnable(word)


def test_min_len_is_configurable():
    assert not is_learnable("да", min_len=3)
    assert is_learnable("дом", min_len=3)


def test_simple_sentence_is_one_chain():
    assert tokenize("Салом алейкум Абдукабир ака") == [[
        ("Салом", True), ("алейкум", False), ("Абдукабир", False), ("ака", False),
    ]]


def test_punctuation_is_stripped_and_comma_keeps_chain():
    assert words("Салом, «Абдукабир» (ака): яхшимисиз") == [
        ["Салом", "Абдукабир", "ака", "яхшимисиз"]
    ]


def test_sentence_end_breaks_chain_and_marks_start():
    assert tokenize("Рахмат катта. Эртага келаман! Хоп") == [
        [("Рахмат", True), ("катта", False)],
        [("Эртага", True), ("келаман", False)],
        [("Хоп", True)],
    ]


def test_newline_breaks_chain():
    assert tokenize("салом дўстим\nяхши раҳмат") == [
        [("салом", True), ("дўстим", False)],
        [("яхши", True), ("раҳмат", False)],
    ]


def test_numbers_break_chain():
    assert words("нархи 150000 сум булади") == [["нархи"], ["сум", "булади"]]
    assert words("тел +998901234567 ёзинг") == [["тел"], ["ёзинг"]]
    assert words("iphone15 олдим") == [["олдим"]]


@pytest.mark.parametrize("text", [
    "https://t.me/abdukabir",
    "http://example.com/path?x=1",
    "www.example.com",
    "example.uz",
    "user@mail.ru",
    "@abdukabir_uz",
    "#chegirma",
    "C:\\Users\\file",
    "a/b",
    "snake_case",
])
def test_links_handles_and_paths_are_ignored(text):
    assert tokenize(text) == []
    assert words(f"мана {text} курдингми") == [["мана"], ["курдингми"]]


def test_short_and_single_letter_words_break_chain():
    assert words("мен я у билан") == [["мен"], ["билан"]]
    assert words("ааа яхши ммм") == [["яхши"]]


def test_dot_without_space_between_cyrillic_words_is_sentence_end():
    assert tokenize("Салом.Яхшимисиз") == [[("Салом", True)], [("Яхшимисиз", True)]]


def test_comma_without_space_splits_words():
    assert words("да,нет,балки") == [["да", "нет", "балки"]]


def test_hyphen_and_apostrophe_stay_inside_word():
    assert words("кто-то o'zbek ma\u2019no") == [["кто-то", "o'zbek", "ma\u2019no"]]


def test_emoji_and_symbols():
    assert words("салом 😀 дўстим 👍") == [["салом", "дўстим"]]
    assert words("рахмат🙏катта") == [["рахмат", "катта"]]


def test_capital_after_number_is_not_sentence_start():
    assert tokenize("2 Абдукабир") == [[("Абдукабир", False)]]


def test_empty_and_punctuation_only():
    assert tokenize("") == []
    assert tokenize("... !!! — ?") == []
