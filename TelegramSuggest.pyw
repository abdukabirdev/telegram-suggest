"""Launcher without a console window; also the entry point of the packed .exe."""

import sys

from app.main import main

if __name__ == "__main__":
    sys.exit(main())
