"""SQLite-слой: схема, миграции и потокобезопасный доступ.

Соединение одно на процесс: pywebview вызывает методы Api из разных потоков,
поэтому все обращения идут через ``RLock``.  Транзакции — явные, через
:meth:`Database.transaction`.
"""

from __future__ import annotations

import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator, Sequence

SCHEMA_VERSION = 1

_SCHEMA_V1 = """
CREATE TABLE IF NOT EXISTS files (
    id            INTEGER PRIMARY KEY,
    original_name TEXT    NOT NULL,
    stored_path   TEXT    NOT NULL UNIQUE,   -- относительно vault/
    hash          TEXT    NOT NULL,          -- SHA-256 содержимого
    size          INTEGER NOT NULL,
    added_at      TEXT    NOT NULL,          -- локальное время, ISO 8601
    mtime         TEXT,
    note          TEXT,
    source        TEXT,
    deleted_at    TEXT,                      -- NULL = файл в зоне
    trash_path    TEXT                       -- относительно vault/
);

CREATE TABLE IF NOT EXISTS tags (
    id       INTEGER PRIMARY KEY,
    name     TEXT NOT NULL,              -- как ввёл пользователь
    name_key TEXT NOT NULL               -- нормализованный ключ уникальности
);

CREATE TABLE IF NOT EXISTS file_tags (
    file_id INTEGER NOT NULL REFERENCES files(id) ON DELETE CASCADE,
    tag_id  INTEGER NOT NULL REFERENCES tags(id)  ON DELETE CASCADE,
    PRIMARY KEY (file_id, tag_id)
);

CREATE TABLE IF NOT EXISTS search_log (
    id     INTEGER PRIMARY KEY,
    query  TEXT NOT NULL,
    results_count INTEGER NOT NULL,
    ts     TEXT NOT NULL
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_tag_key ON tags(name_key);
CREATE UNIQUE INDEX IF NOT EXISTS idx_hash ON files(hash) WHERE deleted_at IS NULL;
CREATE INDEX IF NOT EXISTS idx_added_at ON files(added_at);
CREATE INDEX IF NOT EXISTS idx_file_tags_tag ON file_tags(tag_id);
"""

MIGRATIONS: tuple[str, ...] = (_SCHEMA_V1,)


class Database:
    """Тонкая обёртка над sqlite3 с блокировкой и миграциями."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self._lock = threading.RLock()
        self._conn: sqlite3.Connection | None = None

    # --- соединение -------------------------------------------------------
    def connect(self) -> sqlite3.Connection:
        with self._lock:
            if self._conn is None:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                conn = sqlite3.connect(str(self.path), check_same_thread=False, timeout=15.0)
                conn.row_factory = sqlite3.Row
                conn.execute("PRAGMA journal_mode = WAL")
                conn.execute("PRAGMA synchronous = NORMAL")
                conn.execute("PRAGMA foreign_keys = ON")
                self._conn = conn
            return self._conn

    def close(self) -> None:
        with self._lock:
            if self._conn is not None:
                self._conn.close()
                self._conn = None

    # --- схема ------------------------------------------------------------
    def initialize(self) -> None:
        with self._lock:
            conn = self.connect()
            version = conn.execute("PRAGMA user_version").fetchone()[0]
            for index in range(version, len(MIGRATIONS)):
                conn.executescript(MIGRATIONS[index])
                conn.execute(f"PRAGMA user_version = {index + 1}")
                conn.commit()

    # --- запросы ----------------------------------------------------------
    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        with self._lock:
            conn = self.connect()
            try:
                yield conn
            except BaseException:
                conn.rollback()
                raise
            else:
                conn.commit()

    def execute(self, sql: str, params: Sequence[object] = ()) -> sqlite3.Cursor:
        with self._lock:
            return self.connect().execute(sql, params)

    def executemany(self, sql: str, rows: Sequence[Sequence[object]]) -> sqlite3.Cursor:
        with self._lock:
            return self.connect().executemany(sql, rows)

    def query(self, sql: str, params: Sequence[object] = ()) -> list[sqlite3.Row]:
        with self._lock:
            return list(self.connect().execute(sql, params).fetchall())

    def query_one(self, sql: str, params: Sequence[object] = ()) -> sqlite3.Row | None:
        with self._lock:
            return self.connect().execute(sql, params).fetchone()
