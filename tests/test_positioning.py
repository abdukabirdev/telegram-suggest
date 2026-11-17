import threading
from types import SimpleNamespace

import pytest

from app import positioning
from app.positioning import (Anchor, CaretStrategy, Locator, WebStrategy, WindowStrategy,
                             _boxes, guess_anchor, is_web_address, monitor_work_area, place)

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


# ---- Telegram Web in a browser -----------------------------------------------

BROWSER_PID = 77


def test_web_address_check():
    assert is_web_address("https://web.telegram.org/k/#@durov")
    assert is_web_address("https://web.telegram.org/a/")
    assert is_web_address("https://webk.telegram.org/")
    assert not is_web_address("http://web.telegram.org/k/")
    assert not is_web_address("https://telegram.org/")
    assert not is_web_address("https://web.telegram.org.evil.com/")
    assert not is_web_address("https://www.google.com/search?q=web.telegram.org")
    assert not is_web_address("")


class _Range:
    def __init__(self, boxes, before=None):
        self.boxes = boxes              # flat x, y, width, height numbers
        self.before = before            # boxes after moving the start one back

    def Clone(self):
        return _Range(self.boxes, self.before)

    def GetBoundingRectangles(self):
        return self.boxes

    def MoveEndpointByUnit(self, endpoint, unit, count):
        self.boxes = self.before


class _Element:
    def __init__(self, kind, rect=(0, 0, 10, 10), parent=None, value=None,
                 pid=BROWSER_PID, password=False, read_only=True, caret=None):
        self.CurrentControlType = kind
        left, top, right, bottom = rect
        self.CurrentBoundingRectangle = SimpleNamespace(left=left, top=top, right=right,
                                                        bottom=bottom)
        self.CurrentIsPassword = password
        self.CurrentProcessId = pid
        self.CurrentIsOffscreen = False
        self.CurrentHasKeyboardFocus = False
        self.parent = parent
        self.value = value
        self.read_only = read_only
        self.caret = caret
        self.children = []

    def GetCurrentPattern(self, pattern_id):
        if pattern_id == WebStrategy._TEXT_PATTERN:
            if self.caret is None:
                return None
            selection = SimpleNamespace(Length=1, GetElement=lambda i: self.caret)
            return SimpleNamespace(QueryInterface=lambda iface: SimpleNamespace(
                GetSelection=lambda: selection))
        if self.value is None:
            return None
        return SimpleNamespace(QueryInterface=lambda iface: SimpleNamespace(
            CurrentValue=self.value, CurrentIsReadOnly=self.read_only))

    def FindAll(self, scope, condition):
        found = [c for c in self.children if c.CurrentControlType == WebStrategy._EDIT]
        return SimpleNamespace(Length=len(found), GetElement=found.__getitem__)


def _web_strategy(monkeypatch, focused, name="chrome.exe", mode="all"):
    monkeypatch.setattr(positioning, "window_ids", lambda hwnd: (1, BROWSER_PID))
    monkeypatch.setattr(positioning, "process_name", lambda pid: name)
    monkeypatch.setattr(positioning, "window_rect", lambda hwnd: (0, 0, 1920, 1040))
    strategy = WebStrategy.__new__(WebStrategy)
    strategy._browsers = frozenset(positioning.BROWSERS)
    strategy._hosts = positioning.WEB_HOSTS
    strategy._woken = {0x10}
    strategy._last = (0, 0, False)
    strategy._value_interface = None
    strategy._text_interface = None
    strategy._mode = lambda: mode

    def get_focused():
        if isinstance(focused, Exception):
            raise focused
        return focused

    strategy._uia = SimpleNamespace(GetFocusedElement=get_focused)
    strategy._walker = SimpleNamespace(GetParentElement=lambda element: element.parent)
    strategy._edit_condition = None
    return strategy


def _page(url):
    window = _Element(50032)
    return _Element(WebStrategy._DOCUMENT, (0, 80, 1920, 1040), window, url)


def test_web_field_on_telegram_web_is_used(monkeypatch):
    box = _Element(50026, parent=_page("https://web.telegram.org/k/"))
    field = _Element(WebStrategy._EDIT, (500, 980, 1800, 1020), box)
    anchor = _web_strategy(monkeypatch, field).locate(0x10)
    assert anchor == Anchor(500, 980, 1800, 1020, "web")


