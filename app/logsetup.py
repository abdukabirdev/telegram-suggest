"""File logging with rotation.

The log is for diagnosing technical problems. Typed text, prefixes, words and
suggestions must never be passed to the logger anywhere in the program.
"""

from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

from .paths import log_dir

_FORMAT = "%(asctime)s %(levelname)s %(threadName)s %(name)s: %(message)s"


def setup_logging(level: str = "INFO", directory: Path | None = None) -> Path:
    directory = directory or log_dir()
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "app.log"
    handler = RotatingFileHandler(
        path, maxBytes=512 * 1024, backupCount=3, encoding="utf-8"
    )
    handler.setFormatter(logging.Formatter(_FORMAT))
    root = logging.getLogger()
    for old in list(root.handlers):
        root.removeHandler(old)
    root.addHandler(handler)
    root.setLevel(getattr(logging, str(level).upper(), logging.INFO))
    return path
