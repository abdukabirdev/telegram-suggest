"""Hook decisions (pure logic) and one live check with a harmless key."""

import ctypes
import time

import pytest

from app import winapi as w
from app.hook import KeyboardHook

TG = 0x100          # pretend Telegram window
OTHER = 0x200
VK_A = 0x41
VK_UNASSIGNED = 0xE8    # produces nothing in any program


class Rig:
    def __init__(self):
        self.events = []
        self.fg = TG
        self.down = set()
        self.hook = KeyboardHook(
            sink=self.events.append,
            is_target=lambda hwnd: hwnd == TG,
            foreground=lambda: self.fg,
            key_down=lambda vk: vk in self.down,
        )

    def press(self, vk, scan=0):
        return self.hook.handle(vk, scan, True)

    def release(self, vk, scan=0):
        return self.hook.handle(vk, scan, False)

    def keys(self):
        return [e for e in self.events if e[0] == "key"]


@pytest.fixture
def rig():
    return Rig()


def test_key_in_telegram_is_reported_and_passed_on(rig):
    assert rig.press(VK_A, 30) is False
    assert rig.events == [
        ("focus", True, TG),
        ("key", VK_A, 30, False, False, False, False, False, None, TG),
    ]
    assert rig.release(VK_A) is False
    assert len(rig.events) == 2            # key-ups are not reported


def test_nothing_is_reported_outside_telegram(rig):
    rig.fg = OTHER
    for vk in (VK_A, w.VK_TAB, w.VK_RETURN, 0x31):
        assert rig.press(vk) is False
        assert rig.release(vk) is False
    assert rig.events == []


def test_focus_change_is_reported_once(rig):
    rig.press(VK_A)
    rig.fg = OTHER
    rig.press(VK_A)
    rig.press(VK_A)
    rig.fg = TG
    rig.press(VK_A)
    assert [e for e in rig.events if e[0] == "focus"] == [
        ("focus", True, TG), ("focus", False, OTHER), ("focus", True, TG),
    ]
    assert len(rig.keys()) == 2


def test_modifier_state_is_attached(rig):
    rig.down = {w.VK_SHIFT}
    rig.press(VK_A)
    assert rig.keys()[-1][3:7] == (True, False, False, False)
    rig.down = {w.VK_CONTROL, w.VK_MENU}
    rig.press(VK_A)
    assert rig.keys()[-1][3:7] == (False, True, True, False)
    rig.down = {w.VK_RWIN}
    rig.press(VK_A)
    assert rig.keys()[-1][3:7] == (False, False, False, True)


def test_modifier_keys_themselves_are_not_reported(rig):
    for vk in (w.VK_LSHIFT, w.VK_RCONTROL, w.VK_LMENU, w.VK_LWIN):
        assert rig.press(vk) is False
        assert rig.release(vk) is False
    assert rig.events == []


def test_tab_passes_through_when_nothing_is_shown(rig):
    assert rig.press(w.VK_TAB) is False
    assert rig.keys()[-1][8] is None


def test_tab_is_swallowed_when_suggestions_are_shown(rig):
    rig.hook.visible_count = 3
    assert rig.press(w.VK_TAB) is True
    assert rig.keys()[-1][8] == ("accept", 0)
    assert rig.press(w.VK_TAB) is True        # auto-repeat while held
    assert len(rig.keys()) == 1
    assert rig.release(w.VK_TAB) is True      # its key-up too
    assert rig.release(w.VK_TAB) is False


def test_escape_dismisses_when_shown(rig):
    rig.hook.visible_count = 1
    assert rig.press(w.VK_ESCAPE) is True
    assert rig.keys()[-1][8] == ("dismiss",)
    rig.release(w.VK_ESCAPE)
    rig.hook.visible_count = 0
    assert rig.press(w.VK_ESCAPE) is False


