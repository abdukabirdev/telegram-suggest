import math

import pytest

from app.lexicon import Lexicon, apply_case
from app.settings import Settings
from app.store import Store

from .conftest import texts


def learn_many(lexicon, word, times, **kwargs):
    for _ in range(times):
        lexicon.learn(word, **kwargs)


# ---- prefix search ---------------------------------------------------------

def test_cyrillic_prefixes(lexicon):
    for word in ("салом", "сават", "савдо", "китоб"):
        lexicon.learn(word)
    assert set(texts(lexicon.suggest("с"))) == {"салом", "сават", "савдо"}
    assert set(texts(lexicon.suggest("са"))) == {"салом", "сават", "савдо"}
    assert set(texts(lexicon.suggest("сав"))) == {"сават", "савдо"}
    assert texts(lexicon.suggest("савд")) == ["савдо"]
    assert texts(lexicon.suggest("к")) == ["китоб"]
    assert lexicon.suggest("я") == []
    assert lexicon.suggest("") == []


def test_one_letter_prefix_is_enough(lexicon):
    lexicon.learn("Абдукабир")
    assert texts(lexicon.suggest("А")) == ["Абдукабир"]


def test_fully_typed_word_is_not_suggested(lexicon):
    lexicon.learn("салом")
    lexicon.learn("саломат")
    assert texts(lexicon.suggest("салом")) == ["саломат"]
    assert lexicon.suggest("саломат") == []


def test_limit(lexicon, settings):
    for i, word in enumerate(["бозор", "бола", "бугун", "бахт", "барча", "бироз"]):
        learn_many(lexicon, word, i + 1)
    assert len(lexicon.suggest("б")) == settings.max_suggestions
    assert texts(lexicon.suggest("б", limit=2)) == ["бироз", "барча"]


def test_latin_and_russian_words(lexicon):
    for word in ("привет", "пожалуйста", "price", "product"):
        lexicon.learn(word)
    assert set(texts(lexicon.suggest("п"))) == {"привет", "пожалуйста"}
    assert set(texts(lexicon.suggest("pr"))) == {"price", "product"}
    assert texts(lexicon.suggest("pri")) == ["price"]


# ---- what is learned -------------------------------------------------------

@pytest.mark.parametrize("token", ["я", "5", "2024", "abc123", "ааа", "t.me", "a@b", ""])
def test_junk_is_not_learned(lexicon, token):
    assert lexicon.learn(token) is None
    assert len(lexicon) == 0


def test_short_words_are_learned_but_not_suggested(lexicon):
    learn_many(lexicon, "да", 10)
    lexicon.learn("дарс")
    assert "да" in lexicon
    assert texts(lexicon.suggest("д")) == ["дарс"]


def test_freq_counts_every_use(lexicon):
    learn_many(lexicon, "рахмат", 3)
    lexicon.learn("Рахмат", sentence_start=True)
    info = lexicon.get("РАХМАТ")
    assert info.freq == 4
    assert info.word == "рахмат"


# ---- ranking: frequency and recency ----------------------------------------

def test_more_frequent_word_goes_first(lexicon):
    learn_many(lexicon, "китоб", 2)
    learn_many(lexicon, "келдим", 5)
    learn_many(lexicon, "катта", 3)
    assert texts(lexicon.suggest("к")) == ["келдим", "катта", "китоб"]


def test_recent_word_beats_old_frequent_word(lexicon, clock):
    learn_many(lexicon, "мактаб", 5)
    clock.advance(120)          # four half-lives: 5 uses decay to ~0.31
    learn_many(lexicon, "машина", 2)
    assert texts(lexicon.suggest("м")) == ["машина", "мактаб"]


def test_old_frequent_word_still_wins_while_fresh(lexicon, clock):
    learn_many(lexicon, "мактаб", 5)
    clock.advance(10)
    learn_many(lexicon, "машина", 2)
    assert texts(lexicon.suggest("м")) == ["мактаб", "машина"]


