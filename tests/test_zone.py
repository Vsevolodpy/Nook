from pathlib import Path
import zipfile

from conftest import record_by_name


def test_add_copies_file_into_flat_zone(library, make_file):
    source = make_file("конспект.pdf", b"pdf-data")
    result = library.zone.add(source, tags=["учёба"])

    assert result.status == "added"
    record = result.record
    assert record is not None
    assert record.original_name == "конспект.pdf"
    assert record.stored_path.startswith("files/")
    assert record.stored_path.endswith(".pdf")
    assert record.size == len(b"pdf-data")
    assert record.tags == ("учёба",)
    assert library.zone.absolute(record.stored_path).read_bytes() == b"pdf-data"
    assert source.exists(), "по умолчанию файл копируется, оригинал остаётся"


def test_duplicate_by_content_is_rejected(library, make_file):
    first = make_file("договор.pdf", b"same-bytes")
    second = make_file("договор (копия).pdf", b"same-bytes")

    assert library.zone.add(first).status == "added"
    duplicate = library.zone.add(second)

    assert duplicate.status == "duplicate"
    assert "Уже есть" in duplicate.message
    assert len(library.index) == 1
    assert len(list(library.settings.files_dir.iterdir())) == 1


def test_same_name_different_content_is_allowed(library, make_file):
    first = make_file("отчёт.docx", b"v1")
    assert library.zone.add(first).status == "added"

    second = make_file("отчёт.docx", b"v2")
    assert library.zone.add(second).status == "added"
    assert len(library.index) == 2


def test_add_missing_file_returns_error(library, tmp_path):
    result = library.zone.add(tmp_path / "нет-такого.pdf")
    assert result.status == "error"
    assert "не найден" in result.message.lower()


def test_add_directory_is_rejected(library, tmp_path):
    folder = tmp_path / "папка с документами"
    folder.mkdir()

    result = library.zone.add(folder)

    assert result.status == "error"
    assert "папка" in result.message.lower()
    assert "нельзя" in result.message.lower()
    assert len(library.index) == 0


def test_move_mode_removes_original(library, make_file):
    library.settings.copy_mode = "move"
    source = make_file("переезд.txt", b"move-me")

    result = library.zone.add(source)

    assert result.status == "added"
    assert not source.exists()
    assert library.zone.absolute(result.record.stored_path).read_bytes() == b"move-me"
    library.settings.copy_mode = "copy"


def test_delete_moves_to_trash_and_restore_brings_back(library, make_file):
    source = make_file("черновик.txt", b"trash-me")
    record = library.zone.add(source).record
    stored = library.zone.absolute(record.stored_path)

    assert library.zone.delete([record.id]) == 1
    assert library.index.get(record.id) is None
    assert not stored.exists()
    assert len(list(library.settings.trash_dir.iterdir())) == 1

    row = library.db.query_one("SELECT deleted_at, trash_path FROM files WHERE id = ?", (record.id,))
    assert row["deleted_at"] is not None
    assert row["trash_path"].startswith("trash/")

    assert library.zone.restore([record.id]) == 1
    assert library.index.get(record.id) is not None
    assert stored.exists()
    assert library.zone.absolute(row["trash_path"]).exists() is False


def test_trashed_file_is_not_found_by_search(library, make_file):
    record = library.zone.add(make_file("скрытый.txt", b"hidden")).record
    library.zone.delete([record.id])

    payload = library.search("скрытый")
    assert payload["items"] == []


def test_export_zip_contains_files_and_manifest(library, make_file, tmp_path):
    library.zone.add(make_file("смета.xlsx", b"xlsx"), ["учёба"])
    library.zone.add(make_file("договор.pdf", b"pdf"), [])

    target = tmp_path / "export.zip"
    path = library.zone.export_zip(target)

    assert path.exists()
    with zipfile.ZipFile(path) as archive:
        names = archive.namelist()
        assert "manifest.json" in names
        assert "files/смета.xlsx" in names
        assert "files/договор.pdf" in names
        manifest = archive.read("manifest.json").decode("utf-8")
        assert "учёба" in manifest
        assert b"xlsx" in archive.read("files/смета.xlsx")


def test_export_zip_deduplicates_same_names(library, make_file, tmp_path):
    library.zone.add(make_file("отчёт.docx", b"v1"))
    library.zone.add(make_file("отчёт.docx", b"v2"))

    target = tmp_path / "export.zip"
    library.zone.export_zip(target)

    with zipfile.ZipFile(target) as archive:
        names = [name for name in archive.namelist() if name.startswith("files/")]
    assert sorted(names) == ["files/отчёт (2).docx", "files/отчёт.docx"]


def test_stats_counts_files_bytes_and_tags(library, make_file):
    library.zone.add(make_file("a.txt", b"12345"), ["тег"])
    library.zone.add(make_file("b.txt", b"123"), [])

    stats = library.zone.stats()
    assert stats["files"] == 2
    assert stats["bytes"] == 8
    assert stats["tags"] == 1


def test_purge_trash_removes_records_and_files(library, make_file):
    record = library.zone.add(make_file("мусор.txt", b"junk")).record
    library.zone.delete([record.id])

    assert library.zone.purge_trash() == 1
    assert library.db.query_one("SELECT id FROM files WHERE id = ?", (record.id,)) is None
    assert not list(library.settings.trash_dir.iterdir())


def test_stored_paths_have_uuid_names(library, make_file):
    record = library.zone.add(make_file("Очень важный документ 2024.docx", b"data")).record
    stored = Path(record.stored_path).name
    assert record.original_name == "Очень важный документ 2024.docx"
    assert stored != record.original_name
    assert len(stored.split(".")[0]) == 32


def test_note_is_saved(library, make_file):
    record = library.zone.add(make_file("note.txt", b"n"), note="подписанный скан").record
    assert record.note == "подписанный скан"

    updated = library.zone.set_note(record.id, "другая заметка")
    assert updated.note == "другая заметка"
    assert library.index.get(record.id).note == "другая заметка"
    assert library.zone.set_note(record.id, "").note is None
