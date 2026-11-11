import pytest

from app.translit import cyr_to_lat, fold, lat_to_cyr, script_of, to_script


@pytest.mark.parametrize("src, expected", [
    ("Қил", "кил"),
    ("Ўзбек", "узбек"),
    ("ғалаба", "галаба"),
    ("ҲАВО", "хаво"),
    ("ёз", "ез"),
    ("o'zbek", "ozbek"),
    ("oʻzbek", "ozbek"),
    ("o‘zbek", "ozbek"),
    ("G’alaba", "galaba"),
    ("Абдукабир", "абдукабир"),
])
def test_fold(src, expected):
    assert fold(src) == expected


def test_fold_normalises_combining_marks():
    # "й" and "ў" typed as base letter + combining breve
    assert fold("й") == "й"
    assert fold("ўзбек") == "узбек"


@pytest.mark.parametrize("word, script", [
    ("салом", "cyr"), ("Ўзбек", "cyr"), ("salom", "lat"), ("O'zbek", "lat"),
    ("'қил", "cyr"), ("", "lat"),
])
def test_script_of(word, script):
    assert script_of(word) == script


@pytest.mark.parametrize("cyr, lat", [
    ("Ўзбекистон", "O'zbekiston"),
    ("Қарши", "Qarshi"),
    ("Ғалаба", "G'alaba"),
    ("Ҳаво", "Havo"),
    ("Шаҳар", "Shahar"),
    ("Чой", "Choy"),
    ("Абдукабир", "Abdukabir"),
    ("яхши", "yaxshi"),
    ("Юлдуз", "Yulduz"),
    ("ер", "yer"),
    ("келди", "keldi"),
    ("поезд", "poyezd"),
    ("маъно", "ma'no"),
    ("цирк", "sirk"),
    ("милиция", "militsiya"),
    ("концерт", "konsert"),
    ("ШАҲАР", "SHAHAR"),
    ("ЎЗБЕК", "O'ZBEK"),
    ("ёз", "yoz"),
    ("кўл", "ko'l"),
])
def test_cyr_to_lat(cyr, lat):
    assert cyr_to_lat(cyr) == lat


@pytest.mark.parametrize("lat, cyr", [
    ("O'zbekiston", "Ўзбекистон"),
    ("Oʻzbekiston", "Ўзбекистон"),
    ("Qarshi", "Қарши"),
    ("G'alaba", "Ғалаба"),
    ("Havo", "Ҳаво"),
    ("Shahar", "Шаҳар"),
    ("Choy", "Чой"),
    ("yo'l", "йўл"),
    ("yoz", "ёз"),
    ("ma'no", "маъно"),
    ("elak", "элак"),
    ("kel", "кел"),
    ("aeroport", "аэропорт"),
    ("Yaxshi", "Яхши"),
    ("SHAHAR", "ШАҲАР"),
    ("ketsa", "кетса"),
    ("Is'hoq", "Исҳоқ"),
    ("yer", "ер"),
    ("rahmat", "раҳмат"),
])
def test_lat_to_cyr(lat, cyr):
    assert lat_to_cyr(lat) == cyr


@pytest.mark.parametrize("word", [
    "Ўзбекистон", "Қарши", "Ғалаба", "Ҳаво", "Шаҳар", "Чой", "Абдукабир",
    "яхши", "маъно", "йўл", "ер", "қилдим", "ўғил", "ҳурмат",
])
def test_roundtrip_cyr_lat_cyr(word):
    assert lat_to_cyr(cyr_to_lat(word)) == word


def test_to_script_keeps_word_in_same_script():
    assert to_script("салом", "cyr") == "салом"
    assert to_script("салом", "lat") == "salom"
    assert to_script("salom", "cyr") == "салом"
    assert to_script("salom", "lat") == "salom"
