import os
import sys

from app import window_watch
from app.window_watch import WindowWatch, process_name, window_ids, window_rect


def test_process_name_of_this_process():
    assert process_name(os.getpid()) == os.path.basename(sys.executable).lower()


def test_process_name_of_missing_process():
    assert process_name(0) == ""
    assert process_name(0x7FFFFFF0) == ""


def test_missing_window():
    assert window_ids(None) == (0, 0)
    assert window_ids(0x7FFFFFF0) == (0, 0)
    assert window_rect(0) is None
    assert WindowWatch().is_target(None) is False
    assert WindowWatch().is_target(0x7FFFFFF0) is False


def test_foreground_check_returns_a_pair():
    hwnd, is_telegram = WindowWatch().check()
    assert isinstance(is_telegram, bool)


def test_target_matching_is_case_insensitive_and_cached(monkeypatch):
    names = {11: "telegram.exe", 22: "chrome.exe"}
    pids = {0x100: 11, 0x200: 22}
    lookups = []

    def fake_name(pid):
        lookups.append(pid)
        return names.get(pid, "")

    monkeypatch.setattr(window_watch, "window_ids", lambda hwnd: (1, pids.get(hwnd, 0)))
    monkeypatch.setattr(window_watch, "process_name", fake_name)

    watch = WindowWatch(targets=["Telegram.EXE"])
    assert watch.is_target(0x100) is True
    assert watch.is_target(0x100) is True
    assert lookups == [11]                    # the second answer came from the cache
    assert watch.is_target(0x200) is False
    assert watch.is_target(0x100) is True
    assert lookups == [11, 22, 11]


def test_telegram_forks_are_targets(monkeypatch):
    names = {11: "telegram.exe", 22: "ayugram.exe", 33: "kotatogram.exe", 44: "64gram.exe",
             55: "notepad.exe"}
    monkeypatch.setattr(window_watch, "window_ids", lambda hwnd: (1, hwnd))
    monkeypatch.setattr(window_watch, "process_name", lambda pid: names.get(pid, ""))
    watch = WindowWatch()
    assert [watch.is_target(pid) for pid in (11, 22, 33, 44, 55)] == [True] * 4 + [False]


def test_reused_window_handle_is_rechecked(monkeypatch):
    pids = {0x100: 11}
    monkeypatch.setattr(window_watch, "window_ids", lambda hwnd: (1, pids.get(hwnd, 0)))
    monkeypatch.setattr(window_watch, "process_name",
                        lambda pid: "telegram.exe" if pid == 11 else "other.exe")
    watch = WindowWatch()
    assert watch.is_target(0x100) is True
    pids[0x100] = 33                          # same handle value, another process now
    assert watch.is_target(0x100) is False


def _fake_windows(monkeypatch, names, titles):
    monkeypatch.setattr(window_watch, "window_ids", lambda hwnd: (1, hwnd))
    monkeypatch.setattr(window_watch, "process_name", lambda pid: names.get(pid, ""))
    monkeypatch.setattr(window_watch, "window_title", lambda hwnd: titles.get(hwnd, ""))


def test_browser_counts_only_with_telegram_in_its_title(monkeypatch):
    titles = {1: "Telegram Web - Google Chrome", 2: "(3) Telegram Web — Mozilla Firefox"}
    _fake_windows(monkeypatch, {1: "chrome.exe", 2: "firefox.exe", 3: "telegram.exe"}, titles)
    watch = WindowWatch()
    assert watch.is_target(1) and watch.is_target(2)
    assert watch.is_browser(1) and not watch.is_browser(3)
    titles[1] = "YouTube - Google Chrome"          # another tab, same window
    assert watch.is_target(1) is False
    assert watch.kind(1) == "browser" and watch.kind(3) == "app" and watch.kind(4) == ""


def test_telegram_web_can_be_turned_off(monkeypatch):
    _fake_windows(monkeypatch, {1: "msedge.exe", 3: "telegram.exe"},
                  {1: "Telegram Web - Microsoft Edge"})
    watch = WindowWatch(web=False)
    assert watch.is_target(1) is False and watch.is_browser(1) is False
    assert watch.is_target(3) is True
    watch.web = True
    assert watch.is_target(1) is True


def test_window_title_of_missing_window():
    assert window_watch.window_title(0) == ""
    assert window_watch.window_title(0x7FFFFFF0) == ""
    assert window_watch.is_web_title("Telegram Web") and not window_watch.is_web_title("Почта")
