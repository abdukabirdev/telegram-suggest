import pytest

from app.engine import Insertion

from .conftest import texts


def type_keys(engine, text):
    """Type text; '\\b' stands for the Backspace key."""
    for ch in text:
        if ch == "\b":
            engine.backspace()
        else:
            engine.feed(ch)


# ---- suggesting and accepting ----------------------------------------------

def test_suggestions_follow_the_buffer(engine):
    type_keys(engine, "салом Абдукабир ака\n")
    assert engine.suggestions() == []
    type_keys(engine, "а")
    assert texts(engine.suggestions()) == ["Абдукабир", "ака"]
    type_keys(engine, "бд")
    assert engine.prefix == "абд"
    assert texts(engine.suggestions()) == ["Абдукабир"]
    type_keys(engine, "\b\b\b")
    assert engine.prefix == ""
    assert engine.suggestions() == []


def test_accept_replaces_typed_prefix(engine, lexicon):
    type_keys(engine, "салом Абдукабир ака\n")
    type_keys(engine, "абд")
    assert engine.accept(0) == Insertion(backspaces=3, text="Абдукабир ")
    assert engine.prefix == ""
    assert engine.suggestions() == []
    type_keys(engine, "яхшимисиз\n")
    assert lexicon.get("абдукабир").freq == 2
    assert "абд" not in lexicon


def test_accept_by_index(engine):
    type_keys(engine, "китоб келди келди катта катта катта\n")
    type_keys(engine, "к")
    assert texts(engine.suggestions()) == ["катта", "келди", "китоб"]
    assert engine.accept(2) == Insertion(1, "китоб ")


def test_accept_without_suggestions(engine):
    assert engine.accept(0) is None
    type_keys(engine, "салом\nса")
    assert engine.accept(5) is None
    assert engine.accept(-1) is None
    assert engine.prefix == "са"


def test_accepted_word_links_to_next_word(engine, lexicon):
    type_keys(engine, "ассалому алайкум\n")
    type_keys(engine, "асс")
    engine.accept(0)
    type_keys(engine, "ал")
    assert texts(engine.suggestions()) == ["алайкум"]
    engine.accept(0)
    type_keys(engine, "\n")
    assert lexicon.get("алайкум").freq == 2
    assert lexicon.bigram_count() == 1


def test_backspace_after_accept_edits_the_word(engine, lexicon):
    type_keys(engine, "саломат\n")
    type_keys(engine, "сал")
    engine.accept(0)                       # "саломат "
    type_keys(engine, "\b")                # remove the space
    assert engine.prefix == "саломат"
    type_keys(engine, "лик\n")
    assert "саломатлик" in lexicon
    assert lexicon.get("саломат").freq == 1


def test_dictionary_capital_is_not_reinforced_by_accepting(engine, lexicon):
    type_keys(engine, "Рахмат\n")          # sentence start: capital is ambiguous
    for _ in range(3):
        type_keys(engine, "катта р")
        assert texts(engine.suggestions()) == ["Рахмат"]
        engine.accept(0)
        type_keys(engine, "\n")
    type_keys(engine, "катта рахмат\n")    # typed in lowercase once
    type_keys(engine, "катта р")
    assert texts(engine.suggestions()) == ["рахмат"]


def test_dismiss_hides_until_next_word(engine):
    type_keys(engine, "салом саломат\n")
    type_keys(engine, "са")
    assert engine.suggestions()
    engine.dismiss()
    assert engine.suggestions() == []
    type_keys(engine, "л")
    assert engine.suggestions() == []
    type_keys(engine, "ом са")
    assert engine.suggestions()


def test_min_prefix_len(engine, settings):
    type_keys(engine, "салом\n")
    settings.min_prefix_len = 2
    type_keys(engine, "с")
    assert engine.suggestions() == []
    type_keys(engine, "а")
    assert texts(engine.suggestions()) == ["салом"]


# ---- learning --------------------------------------------------------------

def test_word_is_learned_when_next_word_starts(engine, lexicon):
    type_keys(engine, "салом")
    assert len(lexicon) == 0
    type_keys(engine, " ")
    assert len(lexicon) == 0               # still pending: may be edited
    type_keys(engine, "д")
    assert "салом" in lexicon


def test_enter_learns_immediately(engine, lexicon):
    type_keys(engine, "салом дўстим\n")
    assert lexicon.get("салом").freq == 1
    assert lexicon.get("дўстим").freq == 1
    assert lexicon.bigram_count() == 1


def test_backspace_over_separator_restores_word(engine, lexicon):
    type_keys(engine, "Абду \bкабир\n")
    assert "абдукабир" in lexicon
    assert "абду" not in lexicon
    assert "кабир" not in lexicon


def test_backspace_over_several_separators(engine, lexicon):
    type_keys(engine, "сало,  \b\b")
    assert engine.prefix == ""
    type_keys(engine, "\b")
    assert engine.prefix == "сало"
    type_keys(engine, "м\n")
    assert list(w.word for w in lexicon.search()) == ["салом"]


def test_backspace_inside_word(engine, lexicon):
    type_keys(engine, "салон\bм\n")
    assert "салом" in lexicon and "салон" not in lexicon


def test_backspace_into_unknown_text_resets(engine, lexicon):
    type_keys(engine, "салом\n")
    type_keys(engine, "\bса")              # deleting something typed earlier
    assert texts(engine.suggestions()) == ["салом"]
    type_keys(engine, "\b\b\b")
    assert engine.prefix == ""


def test_bigram_through_typing(engine):
    for _ in range(3):
        type_keys(engine, "Салом алейкум\n")
    for _ in range(10):
        type_keys(engine, "абдукабир\n")
    type_keys(engine, "а")
    assert texts(engine.suggestions()) == ["абдукабир", "алейкум"]
    type_keys(engine, "\bСалом а")
    assert texts(engine.suggestions()) == ["алейкум", "абдукабир"]


