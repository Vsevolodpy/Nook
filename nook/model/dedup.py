"""Проверка «этот файл уже в зоне?» по SHA-256 содержимого."""

from __future__ import annotations

import hashlib
from pathlib import Path

CHUNK_SIZE = 1024 * 1024


def sha256_file(path: str | Path, chunk_size: int = CHUNK_SIZE) -> str:
    """SHA-256 файла, читая его кусками (большие файлы не грузим в память)."""
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        while chunk := handle.read(chunk_size):
            digest.update(chunk)
    return digest.hexdigest()


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()
