"""Модель Nook: чистая логика без единого упоминания UI."""

from .config import Settings
from .dedup import sha256_file
from .library import Library
from .query import Query, parse_query

__all__ = ["Library", "Settings", "Query", "parse_query", "sha256_file"]
