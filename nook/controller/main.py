"""Контроллер: тонкий мост JS ⇄ Python и запуск окна.

Никакой бизнес-логики — только приём JSON-аргументов, вызов :class:`Library`
и возврат JSON-совместимых словарей.
"""

from __future__ import annotations

import functools
import json
import logging
import sys
from pathlib import Path
from typing import Any, Callable, Sequence

import webview

from ..model.library import Library, serialize
from ..model.config import APP_TITLE, MIN_WINDOW_SIZE, Settings

logger = logging.getLogger("nook")


def view_dir() -> Path:
    """Каталог с HTML/CSS/JS — внутри .exe (PyInstaller) или рядом с пакетом."""
    if getattr(sys, "frozen", False):
        base = Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
        return base / "view"
    return Path(__file__).resolve().parents[1] / "view"


def api_method(func: Callable[..., dict]) -> Callable[..., dict]:
    """Любая ошибка метода превращается в ``{"ok": false}``, а не в падение окна."""

    @functools.wraps(func)
    def wrapper(self, *args: Any, **kwargs: Any) -> dict:
        try:
            result = func(self, *args, **kwargs)
            return result if isinstance(result, dict) else {"ok": True, "value": result}
        except Exception as error:  # noqa: BLE001 - мост не должен ронять UI
            logger.exception("Ошибка в API-методе %s", func.__name__)
            return {"ok": False, "error": str(error)}

    return wrapper


class Api:
    """Класс, который pywebview выставляет в JS как ``window.pywebview.api``."""

    def __init__(self, library: Library) -> None:
        self._library = library
        self._window: webview.Window | None = None

    def attach(self, window: webview.Window) -> None:
        self._window = window

    # --- состояние --------------------------------------------------------
    @api_method
    def state(self) -> dict:
        stats = self._library.stats()
        return {
            "ok": True,
            "stats": stats,
            "tags": self._library.tags.list(),
            "vault": stats["vault"],
            "data_dir": stats["data_dir"],
            "empty_queries": self._library.recent_empty_queries(5),
        }

    @api_method
    def search(self, query: str = "", limit: int = 300) -> dict:
        payload = self._library.search(query or "", limit=int(limit))
        payload["ok"] = True
        return payload

    # --- добавление -------------------------------------------------------
    @api_method
    def pick_files(self) -> dict:
        """Показать системный диалог и вернуть выбранные пути в JS."""
        if self._window is None:
            return {"ok": False, "error": "Окно ещё не готово"}
        result = self._window.create_file_dialog(
            webview.FileDialog.OPEN,
            allow_multiple=True,
            file_types=("Все файлы (*.*)",),
        )
        paths = [str(item) for item in (result or ())]
        return {"ok": True, "paths": paths}

    @api_method
    def add_paths(
        self,
        paths: Sequence[str] | None = None,
        tags: Sequence[str] | None = None,
        note: str | None = None,
    ) -> dict:
        clean = [str(path) for path in (paths or ()) if str(path).strip()]
        if not clean:
            return {"ok": False, "error": "Нет файлов для добавления"}
        result = self._library.add_paths(clean, tags or (), note)
        result["ok"] = True
        return result

    # --- удаление / восстановление ---------------------------------------
    @api_method
    def delete_files(self, ids: Sequence[int] | None = None) -> dict:
        return self._library.delete([int(item) for item in (ids or ())])

    @api_method
    def restore_files(self, ids: Sequence[int] | None = None) -> dict:
        return self._library.restore([int(item) for item in (ids or ())])

    # --- файлы ------------------------------------------------------------
    @api_method
    def open_file(self, file_id: int) -> dict:
        ok, error = self._library.zone.open(int(file_id))
        return {"ok": ok, "error": error}

    @api_method
    def reveal_file(self, file_id: int) -> dict:
        ok, error = self._library.zone.reveal(int(file_id))
        return {"ok": ok, "error": error}

    @api_method
    def open_vault(self) -> dict:
        ok, error = self._library.zone.reveal_dir(self._library.settings.vault_dir)
        return {"ok": ok, "error": error}

    @api_method
    def set_note(self, file_id: int, note: str = "") -> dict:
        record = self._library.zone.set_note(int(file_id), note)
        return {"ok": record is not None, "item": serialize(record) if record else None}

    # --- теги -------------------------------------------------------------
    @api_method
    def tags(self) -> dict:
        return {"ok": True, "tags": self._library.tags.list()}

    @api_method
    def tag_suggest(self, prefix: str = "", limit: int = 12) -> dict:
        return {"ok": True, "tags": self._library.tags.suggest(prefix or "", int(limit))}

    @api_method
    def assign_tag(self, ids: Sequence[int] | None = None, tag: str = "") -> dict:
        return self._library.assign_tag([int(item) for item in (ids or ())], tag)

    @api_method
    def unassign_tag(self, ids: Sequence[int] | None = None, tag: str = "") -> dict:
        return self._library.unassign_tag([int(item) for item in (ids or ())], tag)

    @api_method
    def set_tags(self, file_id: int, tags: Sequence[str] | None = None) -> dict:
        return self._library.set_tags(int(file_id), tags or ())

    @api_method
    def rename_tag(self, old: str = "", new: str = "") -> dict:
        return self._library.rename_tag(old, new)

    @api_method
    def merge_tags(self, sources: Sequence[str] | None = None, target: str = "") -> dict:
        return self._library.merge_tags(sources or (), target)

    # --- экспорт ----------------------------------------------------------
    @api_method
    def export_zip(self) -> dict:
        if self._window is None:
            return {"ok": False, "error": "Окно ещё не готово"}
        from datetime import datetime

        suggested = f"nook-export-{datetime.now():%Y%m%d-%H%M}.zip"
        target = self._window.create_file_dialog(
            webview.FileDialog.SAVE,
            save_filename=suggested,
            file_types=("ZIP-архив (*.zip)",),
        )
        if isinstance(target, (list, tuple)):
            target = target[0] if target else None
        if not target:
            return {"ok": False, "canceled": True}
        path = self._library.zone.export_zip(target)
        return {"ok": True, "path": str(path), "count": len(self._library.index)}

    # --- drag & drop (пути приходят из pywebview DOM-события) --------------
    def on_drop(self, event: dict) -> None:
        """Обработчик drop, зарегистрированный на ``document``."""
        try:
            files = (event.get("dataTransfer") or {}).get("files") or []
            paths = [item.get("pywebviewFullPath") for item in files if item.get("pywebviewFullPath")]
            if not paths or self._window is None:
                return
            payload = json.dumps(paths, ensure_ascii=False)
            self._window.evaluate_js(f"window.nook && window.nook.onDropped({payload})")
        except Exception:  # noqa: BLE001 - drop не должен ломать окно
            logger.exception("Не удалось обработать drop")


def run(debug: bool = False) -> None:
    """Создать окно, навесить мост и запустить цикл pywebview."""
    settings = Settings.load()
    settings.ensure()
    library = Library(settings)
    api = Api(library)

    window = webview.create_window(
        APP_TITLE,
        url=str(view_dir() / "index.html"),
        js_api=api,
        width=settings.window_width,
        height=settings.window_height,
        min_size=MIN_WINDOW_SIZE,
        text_select=False,
    )
    api.attach(window)

    def register_drop() -> None:
        try:
            window.dom.document.events.drop += api.on_drop
        except Exception:  # noqa: BLE001 - без DnD приложение остаётся рабочим
            logger.exception("Не удалось включить drag & drop")

    window.events.loaded += register_drop

    webview.start(debug=debug)
