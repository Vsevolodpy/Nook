from conftest import set_added_at


def seed(library, make_file):
    practice = library.zone.add(make_file("Практика_отчёт.pdf", b"a"), ["курсовая"]).record
    lecture = library.zone.add(make_file("Лекция 1.docx", b"b"), ["учёба"]).record
    estimate = library.zone.add(make_file("Смета.xlsx", b"c")).record

    set_added_at(library, practice.id, "2020-04-10T10:00:00")
    set_added_at(library, lecture.id, "2024-09-01T10:00:00")
    set_added_at(library, estimate.id, "2025-01-15T10:00:00")
    return practice, lecture, estimate


def names(payload):
    return [item["name"] for item in payload["items"]]


def test_fuzzy_by_prefix(library, make_file):
    seed(library, make_file)
    assert names(library.search("практ"))[0] == "Практика_отчёт.pdf"


def test_fuzzy_with_typo_and_two_words(library, make_file):
    seed(library, make_file)
    assert "Практика_отчёт.pdf" in names(library.search("практика отчет"))


def test_fuzzy_is_case_insensitive(library, make_file):
    seed(library, make_file)
    assert names(library.search("ПРАКТИКА")) == ["Практика_отчёт.pdf"]


def test_tag_filter_after_separator(library, make_file):
    seed(library, make_file)
    assert names(library.search("\\ #курсовая")) == ["Практика_отчёт.pdf"]


def test_bare_tag_filter(library, make_file):
    seed(library, make_file)
    assert names(library.search("#курсовая")) == ["Практика_отчёт.pdf"]


def test_negative_tag_filter(library, make_file):
    seed(library, make_file)
    assert set(names(library.search("-#курсовая"))) == {"Лекция 1.docx", "Смета.xlsx"}


def test_extension_filter(library, make_file):
    seed(library, make_file)
    assert names(library.search(".xlsx")) == ["Смета.xlsx"]
    assert names(library.search("смета.xlsx")) == ["Смета.xlsx"]


def test_extension_filter_in_params(library, make_file):
    seed(library, make_file)
    assert names(library.search("\\ .xlsx")) == ["Смета.xlsx"]
    assert names(library.search("смета \\ .xlsx")) == ["Смета.xlsx"]


def test_date_without_brackets(library, make_file):
    seed(library, make_file)
    assert names(library.search("\\ <01.01.2021")) == ["Практика_отчёт.pdf"]
    assert set(names(library.search("\\ 01.01.2024 31.12.2025"))) == {
        "Лекция 1.docx",
        "Смета.xlsx",
    }


def test_date_upper_bound(library, make_file):
    seed(library, make_file)
    assert names(library.search("\\ [<01.01.2021]")) == ["Практика_отчёт.pdf"]


def test_date_range(library, make_file):
    seed(library, make_file)
    assert set(names(library.search("\\ [01.01.2024,31.12.2025]"))) == {
        "Лекция 1.docx",
        "Смета.xlsx",
    }


def test_negative_date(library, make_file):
    seed(library, make_file)
    assert set(names(library.search("\\ -[<01.01.2021]"))) == {"Лекция 1.docx", "Смета.xlsx"}


def test_combined_text_tag_and_date(library, make_file):
    seed(library, make_file)
    assert names(library.search("практ \\ #курсовая [<01.01.2021]")) == ["Практика_отчёт.pdf"]

    payload = library.search("смета \\ #учёба")
    assert payload["items"] == []


def test_empty_query_returns_all_newest_first(library, make_file):
    seed(library, make_file)
    assert names(library.search("")) == ["Смета.xlsx", "Лекция 1.docx", "Практика_отчёт.pdf"]


def test_no_results(library, make_file):
    seed(library, make_file)
    assert library.search("абракадабра")["items"] == []


def test_limit_is_respected(library, make_file):
    seed(library, make_file)
    assert len(library.search("", limit=2)["items"]) == 2


def test_search_payload_metadata(library, make_file):
    seed(library, make_file)
    payload = library.search("практ")

    assert payload["total"] == 3
    assert payload["took_ms"] >= 0
    assert payload["query"]["text"] == "практ"

    item = payload["items"][0]
    assert item["size_human"]
    assert item["added_at_human"] == "10.04.2020 10:00"
    assert item["mtime_at_human"]
    assert item["tags"] == ["курсовая"]


def test_empty_result_queries_are_logged_once(library, make_file):
    seed(library, make_file)
    library.search("абракадабра")
    library.search("абракадабра")

    rows = library.db.query("SELECT query FROM search_log")
    assert len(rows) == 1
    assert library.recent_empty_queries() == ["абракадабра"]


def test_successful_queries_are_not_logged(library, make_file):
    seed(library, make_file)
    library.search("практ")
    assert library.db.query("SELECT * FROM search_log") == []
