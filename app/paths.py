"""Where the program keeps its files. Everything stays on this computer."""

from __future__ import annotations

import os
from pathlib import Path

APP_DIR_NAME = "TelegramSuggest"


def data_dir() -> Path:
    """%APPDATA%\\TelegramSuggest: the dictionary and settings."""
    base = os.environ.get("APPDATA") or str(Path.home() / "AppData" / "Roaming")
    return Path(base) / APP_DIR_NAME


def database_path() -> Path:
    return data_dir() / "data.db"


def log_dir() -> Path:
    """%LOCALAPPDATA%\\TelegramSuggest\\logs: technical log, no typed text."""
    base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
    return Path(base) / APP_DIR_NAME / "logs"
