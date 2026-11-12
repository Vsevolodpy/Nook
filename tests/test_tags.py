def test_tags_are_case_and_yo_insensitive(library, make_file):
    first = library.zone.add(make_file("a.txt", b"a"), ["Курсовая"]).record
    second = library.zone.add(make_file("b.txt", b"b")).record

    library.tags.assign([second.id], "КУРСОВАЯ")
    library.tags.assign([second.id], "курсовая")

    tags = library.tags.list()
    assert len(tags) == 1
    assert tags[0]["count"] == 2
    assert library.tags.for_file(first.id) == ["Курсовая"]


def test_assign_returns_only_new_links(library, make_file):
    record = library.zone.add(make_file("a.txt", b"a")).record

    assert library.tags.assign([record.id], "тег") == 1
    assert library.tags.assign([record.id], "тег") == 0
    assert library.tags.assign([record.id], "#ТЕГ") == 0


def test_set_for_file_replaces_tags(library, make_file):
    record = library.zone.add(make_file("a.txt", b"a"), ["старый", "лишний"]).record

    current = library.tags.set_for_file(record.id, ["новый", "#Новый"])

    assert current == ["новый"]
    assert library.index.get(record.id).tags == ("новый",)


def test_unassign_and_cleanup(library, make_file):
    record = library.zone.add(make_file("a.txt", b"a"), ["временный"]).record

    assert library.tags.unassign([record.id], "временный") == 1
    assert library.tags.list() == []
    assert library.tags.cleanup() == 1


def test_suggest_by_substring(library, make_file):
    record = library.zone.add(make_file("a.txt", b"a"), ["курсовая2024", "диплом"]).record
    library.tags.assign([record.id], "курсовая2023")

    suggestions = library.tags.suggest("курс")
    assert set(suggestions) == {"курсовая2024", "курсовая2023"}
    assert library.tags.suggest("") != []


def test_rename_tag(library, make_file):
    record = library.zone.add(make_file("a.txt", b"a"), ["крсовая"]).record

    result = library.tags.rename("крсовая", "курсовая")

    assert result["ok"] is True
    assert library.tags.for_file(record.id) == ["курсовая"]
    assert library.index.get(record.id).tags == ("курсовая",)


def test_rename_to_existing_merges(library, make_file):
    first = library.zone.add(make_file("a.txt", b"a"), ["курсовая"]).record
    second = library.zone.add(make_file("b.txt", b"b"), ["курсовая2024"]).record

    result = library.tags.rename("курсовая2024", "курсовая")

    assert result["merged"] is True
    assert library.tags.for_file(first.id) == ["курсовая"]
    assert library.tags.for_file(second.id) == ["курсовая"]
    assert len(library.tags.list()) == 1


def test_merge_several_tags(library, make_file):
    first = library.zone.add(make_file("a.txt", b"a"), ["учеба", "учёба"]).record
    second = library.zone.add(make_file("b.txt", b"b"), ["учебное"]).record

    affected = library.tags.merge(["учёба", "учебное"], "учеба")

    # «учёба» и «учеба» — один и тот же тег, реально переехал только «учебное».
    assert affected == 1
    assert library.tags.list() == [{"name": "учеба", "count": 2}]
    assert library.tags.for_file(first.id) == ["учеба"]
    assert library.tags.for_file(second.id) == ["учеба"]


def test_tags_survive_trash_and_restore(library, make_file):
    record = library.zone.add(make_file("a.txt", b"a"), ["тег"]).record
    library.zone.delete([record.id])

    # В корзине тег не виден, но связь сохранена — вернули файл, вернулись и теги.
    assert library.tags.list() == []
    assert library.db.query("SELECT * FROM file_tags") != []

    library.zone.restore([record.id])
    assert library.tags.for_file(record.id) == ["тег"]


def test_bulk_assign_many_files(library, make_file):
    first = library.zone.add(make_file("a.txt", b"a")).record
    second = library.zone.add(make_file("b.txt", b"b")).record

    added = library.tags.assign([first.id, second.id], "общий")

    assert added == 2
    assert library.tags.for_file(first.id) == ["общий"]
    assert library.tags.for_file(second.id) == ["общий"]
