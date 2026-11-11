import pytest
from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import QApplication

from app import winapi as w
from app.overlay import Overlay, hint_for


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


def _mouse(kind, pos):
    return QMouseEvent(kind, QPointF(pos), QPointF(pos), Qt.MouseButton.LeftButton,
                       Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)


def _centers(overlay):
    return [rect.center() for rect in overlay._rects]


def test_hints():
    assert [hint_for(i) for i in range(3)] == ["Tab", "Ctrl+2", "Ctrl+3"]


def test_size_follows_content(overlay):
    overlay.set_items(["да"])
    small = overlay.width()
    overlay.set_items(["Абдукабир", "алейкум", "ассалому"])
    assert overlay.width() > small
    assert overlay.height() == 36
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
    center = _centers(overlay)[1]
    overlay.mousePressEvent(_mouse(QMouseEvent.Type.MouseButtonPress, center))
    overlay.mouseReleaseEvent(_mouse(QMouseEvent.Type.MouseButtonRelease, center))
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


def test_renders_in_both_themes(overlay):
    overlay.set_items(["Абдукабир", "алейкум", "ака"])
    for theme in ("dark", "light", "system"):
        overlay.set_theme(theme)
        image = overlay.grab().toImage()
        assert image.width() >= overlay.width()
        center = image.pixelColor(image.width() // 2, image.height() // 2)
        assert center.alpha() == 255


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
