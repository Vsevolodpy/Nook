"""``python -m nook`` — окно по умолчанию, CLI-команды для разработки."""

from __future__ import annotations

from .cli import main

if __name__ == "__main__":
    raise SystemExit(main())
