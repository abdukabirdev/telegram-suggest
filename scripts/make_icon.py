"""Write the program icon (.ico) for the packed .exe.

Run:  .venv\\Scripts\\python.exe scripts\\make_icon.py build\\icon.ico
The picture is the same as the tray icon (app.tray.icon_pixmap).
"""

from __future__ import annotations

import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtCore import QBuffer, QIODevice  # noqa: E402
from PySide6.QtGui import QGuiApplication  # noqa: E402

from app.tray import icon_pixmap  # noqa: E402

SIZES = (16, 20, 24, 32, 40, 48, 64, 128, 256)


def png_bytes(size: int) -> bytes:
    buffer = QBuffer()
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    icon_pixmap(size).save(buffer, "PNG")
    return bytes(buffer.data())


def ico_bytes(images: list[tuple[int, bytes]]) -> bytes:
    """ICO container with PNG-compressed images (Windows Vista and later)."""
    header = struct.pack("<HHH", 0, 1, len(images))
    offset = len(header) + 16 * len(images)
    entries, blobs = b"", b""
    for size, data in images:
        side = 0 if size >= 256 else size
        entries += struct.pack("<BBBBHHII", side, side, 0, 0, 1, 32, len(data), offset)
        blobs += data
        offset += len(data)
    return header + entries + blobs


def main() -> int:
    target = Path(sys.argv[1] if len(sys.argv) > 1 else "build/icon.ico")
    QGuiApplication(sys.argv[:1])
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(ico_bytes([(size, png_bytes(size)) for size in SIZES]))
    print(f"icon written: {target}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
