"""Индекс зоны в памяти: поиск не ходит в SQLite на каждый запрос."""

from __future__ import annotations

import threading
from dataclasses import dataclass, replace
from datetime import datetime
from functools import cached_property
from pathlib import PurePath

from .db import Database
from .query import normalize_tag, normalize_text

_TAG_SEPARATOR = "\x1f"

_SELECT_FILES = """
SELECT f.id, f.original_name, f.stored_path, f.hash, f.size,
       f.added_at, f.mtime, f.created_at, f.note, f.source,
       GROUP_CONCAT(t.name, char(31)) AS tag_names
FROM files f
LEFT JOIN file_tags ft ON ft.file_id = f.id
LEFT JOIN tags t       ON t.id = ft.tag_id
WHERE f.deleted_at IS NULL
{where}
GROUP BY f.id
"""


@dataclass(frozen=True)
class Record:
    """Файл в зоне — ровно то, что нужно поиску и таблице."""

    id: int
    original_name: str
    stored_path: str
    hash: str
    size: int
    added_at: datetime
    mtime: datetime | None = None
    created_at: datetime | None = None
    note: str | None = None
    source: str | None = None
    tags: tuple[str, ...] = ()

    @cached_property
    def ext(self) -> str:
        return PurePath(self.original_name).suffix.lstrip(".").casefold()

    @cached_property
    def norm_name(self) -> str:
        return normalize_text(self.original_name)

    @cached_property
    def tags_lower(self) -> frozenset[str]:
        return frozenset(normalize_tag(tag) for tag in self.tags)

    def with_tags(self, tags: tuple[str, ...]) -> "Record":
        return replace(self, tags=tags)


def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def record_from_row(row) -> Record:
    names = row["tag_names"] if "tag_names" in row.keys() else None
    tags = tuple(sorted(name for name in (names or "").split(_TAG_SEPARATOR) if name))
    return Record(
        id=int(row["id"]),
        original_name=row["original_name"],
        stored_path=row["stored_path"],
        hash=row["hash"],
        size=int(row["size"]),
        added_at=_parse_dt(row["added_at"]) or datetime.now(),
        mtime=_parse_dt(row["mtime"]),
        created_at=_parse_dt(row["created_at"]),
        note=row["note"],
        source=row["source"],
        tags=tags,
    )


class Index:
    """Потокобезопасный снимок таблицы ``files`` (без удалённых в корзину)."""

    def __init__(self) -> None:
        self._items: dict[int, Record] = {}
        self._lock = threading.RLock()

    def load(self, db: Database) -> None:
        rows = db.query(_SELECT_FILES.format(where=""))
        items = {record.id: record for record in map(record_from_row, rows)}
        with self._lock:
            self._items = items

    def refresh(self, db: Database, file_id: int) -> Record | None:
        """Перечитать одну запись (после смены тегов/заметки)."""
        row = db.query_one(_SELECT_FILES.format(where="AND f.id = ?"), (file_id,))
        record = record_from_row(row) if row is not None else None
        with self._lock:
            if record is None:
                self._items.pop(file_id, None)
            else:
                self._items[file_id] = record
        return record

    def remove(self, file_id: int) -> None:
        with self._lock:
            self._items.pop(file_id, None)

    def get(self, file_id: int) -> Record | None:
        with self._lock:
            return self._items.get(file_id)

    def snapshot(self) -> tuple[Record, ...]:
        with self._lock:
            return tuple(self._items.values())

    def __len__(self) -> int:
        with self._lock:
            return len(self._items)
