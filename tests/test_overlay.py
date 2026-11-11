import pytest
from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import QApplication

from app import winapi as w
from app.overlay import SHADOW, Overlay, confirm_text, hint_for
from app.theme import palette_from_background


@pytest.fixture(scope="module")
def qt_app():
    app = QApplication.instance() or QApplication([])
    yield app


@pytest.fixture
def overlay(qt_app):
    widget = Overlay("dark")
    yield widget
    widget.hide()
    widget.deleteLater()


def _mouse(kind, pos, button=Qt.MouseButton.LeftButton):
    return QMouseEvent(kind, QPointF(pos), QPointF(pos), button,
                       button, Qt.KeyboardModifier.NoModifier)


def _click(overlay, pos, button=Qt.MouseButton.LeftButton):
    overlay.mousePressEvent(_mouse(QMouseEvent.Type.MouseButtonPress, pos, button))
    overlay.mouseReleaseEvent(_mouse(QMouseEvent.Type.MouseButtonRelease, pos, button))


def _centers(overlay):
    return [rect.center() for rect in overlay._rects]


def test_hints():
    assert [hint_for(i) for i in range(3)] == ["1", "2", "3"]


def test_size_follows_content(overlay):
    overlay.set_items(["да"])
    small = overlay.width()
    overlay.set_items(["Абдукабир", "алейкум", "ассалому"])
    assert overlay.width() > small
    assert overlay.height() == 32 + 2 * 4 + 2 * SHADOW
    assert overlay.items() == ["Абдукабир", "алейкум", "ассалому"]


def test_hit_testing(overlay):
    overlay.set_items(["Абдукабир", "алейкум", "ака"])
    centers = _centers(overlay)
    assert [overlay.index_at(c) for c in centers] == [0, 1, 2]
    assert overlay.index_at(QPoint(1, 1)) == -1
    assert overlay.index_at(QPoint(overlay.width() + 50, 10)) == -1


def test_click_emits_index(overlay):
    overlay.set_items(["Абдукабир", "алейкум", "ака"])
    clicked = []
    overlay.clicked.connect(clicked.append)
    _click(overlay, _centers(overlay)[1])
    assert clicked == [1]


def test_press_and_release_on_different_items_is_not_a_click(overlay):
    overlay.set_items(["Абдукабир", "алейкум", "ака"])
    clicked = []
    overlay.clicked.connect(clicked.append)
    centers = _centers(overlay)
    overlay.mousePressEvent(_mouse(QMouseEvent.Type.MouseButtonPress, centers[0]))
    overlay.mouseReleaseEvent(_mouse(QMouseEvent.Type.MouseButtonRelease, centers[2]))
    assert clicked == []


def test_hover_highlight_follows_mouse(overlay):
    overlay.set_items(["Абдукабир", "алейкум"])
    overlay.mouseMoveEvent(_mouse(QMouseEvent.Type.MouseMove, _centers(overlay)[1]))
    assert overlay._hover == 1
    overlay.leaveEvent(None)
    assert overlay._hover == -1


def test_very_long_word_is_shortened(overlay):
    overlay.set_items(["ж" * 200])
    assert overlay.width() < 400
    assert overlay._shown[0].endswith("…")
    assert overlay.items() == ["ж" * 200]      # what gets inserted is intact


