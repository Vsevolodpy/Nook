"""Разбор поискового запроса Nook.

Формат::

    <текст для fuzzy-поиска> \\ <параметры>

Параметры: теги (``#тег`` / ``№тег``), даты (``[12.04.2020]``,
``[<12.04.2020]``, ``[12.04.2020,31.12.2024]``) и отрицание через ``-``.
Модуль ничего не знает про БД: только строки → структура :class:`Query`.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime

SEPARATOR = "\\"

DATE_FORMATS = ("%d.%m.%Y", "%d.%m.%y", "%Y-%m-%d", "%d/%m/%Y")

_TAG_RE = re.compile(r"(?<!\S)(-?)[#№]([^\s\[\]#№]+)")
_BRACKET_RE = re.compile(r"(?<!\S)(-?)\[([^\]]*)\]")
_EXT_RE = re.compile(r"^[A-Za-z]{2,15}$")
_ONLY_TAGS_RE = re.compile(r"^(?:\s*-?[#№][^\s\[\]#]+)+\s*$")
_BARE_EXT_RE = re.compile(r"(?:^|\s)\*?\.([A-Za-z]{2,15})(?=\s|$)")
_DATE_TOKEN_RE = re.compile(
    r"^(<=|>=|<|>)?\s*(\d{1,2}[./]\d{1,2}[./]\d{2,4}|\d{4}-\d{2}-\d{2})$"
)


# --------------------------------------------------------------------------
# структуры
# --------------------------------------------------------------------------
@dataclass(frozen=True)
class DateRange:
    """Диапазон дат добавления; ``start``/``end`` — включительно."""

    start: date | None = None
    end: date | None = None
    negated: bool = False

    def matches(self, value: datetime | date) -> bool:
        day = value.date() if isinstance(value, datetime) else value
        if self.start is not None and day < self.start:
            return False
        if self.end is not None and day > self.end:
            return False
        return True


@dataclass(frozen=True)
class Query:
    """Результат разбора строки поиска."""

    raw: str = ""
    text: str = ""
    tags: tuple[str, ...] = ()
    neg_tags: tuple[str, ...] = ()
    dates: tuple[DateRange, ...] = ()
    ext: str | None = None

    @property
    def is_empty(self) -> bool:
        return not (self.text or self.tags or self.neg_tags or self.dates or self.ext)

    @property
    def has_filters(self) -> bool:
        return bool(self.tags or self.neg_tags or self.dates or self.ext)


# --------------------------------------------------------------------------
# нормализация
# --------------------------------------------------------------------------
def normalize_text(value: str) -> str:
    """Нижний регистр, ``ё→е``, пунктуация → пробел, лишние пробелы убраны."""
    value = (value or "").casefold().replace("ё", "е")
    value = re.sub(r"[\W_]+", " ", value, flags=re.UNICODE)
    return " ".join(value.split())


def normalize_tag(name: str) -> str:
    name = (name or "").strip().lstrip("#№").strip()
    return " ".join(name.casefold().replace("ё", "е").split())


# --------------------------------------------------------------------------
# парсинг
# --------------------------------------------------------------------------
def parse_query(raw: str) -> Query:
    """Разобрать строку поиска в :class:`Query` (никогда не бросает)."""
    raw = (raw or "").strip()
    if not raw:
        return Query(raw=raw)

    if SEPARATOR not in raw and _ONLY_TAGS_RE.match(raw):
        # Сценарий «ищу #курсовая2024»: голая строка из тегов — это фильтр.
        text_part, params_part = "", raw
    else:
        text_part, params_part = split_params(raw)

    text_part, ext = extract_extension(text_part)

    tags: list[str] = []
    neg_tags: list[str] = []
    dates: list[DateRange] = []

    if params_part:
        for match in _BRACKET_RE.finditer(params_part):
            parsed = parse_bracket(match.group(2), negated=bool(match.group(1)))
            if parsed is not None:
                dates.append(parsed)
        rest = _BRACKET_RE.sub(" ", params_part)

        for match in _TAG_RE.finditer(rest):
            name = normalize_tag(match.group(2))
            if not name:
                continue
            if match.group(1):
                neg_tags.append(name)
            elif name not in tags:
                tags.append(name)
        rest = _TAG_RE.sub(" ", rest)

        # Расширение можно писать и в параметрах: `\ .pdf` или `\ *.pdf`.
        if ext is None:
            found = _BARE_EXT_RE.search(rest)
            if found is not None:
                ext = found.group(1).casefold()
                rest = f"{rest[: found.start()]} {rest[found.end():]}"

        # Даты без скобок: `\ 12.11.2026`, `\ <12.11.2026`, две даты — диапазон.
        bare = [parsed for token in rest.split() if (parsed := parse_bare_date(token)) is not None]
        dates.extend(merge_bare_dates(bare))

    return Query(
        raw=raw,
        text=normalize_text(text_part),
        tags=tuple(tags),
        neg_tags=tuple(neg_tags),
        dates=tuple(dates),
        ext=ext,
    )


def parse_bare_date(token: str) -> DateRange | None:
    """Дата в параметрах без квадратных скобок: ``12.11.2026``, ``<12.11.2026``."""
    match = _DATE_TOKEN_RE.match((token or "").strip().rstrip(",;"))
    if match is None:
        return None
    value = parse_date(match.group(2))
    if value is None:
        return None
    prefix = match.group(1) or ""
    if prefix.startswith("<"):
        return DateRange(end=value)
    if prefix.startswith(">"):
        return DateRange(start=value)
    return DateRange(start=value, end=value)


def merge_bare_dates(ranges: list[DateRange]) -> list[DateRange]:
    """Две даты подряд без знаков сравнения — это диапазон ``12.11.2026 31.12.2026``."""
    plain = [item for item in ranges if item.start is not None and item.start == item.end]
    if len(ranges) == 2 and len(plain) == 2:
        first, second = sorted(plain, key=lambda item: item.start)
        return [DateRange(start=first.start, end=second.end)]
    return ranges


def split_params(raw: str) -> tuple[str, str]:
    """Разделить запрос по первому ``\\`` на текст и параметры."""
    if SEPARATOR in raw:
        head, _, tail = raw.partition(SEPARATOR)
        return head, tail
    return raw, ""


def extract_extension(text_part: str) -> tuple[str, str | None]:
    """Вынести ``.xlsx`` из текста запроса, если это похоже на расширение."""
    stripped = text_part.rstrip()
    stem, dot, suffix = stripped.rpartition(".")
    if not dot or not _EXT_RE.match(suffix):
        return text_part, None
    return stem, suffix.casefold()


def parse_bracket(content: str, negated: bool = False) -> DateRange | None:
    """Разобрать содержимое ``[...]``: точка, ``<``/``>`` или две даты."""
    content = (content or "").strip().replace("—", "-").replace("–", "-")
    if not content:
        return None

    if "," in content:
        left, _, right = content.partition(",")
        start = parse_date(left)
        end = parse_date(right)
        if start is None and end is None:
            return None
        if start and end and start > end:
            start, end = end, start
        return DateRange(start=start, end=end, negated=negated)

    # "<X" — не позже X, ">X" — не раньше X.
    for prefix, upper_bound in (("<=", True), ("<", True), (">=", False), (">", False)):
        if content.startswith(prefix):
            value = parse_date(content[len(prefix):])
            if value is None:
                return None
            if upper_bound:
                return DateRange(end=value, negated=negated)
            return DateRange(start=value, negated=negated)

    value = parse_date(content)
    if value is None:
        return None
    return DateRange(start=value, end=value, negated=negated)


def parse_date(token: str) -> date | None:
    token = (token or "").strip()
    if not token:
        return None
    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(token, fmt).date()
        except ValueError:
            continue
    return None
