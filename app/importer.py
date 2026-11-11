"""Learning from a Telegram Desktop export.

Telegram Desktop can save the history of one chat (chat menu > "Export chat
history") or of all chats (Settings > Advanced > "Export Telegram data"),
as HTML (the default) or as JSON. Both formats are read here.

Only the user's own messages are learned: the point is their vocabulary, not
the words of the people they talk to. Forwarded messages and messages sent
through bots are skipped as well. As with typing, only separate words and
pairs of words reach the dictionary; message texts are not stored.

A re-import of the same export does not count the same messages twice: for
every chat the id of the last imported message is remembered.
"""

from __future__ import annotations

import json
import re
import time
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from html.parser import HTMLParser
from pathlib import Path
from typing import Callable, Iterable, Optional

from .textutil import tokenize


class ExportError(Exception):
    """A problem with the chosen files; the message is for the user (Russian)."""


@dataclass
class Message:
    chat: str           # chat key, also the key of the import mark
    id: int
    sender: str         # sender key
    ts: float           # unix time
    text: str


@dataclass
class ExportScan:
    messages: list[Message] = field(default_factory=list)
    senders: Counter = field(default_factory=Counter)      # key -> messages
    names: dict[str, str] = field(default_factory=dict)    # key -> display name
    own: Optional[str] = None       # the user's own key, when the export says it
    chats: set[str] = field(default_factory=set)
    kind: str = ""                  # "json" | "html"

    def candidates(self) -> list[tuple[str, str, int]]:
        """(key, name, number of messages): who could be "me", most active first."""
        return [(key, self.names.get(key, key), n) for key, n in self.senders.most_common()]


@dataclass
class ImportResult:
    messages: int = 0           # own messages learned now
    words: int = 0              # word uses learned
    skipped: int = 0            # own messages imported earlier, not counted again
    cancelled: bool = False


# ---- finding the files -------------------------------------------------------

_HTML_NAME = re.compile(r"messages(\d*)\.html$", re.IGNORECASE)


def _html_order(path: Path) -> tuple:
    m = _HTML_NAME.search(path.name)
    return (str(path.parent).lower(), int(m.group(1) or 1) if m else 0)


def find_export_files(path: Path) -> tuple[str, list[Path]]:
    """("json", [result.json]) or ("html", [messages.html, messages2.html, ...])."""
    path = Path(path)
    if not path.exists():
        raise ExportError("Файл или папка не найдены.")
    if path.is_file():
        if path.suffix.lower() == ".json":
            return "json", [path]
        if _HTML_NAME.search(path.name):
            siblings = [p for p in path.parent.iterdir() if _HTML_NAME.search(p.name)]
            return "html", sorted(siblings, key=_html_order)
        raise ExportError(
            "Это не файл экспорта Telegram. Выберите файл result.json или messages.html "
            "из папки, которую сохранил Telegram."
        )
    direct = path / "result.json"
    if direct.is_file():
        return "json", [direct]
    pages = [p for p in path.rglob("messages*.html") if _HTML_NAME.search(p.name)]
    if pages:
        return "html", sorted(pages, key=_html_order)
    nested = sorted(path.rglob("result.json"))
    if nested:
        return "json", [nested[0]]
    raise ExportError(
        "В этой папке нет экспорта Telegram (файлов result.json или messages.html). "
        "Выберите папку, которую создал Telegram при экспорте, обычно её имя "
        "начинается с «ChatExport» или «DataExport»."
    )


def scan(path: Path) -> ExportScan:
    kind, files = find_export_files(path)
    result = read_json(files[0]) if kind == "json" else read_html(files)
    if not result.messages:
        raise ExportError("В экспорте не найдено ни одного текстового сообщения.")
    return result


# ---- JSON --------------------------------------------------------------------

# Parts of a message that are not the user's words
_SKIP_ENTITIES = frozenset({
    "link", "email", "phone", "mention", "mention_name", "hashtag", "cashtag",
    "bot_command", "code", "pre", "bank_card",
})


def json_text(value) -> str:
    """Plain text of a JSON message; links, mentions, code become line breaks.

    A line break ends a word chain, so no word pair is formed across them.
    """
    if isinstance(value, str):
        return value
    if not isinstance(value, list):
        return ""
    parts = []
    for part in value:
        if isinstance(part, str):
            parts.append(part)
        elif isinstance(part, dict):
            if part.get("type") in _SKIP_ENTITIES:
                parts.append("\n")
            else:
                parts.append(str(part.get("text", "")))
    return "".join(parts)


def _json_ts(message: dict) -> float:
    raw = message.get("date_unixtime")
    if raw is not None:
        try:
            return float(raw)
        except (TypeError, ValueError):
            pass
    try:
        return datetime.fromisoformat(str(message.get("date"))).timestamp()
    except (TypeError, ValueError):
        return 0.0


