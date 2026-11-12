"""Пути приложения и сохраняемые настройки.

Все данные Nook живут в одном каталоге (по умолчанию ``%APPDATA%\\nook``):
``config.json``, ``nook.db`` и сама зона ``vault/``.  Зона может быть
переопределена пользователем — тогда файлы лежат в выбранной им папке, а
служебные данные остаются в AppData.
"""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import asdict, dataclass, field
from pathlib import Path

import platformdirs

APP_NAME = "nook"
APP_TITLE = "Nook"

DEFAULT_WINDOW_SIZE = (1180, 760)
MIN_WINDOW_SIZE = (760, 480)


@dataclass
class Settings:
    """Настройки приложения и раскладка каталогов."""

    data_dir: Path
    vault_dir: Path
    copy_mode: str = "copy"  # "copy" | "move"
    window_width: int = DEFAULT_WINDOW_SIZE[0]
    window_height: int = DEFAULT_WINDOW_SIZE[1]

    # --- производные пути -------------------------------------------------
    @property
    def files_dir(self) -> Path:
        return self.vault_dir / "files"

    @property
    def trash_dir(self) -> Path:
        return self.vault_dir / "trash"

    @property
    def db_path(self) -> Path:
        return self.data_dir / "nook.db"

    @property
    def config_path(self) -> Path:
        return self.data_dir / "config.json"

    @property
    def exports_dir(self) -> Path:
        return self.data_dir / "exports"

    # --- жизненный цикл ---------------------------------------------------
    @classmethod
    def default(cls) -> "Settings":
        env_dir = os.environ.get("NOOK_DATA_DIR")
        if env_dir:
            data_dir = Path(env_dir).expanduser()
        else:
            data_dir = Path(platformdirs.user_data_dir(APP_NAME, appauthor=False))
        return cls(data_dir=data_dir, vault_dir=data_dir / "vault")

    @classmethod
    def load(cls, config_path: Path | str | None = None) -> "Settings":
        """Прочитать настройки; отсутствующий/битый файл — не ошибка."""
        if config_path is not None:
            config_path = Path(config_path)
            settings = cls(data_dir=config_path.parent, vault_dir=config_path.parent / "vault")
            if config_path.exists():
                settings._apply(cls._read_json(config_path))
            return settings

        settings = cls.default()
        if settings.config_path.exists():
            settings._apply(cls._read_json(settings.config_path))
        return settings

    def save(self) -> None:
        self.ensure()
        payload = asdict(self)
        payload["data_dir"] = str(self.data_dir)
        payload["vault_dir"] = str(self.vault_dir)
        self._write_json(self.config_path, payload)

    def ensure(self) -> None:
        """Создать каталоги зоны и данных, если их ещё нет."""
        for path in (self.data_dir, self.vault_dir, self.files_dir, self.trash_dir):
            path.mkdir(parents=True, exist_ok=True)

    def set_vault(self, path: Path | str) -> None:
        self.vault_dir = Path(path).expanduser().resolve()
        self.ensure()

    # --- внутреннее -------------------------------------------------------
    def _apply(self, payload: dict) -> None:
        if not isinstance(payload, dict):
            return
        vault = payload.get("vault_dir")
        if isinstance(vault, str) and vault.strip():
            self.vault_dir = Path(vault).expanduser()
        copy_mode = payload.get("copy_mode")
        if copy_mode in ("copy", "move"):
            self.copy_mode = copy_mode
        for attr in ("window_width", "window_height"):
            value = payload.get(attr)
            if isinstance(value, int) and value > 0:
                setattr(self, attr, value)

    @staticmethod
    def _read_json(path: Path) -> dict:
        try:
            with path.open("r", encoding="utf-8") as handle:
                data = json.load(handle)
            return data if isinstance(data, dict) else {}
        except (OSError, ValueError):
            return {}

    @staticmethod
    def _write_json(path: Path, payload: dict) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        handle, tmp_name = tempfile.mkstemp(dir=str(path.parent), prefix=".config-", suffix=".tmp")
        try:
            with os.fdopen(handle, "w", encoding="utf-8") as tmp:
                json.dump(payload, tmp, ensure_ascii=False, indent=2)
            os.replace(tmp_name, path)
        except BaseException:
            Path(tmp_name).unlink(missing_ok=True)
            raise
