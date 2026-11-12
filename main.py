"""Точка входа для PyInstaller: ``python main.py`` — то же, что ``python -m nook``."""

from nook.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
