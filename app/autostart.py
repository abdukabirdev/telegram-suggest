"""Start together with Windows: one value under HKCU\\...\\CurrentVersion\\Run.

Per user, no administrator rights. The command carries ``--autostart`` so the
program knows it was started at sign-in and stays quiet (no greeting balloon).
If the .exe is moved, the next start writes the new path.
"""

from __future__ import annotations

import logging
import sys
import winreg
from pathlib import Path
from typing import Optional

log = logging.getLogger(__name__)

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
VALUE_NAME = "TelegramSuggest"
FLAG = "--autostart"


def launch_command() -> str:
    if getattr(sys, "frozen", False):           # the packed .exe
        return f'"{sys.executable}" {FLAG}'
    # From the sources: the windowless interpreter and the launcher script
    exe = Path(sys.executable)
    pythonw = exe.with_name("pythonw.exe")
    if not pythonw.exists():
        pythonw = exe
    script = Path(__file__).resolve().parent.parent / "TelegramSuggest.pyw"
    return f'"{pythonw}" "{script}" {FLAG}'


def _read(key_path: str) -> Optional[str]:
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path) as key:
            value, _ = winreg.QueryValueEx(key, VALUE_NAME)
            return str(value)
    except OSError:
        return None


def is_enabled(key_path: str = RUN_KEY) -> bool:
    return _read(key_path) is not None


def enable(command: Optional[str] = None, key_path: str = RUN_KEY) -> bool:
    command = command or launch_command()
    try:
        with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, key_path, 0,
                                winreg.KEY_SET_VALUE) as key:
            winreg.SetValueEx(key, VALUE_NAME, 0, winreg.REG_SZ, command)
        return True
    except OSError:
        log.exception("could not enable autostart")
        return False


def disable(key_path: str = RUN_KEY) -> bool:
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path, 0,
                            winreg.KEY_SET_VALUE) as key:
            winreg.DeleteValue(key, VALUE_NAME)
        return True
    except FileNotFoundError:
        return True
    except OSError:
        log.exception("could not disable autostart")
        return False


def sync(enabled: bool, key_path: str = RUN_KEY) -> bool:
    """Make the registry match the setting; refresh the path if it changed."""
    if not enabled:
        return disable(key_path)
    command = launch_command()
    if _read(key_path) == command:
        return True
    return enable(command, key_path)