def test_comma_keeps_bigram_and_sentence_end_breaks_it(engine, lexicon):
    type_keys(engine, "привет, мир\n")
    assert lexicon.bigram_count() == 1
    type_keys(engine, "рахмат. катта\n")
    assert lexicon.bigram_count() == 1
    type_keys(engine, "хоп! майли\n")
    assert lexicon.bigram_count() == 1


def test_enter_breaks_bigram(engine, lexicon):
    type_keys(engine, "салом\nдўстим\n")
    assert lexicon.bigram_count() == 0


def test_name_in_the_middle_of_sentence_keeps_capital(engine):
    type_keys(engine, "салом Абдукабир ака\n")
    type_keys(engine, "аб")
    assert texts(engine.suggestions()) == ["Абдукабир"]


def test_capital_after_sentence_end_is_neutral(engine):
    type_keys(engine, "хоп. Рахмат катта\n")
    type_keys(engine, "хоп рахмат\n")
    type_keys(engine, "р")
    assert texts(engine.suggestions()) == ["рахмат"]


def test_capital_prefix_at_sentence_start(engine):
    type_keys(engine, "хоп рахмат\n")
    type_keys(engine, "Р")
    assert texts(engine.suggestions()) == ["Рахмат"]
    assert engine.accept(0) == Insertion(1, "Рахмат ")


@pytest.mark.parametrize("typed", [
    "я ", "ааа ", "5 ", "2024 ", "abc123 ", "тел998 ",
    "https://t.me/abdukabir ", "http://example.com/page?x=1 ",
    "example.com ", "www.example.com ", "user@mail.ru ", "@abdukabir ",
    "#chegirma ", "C:\\Users\\file ", "a/b ", "snake_case ",
])
def test_junk_is_not_learned(engine, lexicon, typed):
    type_keys(engine, typed + "\n")
    assert len(lexicon) == 0


def test_no_suggestions_inside_link_or_number(engine):
    type_keys(engine, "телефон тест\n")
    type_keys(engine, "t.me/т")
    assert engine.suggestions() == []
    type_keys(engine, " т")
    assert engine.suggestions() != []
    type_keys(engine, "\b5т")
    assert engine.suggestions() == []


def test_typing_continues_normally_after_link(engine, lexicon):
    type_keys(engine, "мана https://t.me/abc курдингми ака\n")
    assert sorted(w.word for w in lexicon.search()) == ["ака", "курдингми", "мана"]
    assert lexicon.bigram_count() == 1     # only курдингми -> ака


def test_number_breaks_bigram(engine, lexicon):
    type_keys(engine, "нархи 150000 сум\n")
    assert sorted(w.word for w in lexicon.search()) == ["нархи", "сум"]
    assert lexicon.bigram_count() == 0


def test_mistyped_glue_can_be_deleted(engine):
    type_keys(engine, "салом\n")
    type_keys(engine, "@\bса")
    assert texts(engine.suggestions()) == ["салом"]


def test_hyphen_and_apostrophe_inside_word(engine, lexicon):
    type_keys(engine, "кто-то o'zbek - да\n")
    assert sorted(w.word for w in lexicon.search()) == ["o'zbek", "да", "кто-то"]
    type_keys(engine, "o'")
    assert texts(engine.suggestions()) == ["o'zbek"]
    assert engine.accept(0) == Insertion(2, "o'zbek ")


def test_trailing_joiner_is_counted_for_backspaces(engine, lexicon):
    type_keys(engine, "саломат\n")
    type_keys(engine, "сал- \b")
    assert engine.prefix == "сал-"
    type_keys(engine, "\b")
    assert engine.accept(0) == Insertion(3, "саломат ")


# ---- reset (caret moved, paste, focus lost) --------------------------------

def test_reset_drops_unfinished_unknown_word(engine, lexicon):
    type_keys(engine, "приве")
    engine.reset()
    type_keys(engine, " \n")
    assert len(lexicon) == 0
    assert engine.prefix == ""


def test_reset_keeps_finished_word(engine, lexicon):
    type_keys(engine, "привет ")
    engine.reset()
    assert "привет" in lexicon


def test_reset_counts_known_word(engine, lexicon):
    type_keys(engine, "привет\n")
    type_keys(engine, "привет")
    engine.reset()                         # e.g. sent with a mouse click
    assert lexicon.get("привет").freq == 2


def test_reset_breaks_context(engine, lexicon):
    type_keys(engine, "салом ")
    engine.reset()                         # e.g. Ctrl+V or an arrow key
    type_keys(engine, "Алейкум\n")
    assert lexicon.bigram_count() == 0
    type_keys(engine, "а")
    # capital right after a reset is treated as ambiguous, the word is kept as typed
    assert texts(engine.suggestions()) == ["Алейкум"]


# ---- next word prediction --------------------------------------------------

def test_predict_next_word_is_optional(engine, settings):
    type_keys(engine, "Салом алейкум\n")
    type_keys(engine, "Салом ")
    assert engine.suggestions() == []
    settings.predict_next_word = True
    type_keys(engine, "\b ")
    assert texts(engine.suggestions()) == ["алейкум"]
    assert engine.accept(0) == Insertion(0, "алейкум ")


def test_predict_next_not_after_punctuation(engine, settings):
    settings.predict_next_word = True
    type_keys(engine, "Салом алейкум\n")
    type_keys(engine, "Салом. ")
    assert engine.suggestions() == []


# ---- multi-character input -------------------------------------------------

def test_feed_accepts_strings(engine, lexicon):
    engine.feed("салом дўстим\r")
    assert len(lexicon) == 2