def test_web_password_field_is_reported(monkeypatch):
    field = _Element(WebStrategy._EDIT, (500, 500, 900, 530),
                     _page("https://web.telegram.org/a/"), password=True)
    anchor = _web_strategy(monkeypatch, field).locate(0x10)
    assert anchor.is_password and not anchor.foreign


def test_web_field_on_any_site(monkeypatch):
    field = _Element(WebStrategy._EDIT, (300, 600, 1200, 640), _page("https://chatgpt.com/"))
    assert _web_strategy(monkeypatch, field).locate(0x10) == Anchor(300, 600, 1200, 640, "web")


def test_web_contenteditable_box_counts_when_not_read_only(monkeypatch):
    page = _page("https://claude.ai/new")
    box = _Element(50026, (300, 600, 1200, 640), page, value="", read_only=False)
    assert _web_strategy(monkeypatch, box).locate(0x10).foreign is False
    plain = _Element(50026, (300, 600, 1200, 640), page, value="", read_only=True)
    assert _web_strategy(monkeypatch, plain).locate(0x10).foreign is True


def test_web_tall_field_follows_the_caret(monkeypatch):
    page = _page("https://mail.google.com/")
    typing = _Range((), before=(400, 520, 9, 20, 409, 520, 8, 20))
    field = _Element(WebStrategy._EDIT, (300, 200, 1200, 900), page, caret=typing)
    assert _web_strategy(monkeypatch, field).locate(0x10) == Anchor(417, 520, 1200, 540,
                                                                   "web-caret")
    short = _Element(WebStrategy._EDIT, (300, 500, 1200, 545), page, caret=typing)
    assert _web_strategy(monkeypatch, short).locate(0x10).source == "web"
    empty = _Element(WebStrategy._EDIT, (300, 200, 1200, 900), page, caret=_Range((), ()))
    assert _web_strategy(monkeypatch, empty).locate(0x10).source == "web"


def test_flat_rectangles_become_boxes():
    assert _boxes((1.4, 2, 3, 4, 10, 10, 0, 0)) == [(1, 2, 4, 6)]
    assert _boxes(None) == [] and _boxes((1, 2, 3)) == []


def test_web_other_site_is_foreign_in_telegram_mode(monkeypatch):
    field = _Element(WebStrategy._EDIT, parent=_page("https://mail.google.com/"))
    assert _web_strategy(monkeypatch, field, mode="telegram").locate(0x10).foreign
    field = _Element(WebStrategy._EDIT, parent=_page("https://web.telegram.org/k/"))
    assert not _web_strategy(monkeypatch, field, mode="telegram").locate(0x10).foreign


@pytest.mark.parametrize("case", ["button", "page itself", "address bar", "other process",
                                  "error", "nothing"])
def test_web_anything_else_is_foreign(monkeypatch, case):
    focused = {
        "button": _Element(50000, parent=_page("https://www.youtube.com/")),
        "page itself": _page("https://www.youtube.com/watch"),
        "address bar": _Element(WebStrategy._EDIT, parent=_Element(50033, value="")),
        "other process": _Element(WebStrategy._EDIT, pid=5,
                                  parent=_page("https://web.telegram.org/k/")),
        "error": RuntimeError("COM"),
        "nothing": None,
    }[case]
    anchor = _web_strategy(monkeypatch, focused).locate(0x10)
    assert anchor is not None and anchor.foreign and anchor.source == "web"


def test_web_page_without_focused_field_uses_its_lowest_field(monkeypatch):
    page = _page("https://web.telegram.org/k/")
    page.children = [_Element(WebStrategy._EDIT, (100, 90, 400, 120)),
                     _Element(WebStrategy._EDIT, (500, 980, 1800, 1020))]
    anchor = _web_strategy(monkeypatch, page).locate(0x10)
    assert (anchor.left, anchor.top, anchor.source, anchor.foreign) == (500, 980, "web", False)


def test_web_strategy_leaves_other_programs_alone(monkeypatch):
    strategy = _web_strategy(monkeypatch, None, name="telegram.exe")
    assert strategy.locate(0x10) is None
