"""Теги: единственный способ «собрать файлы вместе».

Плоские, без иерархии.  Уникальность — по нормализованному ключу
(``casefold`` + ``ё→е``), хранение — в том виде, как ввёл пользователь.
SQLite ``LOWER()`` не понимает кириллицу, поэтому ключ считаем в Python и
держим в колонке ``tags.name_key``.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterable, Sequence

from .db import Database
from .index import Index
from .query import normalize_tag


class TagStore:
    def __init__(self, db: Database, index: Index) -> None:
        self.db = db
        self.index = index

    # --- чтение -----------------------------------------------------------
    def list(self) -> list[dict[str, object]]:
        rows = self.db.query(
            """
            SELECT t.name AS name, COUNT(ft.file_id) AS count
            FROM tags t
            JOIN file_tags ft ON ft.tag_id = t.id
            JOIN files f      ON f.id = ft.file_id AND f.deleted_at IS NULL
            GROUP BY t.id
            ORDER BY t.name COLLATE NOCASE
            """
        )
        return [{"name": row["name"], "count": int(row["count"])} for row in rows]

    def suggest(self, prefix: str = "", limit: int = 12) -> list[str]:
        key = normalize_tag(prefix)
        rows = self.db.query(
            """
            SELECT t.name AS name, COUNT(ft.file_id) AS count
            FROM tags t
            LEFT JOIN file_tags ft ON ft.tag_id = t.id
            LEFT JOIN files f      ON f.id = ft.file_id AND f.deleted_at IS NULL
            WHERE t.name_key LIKE ?
            GROUP BY t.id
            ORDER BY count DESC, t.name COLLATE NOCASE
            LIMIT ?
            """,
            (f"%{key}%", max(1, int(limit))),
        )
        return [row["name"] for row in rows]

    def for_file(self, file_id: int) -> list[str]:
        rows = self.db.query(
            """
            SELECT t.name AS name
            FROM tags t
            JOIN file_tags ft ON ft.tag_id = t.id
            WHERE ft.file_id = ?
            ORDER BY t.name COLLATE NOCASE
            """,
            (file_id,),
        )
        return [row["name"] for row in rows]

    # --- запись -----------------------------------------------------------
    def set_for_file(self, file_id: int, names: Iterable[str]) -> list[str]:
        """Заменить набор тегов файла целиком."""
        wanted = self._normalize_names(names)
        with self.db.transaction() as conn:
            conn.execute("DELETE FROM file_tags WHERE file_id = ?", (file_id,))
            for name in wanted:
                tag_id = self._ensure_tag(conn, name)
                conn.execute(
                    "INSERT OR IGNORE INTO file_tags(file_id, tag_id) VALUES (?, ?)",
                    (file_id, tag_id),
                )
        self.index.refresh(self.db, file_id)
        return self.for_file(file_id)

    def assign(self, file_ids: Sequence[int], name: str) -> int:
        """Повесить тег на несколько файлов. Возвращает число новых связей."""
        tag_name = self._clean(name)
        if not tag_name or not file_ids:
            return 0
        added = 0
        with self.db.transaction() as conn:
            tag_id = self._ensure_tag(conn, tag_name)
            for file_id in file_ids:
                cursor = conn.execute(
                    "INSERT OR IGNORE INTO file_tags(file_id, tag_id) VALUES (?, ?)",
                    (file_id, tag_id),
                )
                added += cursor.rowcount
        self._refresh(file_ids)
        return added

    def unassign(self, file_ids: Sequence[int], name: str) -> int:
        tag = self.db.query_one("SELECT id FROM tags WHERE name_key = ?", (normalize_tag(name),))
        if tag is None or not file_ids:
            return 0
        removed = 0
        with self.db.transaction() as conn:
            for file_id in file_ids:
                cursor = conn.execute(
                    "DELETE FROM file_tags WHERE file_id = ? AND tag_id = ?",
                    (file_id, tag["id"]),
                )
                removed += cursor.rowcount
        self._refresh(file_ids)
        return removed

    def rename(self, old: str, new: str) -> dict[str, object]:
        """Переименовать тег; если целевой уже есть — слить с ним."""
        new_name = self._clean(new)
        old_tag = self.db.query_one("SELECT id, name FROM tags WHERE name_key = ?", (normalize_tag(old),))
        if old_tag is None:
            return {"ok": False, "error": "Тег не найден"}
        if not new_name:
            return {"ok": False, "error": "Пустое имя тега"}
        if normalize_tag(new_name) == normalize_tag(old):
            return {"ok": True, "merged": False, "affected": 0}

        target = self.db.query_one("SELECT id FROM tags WHERE name_key = ?", (normalize_tag(new_name),))
        if target is not None:
            result = self.merge([old], new_name)
            return {"ok": True, "merged": True, "affected": result}

        affected = self._file_ids_for_tag(int(old_tag["id"]))
        with self.db.transaction() as conn:
            conn.execute(
                "UPDATE tags SET name = ?, name_key = ? WHERE id = ?",
                (new_name, normalize_tag(new_name), old_tag["id"]),
            )
        self._refresh(affected)
        return {"ok": True, "merged": False, "affected": len(affected)}

    def merge(self, sources: Iterable[str], target: str) -> int:
        """Слить теги ``sources`` в ``target``. Возвращает число затронутых файлов."""
        target_name = self._clean(target)
        if not target_name:
            raise ValueError("Пустое имя целевого тега")

        affected: set[int] = set()
        with self.db.transaction() as conn:
            target_id = self._ensure_tag(conn, target_name)
            for source in sources:
                source_key = normalize_tag(source)
                if not source_key or source_key == normalize_tag(target_name):
                    continue
                row = conn.execute(
                    "SELECT id FROM tags WHERE name_key = ?", (source_key,)
                ).fetchone()
                if row is None:
                    continue
                source_id = int(row["id"])
                file_ids = [
                    int(item["file_id"])
                    for item in conn.execute(
                        "SELECT file_id FROM file_tags WHERE tag_id = ?", (source_id,)
                    ).fetchall()
                ]
                affected.update(file_ids)
                conn.execute(
                    "INSERT OR IGNORE INTO file_tags(file_id, tag_id) "
                    "SELECT file_id, ? FROM file_tags WHERE tag_id = ?",
                    (target_id, source_id),
                )
                conn.execute("DELETE FROM file_tags WHERE tag_id = ?", (source_id,))
                conn.execute("DELETE FROM tags WHERE id = ?", (source_id,))
        self._refresh(affected)
        return len(affected)

    def cleanup(self) -> int:
        """Удалить теги без файлов (вызывается при старте)."""
        with self.db.transaction() as conn:
            cursor = conn.execute(
                "DELETE FROM tags WHERE id NOT IN (SELECT tag_id FROM file_tags)"
            )
        return cursor.rowcount

    # --- внутреннее -------------------------------------------------------
    @staticmethod
    def _clean(name: str) -> str:
        return " ".join((name or "").strip().lstrip("#№").split())

    def _normalize_names(self, names: Iterable[str]) -> list[str]:
        result: list[str] = []
        seen: set[str] = set()
        for raw in names or ():
            name = self._clean(raw)
            key = normalize_tag(name)
            if not key or key in seen:
                continue
            seen.add(key)
            result.append(name)
        return result

    def _ensure_tag(self, conn: sqlite3.Connection, name: str) -> int:
        key = normalize_tag(name)
        row = conn.execute("SELECT id FROM tags WHERE name_key = ?", (key,)).fetchone()
        if row is not None:
            return int(row["id"])
        cursor = conn.execute("INSERT INTO tags(name, name_key) VALUES (?, ?)", (name, key))
        return int(cursor.lastrowid)

    def _file_ids_for_tag(self, tag_id: int) -> list[int]:
        rows = self.db.query("SELECT file_id FROM file_tags WHERE tag_id = ?", (tag_id,))
        return [int(row["file_id"]) for row in rows]

    def _refresh(self, file_ids: Iterable[int]) -> None:
        for file_id in set(file_ids):
            self.index.refresh(self.db, file_id)