def test_renders_in_any_palette(overlay):
    overlay.set_items(["Абдукабир", "алейкум", "ака"])
    for bg in ((255, 255, 255), (0x17, 0x21, 0x2b), (0xe6, 0xeb, 0xee)):
        palette = palette_from_background(bg)
        overlay.set_palette(palette)
        assert overlay.palette_colors() == palette
        image = overlay.grab().toImage()
        assert image.width() >= overlay.width()
        center = image.pixelColor(image.width() // 2, image.height() // 2)
        assert center.alpha() == 255
        corner = image.pixelColor(0, 0)
        assert corner.alpha() < 10                  # shadow margin stays see-through


def test_key_numbers_only_while_ctrl_is_held(overlay):
    overlay.set_items(["Абдукабир", "алейкум"])
    overlay.set_key_hints("ctrl")
    assert not overlay.hints_visible()
    overlay.set_ctrl_held(True)
    assert overlay.hints_visible()
    overlay.set_ctrl_held(False)
    overlay.set_key_hints("always")
    assert overlay.hints_visible()
    overlay.set_key_hints("never")
    overlay.set_ctrl_held(True)
    assert not overlay.hints_visible()
    width = overlay.width()
    overlay.set_key_hints("always")
    assert overlay.width() == width                 # numbers never move the words


def test_right_click_asks_then_left_click_deletes(overlay):
    overlay.set_items(["Абдукабир", "алейкум", "ака"])
    clicked, deleted = [], []
    overlay.clicked.connect(clicked.append)
    overlay.delete_requested.connect(deleted.append)
    width = overlay.width()
    _click(overlay, _centers(overlay)[2], Qt.MouseButton.RightButton)
    assert overlay.confirming() == 2
    assert overlay.width() > width                  # the chip now asks the question
    assert confirm_text("ака") == "Удалить «ака»?"
    assert deleted == [] and clicked == []
    _click(overlay, _centers(overlay)[2])
    assert deleted == [2] and clicked == []
    assert overlay.confirming() == -1


def test_question_is_cancelled_by_another_word_or_new_items(overlay):
    overlay.set_items(["Абдукабир", "алейкум", "ака"])
    clicked, deleted = [], []
    overlay.clicked.connect(clicked.append)
    overlay.delete_requested.connect(deleted.append)
    _click(overlay, _centers(overlay)[1], Qt.MouseButton.RightButton)
    _click(overlay, _centers(overlay)[0])
    assert clicked == [0] and deleted == []
    assert overlay.confirming() == -1
    _click(overlay, _centers(overlay)[1], Qt.MouseButton.RightButton)
    overlay.set_items(["алло"])
    assert overlay.confirming() == -1
    _click(overlay, _centers(overlay)[0], Qt.MouseButton.RightButton)
    overlay.cancel_confirm()
    _click(overlay, _centers(overlay)[0])
    assert deleted == [] and clicked == [0, 0]


def test_panel_is_inside_the_shadow_margin(overlay):
    overlay.set_items(["Абдукабир"])
    panel = overlay.panel_rect()
    assert panel.left() == SHADOW and panel.top() == SHADOW
    assert all(panel.contains(rect) for rect in overlay._rects)


def test_window_never_takes_focus(overlay):
    overlay.set_items(["Абдукабир"])
    style = w.GetWindowLongPtrW(overlay.native_handle(), w.GWL_EXSTYLE)
    assert style & w.WS_EX_NOACTIVATE
    assert style & w.WS_EX_TOOLWINDOW
    assert overlay.focusPolicy() == Qt.FocusPolicy.NoFocus
    assert overlay.native_rect() is None       # hidden


def test_show_at_does_not_steal_foreground(overlay, qt_app):
    before = w.GetForegroundWindow()
    overlay.set_items(["Абдукабир", "алейкум"])
    work_x, work_y = 40, 40
    overlay.show_at(work_x, work_y)
    qt_app.processEvents()
    rect = overlay.native_rect()
    overlay.hide()
    qt_app.processEvents()
    assert rect is not None
    assert (rect[0], rect[1]) == (work_x, work_y)
    assert (rect[2] - rect[0], rect[3] - rect[1]) == overlay.physical_size()
    assert w.GetForegroundWindow() == before


def test_native_panel_rect_excludes_shadow(overlay, qt_app):
    overlay.set_items(["Абдукабир"])
    overlay.show_at(60, 60)
    qt_app.processEvents()
    outer, inner = overlay.native_rect(), overlay.native_panel_rect()
    overlay.hide()
    m = overlay.margin_physical()
    assert inner == (outer[0] + m, outer[1] + m, outer[2] - m, outer[3] - m)
    assert overlay.native_panel_rect() is None