def test_score_halves_after_half_life(lexicon, clock, settings):
    lexicon.learn("салом")
    assert lexicon.suggest("с")[0].score == pytest.approx(1.0)
    clock.advance(settings.half_life_days)
    assert lexicon.suggest("с")[0].score == pytest.approx(0.5)
    lexicon.learn("салом")
    assert lexicon.suggest("с")[0].score == pytest.approx(1.5)


def test_older_timestamp_adds_decayed_weight(lexicon, clock, settings):
    lexicon.learn("салом")
    lexicon.learn("салом", ts=clock.now - settings.half_life_days * 86400)
    assert lexicon.suggest("с")[0].score == pytest.approx(1.5)


def test_ranking_survives_cache_and_updates(lexicon):
    learn_many(lexicon, "олма", 3)
    learn_many(lexicon, "олтин", 2)
    assert texts(lexicon.suggest("о")) == ["олма", "олтин"]   # fills the cache
    learn_many(lexicon, "олтин", 5)
    assert texts(lexicon.suggest("о")) == ["олтин", "олма"]
    lexicon.learn("олов")
    assert texts(lexicon.suggest("о")) == ["олтин", "олма", "олов"]


def test_top_k_selection_on_big_range(lexicon):
    lexicon.autoflush = False
    for i in range(200):
        lexicon.learn(f"т{chr(0x430 + i % 30)}{chr(0x430 + i // 30)}ст")
    learn_many(lexicon, "тайёр", 4)
    learn_many(lexicon, "телефон", 3)
    assert texts(lexicon.suggest("т", limit=2)) == ["тайёр", "телефон"]


def test_incrementally_updated_cache_matches_fresh_index(store, settings, clock):
    """Tops kept up to date on every learn must equal a from-scratch rebuild."""
    import random

    rng = random.Random(7)
    letters = "абвк"
    vocab = sorted({
        "".join(rng.choice(letters) for _ in range(rng.randint(3, 6)))
        for _ in range(600)
    })
    vocab = [w for w in vocab if len(set(w)) > 1]
    lexicon = Lexicon(store, settings, clock=clock)
    prefixes = [a for a in letters] + [a + b for a in letters for b in letters]
    for step in range(3000):
        lexicon.learn(rng.choice(vocab))
        if step % 7 == 0:
            lexicon.suggest(rng.choice(prefixes))      # populate caches on the way
        if step % 50 == 0:
            clock.advance(rng.random() * 3)
        if step % 400 == 399:
            lexicon.delete(rng.choice(vocab))

    fresh = Lexicon(store, settings, clock=clock)
    assert len(fresh) == len(lexicon)
    for prefix in prefixes + [w[:3] for w in vocab[::40]]:
        live = lexicon.suggest(prefix, limit=20)
        rebuilt = fresh.suggest(prefix, limit=20)
        assert texts(live) == texts(rebuilt), prefix
        assert [s.score for s in live] == pytest.approx([s.score for s in rebuilt])


def test_half_life_change_is_applied_on_refresh(lexicon, clock, settings):
    learn_many(lexicon, "мактаб", 5)
    clock.advance(30)           # one half-life: 5 uses decay to 2.5, still > 2
    learn_many(lexicon, "машина", 2)
    assert texts(lexicon.suggest("м")) == ["мактаб", "машина"]
    settings.half_life_days = 10    # now three half-lives: 5 -> 0.625
    lexicon.refresh_settings()
    assert texts(lexicon.suggest("м")) == ["машина", "мактаб"]


# ---- case ------------------------------------------------------------------

def test_name_is_remembered_as_written(lexicon):
    lexicon.learn("Абдукабир", prev=None, sentence_start=False)
    assert texts(lexicon.suggest("абд")) == ["Абдукабир"]
    assert texts(lexicon.suggest("Абд")) == ["Абдукабир"]
    assert texts(lexicon.suggest("а")) == ["Абдукабир"]


def test_capital_prefix_capitalises_suggestion(lexicon):
    lexicon.learn("салом")
    assert texts(lexicon.suggest("с")) == ["салом"]
    assert texts(lexicon.suggest("С")) == ["Салом"]
    assert texts(lexicon.suggest("Са")) == ["Салом"]
    assert texts(lexicon.suggest("СА")) == ["САЛОМ"]


