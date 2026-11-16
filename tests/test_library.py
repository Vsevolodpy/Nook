import json

from nook.model.config import Settings
from nook.model.library import Library, human_size


def test_add_paths_payload(library, make_file, tmp_path):
    first = make_file("one.txt", b"1")
    duplicate = make_file("one-copy.txt", b"1")

    payload = library.add_paths([str(first), str(duplicate), str(tmp_path / "нет.txt")], ["тег"])

    assert payload["added"] == ["one.txt"]
    assert len(payload["duplicates"]) == 1
    assert len(payload["errors"]) == 1
    assert payload["total"] == 3
    assert len(library.index) == 1


def test_state_and_stats(library, make_file):
    library.zone.add(make_file("a.txt", b"1234"), ["тег"])

    stats = library.stats()
    assert stats["files"] == 1
    assert stats["bytes"] == 4
    assert stats["tags"] == 1
    assert stats["vault"] == str(library.settings.vault_dir)


def test_delete_and_restore_via_library(library, make_file):
    record = library.zone.add(make_file("a.txt", b"a")).record

    assert library.delete([record.id])["deleted"] == 1
    assert library.restore([record.id])["restored"] == 1
    assert library.index.get(record.id) is not None


def test_settings_roundtrip(tmp_path):
    settings = Settings(data_dir=tmp_path / "data", vault_dir=tmp_path / "vault")
    settings.copy_mode = "move"
    settings.window_width = 900
    settings.save()

    loaded = Settings.load(settings.config_path)

    assert loaded.copy_mode == "move"
    assert loaded.window_width == 900
    assert loaded.vault_dir == tmp_path / "vault"

    raw = json.loads((tmp_path / "data" / "config.json").read_text(encoding="utf-8"))
    assert raw["vault_dir"] == str(tmp_path / "vault")


def test_settings_tolerate_broken_file(tmp_path):
    config = tmp_path / "config.json"
    config.write_text("{не json", encoding="utf-8")

    settings = Settings.load(config)

    assert settings.vault_dir == tmp_path / "vault"
    assert settings.copy_mode == "copy"


def test_settings_ignore_unknown_copy_mode(tmp_path):
    config = tmp_path / "config.json"
    config.write_text(json.dumps({"copy_mode": "delete"}), encoding="utf-8")

    assert Settings.load(config).copy_mode == "copy"


def test_library_survives_reopen(library, make_file):
    record = library.zone.add(make_file("a.txt", b"a"), ["тег"]).record
    library.close()

    reopened = Library(library.settings)
    try:
        assert reopened.index.get(record.id) is not None
        assert reopened.tags.for_file(record.id) == ["тег"]
    finally:
        reopened.close()


def test_human_size():
    assert human_size(0) == "0 Б"
    assert human_size(999) == "999 Б"
    assert human_size(1024) == "1 КБ"
    assert human_size(1536) == "1.5 КБ"


def test_created_at_is_saved_and_serialized(library, make_file):
    record = library.zone.add(make_file("a.txt", b"a")).record

    assert record.created_at is not None
    item = library.search("a")["items"][0]
    assert item["created_at_human"]
    assert item["mtime_at_human"]


def test_schema_migrates_from_v1(settings, tmp_path):
    """Старая база (v1) открывается, получает created_at и не теряет записи."""
    import sqlite3

    from nook.model.db import _SCHEMA_V1

    connection = sqlite3.connect(settings.db_path)
    connection.executescript(_SCHEMA_V1)
    connection.execute("PRAGMA user_version = 1")
    connection.execute(
        "INSERT INTO files(original_name, stored_path, hash, size, added_at) "
        "VALUES ('old.txt', 'files/old.txt', 'hash', 3, '2024-01-01T00:00:00')"
    )
    connection.commit()
    connection.close()

    migrated = Library(settings)
    try:
        columns = {row["name"] for row in migrated.db.query("PRAGMA table_info(files)")}
        assert "created_at" in columns
        records = migrated.index.snapshot()
        assert len(records) == 1
        assert records[0].original_name == "old.txt"
        assert records[0].created_at is None
    finally:
        migrated.close()
