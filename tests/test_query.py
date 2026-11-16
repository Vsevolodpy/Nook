from datetime import date, datetime

import pytest

from nook.model.query import (
    DateRange,
    normalize_tag,
    normalize_text,
    parse_bracket,
    parse_date,
    parse_query,
)


def test_plain_text_has_no_filters():
    query = parse_query("практ")
    assert query.text == "практ"
    assert query.tags == ()
    assert query.ext is None
    assert query.has_filters is False


def test_empty_query():
    assert parse_query("").is_empty
    assert parse_query("   ").is_empty


def test_separator_splits_text_and_params():
    query = parse_query("практ \\ #курсовая [<12.04.2020]")
    assert query.text == "практ"
    assert query.tags == ("курсовая",)
    assert len(query.dates) == 1
    assert query.dates[0].end == date(2020, 4, 12)
    assert query.dates[0].start is None


def test_params_only_after_separator():
    query = parse_query("Отчет №5 (копия)")
    assert query.tags == ()
    assert query.text == "отчет 5 копия"


def test_bare_tag_query_is_a_filter():
    query = parse_query("#курсовая2024")
    assert query.text == ""
    assert query.tags == ("курсовая2024",)


def test_bare_cyrillic_tag_sign():
    assert parse_query("№диплом").tags == ("диплом",)


def test_bare_negative_tag():
    query = parse_query("-#черновик")
    assert query.neg_tags == ("черновик",)


def test_text_with_hash_is_not_a_tag():
    query = parse_query("смета #2")
    assert query.tags == ()
    assert query.text == "смета 2"


def test_extension_detected():
    query = parse_query("смета.xlsx")
    assert query.ext == "xlsx"
    assert query.text == "смета"

    query = parse_query("архив.torrent")
    assert query.ext == "torrent"
    assert query.text == "архив"


@pytest.mark.parametrize("raw", ["отчет.2024", "лекция.Часть1", "версия.слишкомдлинноерасширение"])
def test_extension_not_detected(raw):
    assert parse_query(raw).ext is None


def test_extension_with_params():
    query = parse_query("смета.xlsx \\ #учёба")
    assert query.ext == "xlsx"
    assert query.tags == ("учеба",)


def test_extension_in_params():
    query = parse_query("смета \\ .xlsx")
    assert query.ext == "xlsx"
    assert query.text == "смета"
    assert parse_query("\\ *.pdf").ext == "pdf"
    assert parse_query("\\ .PDF").ext == "pdf"


def test_bare_date():
    query = parse_query("\\ 12.11.2026")
    assert query.text == ""
    assert query.dates[0].start == date(2026, 11, 12)
    assert query.dates[0].end == date(2026, 11, 12)


def test_bare_date_comparison():
    assert parse_query("\\ <12.11.2026").dates[0].end == date(2026, 11, 12)
    assert parse_query("\\ >12.11.2026").dates[0].start == date(2026, 11, 12)
    assert parse_query("\\ >=12.11.2026").dates[0].start == date(2026, 11, 12)


def test_bare_date_range_from_two_dates():
    query = parse_query("\\ 12.11.2026 31.12.2026")
    assert len(query.dates) == 1
    assert query.dates[0].start == date(2026, 11, 12)
    assert query.dates[0].end == date(2026, 12, 31)


def test_bare_date_with_text_tag_and_extension():
    query = parse_query("практ \\ #курсовая 12.04.2020 .pdf")
    assert query.text == "практ"
    assert query.tags == ("курсовая",)
    assert query.dates[0].start == date(2020, 4, 12)
    assert query.ext == "pdf"


def test_number_is_not_a_date():
    assert parse_query("\\ 2024").dates == ()
    assert parse_query("\\ 123").dates == ()


def test_brackets_still_work():
    query = parse_query("\\ [<12.04.2020]")
    assert query.dates[0].end == date(2020, 4, 12)


def test_tag_normalization_yo_and_case():
    query = parse_query("\\ #Ёлка #УЧЁБА")
    assert set(query.tags) == {"елка", "учеба"}


def test_negated_tag_in_params():
    query = parse_query("договор \\ #работа -#архив")
    assert query.tags == ("работа",)
    assert query.neg_tags == ("архив",)


def test_date_range():
    query = parse_query("\\ [12.04.2020,31.12.2024]")
    date_range = query.dates[0]
    assert date_range.start == date(2020, 4, 12)
    assert date_range.end == date(2024, 12, 31)


def test_date_range_is_swapped_when_reversed():
    date_range = parse_query("\\ [31.12.2024,12.04.2020]").dates[0]
    assert date_range.start == date(2020, 4, 12)
    assert date_range.end == date(2024, 12, 31)


def test_open_ended_ranges():
    assert parse_query("\\ [<12.04.2020]").dates[0].start is None
    assert parse_query("\\ [>12.04.2020]").dates[0].end is None
    assert parse_query("\\ [>=12.04.2020]").dates[0].start == date(2020, 4, 12)
    assert parse_query("\\ [<=12.04.2020]").dates[0].end == date(2020, 4, 12)


def test_negated_date():
    date_range = parse_query("\\ -[<12.04.2020]").dates[0]
    assert date_range.negated is True
    assert date_range.end == date(2020, 4, 12)


def test_problem_chars_inside_filename():
    query = parse_query("проект [финал]")
    assert query.dates == ()
    assert query.text == "проект финал"


def test_bad_date_is_ignored():
    assert parse_query("\\ [не дата]").dates == ()


def test_parse_date_formats():
    assert parse_date("12.04.2020") == date(2020, 4, 12)
    assert parse_date("12.04.20") == date(2020, 4, 12)
    assert parse_date("2020-04-12") == date(2020, 4, 12)
    assert parse_date("12/04/2020") == date(2020, 4, 12)
    assert parse_date("32.13.2020") is None


def test_date_range_matches_inclusive():
    date_range = DateRange(start=date(2020, 1, 1), end=date(2020, 12, 31))
    assert date_range.matches(datetime(2020, 1, 1, 0, 0))
    assert date_range.matches(datetime(2020, 12, 31, 23, 59))
    assert not date_range.matches(datetime(2021, 1, 1))


def test_normalize_text():
    assert normalize_text("Практика_Отчёт (финал).PDF") == "практика отчет финал pdf"


def test_normalize_tag():
    assert normalize_tag("#Ёлка ") == "елка"
    assert normalize_tag("№Ёлка") == "елка"


def test_parse_bracket_empty():
    assert parse_bracket("") is None
