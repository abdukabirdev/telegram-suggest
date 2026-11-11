"""Key routing: hook events -> engine actions. No threads, no WinAPI."""

import pytest

from app import winapi as w
from app.engine import Engine
from app.worker import EngineWorker

HWND = 0x1234

# A tiny "keyboard": virtual key -> (plain, shifted)
KEYS = {
    0x41: ("а", "А"), 0x42: ("б", "Б"), 0x44: ("д", "Д"), 0x4B: ("к", "К"),
    0x4C: ("л", "Л"), 0x4D: ("м", "М"), 0x4F: ("о", "О"), 0x53: ("с", "С"),
    0x55: ("у", "У"), 0x49: ("и", "И"), 0x52: ("р", "Р"),
    0x4E: ("н", "Н"), 0x50: ("п", "П"), 0x59: ("ь", "Ь"),
    w.VK_SPACE: (" ", " "), 0xBC: (",", "<"), 0xBE: (".", ">"), 0x35: ("5", "%"),
}
VK = {plain: vk for vk, (plain, _) in KEYS.items()}
VK.update({shifted: vk for vk, (_, shifted) in KEYS.items() if shifted.isalpha()})


class FakeTranslator:
    last_layout = 0x04190419

    def layout_of_window(self, hwnd):
        return self.last_layout

    def translate(self, vk, scan, shift, caps, altgr, hkl):
        pair = KEYS.get(vk)
        if pair is None:
            return ""
        return pair[1] if (shift != caps) else pair[0]


class Rig:
    def __init__(self, lexicon, settings):
        self.inserted = []
        self.updates = []
        self.visible = 0
        self.word_starts = []
        self.diag = []
        self.foreground_ok = True
        self.insert_ok = True
        self.engine = Engine(lexicon, settings)
        self.worker = EngineWorker(
            self.engine, lexicon, FakeTranslator(),
            insert=self._insert,
            foreground_is_target=lambda: self.foreground_ok,
            set_visible=self._set_visible,
            on_update=self.updates.append,
            on_word_start=self.word_starts.append,
            on_diag=self.diag.append,
        )

    def _insert(self, backspaces, text):
        self.inserted.append((backspaces, text))
        return self.insert_ok

    def _set_visible(self, count):
        self.visible = count

    def key(self, vk, *, shift=False, ctrl=False, alt=False, win=False, caps=False,
            action=None, scan=0, hwnd=HWND):
        self.worker.process(("key", vk, scan, shift, ctrl, alt, win, caps, action, hwnd))

    def type(self, text):
        for ch in text:
            if ch == "\n":
                self.key(w.VK_RETURN)
            elif ch == "\b":
                self.key(w.VK_BACK)
            else:
                self.key(VK[ch], shift=ch.isupper())

    @property
    def shown(self):
        return self.updates[-1] if self.updates else []


@pytest.fixture
def rig(lexicon, settings):
    return Rig(lexicon, settings)


def test_typing_shows_suggestions_and_counts_them(rig):
    rig.type("салом\n")
    assert rig.shown == []
    rig.type("са")
    assert rig.shown == ["салом"]
    assert rig.visible == 1
    assert rig.engine.prefix == "са"


def test_tab_action_inserts_first_suggestion(rig):
    rig.type("салом\nса")
    rig.key(w.VK_TAB, action=("accept", 0))
    assert rig.inserted == [(2, "салом ")]
    assert rig.shown == []
    assert rig.visible == 0


def test_ctrl_digit_action_inserts_chosen_suggestion(rig):
    rig.type("салом салом сало\nса")
    assert rig.shown == ["салом", "сало"]
    rig.key(0x32, ctrl=True, action=("accept", 1))
    assert rig.inserted == [(2, "сало ")]


def test_mouse_click_accepts(rig):
    rig.type("салом\nса")
    rig.worker.process(("accept", 0))
    assert rig.inserted == [(2, "салом ")]


def test_accept_is_refused_when_telegram_lost_focus(rig, lexicon):
    rig.type("салом\nса")
    rig.foreground_ok = False
    rig.worker.process(("accept", 0))
    assert rig.inserted == []
    assert rig.engine.prefix == ""
    assert lexicon.get("салом").freq == 1


