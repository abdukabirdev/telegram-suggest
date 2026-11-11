import json

import pytest

from app.importer import (ExportError, find_export_files, html_ts, json_text, learn_messages,
                          read_html, read_json, scan)

from .conftest import texts

T0 = 1_700_000_000


def _msg(i, sender, name, text, **extra):
    m = {"id": i, "type": "message", "date": "2023-11-14T22:13:20",
         "date_unixtime": str(T0 + i), "from": name, "from_id": sender, "text": text}
    m.update(extra)
    return m


CHAT = {
    "name": "Кабир", "type": "personal_chat", "id": 42,
    "messages": [
        _msg(1, "user1", "Абдукабир", "Ассалому алейкум ака"),
        _msg(2, "user2", "Кабир", "Ваалейкум ассалом"),
        _msg(3, "user1", "Абдукабир", ["Смотри ", {"type": "link", "text": "google.com"},
                                       " ", {"type": "bold", "text": "хорошо"}]),
        _msg(4, "user1", "Абдукабир", "переслано чужое", forwarded_from="Канал"),
        _msg(5, "user1", "Абдукабир", "через бота", via_bot="@gif"),
        {"id": 6, "type": "service", "date_unixtime": str(T0), "actor": "Абдукабир",
         "action": "phone_call", "text": ""},
        _msg(7, "user1", "Абдукабир", ""),               # a photo without caption
        _msg(8, "user1", "Абдукабир", "Ассалому алейкум"),
    ],
}

FULL = {
    "personal_information": {"user_id": 1, "first_name": "Абдукабир", "last_name": ""},
    "chats": {"about": "", "list": [
        CHAT,
        {"name": None, "type": "saved_messages", "id": 7, "messages": [
            _msg(1, "user1", "Абдукабир", "заметка себе"),
        ]},
    ]},
    "left_chats": {"about": "", "list": [
        {"name": "Группа", "type": "private_supergroup", "id": 9, "messages": [
            _msg(10, "user1", "Абдукабир", "прощайте друзья"),
            _msg(11, "user3", "Другой", "пока"),
        ]},
    ]},
}


def _page(name, messages):
    return ("<!DOCTYPE html><html><head><meta charset=\"utf-8\"/></head><body>"
            "<div class=\"page_wrap\"><div class=\"page_header\"><div class=\"content\">"
            f"<div class=\"text bold\">{name}</div></div></div>"
            "<div class=\"page_body chat_page\"><div class=\"history\">"
            + "".join(messages) + "</div></div></div></body></html>")


def _html_msg(i, text, sender=None, joined=False, forwarded=None, date="14.11.2023 22:13:20 UTC+05:00"):
    cls = "message default clearfix" + (" joined" if joined else "")
    parts = [f"<div class=\"{cls}\" id=\"message{i}\">",
             "<div class=\"pull_left userpic_wrap\"><div class=\"userpic\"><div class=\"initials\">А</div></div></div>",
             "<div class=\"body\">",
             f"<div class=\"pull_right date details\" title=\"{date}\">22:13</div>"]
    if sender:
        parts.append(f"<div class=\"from_name\">{sender} </div>")
    if forwarded:
        parts.append(f"<div class=\"forwarded body\"><div class=\"from_name\">{forwarded}</div>"
                     f"<div class=\"text\">{text}</div></div>")
    else:
        parts.append(f"<div class=\"text\">{text}</div>")
    parts.append("</div></div>")
    return "".join(parts)


SERVICE = ("<div class=\"message service\" id=\"message-1\">"
           "<div class=\"body details\">14 ноября 2023</div></div>")


@pytest.fixture
def html_export(tmp_path):
    folder = tmp_path / "ChatExport_2023-11-14"
    folder.mkdir()
    (folder / "messages.html").write_text(_page("Кабир", [
        SERVICE,
        _html_msg(10, "Ассалому алейкум<br>ака", sender="Абдукабир"),
        _html_msg(11, "Как дела &amp; здоровье?", joined=True),
        _html_msg(12, "Ваалейкум ассалом", sender="Кабир"),
        _html_msg(13, "чужой текст", sender="Абдукабир", forwarded="Канал новостей"),
        _html_msg(14, "Смотри <code>print(x)</code> <a href=\"https://t.me/x\">@x</a> хорошо",
                  sender="Абдукабир"),
    ]), encoding="utf-8")
    (folder / "messages2.html").write_text(_page("Кабир", [
        _html_msg(15, "продолжение разговора", joined=True),
        _html_msg(16, "бот ответил", sender="Абдукабир via @gif"),
    ]), encoding="utf-8")
    return folder


# ---- JSON --------------------------------------------------------------------


def test_json_text_drops_links_and_code():
    assert json_text("просто") == "просто"
    value = ["a ", {"type": "link", "text": "x.com"}, " b ", {"type": "italic", "text": "c"},
             {"type": "code", "text": "z=1"}, {"type": "mention_name", "text": "Имя"}]
    assert json_text(value) == "a \n b c\n\n"
    assert json_text(None) == ""


def test_read_single_chat_json(tmp_path):
    path = tmp_path / "result.json"
    path.write_text(json.dumps(CHAT, ensure_ascii=False), encoding="utf-8")
    export = read_json(path)
    assert export.own is None                   # one chat: Telegram does not say who is "me"
    assert export.candidates()[0] == ("user1", "Абдукабир", 3)
    assert [m.id for m in export.messages if m.sender == "user1"] == [1, 3, 8]
    assert {m.chat for m in export.messages} == {"json:42"}
    assert export.messages[0].ts == T0 + 1