def _json_chat(chat: dict, out: ExportScan, saved_messages_owner: Optional[str]) -> None:
    key = "json:" + str(chat.get("id", chat.get("name", "?")))
    saved = chat.get("type") == "saved_messages"
    for message in chat.get("messages") or ():
        if not isinstance(message, dict) or message.get("type") != "message":
            continue
        if message.get("forwarded_from") or message.get("via_bot") or message.get("saved_from"):
            continue
        text = json_text(message.get("text"))
        if not text.strip():
            continue
        sender = str(message.get("from_id") or "")
        if not sender and saved and saved_messages_owner:
            sender = saved_messages_owner
        if not sender:
            continue
        try:
            msg_id = int(message.get("id"))
        except (TypeError, ValueError):
            continue
        out.messages.append(Message(key, msg_id, sender, _json_ts(message), text))
        out.senders[sender] += 1
        name = message.get("from")
        if name and sender not in out.names:
            out.names[sender] = str(name)
        out.chats.add(key)


def read_json(path: Path) -> ExportScan:
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, UnicodeError, ValueError):
        raise ExportError("Не удалось прочитать файл экспорта: он повреждён или это не JSON.")
    if not isinstance(data, dict):
        raise ExportError("Это не файл экспорта Telegram.")
    out = ExportScan(kind="json")
    personal = data.get("personal_information")
    if isinstance(personal, dict) and personal.get("user_id") is not None:
        out.own = f"user{personal['user_id']}"
        name = " ".join(str(personal.get(k) or "") for k in ("first_name", "last_name")).strip()
        if name:
            out.names[out.own] = name
    if "messages" in data:                      # one chat
        _json_chat(data, out, out.own)
    else:                                       # everything
        for section in ("chats", "left_chats"):
            block = data.get(section)
            for chat in (block.get("list") if isinstance(block, dict) else None) or ():
                if isinstance(chat, dict):
                    _json_chat(chat, out, out.own)
    if out.own is not None and out.own not in out.senders:
        out.own = None
    return out


# ---- HTML --------------------------------------------------------------------

_DATE_RE = re.compile(
    r"(\d{1,2})\.(\d{1,2})\.(\d{4}) (\d{1,2}):(\d{2}):(\d{2})(?: UTC([+-])(\d{1,2}):(\d{2}))?"
)


def html_ts(title: str) -> float:
    m = _DATE_RE.search(title or "")
    if m is None:
        return 0.0
    day, month, year, hour, minute, second = (int(g) for g in m.groups()[:6])
    if m.group(7):
        shift = timedelta(hours=int(m.group(8)), minutes=int(m.group(9)))
        tz = timezone(shift if m.group(7) == "+" else -shift)
        return datetime(year, month, day, hour, minute, second, tzinfo=tz).timestamp()
    return datetime(year, month, day, hour, minute, second).timestamp()


