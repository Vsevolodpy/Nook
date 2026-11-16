"""Зона: физическое хранение файлов, корзина, открытие и экспорт.

Плоская раскладка ``vault/files/<uuid>.<ext>``; человекочитаемое имя живёт
только в базе.  Удаление — перенос в ``vault/trash/`` с сохранением записи,
чтобы файл можно было вернуть.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import uuid
import zipfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import Iterable, Sequence

from .config import Settings
from .db import Database
from .dedup import sha256_file
from .index import Index, Record
from .tags import TagStore

MAX_NAME_LEN = 120


@dataclass
class AddResult:
    status: str  # added | duplicate | error
    message: str = ""
    record: Record | None = None

    @property
    def ok(self) -> bool:
        return self.status == "added"


def _now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


class Zone:
    def __init__(self, settings: Settings, db: Database, index: Index, tags: TagStore) -> None:
        self.settings = settings
        self.db = db
        self.index = index
        self.tags = tags

    # --- пути -------------------------------------------------------------
    def absolute(self, stored_path: str) -> Path:
        return self.settings.vault_dir / PurePosixPath(stored_path)

    def absolute_for(self, record: Record) -> Path:
        return self.absolute(record.stored_path)

    # --- добавление -------------------------------------------------------
    def add(
        self,
        path: str | Path,
        tags: Iterable[str] = (),
        note: str | None = None,
        source: str | None = None,
    ) -> AddResult:
        src = Path(path).expanduser()
        if not src.exists():
            return AddResult("error", f"Файл не найден: {src}")
        if src.is_dir():
            return AddResult(
                "error",
                f"«{src.name}» — папка. В хранилище нельзя добавлять папки: "
                "откройте её и перетащите нужные файлы.",
            )
        if not src.is_file():
            return AddResult("error", f"«{src.name}» — не обычный файл, добавить нельзя.")

        try:
            digest = sha256_file(src)
            source_stat = src.stat()
        except OSError as error:
            return AddResult("error", f"Не удалось прочитать {src.name}: {error}")

        existing = self.db.query_one(
            "SELECT id, original_name, added_at, stored_path FROM files "
            "WHERE hash = ? AND deleted_at IS NULL",
            (digest,),
        )
        if existing is not None:
            added = _format_added(existing["added_at"])
            return AddResult(
                "duplicate",
                f"Уже есть: «{existing['original_name']}» (добавлен {added})",
                self.index.get(int(existing["id"])),
            )

        self.settings.ensure()
        suffix = src.suffix
        stored_rel = f"files/{uuid.uuid4().hex}{suffix}"
        destination = self.absolute(stored_rel)

        try:
            if self.settings.copy_mode == "move":
                shutil.move(str(src), destination)
            else:
                shutil.copy2(src, destination)
        except OSError as error:
            return AddResult("error", f"Не удалось скопировать {src.name}: {error}")

        stat = source_stat if source_stat is not None else destination.stat()
        try:
            with self.db.transaction() as conn:
                cursor = conn.execute(
                    """
                    INSERT INTO files(original_name, stored_path, hash, size,
                                      added_at, mtime, created_at, note, source)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        src.name[:MAX_NAME_LEN] or stored_rel,
                        stored_rel,
                        digest,
                        destination.stat().st_size,
                        _now_iso(),
                        datetime.fromtimestamp(stat.st_mtime).isoformat(timespec="seconds"),
                        datetime.fromtimestamp(stat.st_ctime).isoformat(timespec="seconds"),
                        (note or "").strip() or None,
                        source,
                    ),
                )
                file_id = int(cursor.lastrowid)
        except Exception as error:  # noqa: BLE001 - откатываем копию при любой ошибке записи
            destination.unlink(missing_ok=True)
            duplicate = self.db.query_one(
                "SELECT id FROM files WHERE hash = ? AND deleted_at IS NULL", (digest,)
            )
            if duplicate is not None:
                return AddResult(
                    "duplicate",
                    "Уже есть в зоне",
                    self.index.get(int(duplicate["id"])),
                )
            return AddResult("error", f"Не удалось добавить {src.name}: {error}")

        self.tags.set_for_file(file_id, tags)
        record = self.index.get(file_id)
        return AddResult("added", f"Добавлено: «{src.name}»", record)

    def add_many(
        self,
        paths: Sequence[str | Path],
        tags: Iterable[str] = (),
        note: str | None = None,
        source: str | None = None,
    ) -> list[AddResult]:
        tag_list = list(tags)
        return [self.add(path, tag_list, note, source) for path in paths]

    # --- удаление / корзина ----------------------------------------------
    def delete(self, file_ids: Iterable[int]) -> int:
        moved = 0
        for file_id in dict.fromkeys(int(item) for item in file_ids):
            row = self.db.query_one(
                "SELECT id, stored_path FROM files WHERE id = ? AND deleted_at IS NULL",
                (file_id,),
            )
            if row is None:
                continue
            source = self.absolute(row["stored_path"])
            trash_rel = f"trash/{Path(row['stored_path']).name}"
            destination = self.absolute(trash_rel)
            if source.exists():
                destination.parent.mkdir(parents=True, exist_ok=True)
                try:
                    shutil.move(str(source), destination)
                except OSError:
                    shutil.copy2(source, destination)
                    source.unlink(missing_ok=True)
            with self.db.transaction() as conn:
                conn.execute(
                    "UPDATE files SET deleted_at = ?, trash_path = ? WHERE id = ?",
                    (_now_iso(), trash_rel, file_id),
                )
            self.index.remove(file_id)
            moved += 1
        return moved

    def restore(self, file_ids: Iterable[int]) -> int:
        restored = 0
        for file_id in dict.fromkeys(int(item) for item in file_ids):
            row = self.db.query_one(
                "SELECT id, stored_path, trash_path FROM files "
                "WHERE id = ? AND deleted_at IS NOT NULL",
                (file_id,),
            )
            if row is None:
                continue
            source = self.absolute(row["trash_path"] or row["stored_path"])
            destination = self.absolute(row["stored_path"])
            if source.exists():
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(source), destination)
            with self.db.transaction() as conn:
                conn.execute(
                    "UPDATE files SET deleted_at = NULL, trash_path = NULL WHERE id = ?",
                    (file_id,),
                )
            self.index.refresh(self.db, file_id)
            restored += 1
        return restored

    def purge_trash(self) -> int:
        """Стереть корзину навсегда (файлы и записи)."""
        rows = self.db.query("SELECT id, trash_path FROM files WHERE deleted_at IS NOT NULL")
        for row in rows:
            if row["trash_path"]:
                self.absolute(row["trash_path"]).unlink(missing_ok=True)
        with self.db.transaction() as conn:
            conn.execute("DELETE FROM files WHERE deleted_at IS NOT NULL")
        return len(rows)

    # --- действия с файлом ------------------------------------------------
    def open(self, file_id: int) -> tuple[bool, str]:
        record = self.index.get(file_id)
        if record is None:
            return False, "Файл не найден в зоне"
        path = self.absolute_for(record)
        if not path.exists():
            return False, f"Файл пропал с диска: {path}"
        try:
            if sys.platform == "win32":
                os.startfile(str(path))  # type: ignore[attr-defined]
            elif sys.platform == "darwin":
                subprocess.Popen(["open", str(path)])
            else:
                subprocess.Popen(["xdg-open", str(path)])
        except OSError as error:
            return False, f"Не удалось открыть: {error}"
        return True, ""

    def reveal(self, file_id: int) -> tuple[bool, str]:
        record = self.index.get(file_id)
        if record is None:
            return False, "Файл не найден в зоне"
        path = self.absolute_for(record)
        try:
            if sys.platform == "win32":
                subprocess.Popen(["explorer", "/select,", str(path)])
            elif sys.platform == "darwin":
                subprocess.Popen(["open", "-R", str(path)])
            else:
                subprocess.Popen(["xdg-open", str(path.parent)])
        except OSError as error:
            return False, f"Не удалось показать: {error}"
        return True, ""

    def reveal_dir(self, path: str | Path) -> tuple[bool, str]:
        """Открыть каталог (зону или корзину) в системном файловом менеджере."""
        target = Path(path)
        target.mkdir(parents=True, exist_ok=True)
        try:
            if sys.platform == "win32":
                os.startfile(str(target))  # type: ignore[attr-defined]
            elif sys.platform == "darwin":
                subprocess.Popen(["open", str(target)])
            else:
                subprocess.Popen(["xdg-open", str(target)])
        except OSError as error:
            return False, f"Не удалось открыть каталог: {error}"
        return True, ""

    def set_note(self, file_id: int, note: str | None) -> Record | None:
        with self.db.transaction() as conn:
            conn.execute("UPDATE files SET note = ? WHERE id = ?", ((note or "").strip() or None, file_id))
        return self.index.refresh(self.db, file_id)

    # --- экспорт ----------------------------------------------------------
    def export_zip(self, target: str | Path | None = None) -> Path:
        """Собрать удобный zip для переноса (не бэкап!)."""
        self.settings.exports_dir.mkdir(parents=True, exist_ok=True)
        if target is None:
            stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
            target = self.settings.exports_dir / f"nook-export-{stamp}.zip"
        target = Path(target)
        target.parent.mkdir(parents=True, exist_ok=True)

        manifest: list[dict[str, object]] = []
        used: set[str] = set()
        with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for record in self.index.snapshot():
                source = self.absolute_for(record)
                if not source.exists():
                    continue
                arcname = _unique_name(record.original_name, used)
                archive.write(source, f"files/{arcname}")
                manifest.append(
                    {
                        "name": record.original_name,
                        "file": f"files/{arcname}",
                        "tags": list(record.tags),
                        "added_at": record.added_at.isoformat(),
                        "note": record.note,
                        "size": record.size,
                        "sha256": record.hash,
                    }
                )
            archive.writestr(
                "manifest.json",
                json.dumps(
                    {"app": "Nook", "exported_at": _now_iso(), "files": manifest},
                    ensure_ascii=False,
                    indent=2,
                ),
            )
        return target

    # --- статистика -------------------------------------------------------
    def stats(self) -> dict[str, object]:
        records = self.index.snapshot()
        return {
            "files": len(records),
            "bytes": sum(record.size for record in records),
            "tags": len({tag for record in records for tag in record.tags}),
            "vault": str(self.settings.vault_dir),
        }


def _format_added(value: str | None) -> str:
    try:
        return datetime.fromisoformat(value or "").strftime("%d.%m.%Y")
    except ValueError:
        return "?"


def _unique_name(name: str, used: set[str]) -> str:
    name = name or "file"
    if name.casefold() not in used:
        used.add(name.casefold())
        return name
    stem = Path(name).stem
    suffix = Path(name).suffix
    counter = 2
    while f"{stem} ({counter}){suffix}".casefold() in used:
        counter += 1
    result = f"{stem} ({counter}){suffix}"
    used.add(result.casefold())
    return result
