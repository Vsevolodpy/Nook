"""Поиск: жёсткие фильтры (теги, даты, расширение) + fuzzy по имени."""

from __future__ import annotations

from rapidfuzz import fuzz, process

from .index import Index, Record
from .query import Query

DEFAULT_LIMIT = 300
SCORE_CUTOFF = 60.0
SCORER = fuzz.WRatio


def matches_filters(record: Record, query: Query) -> bool:
    """Проверить только жёсткие фильтры (имя не участвует)."""
    if query.ext and record.ext != query.ext:
        return False

    tags = record.tags_lower
    if any(tag not in tags for tag in query.tags):
        return False
    if any(tag in tags for tag in query.neg_tags):
        return False

    for date_range in query.dates:
        if date_range.matches(record.added_at) == date_range.negated:
            return False
    return True


def rank(index: Index, query: Query, limit: int = DEFAULT_LIMIT) -> list[tuple[Record, float | None]]:
    """Отфильтровать и (если есть текст) отсортировать по похожести."""
    limit = max(1, int(limit))
    candidates = [record for record in index.snapshot() if matches_filters(record, query)]

    if not query.text:
        candidates.sort(key=lambda record: (record.added_at, record.id), reverse=True)
        return [(record, None) for record in candidates[:limit]]

    if not candidates:
        return []

    matches = process.extract(
        query.text,
        {record.id: record.norm_name for record in candidates},
        scorer=SCORER,
        score_cutoff=SCORE_CUTOFF,
        limit=limit,
    )
    by_id = {record.id: record for record in candidates}
    return [(by_id[file_id], float(score)) for _, score, file_id in matches]


def search(index: Index, query: Query, limit: int = DEFAULT_LIMIT) -> list[Record]:
    return [record for record, _ in rank(index, query, limit)]


def search_with_scores(
    index: Index, query: Query, limit: int = DEFAULT_LIMIT
) -> list[tuple[Record, float | None]]:
    return rank(index, query, limit)
