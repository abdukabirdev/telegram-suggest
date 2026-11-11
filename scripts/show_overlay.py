"""Show the suggestion window with test words: check its look and position.

Run:  .venv\\Scripts\\python.exe scripts\\show_overlay.py
Nothing is read from the keyboard and nothing is typed anywhere.
"""

from __future__ import annotations

import ctypes
import signal
import sys
import time
from ctypes import wintypes
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtCore import QObject, QTimer, Signal  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from app import winapi as w  # noqa: E402
from app.overlay import Overlay  # noqa: E402
from app.positioning import (Anchor, Locator, WindowStrategy,  # noqa: E402
                             monitor_work_area, place)
from app.window_watch import WindowWatch, window_rect  # noqa: E402

SAMPLES = [
    ["Абдукабир", "алейкум", "ака", "ассалому"],
    ["Ўзбекистон", "ўзбек", "қўнғироқ"],
    ["рахмат"],
    ["яхшимисиз", "яхши"],
]
SECONDS = 60
SOURCES = {
    "caret": "каретка (точное положение курсора ввода)",
    "uia-focus": "поле ввода, в котором сейчас курсор",
    "uia-search": "поле сообщения (найдено в окне Telegram)",
    "window": "запасной вариант: по размерам окна Telegram",
}


def find_telegram() -> int | None:
    watch = WindowWatch()
    best, best_area = None, 0

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def callback(hwnd, _):
        nonlocal best, best_area
        if w.user32.IsWindowVisible(hwnd) and not w.IsIconic(hwnd) and watch.is_target(hwnd):
            rect = window_rect(hwnd)
            if rect:
                area = (rect[2] - rect[0]) * (rect[3] - rect[1])
                if area > best_area:
                    best, best_area = hwnd, area
        return True

    w.user32.EnumWindows(callback, 0)
    return best


class Bridge(QObject):
    anchor = Signal(object, object)


def main() -> int:
    global SECONDS
    if len(sys.argv) > 1 and sys.argv[1].isdigit():
        SECONDS = int(sys.argv[1])
    app = QApplication(sys.argv[:1])
    overlay = Overlay("system")
    bridge = Bridge()
    locator = Locator(bridge.anchor.emit)
    fallback = WindowStrategy()
    state = {"sample": 0, "hwnd": None, "anchor": None, "printed": None}

    def say(text: str) -> None:
        print(time.strftime("[%H:%M:%S] ") + text, flush=True)

    def reposition() -> None:
        hwnd = state["hwnd"]
        anchor = state["anchor"] or (fallback.locate(hwnd) if hwnd else None)
        if anchor is None:
            screen = app.primaryScreen().geometry()
            ratio = app.primaryScreen().devicePixelRatio()
            x = int(screen.width() * ratio * 0.5) - 150
            y = int(screen.height() * ratio * 0.75)
            anchor = Anchor(x, y, x + 300, y + 28, "экран")
        work = monitor_work_area(anchor.left, anchor.top)
        x, y = place(anchor, overlay.physical_size(), work)
        overlay.show_at(x, y)
        line = (f"позиция окна: ({x}, {y}); способ: {SOURCES.get(anchor.source, anchor.source)}; "
                f"поле: ({anchor.left}, {anchor.top})-({anchor.right}, {anchor.bottom})")
        if line != state["printed"]:
            state["printed"] = line
            say(line)

    def on_anchor(hwnd, anchor) -> None:
        if hwnd == state["hwnd"]:
            state["anchor"] = anchor
            reposition()

    def tick() -> None:
        hwnd = find_telegram()
        if hwnd != state["hwnd"]:
            state["hwnd"], state["anchor"] = hwnd, None
            say("окно Telegram найдено" if hwnd else
                "Telegram не найден (запущен? не свёрнут?). Показываю окно внизу экрана.")
        if hwnd:
            locator.request(hwnd)
        reposition()

    def on_click(index: int) -> None:
        say(f"нажата подсказка {index + 1}: «{overlay.items()[index]}». Меняю набор слов.")
        state["sample"] = (state["sample"] + 1) % len(SAMPLES)
        overlay.set_items(SAMPLES[state["sample"]])
        reposition()

    bridge.anchor.connect(on_anchor)
    overlay.clicked.connect(on_click)
    overlay.set_items(SAMPLES[0])
    locator.start()

    print("Проверка окна подсказок.")
    print("1. Откройте Telegram и любой чат, чтобы было видно поле сообщения.")
    print("2. Окно с тестовыми словами должно появиться прямо над полем сообщения, слева.")
    print("3. Щёлкните мышью по любому слову: курсор в Telegram должен остаться на месте.")
    print(f"Окно закроется само через {SECONDS} секунд. Раньше: Ctrl+C.\n")

    timer = QTimer()
    timer.timeout.connect(tick)
    timer.start(700)
    tick()
    QTimer.singleShot(SECONDS * 1000, app.quit)
    signal.signal(signal.SIGINT, lambda *_: app.quit())
    code = app.exec()
    overlay.hide()
    locator.stop()
    locator.join(2.0)
    return code


if __name__ == "__main__":
    sys.exit(main())
