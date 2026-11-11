import os
import threading
import uuid

from app.instance import SingleInstance, is_newer, parse_version


def _name() -> str:
    return "Local\\TelegramSuggest.Test." + uuid.uuid4().hex


def test_versions_compare_as_numbers():
    assert parse_version("0.10.0") == (0, 10, 0)
    assert is_newer("0.10.0", "0.9.0")
    assert not is_newer("0.9.0", "0.10.0")
    assert not is_newer("1.0.0", "1.0.0")
    assert is_newer("1.0.1", "")              # unreadable counts as the oldest
    assert parse_version("1.2-beta") == (1, 2)


def test_second_copy_sees_the_first_and_its_version():
    name = _name()
    first = SingleInstance(name)
    try:
        assert first.first
        first.publish("0.10.0")
        second = SingleInstance(name)
        try:
            assert not second.first
            running = second.running()
            assert running is not None
            assert running.pid == os.getpid() and running.version == "0.10.0"
        finally:
            second.close()
    finally:
        first.close()
    # gone with its last handle: the next launch is the first again
    third = SingleInstance(name)
    assert third.first and third.running() is None
    third.close()


def test_second_launch_asks_the_first_to_show_its_window():
    name = _name()
    first = SingleInstance(name)
    shown = threading.Event()
    first.listen(on_show=shown.set, on_quit=lambda: None)
    try:
        second = SingleInstance(name)
        second.ask_show()
        assert shown.wait(2.0)
        second.close()
    finally:
        first.close()


def test_replace_needs_a_published_copy():
    name = _name()
    first = SingleInstance(name)                # an old copy: publishes nothing
    second = SingleInstance(name)
    try:
        assert second.running() is None
        assert not second.replace_running(timeout_s=0.1)
        assert not second.first
    finally:
        second.close()
        first.close()