def test_failed_insert_is_not_learned(rig, lexicon):
    rig.type("салом\nса")
    rig.insert_ok = False
    rig.key(w.VK_TAB, action=("accept", 0))
    rig.type(" д")
    assert lexicon.get("салом").freq == 1


def test_forget_deletes_the_shown_word(rig, lexicon):
    rig.type("салом салом сало\nса")
    assert rig.shown == ["салом", "сало"]
    rig.worker.process(("forget", 1))
    assert "сало" not in lexicon
    assert rig.shown == ["салом"]
    assert rig.engine.prefix == "са"            # the word being typed stays
    rig.worker.process(("forget", 5))           # no such item: nothing happens
    assert "салом" in lexicon


def test_forget_is_ignored_while_paused(rig, lexicon):
    rig.type("салом\nса")
    rig.worker.process(("pause", True))
    rig.worker.process(("forget", 0))
    assert "салом" in lexicon


def test_refresh_recomputes_after_outside_deletion(rig, lexicon):
    rig.type("салом сало\nса")
    assert rig.shown == ["сало", "салом"] or rig.shown == ["салом", "сало"]
    lexicon.delete("сало")
    rig.worker.process(("refresh",))
    assert rig.shown == ["салом"]


def test_escape_action_dismisses(rig):
    rig.type("салом\nса")
    rig.key(w.VK_ESCAPE, action=("dismiss",))
    assert rig.shown == []
    rig.type("л")
    assert rig.shown == []
    assert rig.engine.prefix == "сал"


def test_shift_and_caps_give_capitals(rig, lexicon):
    rig.key(VK["с"], shift=True)
    assert rig.engine.prefix == "С"
    rig.key(VK["а"], caps=True)
    assert rig.engine.prefix == "СА"
    rig.key(VK["л"], shift=True, caps=True)
    assert rig.engine.prefix == "САл"


def test_backspace_and_enter(rig, lexicon):
    rig.type("салон\bм\n")
    assert "салом" in lexicon and "салон" not in lexicon


@pytest.mark.parametrize("vk", [
    w.VK_LEFT, w.VK_RIGHT, w.VK_UP, w.VK_DOWN, w.VK_HOME, w.VK_END,
    w.VK_PRIOR, w.VK_NEXT, w.VK_DELETE, w.VK_INSERT, w.VK_TAB, w.VK_ESCAPE, w.VK_APPS,
])
def test_navigation_keys_reset_buffer(rig, lexicon, vk):
    rig.type("сало")
    rig.key(vk)
    assert rig.engine.prefix == ""
    rig.type("м\n")
    assert "салом" not in lexicon


@pytest.mark.parametrize("vk", [0x41, 0x56, 0x58, 0x5A, w.VK_BACK, w.VK_LEFT])
def test_ctrl_shortcuts_reset_buffer(rig, vk):
    rig.type("сало")
    rig.key(vk, ctrl=True)             # Ctrl+A, V, X, Z, Backspace, Left
    assert rig.engine.prefix == ""


def test_ctrl_c_changes_nothing(rig):
    rig.type("сало")
    rig.key(0x43, ctrl=True)
    assert rig.engine.prefix == "сало"


def test_alt_and_win_combinations_reset(rig):
    rig.type("сало")
    rig.key(0x41, alt=True)
    assert rig.engine.prefix == ""
    rig.type("сало")
    rig.key(0x44, win=True)
    assert rig.engine.prefix == ""


def test_altgr_is_passed_to_translator(rig):
    rig.key(VK["а"], ctrl=True, alt=True)      # AltGr = Ctrl+Alt: still a character
    assert rig.engine.prefix == "а"


def test_keys_without_characters_are_ignored(rig):
    rig.type("сало")
    rig.key(w.VK_F1)
    rig.key(w.VK_SNAPSHOT)
    rig.key(0xAF)                              # volume up
    assert rig.engine.prefix == "сало"


def test_unicode_packets_from_other_programs(rig, lexicon):
    for ch in "ўзбек":
        rig.key(w.VK_PACKET, scan=ord(ch))
    assert rig.engine.prefix == "ўзбек"
    rig.key(w.VK_PACKET, scan=0xD83D)          # emoji: surrogate pair, one character
    rig.key(w.VK_PACKET, scan=0xDE00)
    assert rig.engine.prefix == ""
    rig.key(w.VK_BACK)                         # deleting the emoji brings the word back
    assert rig.engine.prefix == "ўзбек"