def test_sentence_start_capital_is_not_evidence(lexicon):
    lexicon.learn("Рахмат", sentence_start=True)
    # only ever seen capitalised: keep it as written
    assert texts(lexicon.suggest("р")) == ["Рахмат"]
    lexicon.learn("рахмат")
    # one lowercase use in the middle of a sentence settles it
    assert texts(lexicon.suggest("р")) == ["рахмат"]
    learn_many(lexicon, "Рахмат", 5, sentence_start=True)
    assert texts(lexicon.suggest("р")) == ["рахмат"]


def test_name_stays_capitalised_despite_occasional_lowercase(lexicon):
    learn_many(lexicon, "Абдукабир", 3)
    lexicon.learn("абдукабир")
    assert texts(lexicon.suggest("аб")) == ["Абдукабир"]
    learn_many(lexicon, "абдукабир", 3)
    assert texts(lexicon.suggest("аб")) == ["абдукабир"]


def test_lowercase_fully_typed_name_offers_capitalised_form(lexicon):
    lexicon.learn("Абдукабир")
    assert texts(lexicon.suggest("абдукабир")) == ["Абдукабир"]
    assert lexicon.suggest("Абдукабир") == []


def test_mixed_case_and_abbreviations(lexicon):
    lexicon.learn("iPhone")
    lexicon.learn("ИНН")
    assert texts(lexicon.suggest("ip")) == ["iPhone"]
    assert texts(lexicon.suggest("ин")) == ["ИНН"]


@pytest.mark.parametrize("prefix, text, expected", [
    ("с", "салом", "салом"),
    ("С", "салом", "Салом"),
    ("СА", "салом", "САЛОМ"),
    ("а", "Абдукабир", "Абдукабир"),
    ("Ў", "ўзбек", "Ўзбек"),
    ("", "салом", "салом"),
])
def test_apply_case(prefix, text, expected):
    assert apply_case(prefix, text) == expected


# ---- bigrams ---------------------------------------------------------------

def test_bigram_lifts_follower_above_more_frequent_word(lexicon):
    learn_many(lexicon, "абдукабир", 10)
    for _ in range(3):
        lexicon.learn("Салом", sentence_start=True)
        lexicon.learn("алейкум", prev="Салом")
    assert texts(lexicon.suggest("а")) == ["абдукабир", "алейкум"]
    assert texts(lexicon.suggest("а", prev="Салом")) == ["алейкум", "абдукабир"]
    assert texts(lexicon.suggest("а", prev="салом")) == ["алейкум", "абдукабир"]
    assert texts(lexicon.suggest("а", prev="рахмат")) == ["абдукабир", "алейкум"]


def test_bigram_reaches_word_outside_top_k(lexicon):
    lexicon.autoflush = False
    for i in range(100):
        learn_many(lexicon, f"а{chr(0x430 + i % 30)}{chr(0x430 + i // 30)}ра", 3)
    lexicon.learn("ассалому")
    lexicon.learn("алайкум", prev="ассалому")
    assert "алайкум" not in texts(lexicon.suggest("а"))
    assert texts(lexicon.suggest("а", prev="ассалому"))[0] == "алайкум"


def test_bigram_needs_known_previous_word(lexicon):
    lexicon.learn("келдим", prev="мен")      # "мен" was never learned
    assert lexicon.bigram_count() == 0


def test_bigram_decays(lexicon, clock):
    lexicon.learn("салом")
    lexicon.learn("алейкум", prev="салом")
    clock.advance(300)
    learn_many(lexicon, "абдукабир", 2)
    assert texts(lexicon.suggest("а", prev="салом")) == ["абдукабир", "алейкум"]


def test_predict_next(lexicon):
    lexicon.learn("салом")
    for word, times in (("алейкум", 3), ("дўстим", 1), ("ака", 2)):
        for _ in range(times):
            lexicon.learn("салом")
            lexicon.learn(word, prev="салом")
    assert texts(lexicon.predict_next("Салом")) == ["алейкум", "ака", "дўстим"]
    assert texts(lexicon.predict_next("салом", limit=1)) == ["алейкум"]
    assert lexicon.predict_next("алейкум") == []
    assert lexicon.predict_next("unknown") == []


