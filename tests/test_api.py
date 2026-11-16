"""Мост JS ⇄ Python: диалоги, экспорт, устойчивость к сбоям pywebview."""

from pathlib import Path
import zipfile

from webview.util import parse_file_type

from nook.controller.main import ALL_FILES_FILTER, Api, ZIP_FILES_FILTER


class FakeWindow:
    """Заглушка окна pywebview: запоминает вызовы и умеет падать по заказу."""

    def __init__(self, result=None, error: Exception | None = None) -> None:
        self.result = result
        self.error = error
        self.calls: list[dict] = []

    def create_file_dialog(self, *args, **kwargs):
        self.calls.append(kwargs)
        if self.error is not None:
            raise self.error
        return self.result


def make_api(library, window: FakeWindow) -> Api:
    api = Api(library)
    api.attach(window)
    return api


def test_filters_are_accepted_by_pywebview():
    """Ровно та проверка, на которой падал экспорт: ZIP-архив (*.zip)."""
    assert parse_file_type(ZIP_FILES_FILTER) == ("ZIP архив", "*.zip")
    description, pattern = parse_file_type(ALL_FILES_FILTER)
    assert description == "Все файлы"
    assert pattern == "*.*"


def test_export_zip_to_selected_path(library, make_file, tmp_path):
    library.zone.add(make_file("a.txt", b"a"))
    target = tmp_path / "nook.zip"
    api = make_api(library, FakeWindow(result=str(target)))

    result = api.export_zip()

    assert result["ok"] is True
    assert Path(result["path"]) == target
    assert result["count"] == 1
    with zipfile.ZipFile(target) as archive:
        assert "manifest.json" in archive.namelist()
        assert "files/a.txt" in archive.namelist()


def test_export_zip_empty_zone(library, tmp_path):
    target = tmp_path / "empty.zip"
    api = make_api(library, FakeWindow(result=str(target)))

    result = api.export_zip()

    assert result["ok"] is True
    assert result["count"] == 0
    with zipfile.ZipFile(target) as archive:
        assert archive.namelist() == ["manifest.json"]


def test_export_zip_cancelled(library):
    api = make_api(library, FakeWindow(result=None))

    assert api.export_zip() == {"ok": False, "canceled": True}


def test_export_zip_falls_back_when_dialog_fails(library, make_file):
    """Даже если диалог сломан, экспорт пишет файл в папку экспорта."""
    library.zone.add(make_file("a.txt", b"a"))
    api = make_api(library, FakeWindow(error=ValueError("is not a valid file filter")))

    result = api.export_zip()

    assert result["ok"] is True
    path = Path(result["path"])
    assert path.exists()
    assert path.parent == library.settings.exports_dir
    with zipfile.ZipFile(path) as archive:
        assert "files/a.txt" in archive.namelist()


def test_export_zip_dialog_gets_valid_filter(library, make_file, tmp_path):
    api = make_api(library, FakeWindow(result=str(tmp_path / "x.zip")))
    api.export_zip()

    assert api._window.calls[0]["file_types"] == (ZIP_FILES_FILTER,)


def test_pick_files_returns_paths(library, tmp_path):
    chosen = [str(tmp_path / "one.pdf"), str(tmp_path / "two.pdf")]
    api = make_api(library, FakeWindow(result=chosen))

    result = api.pick_files()

    assert result["ok"] is True
    assert result["paths"] == chosen
    assert api._window.calls[0]["file_types"] == (ALL_FILES_FILTER,)


def test_tags_for_files_endpoint(library, make_file):
    first = library.zone.add(make_file("a.txt", b"a"), ["общий"]).record
    second = library.zone.add(make_file("b.txt", b"b"), ["общий"]).record
    api = make_api(library, FakeWindow())

    result = api.tags_for_files([first.id, second.id])

    assert result == {"ok": True, "tags": [{"name": "общий", "count": 2}]}


def test_api_never_raises_to_js(library):
    api = make_api(library, FakeWindow(error=RuntimeError("boom")))
    api.attach(FakeWindow(error=RuntimeError("boom")))

    result = api.open_file(999)

    assert result["ok"] is False
    assert "error" in result