def test_read_full_json_knows_the_user(tmp_path):
    path = tmp_path / "result.json"
    path.write_text(json.dumps(FULL, ensure_ascii=False), encoding="utf-8")
    export = read_json(path)
    assert export.own == "user1"
    assert export.chats == {"json:42", "json:7", "json:9"}
    own = [m.text for m in export.messages if m.sender == "user1"]
    assert "заметка себе" in own and "прощайте друзья" in own


def test_broken_json_gives_a_clear_error(tmp_path):
    path = tmp_path / "result.json"
    path.write_text("{oops", encoding="utf-8")
    with pytest.raises(ExportError, match="повреждён"):
        read_json(path)


# ---- HTML --------------------------------------------------------------------


def test_html_date():
    assert html_ts("14.11.2023 22:13:20 UTC+05:00") == pytest.approx(1699982000.0)
    assert html_ts("") == 0.0


def test_read_html_export(html_export):
    kind, files = find_export_files(html_export)
    assert kind == "html" and [f.name for f in files] == ["messages.html", "messages2.html"]
    export = read_html(files)
    mine = [(m.id, m.text) for m in export.messages if m.sender == "name:Абдукабир"]
    assert mine == [
        (10, "Ассалому алейкум\nака"),
        (11, "Как дела & здоровье?"),            # joined: same sender as before
        (14, "Смотри \n\n @x хорошо"),
        (15, "продолжение разговора"),            # joined across pages
    ]
    assert export.candidates()[0] == ("name:Абдукабир", "Абдукабир", 4)
    assert export.chats == {"html:Кабир"}


def test_find_files(tmp_path, html_export):
    assert find_export_files(html_export / "messages2.html")[0] == "html"
    (tmp_path / "result.json").write_text("{}", encoding="utf-8")
    assert find_export_files(tmp_path) == ("json", [tmp_path / "result.json"])
    with pytest.raises(ExportError):
        find_export_files(tmp_path / "nope")
    other = tmp_path / "photo.jpg"
    other.write_bytes(b"x")
    with pytest.raises(ExportError, match="не файл экспорта"):
        find_export_files(other)
    empty = tmp_path / "empty"
    empty.mkdir()
    with pytest.raises(ExportError, match="нет экспорта"):
        find_export_files(empty)


def test_scan_rejects_export_without_text(tmp_path):
    path = tmp_path / "result.json"
    path.write_text(json.dumps({"name": "x", "id": 1, "messages": []}), encoding="utf-8")
    with pytest.raises(ExportError, match="ни одного"):
        scan(path)


# ---- learning ----------------------------------------------------------------


def _export(tmp_path, data=CHAT):
    path = tmp_path / "result.json"
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return scan(path)


def test_learns_only_own_words(tmp_path, lexicon):
    export = _export(tmp_path)
    marks = {}
    result = learn_messages(lexicon, export, {"user1"}, marks)
    assert result.messages == 3 and not result.cancelled
    assert "алейкум" in lexicon and "хорошо" in lexicon
    assert "ваалейкум" not in lexicon              # the other person's word
    assert "переслано" not in lexicon and "бота" not in lexicon
    assert "google" not in lexicon
    assert lexicon.get("алейкум").freq == 2
    assert marks == {"json:42": 8}
    # bigrams are learned too: after "Ассалому" comes "алейкум"
    assert texts(lexicon.suggest("а", prev="ассалому"))[0] == "алейкум"


def test_reimport_does_not_count_twice(tmp_path, lexicon):
    export = _export(tmp_path)
    marks = {}
    learn_messages(lexicon, export, {"user1"}, marks)
    again = learn_messages(lexicon, export, {"user1"}, marks)
    assert again.messages == 0 and again.skipped == 3
    assert lexicon.get("алейкум").freq == 2


def test_old_messages_rank_below_recent_typing(tmp_path, lexicon, clock):
    export = _export(tmp_path)                    # messages from 2023
    learn_messages(lexicon, export, {"user1"}, {})
    lexicon.learn("алло")                         # typed now, once
    assert texts(lexicon.suggest("ал"))[0] == "алло"
    assert lexicon.get("алейкум").last_used == T0 + 8


def test_cancel_keeps_marks_consistent(tmp_path, lexicon):
    many = dict(CHAT, messages=[_msg(i, "user1", "А", f"слово{'а' * (i % 5)} тест")
                                for i in range(1, 301)])
    export = _export(tmp_path, many)
    marks = {}
    result = learn_messages(lexicon, export, {"user1"}, marks, cancelled=lambda: True)
    assert result.cancelled
    assert marks["json:42"] == result.messages     # resumes right after the last one
    rest = learn_messages(lexicon, export, {"user1"}, marks)
    assert result.messages + rest.messages == 300
    assert lexicon.get("тест").freq == 300


def test_progress_is_reported(tmp_path, lexicon):
    export = _export(tmp_path)
    seen = []
    learn_messages(lexicon, export, {"user1"}, {}, progress=lambda n, total: seen.append((n, total)))
    assert seen[-1] == (3, 3)


def test_import_is_saved(tmp_path, lexicon, store):
    learn_messages(lexicon, _export(tmp_path), {"user1"}, {})
    assert store.counts()[0] == len(lexicon)
