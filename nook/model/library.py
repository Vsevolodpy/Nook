"""Сервисный слой: связывает БД, индекс, поиск, теги и зону.

Контроллер и CLI работают только через :class:`Library` — так проще тестировать
и нет дублирования «собери компоненты» в двух местах.
"""

from __future__ import annotations

import time
from datetime import datetime
from pathlib import Path
from typing import Iterable, Sequence

from .config import Settings
from .db import Database
from .index import Index, Record
from .query import Query, parse_query
from .search import DEFAULT_LIMIT, search
from .tags import TagStore
from .zone import AddResult, Zone


def human_size(size: int) -> str:
    value = float(size)
    for unit in ("Б", "КБ", "МБ", "ГБ", "ТБ"):
        if value < 1024 or unit == "ТБ":
            if unit == "Б":
                return f"{int(value)} {unit}"
            return f"{value:.1f} {unit}".replace(".0 ", " ")
        value /= 1024
    return f"{value:.1f} ТБ"


def serialize(record: Record) -> dict[str, object]:
    return {
        "id": record.id,
        "name": record.original_name,
        "size": record.size,
        "size_human": human_size(record.size),
        "added_at": record.added_at.isoformat(),
        "added_at_human": record.added_at.strftime("%d.%m.%Y %H:%M"),
        "mtime_at": record.mtime.isoformat() if record.mtime else "",
        "mtime_at_human": record.mtime.strftime("%d.%m.%Y") if record.mtime else "",
        "created_at": record.created_at.isoformat() if record.created_at else "",
        "created_at_human": record.created_at.strftime("%d.%m.%Y") if record.created_at else "",
        "ext": record.ext,
        "tags": list(record.tags),
        "note": record.note or "",
    }


class Library:
    """Композиция модели: одна точка входа для UI и тестов."""

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or Settings.load()
        self.settings.ensure()
        self.db = Database(self.settings.db_path)
        self.db.initialize()
        self.index = Index()
        self.index.load(self.db)
        self.tags = TagStore(self.db, self.index)
        self.zone = Zone(self.settings, self.db, self.index, self.tags)
        self.tags.cleanup()

    def close(self) -> None:
        self.db.close()

    # --- поиск ------------------------------------------------------------
    def search(self, raw: str, limit: int = DEFAULT_LIMIT) -> dict[str, object]:
        query = parse_query(raw)
        started = time.perf_counter()
        records = search(self.index, query, limit=limit)
        elapsed_ms = (time.perf_counter() - started) * 1000.0
        self._log_search(raw, len(records))

        return {
            "query": {
                "text": query.text,
                "tags": list(query.tags),
                "neg_tags": list(query.neg_tags),
                "ext": query.ext,
                "dates": [
                    {
                        "start": date_range.start.isoformat() if date_range.start else None,
                        "end": date_range.end.isoformat() if date_range.end else None,
                        "negated": date_range.negated,
                    }
                    for date_range in query.dates
                ],
            },
            "items": [serialize(record) for record in records],
            "total": len(self.index),
            "took_ms": round(elapsed_ms, 2),
        }

    def _log_search(self, raw: str, results: int) -> None:
        """Карта дыр: копим только запросы без результатов."""
        text = (raw or "").strip()
        if not text or results:
            return
        if len(text) < 3:
            return
        try:
            last = self.db.query_one("SELECT query FROM search_log ORDER BY id DESC LIMIT 1")
            if last is not None and last["query"] == text:
                return
            self.db.execute(
                "INSERT INTO search_log(query, results_count, ts) VALUES (?, ?, ?)",
                (text[:300], results, datetime.now().isoformat(timespec="seconds")),
            )
        except Exception:  # noqa: BLE001 - лог не должен ломать поиск
            pass

    # --- добавление -------------------------------------------------------
    def add_paths(
        self,
        paths: Sequence[str | Path],
        tags: Iterable[str] = (),
        note: str | None = None,
        source: str = "ui",
    ) -> dict[str, object]:
        tag_list = [str(tag) for tag in tags]
        results: list[AddResult] = self.zone.add_many(paths, tag_list, note, source)
        return {
            "added": [item.record.original_name for item in results if item.status == "added" and item.record],
            "added_ids": [item.record.id for item in results if item.status == "added" and item.record],
            "duplicates": [item.message for item in results if item.status == "duplicate"],
            "errors": [item.message for item in results if item.status == "error"],
            "total": len(results),
        }

    def delete(self, file_ids: Sequence[int]) -> dict[str, object]:
        count = self.zone.delete(file_ids)
        return {"ok": True, "deleted": count}

    def restore(self, file_ids: Sequence[int]) -> dict[str, object]:
        count = self.zone.restore(file_ids)
        return {"ok": True, "restored": count}

    # --- теги -------------------------------------------------------------
    def assign_tag(self, file_ids: Sequence[int], tag: str) -> dict[str, object]:
        added = self.tags.assign(file_ids, tag)
        return {"ok": True, "assigned": added, "tags": self.tags.list()}

    def unassign_tag(self, file_ids: Sequence[int], tag: str) -> dict[str, object]:
        removed = self.tags.unassign(file_ids, tag)
        return {"ok": True, "removed": removed, "tags": self.tags.list()}

    def set_tags(self, file_id: int, tags: Iterable[str]) -> dict[str, object]:
        current = self.tags.set_for_file(file_id, tags)
        return {"ok": True, "tags": current}

    def rename_tag(self, old: str, new: str) -> dict[str, object]:
        return self.tags.rename(old, new)

    def merge_tags(self, sources: Sequence[str], target: str) -> dict[str, object]:
        affected = self.tags.merge(sources, target)
        return {"ok": True, "affected": affected, "tags": self.tags.list()}

    # --- прочее -----------------------------------------------------------
    def stats(self) -> dict[str, object]:
        data = self.zone.stats()
        data["data_dir"] = str(self.settings.data_dir)
        data["copy_mode"] = self.settings.copy_mode
        return data

    def recent_empty_queries(self, limit: int = 10) -> list[str]:
        rows = self.db.query(
            "SELECT query FROM search_log WHERE results_count = 0 "
            "GROUP BY query ORDER BY MAX(ts) DESC LIMIT ?",
            (limit,),
        )
        return [row["query"] for row in rows]