class _HtmlExportParser(HTMLParser):
    """Collects (id, sender name, title of date, text) from one messages*.html."""

    _VOID = frozenset({"br", "img", "hr", "input", "meta", "link", "source", "wbr"})

    def __init__(self, last_sender: str) -> None:
        super().__init__(convert_charrefs=True)
        self.chat_name = ""
        self.found: list[tuple[int, str, str, str]] = []
        self.last_sender = last_sender
        self._stack: list[tuple[str, frozenset]] = []
        self._msg_depth = -1
        self._msg: Optional[dict] = None
        self._capture: Optional[str] = None     # "text" | "from" | "chat"
        self._capture_depth = -1
        self._skip_depth = -1                   # inside <code>/<pre>
        self._fwd_depth = -1                    # inside a forwarded block

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        classes = frozenset((attrs.get("class") or "").split())
        if tag in self._VOID:
            if tag == "br" and self._capture == "text" and self._skip_depth < 0:
                self._msg["text"].append("\n")
            return
        depth = len(self._stack)
        self._stack.append((tag, classes))
        if tag == "div" and "message" in classes and (attrs.get("id") or "").startswith("message"):
            self._finish()
            try:
                msg_id = int(attrs["id"][len("message"):])
            except ValueError:
                msg_id = -1
            self._msg = {
                "id": msg_id, "service": "service" in classes, "joined": "joined" in classes,
                "from": [], "text": [], "title": "", "forwarded": False,
            }
            self._msg_depth = depth
            return
        if tag == "div" and "page_header" in classes and self._msg is None:
            self._capture, self._capture_depth = "chat", depth
            return
        if self._msg is None:
            return
        if "forwarded" in classes:
            self._msg["forwarded"] = True
            if self._fwd_depth < 0:
                self._fwd_depth = depth
        if self._fwd_depth >= 0:
            return
        if tag == "div" and "date" in classes and attrs.get("title"):
            self._msg["title"] = attrs["title"]
        elif tag == "div" and "from_name" in classes and self._capture is None:
            self._capture, self._capture_depth = "from", depth
        elif tag == "div" and "text" in classes and self._capture is None:
            self._capture, self._capture_depth = "text", depth
        elif tag in ("code", "pre") and self._capture == "text" and self._skip_depth < 0:
            self._skip_depth = depth
            self._msg["text"].append("\n")

    def handle_endtag(self, tag):
        if tag in self._VOID:
            return
        # tolerate unclosed tags: pop up to the matching one
        for i in range(len(self._stack) - 1, -1, -1):
            if self._stack[i][0] == tag:
                depth = i
                break
        else:
            return
        del self._stack[depth:]
        if self._skip_depth >= depth:
            self._skip_depth = -1
            if self._msg is not None:
                self._msg["text"].append("\n")
        if self._capture_depth >= depth:
            self._capture, self._capture_depth = None, -1
        if self._fwd_depth >= depth:
            self._fwd_depth = -1
        if self._msg_depth >= depth:
            self._finish()

    def handle_data(self, data):
        if self._capture == "chat":
            self.chat_name += data
        elif self._capture == "from" and self._msg is not None:
            self._msg["from"].append(data)
        elif self._capture == "text" and self._skip_depth < 0 and self._msg is not None:
            self._msg["text"].append(data)

    def _finish(self) -> None:
        msg, self._msg = self._msg, None
        self._msg_depth = -1
        self._capture, self._capture_depth = None, -1
        self._skip_depth = self._fwd_depth = -1
        if msg is None or msg["service"]:
            return
        sender = " ".join("".join(msg["from"]).split())
        if sender:
            self.last_sender = sender
        elif msg["joined"]:
            sender = self.last_sender
        if " via @" in sender or msg["forwarded"] or not sender or msg["id"] < 0:
            return
        text = "".join(msg["text"])
        if text.strip():
            self.found.append((msg["id"], sender, msg["title"], text))

    def close(self):
        super().close()
        self._finish()


def read_html(paths: Iterable[Path]) -> ExportScan:
    out = ExportScan(kind="html")
    last_sender = ""
    last_folder = None
    read_any = False
    for path in paths:
        if path.parent != last_folder:
            last_folder, last_sender = path.parent, ""
        try:
            source = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        read_any = True
        parser = _HtmlExportParser(last_sender)
        parser.feed(source)
        parser.close()
        last_sender = parser.last_sender
        chat = "html:" + (" ".join(parser.chat_name.split()) or path.parent.name)
        for msg_id, sender, title, text in parser.found:
            key = "name:" + sender
            out.messages.append(Message(chat, msg_id, key, html_ts(title), text))
            out.senders[key] += 1
            out.names.setdefault(key, sender)
            out.chats.add(chat)
    if not read_any:
        raise ExportError("Не удалось открыть файлы экспорта.")
    return out


# ---- learning ----------------------------------------------------------------


def learn_messages(
    lexicon,
    export: ExportScan,
    own: Iterable[str],
    marks: dict,
    progress: Optional[Callable[[int, int], None]] = None,
    cancelled: Optional[Callable[[], bool]] = None,
    flush_every: int = 5000,
) -> ImportResult:
    """Teach the lexicon the user's own messages.

    ``marks`` (chat key -> last imported id) is updated in place as messages
    are learned, so an interrupted import resumes where it stopped.
    """
    own = set(own)
    result = ImportResult()
    todo = [m for m in export.messages if m.sender in own]
    todo.sort(key=lambda m: (m.chat, m.id))
    min_len = lexicon.settings.min_word_len
    total = len(todo)
    for n, message in enumerate(todo, 1):
        if cancelled is not None and n % 50 == 0 and cancelled():
            result.cancelled = True
            break
        if message.id <= int(marks.get(message.chat, -1)):
            result.skipped += 1
        else:
            ts = message.ts if message.ts > 0 else None
            for chain in tokenize(message.text, min_len):
                prev = None
                for word, sentence_start in chain:
                    key = lexicon.learn(word, prev, sentence_start, ts=ts)
                    if key is not None:
                        result.words += 1
                    prev = word if key is not None else None
            result.messages += 1
            marks[message.chat] = message.id
        if n % flush_every == 0:
            lexicon.flush()
        if n % 200 == 0:
            time.sleep(0)               # let the typing threads in
            if progress is not None:
                progress(n, total)
    lexicon.flush()
    if progress is not None:
        progress(total if not result.cancelled else n, total)
    return result
