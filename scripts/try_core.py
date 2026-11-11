"""Interactive console check of the core (stage 1). Nothing is saved to disk.

Run:  .venv\\Scripts\\python.exe scripts\\try_core.py
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.engine import Engine  # noqa: E402
from app.lexicon import Lexicon  # noqa: E402
from app.settings import Settings  # noqa: E402
from app.store import Store  # noqa: E402

DEMO = [
    "Салом алейкум Абдукабир ака",
    "Салом алейкум, яхшимисиз",
    "Ассалому алайкум Абдукабир ака, ишлар қалай",
    "рахмат катта, эртага қўнғироқ қиламан",
    "Ўзбекистон бўйича етказиб берамиз",
    "нархи 150000 сум, https://t.me/example га ёзинг",
]

HELP = """
Команды:
  любой текст        напечатать его «как в Telegram»: слова запоминаются
  ?абд               показать подсказки для начала слова
  ?Салом а           то же, но с учётом предыдущего слова
  :words [текст]     список слов в базе (можно с поиском)
  :del слово         удалить слово
  :translit          вкл/выкл подсказки из другой раскладки (кириллица <-> латиница)
  :help              эта справка
  :quit              выход
"""


def show(lexicon: Lexicon, query: str) -> None:
    parts = query.split()
    if not parts:
        return
    prefix = parts[-1]
    prev = parts[-2].strip(".,!?;:") if len(parts) > 1 else None
    t0 = time.perf_counter()
    result = lexicon.suggest(prefix, prev)
    ms = (time.perf_counter() - t0) * 1000
    if not result:
        print(f"  (нет подсказок)   [{ms:.3f} мс]")
        return
    for i, s in enumerate(result, 1):
        note = "  <- из другой раскладки" if s.cross else ""
        print(f"  {i}. {s.text:<24} вес {s.score:.2f}{note}")
    print(f"  [{ms:.3f} мс]")


def main() -> None:
    settings = Settings()
    lexicon = Lexicon(Store(":memory:"), settings)
    engine = Engine(lexicon, settings)
    for line in DEMO:
        engine.feed(line + "\n")
    print("Проверка ядра подсказок. База временная, в памяти, на диск ничего не пишется.")
    print(f"Загружено демо-фраз: {len(DEMO)}, слов в базе: {len(lexicon)}.")
    print(HELP)
    while True:
        try:
            line = input("> ").strip().lstrip("﻿")
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if not line:
            continue
        if line in (":quit", ":q", ":exit"):
            break
        if line == ":help":
            print(HELP)
        elif line == ":translit":
            settings.cross_script = not settings.cross_script
            print("  подсказки из другой раскладки:", "вкл" if settings.cross_script else "выкл")
        elif line.startswith(":words"):
            found = lexicon.search(line[6:].strip(), limit=40)
            for w in found:
                print(f"  {w.display:<24} использований: {w.freq}")
            print(f"  показано {len(found)} из {len(lexicon)}")
        elif line.startswith(":del "):
            ok = lexicon.delete(line[5:].strip())
            print("  удалено" if ok else "  такого слова нет")
        elif line.startswith("?"):
            show(lexicon, line[1:])
        else:
            before = len(lexicon)
            engine.feed(line + "\n")
            print(f"  запомнено, новых слов: {len(lexicon) - before}, всего: {len(lexicon)}")


if __name__ == "__main__":
    main()
