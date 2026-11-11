import threading

from app.positioning import (Anchor, CaretStrategy, Locator, WindowStrategy,
                             guess_anchor, monitor_work_area, place)

WORK = (0, 0, 1920, 1040)
FIELD = Anchor(475, 1003, 1830, 1031, "uia-focus")


def test_window_goes_above_the_field_at_its_left_edge():
    assert place(FIELD, (300, 36), WORK) == (475, 1003 - 6 - 36)


def test_user_offset_is_applied():
    assert place(FIELD, (300, 36), WORK, offset=(20, -10)) == (495, 1003 - 6 - 36 - 10)


def test_no_room_above_puts_window_below():
    search = Anchor(83, 10, 418, 35, "uia-focus")
    assert place(search, (300, 36), WORK) == (83, 35 + 6)


def test_window_is_kept_on_screen():
    right_edge = Anchor(1800, 500, 1900, 530, "uia-focus")
    x, y = place(right_edge, (300, 36), WORK)
    assert x == 1920 - 300 and y == 500 - 6 - 36
    x, y = place(FIELD, (300, 36), WORK, offset=(-5000, 5000))
    assert (x, y) == (0, 1040 - 36)


def test_second_monitor_with_negative_coordinates():
    work = (-1920, 0, 0, 1040)
    field = Anchor(-1500, 1000, -200, 1030, "uia-focus")
    assert place(field, (300, 36), work) == (-1500, 1000 - 6 - 36)


def test_caret_anchor_puts_window_above_caret():
    caret = Anchor(640, 500, 641, 518, "caret")
    assert place(caret, (200, 36), WORK) == (640, 500 - 6 - 36)


def test_guess_matches_real_telegram_layout_roughly():
    # measured: window client 0,0-1920,1040; real field at (475,1003)-(1830,1031)
    guess = guess_anchor((0, 0, 1920, 1040))
    assert guess.source == "window"
    assert guess.top == 1003 and guess.bottom == 1031
    assert abs(guess.left - 475) <= 5
    assert guess.right > guess.left


def test_guess_for_narrow_one_column_window():
    guess = guess_anchor((100, 100, 600, 800))
    assert guess.left == 100 + 46
    assert guess.top == 800 - 37


def test_guess_scales_with_dpi():
    guess = guess_anchor((0, 0, 2880, 1560), scale=1.5)
    assert guess.top == 1560 - int(37 * 1.5)
    assert guess.left == int(430 * 1.5) + int(46 * 1.5)


def test_guess_never_produces_inverted_rectangle():
    for width in (1, 50, 120, 400, 641, 5000):
        guess = guess_anchor((0, 0, width, 300))
        assert guess.right > guess.left
        assert guess.bottom > guess.top


def test_monitor_work_area_is_sane():
    left, top, right, bottom = monitor_work_area(10, 10)
    assert right - left >= 640 and bottom - top >= 400


def test_strategies_survive_a_missing_window():
    assert WindowStrategy().locate(0) is None
    assert CaretStrategy().locate(0) is None
    assert WindowStrategy().locate(0x7FFFFFF0) is None


class _Fixed:
    def __init__(self, name, result):
        self.name = name
        self.result = result
        self.calls = 0

    def locate(self, hwnd):
        self.calls += 1
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


def _run_locator(strategies, hwnd=0x10):
    done = threading.Event()
    results = []

    def on_result(h, anchor):
        results.append((h, anchor))
        done.set()

    locator = Locator(on_result, strategies=strategies, min_interval=0)
    locator.start()
    locator.request(hwnd)
    assert done.wait(3.0)
    locator.stop()
    locator.join(3.0)
    assert not locator.is_alive()
    return results


def test_locator_takes_first_strategy_that_answers():
    first = _Fixed("caret", None)
    second = _Fixed("uia", FIELD)
    third = _Fixed("window", Anchor(0, 0, 1, 1, "window"))
    assert _run_locator([first, second, third]) == [(0x10, FIELD)]
    assert (first.calls, second.calls, third.calls) == (1, 1, 0)


def test_locator_survives_failing_strategy():
    broken = _Fixed("uia", RuntimeError("boom"))
    assert _run_locator([broken, _Fixed("window", FIELD)]) == [(0x10, FIELD)]


def test_locator_reports_when_nothing_found():
    assert _run_locator([_Fixed("caret", None)]) == [(0x10, None)]


def test_locator_ignores_empty_window_handle():
    locator = Locator(lambda h, a: None, strategies=[])
    locator.request(0)
    locator.request(None)
    assert not locator._event.is_set()
