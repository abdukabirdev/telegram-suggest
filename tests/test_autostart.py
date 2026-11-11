"""Autostart against a scratch registry key: the real Run key is never touched."""

import winreg

import pytest

from app import autostart

TEST_KEY = r"Software\TelegramSuggestTests\Run"


@pytest.fixture
def key():
    yield TEST_KEY
    for path in (TEST_KEY, r"Software\TelegramSuggestTests"):
        try:
            winreg.DeleteKey(winreg.HKEY_CURRENT_USER, path)
        except OSError:
            pass


def test_enable_and_disable(key):
    assert not autostart.is_enabled(key)
    assert autostart.enable('"C:\\x\\a.exe" --autostart', key)
    assert autostart.is_enabled(key)
    assert autostart._read(key) == '"C:\\x\\a.exe" --autostart'
    assert autostart.disable(key)
    assert not autostart.is_enabled(key)
    assert autostart.disable(key)               # already off: still fine


def test_sync_rewrites_a_moved_program(key):
    autostart.enable('"C:\\old place\\a.exe" --autostart', key)
    assert autostart.sync(True, key)
    assert autostart._read(key) == autostart.launch_command()
    assert autostart.sync(False, key)
    assert not autostart.is_enabled(key)


def test_command_from_sources_uses_the_launcher():
    command = autostart.launch_command()
    assert command.endswith(autostart.FLAG)
    assert "TelegramSuggest.pyw" in command
    assert "pythonw.exe" in command.lower()


def test_command_of_the_packed_exe(monkeypatch):
    monkeypatch.setattr(autostart.sys, "frozen", True, raising=False)
    monkeypatch.setattr(autostart.sys, "executable", "C:\\Programs\\TelegramSuggest.exe")
    assert autostart.launch_command() == '"C:\\Programs\\TelegramSuggest.exe" --autostart'