# ---- Uzbek letters ---------------------------------------------------------

@pytest.mark.parametrize("word, prefixes", [
    ("қилдим", ["қ", "қи", "к", "ки", "Қ", "кил"]),
    ("ўзбек", ["ў", "ўз", "у", "уз", "узб"]),
    ("ғалаба", ["ғ", "ға", "г", "га", "гал"]),
    ("ҳаво", ["ҳ", "ҳа", "х", "ха"]),
    ("ўғил", ["ўғ", "уг", "ўг", "уғ"]),
])
def test_uzbek_letters_match_with_and_without_diacritics(lexicon, word, prefixes):
    lexicon.learn(word)
    for prefix in prefixes:
        assert [t.lower() for t in texts(lexicon.suggest(prefix))] == [word], prefix


def test_plain_spelling_is_found_by_uzbek_prefix(lexicon):
    lexicon.learn("килдим")
    lexicon.learn("хаво")
    assert texts(lexicon.suggest("қи")) == ["килдим"]
    assert texts(lexicon.suggest("ҳа")) == ["хаво"]


def test_both_spellings_are_kept_apart_and_ranked(lexicon):
    learn_many(lexicon, "қилдим", 3)
    lexicon.learn("килдим")
    assert texts(lexicon.suggest("ки")) == ["қилдим", "килдим"]
    # the fully typed plain form still offers the proper spelling
    assert texts(lexicon.suggest("килдим")) == ["қилдим"]


def test_capitalised_uzbek_letters(lexicon):
    lexicon.learn("Ўзбекистон")
    lexicon.learn("Қарши")
    lexicon.learn("Ғайрат")
    lexicon.learn("Ҳасан")
    assert texts(lexicon.suggest("у")) == ["Ўзбекистон"]
    assert texts(lexicon.suggest("К")) == ["Қарши"]
    assert texts(lexicon.suggest("г")) == ["Ғайрат"]
    assert texts(lexicon.suggest("Х")) == ["Ҳасан"]


def test_latin_apostrophe_variants(lexicon):
    lexicon.learn("o'zbek")
    lexicon.learn("g‘alaba")
    assert texts(lexicon.suggest("o")) == ["o'zbek"]
    assert texts(lexicon.suggest("o'z")) == ["o'zbek"]
    assert texts(lexicon.suggest("oʻz")) == ["o'zbek"]
    assert texts(lexicon.suggest("oz")) == ["o'zbek"]
    assert texts(lexicon.suggest("g'a")) == ["g‘alaba"]


# ---- cross-script ----------------------------------------------------------

def test_cross_script_is_off_by_default(lexicon):
    lexicon.learn("ўзбек")
    assert lexicon.suggest("o'z") == []
    assert lexicon.suggest("o") == []


def test_cyrillic_word_is_offered_in_latin(lexicon, settings):
    settings.cross_script = True
    lexicon.learn("ўзбек")
    lexicon.learn("Абдукабир")
    lexicon.learn("шаҳар")
    assert texts(lexicon.suggest("o'z")) == ["o'zbek"]
    assert texts(lexicon.suggest("O")) == ["O'zbek"]
    assert texts(lexicon.suggest("ab")) == ["Abdukabir"]
    assert texts(lexicon.suggest("sh")) == ["shahar"]
    suggestion = lexicon.suggest("ab")[0]
    assert suggestion.cross and suggestion.word == "абдукабир"


def test_latin_word_is_offered_in_cyrillic(lexicon, settings):
    settings.cross_script = True
    lexicon.learn("rahmat")
    lexicon.learn("qilaman")
    assert texts(lexicon.suggest("ра")) == ["раҳмат"]
    assert texts(lexicon.suggest("қи")) == ["қиламан"]
    assert texts(lexicon.suggest("ки")) == ["қиламан"]