def test_word_start_requests_field_location(rig):
    rig.type("са")
    assert rig.word_starts == [HWND]
    rig.type(" до")
    assert rig.word_starts == [HWND, HWND]


def test_pause_hides_and_ignores_keys(rig, lexicon):
    rig.type("салом\nса")
    rig.worker.process(("pause", True))
    assert rig.shown == [] and rig.visible == 0
    rig.type("лом\n")
    assert lexicon.get("салом").freq == 1
    rig.worker.process(("pause", False))
    rig.type("са")
    assert rig.shown == ["салом"]


def test_password_field_blocks_and_forgets(rig, lexicon):
    rig.type("салом\n")
    rig.type("парол")                           # typed before the field was recognised
    rig.worker.process(("blocked", True))
    assert rig.engine.prefix == ""
    rig.type("ь\n")
    rig.type("са")
    assert rig.shown == [] and rig.visible == 0
    assert len(lexicon) == 1
    rig.worker.process(("blocked", False))
    rig.type("\nса")
    assert rig.shown == ["салом"]


def test_blocked_field_rechecks_location_on_tab_and_enter(rig):
    rig.worker.process(("blocked", True))
    rig.key(VK["а"])
    assert rig.word_starts == []
    rig.key(w.VK_RETURN)
    assert rig.word_starts == [HWND]


def test_focus_loss_hides_and_resets(rig):
    rig.type("салом\nса")
    rig.worker.process(("focus", False, 0x999))
    assert rig.shown == [] and rig.visible == 0
    assert rig.engine.prefix == ""


def test_repeated_focus_report_does_not_wipe_started_word(rig):
    rig.type("салом\n")
    rig.worker.process(("focus", False, 0x999))
    rig.worker.process(("focus", True, HWND))  # reported by the hook
    rig.type("са")
    rig.worker.process(("focus", True, HWND))  # the UI timer reports the same later
    assert rig.engine.prefix == "са"
    assert rig.shown == ["салом"]


def test_switching_between_telegram_windows_resets(rig):
    rig.type("са")
    rig.key(VK["л"], hwnd=0x5678)
    assert rig.engine.prefix == "л"


def test_mouse_click_reset_event(rig):
    rig.type("сало")
    rig.worker.process(("reset",))
    assert rig.engine.prefix == ""


def test_update_is_sent_only_on_change(rig):
    rig.type("салом\n")
    count = len(rig.updates)
    rig.type("д")                              # no suggestions before and after
    assert len(rig.updates) == count


def test_diag_snapshot(rig):
    rig.type("салом\nса")
    info = rig.diag[-1]
    assert info["prefix"] == "са"
    assert info["suggestions"] == ["салом"]
    assert info["active"] is True and info["paused"] is False
    assert info["layout"] == "ru-RU"


def test_call_event_runs_in_worker(rig):
    seen = []
    rig.worker.process(("call", lambda: seen.append(1)))
    assert seen == [1]


def test_broken_event_does_not_kill_worker(rig):
    rig.worker.process(("call", lambda: 1 / 0))
    rig.type("салом\nса")
    assert rig.shown == ["салом"]


def test_thread_flushes_dictionary_when_idle(store, settings, clock):
    from app.lexicon import Lexicon

    lexicon = Lexicon(store, settings, clock=clock, autoflush=False)
    rig = Rig(lexicon, settings)
    rig.worker._idle_flush = 0.05
    rig.worker.start()
    for ch in "салом":
        rig.worker.post("key", VK[ch], 0, False, False, False, False, False, None, HWND)
    rig.worker.post("key", w.VK_RETURN, 0, False, False, False, False, False, None, HWND)
    import time

    deadline = time.monotonic() + 3
    while store.counts()[0] == 0 and time.monotonic() < deadline:
        time.sleep(0.02)
    rig.worker.stop()
    rig.worker.join(3)
    assert not rig.worker.is_alive()
    assert store.counts() == (1, 0)
