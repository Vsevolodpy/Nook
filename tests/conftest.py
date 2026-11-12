import re
import shutil
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from nook.model.config import Settings  # noqa: E402
from nook.model.library import Library  # noqa: E402


@pytest.fixture
def tmp_path(request) -> Path:
    """Свой tmp_path: pytest создаёт каталоги с mode=0700, что ломает песочницы."""
    base = ROOT / ".tmp-tests"
    slug = re.sub(r"[^A-Za-z0-9_.-]+", "_", request.node.nodeid)[:80]
    path = base / slug
    shutil.rmtree(path, ignore_errors=True)
    path.mkdir(parents=True, exist_ok=True)
    try:
        yield path
    finally:
        shutil.rmtree(path, ignore_errors=True)


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    config = Settings(data_dir=tmp_path / "data", vault_dir=tmp_path / "data" / "vault")
    config.ensure()
    return config


@pytest.fixture
def library(settings: Settings):
    instance = Library(settings)
    yield instance
    instance.close()


@pytest.fixture
def make_file(tmp_path: Path):
    source = tmp_path / "src"
    source.mkdir()

    def _make(name: str, content: bytes | None = None) -> Path:
        path = source / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content if content is not None else name.encode("utf-8"))
        return path

    return _make


def set_added_at(library: Library, file_id: int, value: str) -> None:
    library.db.execute("UPDATE files SET added_at = ? WHERE id = ?", (value, file_id))
    library.index.refresh(library.db, file_id)


def record_by_name(library: Library, name: str):
    for record in library.index.snapshot():
        if record.original_name == name:
            return record
    raise AssertionError(f"Нет файла {name}")