def test_same_script_word_beats_transliterated_one(lexicon, settings):
    settings.cross_script = True
    learn_many(lexicon, "салом", 3)
    learn_many(lexicon, "salomat", 2)
    result = lexicon.suggest("sa")
    assert texts(result) == ["salomat", "salom"]
    assert result[1].score == pytest.approx(3 * settings.cross_script_penalty)


def test_cross_script_duplicates_are_merged(lexicon, settings):
    settings.cross_script = True
    lexicon.learn("салом")
    lexicon.learn("salom")
    result = lexicon.suggest("sa")
    assert texts(result) == ["salom"]
    assert not result[0].cross


# ---- persistence -----------------------------------------------------------

def test_reload_from_store_gives_same_suggestions(store, settings, clock):
    first = Lexicon(store, settings, clock=clock)
    learn_many(first, "Абдукабир", 3)
    first.learn("ака", prev="Абдукабир")
    first.learn("Салом", sentence_start=True)
    first.learn("алейкум", prev="Салом")
    first.learn("қилдим")
    clock.advance(3)

    second = Lexicon(store, settings, clock=clock)
    assert len(second) == len(first) == 5
    assert second.bigram_count() == 2
    for prefix, prev in [("а", None), ("а", "Салом"), ("а", "Абдукабир"), ("к", None)]:
        a = first.suggest(prefix, prev)
        b = second.suggest(prefix, prev)
        assert texts(a) == texts(b)
        assert [s.score for s in a] == pytest.approx([s.score for s in b])
    assert second.get("абдукабир").freq == 3


def test_deferred_flush(store, settings, clock):
    lexicon = Lexicon(store, settings, clock=clock, autoflush=False)
    lexicon.learn("салом")
    lexicon.learn("алейкум", prev="салом")
    assert store.counts() == (0, 0)
    lexicon.flush()
    assert store.counts() == (2, 1)
    lexicon.flush()                     # nothing new: no-op
    assert store.counts() == (2, 1)


def test_file_database(tmp_path, settings, clock):
    path = tmp_path / "data.db"
    store = Store(path)
    lexicon = Lexicon(store, settings, clock=clock)
    lexicon.learn("Абдукабир")
    store.close()

    store = Store(path)
    assert texts(Lexicon(store, Settings(), clock=clock).suggest("а")) == ["Абдукабир"]
    store.close()


# ---- deleting --------------------------------------------------------------

def test_delete_word(lexicon, store):
    lexicon.learn("салом")
    lexicon.learn("алейкум", prev="салом")
    lexicon.learn("салом", prev="алейкум")
    assert lexicon.delete("Салом") is True
    assert lexicon.delete("салом") is False
    assert "салом" not in lexicon
    assert lexicon.suggest("с") == []
    assert lexicon.bigram_count() == 0
    assert store.counts() == (1, 0)
    assert texts(lexicon.suggest("а")) == ["алейкум"]
    # can be learned again from scratch
    lexicon.learn("салом")
    assert lexicon.get("салом").freq == 1


def test_clear(lexicon, store):
    lexicon.learn("салом")
    lexicon.learn("алейкум", prev="салом")
    lexicon.clear()
    assert len(lexicon) == 0
    assert lexicon.bigram_count() == 0
    assert lexicon.suggest("с") == []
    assert store.counts() == (0, 0)


def test_search(lexicon):
    learn_many(lexicon, "Абдукабир", 3)
    learn_many(lexicon, "кабинет", 2)
    lexicon.learn("қилдим")
    assert [w.word for w in lexicon.search()] == ["абдукабир", "кабинет", "қилдим"]
    assert [w.display for w in lexicon.search("каб")] == ["Абдукабир", "кабинет"]
    assert [w.word for w in lexicon.search("кил")] == ["қилдим"]
    assert [w.word for w in lexicon.search("qil")] == ["қилдим"]
    assert lexicon.search("zzz") == []
    assert len(lexicon.search(limit=1)) == 1


def test_scores_stay_finite_over_long_history(lexicon, clock):
    for _ in range(500):
        lexicon.learn("салом")
        clock.advance(7)
    score = lexicon.suggest("с")[0].score
    assert math.isfinite(score) and 1.0 < score < 10.0
