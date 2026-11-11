from app import winapi as w
from app.inserter import build_inputs, held_modifiers

UNI = w.KEYEVENTF_UNICODE
UP = w.KEYEVENTF_KEYUP


def describe(events):
    return [(e.ki.wVk, e.ki.wScan, e.ki.dwFlags) for e in events]


def test_backspaces_then_text():
    events = build_inputs(2, "аб")
    assert describe(events) == [
        (w.VK_BACK, 0, 0), (w.VK_BACK, 0, UP),
        (w.VK_BACK, 0, 0), (w.VK_BACK, 0, UP),
        (0, ord("а"), UNI), (0, ord("а"), UNI | UP),
        (0, ord("б"), UNI), (0, ord("б"), UNI | UP),
    ]


def test_every_event_is_tagged_as_ours():
    events = build_inputs(3, "Абдукабир ", [w.VK_LCONTROL])
    assert events
    for e in events:
        assert e.type == w.INPUT_KEYBOARD
        assert e.ki.dwExtraInfo == w.INJECT_TAG


def test_uzbek_letters_and_space():
    events = build_inputs(0, "Ўқғҳ ")
    units = [e.ki.wScan for e in events[::2]]
    assert units == [ord(c) for c in "Ўқғҳ "]


def test_characters_outside_bmp_use_surrogate_pairs():
    events = build_inputs(0, "😀")
    assert [e.ki.wScan for e in events] == [0xD83D, 0xD83D, 0xDE00, 0xDE00]


def test_held_modifiers_are_released_first_and_pressed_back_last():
    events = describe(build_inputs(1, "а", [w.VK_LCONTROL, w.VK_RCONTROL]))
    assert events[0] == (w.VK_LCONTROL, 0, UP)
    assert events[1] == (w.VK_RCONTROL, 0, UP | w.KEYEVENTF_EXTENDEDKEY)
    assert events[2:4] == [(w.VK_BACK, 0, 0), (w.VK_BACK, 0, UP)]
    assert events[-2] == (w.VK_RCONTROL, 0, w.KEYEVENTF_EXTENDEDKEY)
    assert events[-1] == (w.VK_LCONTROL, 0, 0)


def test_nothing_to_do():
    assert build_inputs(0, "") == []
    assert describe(build_inputs(-5, "")) == []


def test_held_modifiers_detection():
    down = {w.VK_LCONTROL, w.VK_RSHIFT, w.VK_MENU}
    assert held_modifiers(lambda vk: vk in down) == [w.VK_LCONTROL, w.VK_RSHIFT]
    assert held_modifiers(lambda vk: False) == []


def test_input_structure_size_matches_windows():
    import ctypes
    import struct

    # 40 bytes on 64-bit Windows, 28 on 32-bit: SendInput rejects anything else
    assert ctypes.sizeof(w.INPUT) == (40 if struct.calcsize("P") == 8 else 28)
