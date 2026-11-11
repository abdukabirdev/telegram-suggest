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


def test_reused_window_handle_is_rechecked(monkeypatch):
    pids = {0x100: 11}
    monkeypatch.setattr(window_watch, "window_ids", lambda hwnd: (1, pids.get(hwnd, 0)))
    monkeypatch.setattr(window_watch, "process_name",
                        lambda pid: "telegram.exe" if pid == 11 else "other.exe")
    watch = WindowWatch()
    assert watch.is_target(0x100) is True
    pids[0x100] = 33                          # same handle value, another process now
    assert watch.is_target(0x100) is False