def test_ctrl_digits_pick_shown_suggestions_only(rig):
    rig.hook.visible_count = 2
    rig.down = {w.VK_CONTROL}
    assert rig.press(0x31) is True
    assert rig.keys()[-1][8] == ("accept", 0)
    rig.release(0x31)
    assert rig.press(0x32) is True
    assert rig.keys()[-1][8] == ("accept", 1)
    rig.release(0x32)
    assert rig.press(0x33) is False           # only two are shown: Telegram gets Ctrl+3
    assert rig.keys()[-1][8] is None


def test_digit_without_ctrl_is_text(rig):
    rig.hook.visible_count = 3
    assert rig.press(0x31) is False
    assert rig.keys()[-1][8] is None


def test_digit_repeat_is_swallowed_even_after_ctrl_was_released_by_us(rig):
    rig.hook.visible_count = 3
    rig.down = {w.VK_CONTROL}
    assert rig.press(0x31) is True
    rig.down = set()                          # the inserter released Ctrl
    rig.hook.visible_count = 0                # and the suggestions are gone
    assert rig.press(0x31) is True            # auto-repeat must not type "1"
    assert rig.release(0x31) is True
    assert rig.press(0x31) is False


@pytest.mark.parametrize("held", [w.VK_SHIFT, w.VK_MENU, w.VK_LWIN])
def test_hotkeys_need_no_other_modifiers(rig, held):
    rig.hook.visible_count = 3
    rig.down = {held}
    assert rig.press(w.VK_TAB) is False       # Shift+Tab, Alt+Tab, Win+Tab stay as they are
    assert rig.keys()[-1][8] is None


def test_paused_hook_reports_nothing(rig):
    rig.hook.paused = True
    rig.hook.visible_count = 3
    assert rig.press(VK_A) is False
    assert rig.press(w.VK_TAB) is False
    assert rig.events == []


def test_caps_lock_is_tracked_everywhere(rig):
    rig.fg = OTHER
    rig.press(w.VK_CAPITAL)
    rig.press(w.VK_CAPITAL)                   # auto-repeat does not toggle again
    rig.release(w.VK_CAPITAL)
    rig.fg = TG
    rig.press(VK_A)
    assert rig.keys()[-1][7] is True
    rig.press(w.VK_CAPITAL)
    rig.release(w.VK_CAPITAL)
    rig.press(VK_A)
    assert rig.keys()[-1][7] is False
    assert all(e[1] != w.VK_CAPITAL for e in rig.keys())


# ---- live: a real hook and a real (harmless) injected key --------------------

def _inject(vk, tagged):
    events = (w.INPUT * 2)()
    for i, flags in enumerate((0, w.KEYEVENTF_KEYUP)):
        events[i].type = w.INPUT_KEYBOARD
        events[i].ki = w.KEYBDINPUT(vk, 0, flags, 0, w.INJECT_TAG if tagged else 0)
    assert w.SendInput(2, events, ctypes.sizeof(w.INPUT)) == 2


def _wait_for(predicate, timeout=2.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.01)
    return predicate()


def test_live_hook_sees_foreign_keys_and_skips_our_own():
    seen = []

    def sink(event):
        # keep only the test key: anything else typed meanwhile is not ours to look at
        if event[0] == "key" and event[1] == VK_UNASSIGNED:
            seen.append(event)

    hook = KeyboardHook(sink=sink, is_target=lambda hwnd: True)
    hook.start()
    try:
        assert hook.installed.wait(3.0)
        before = hook.last_callback

        _inject(VK_UNASSIGNED, tagged=True)       # our own event: must be skipped
        assert _wait_for(lambda: hook.last_callback > before)
        time.sleep(0.05)
        assert seen == []

        _inject(VK_UNASSIGNED, tagged=False)      # somebody else's event: reported
        assert _wait_for(lambda: len(seen) == 1)

        hook.reinstall()                          # still works after re-installing
        time.sleep(0.1)
        _inject(VK_UNASSIGNED, tagged=False)
        assert _wait_for(lambda: len(seen) == 2)
    finally:
        hook.stop()
        hook.join(3.0)
    assert not hook.is_alive()
