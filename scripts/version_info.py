"""Write the version resource of the .exe (Explorer > Properties > Details).

Run:  .venv\\Scripts\\python.exe scripts\\version_info.py build\\version_info.txt
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import __version__  # noqa: E402

TEMPLATE = """# UTF-8
VSVersionInfo(
  ffi=FixedFileInfo(
    filevers={nums}, prodvers={nums},
    mask=0x3f, flags=0x0, OS=0x40004, fileType=0x1, subtype=0x0, date=(0, 0)),
  kids=[
    StringFileInfo([
      StringTable('041904B0', [
        StringStruct('CompanyName', 'Telegram Suggest'),
        StringStruct('FileDescription', 'Подсказки для Telegram'),
        StringStruct('FileVersion', '{text}'),
        StringStruct('InternalName', 'TelegramSuggest'),
        StringStruct('OriginalFilename', 'TelegramSuggest.exe'),
        StringStruct('ProductName', 'Подсказки для Telegram'),
        StringStruct('ProductVersion', '{text}')])
    ]),
    VarFileInfo([VarStruct('Translation', [0x0419, 1200])])
  ]
)
"""


def main() -> int:
    target = Path(sys.argv[1] if len(sys.argv) > 1 else "build/version_info.txt")
    parts = [int(p) for p in __version__.split(".")] + [0, 0, 0, 0]
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(TEMPLATE.format(nums=tuple(parts[:4]), text=__version__),
                      encoding="utf-8")
    print(f"version info written: {target} ({__version__})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
