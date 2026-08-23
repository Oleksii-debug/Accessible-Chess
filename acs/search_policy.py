from __future__ import annotations

"""Canonical search policy shared by ACSDB and Library/Search services."""

import sqlite3
import unicodedata

SEARCH_FOLD_SQL_FUNCTION = "ACS_SEARCH_FOLD"
MAX_SEARCH_TERM_CHARS = 256
MAX_SEARCH_PAGE_SIZE = 200
SQLITE_INTEGER_MAX = (1 << 63) - 1
SEARCH_RESULTS = frozenset({"1-0", "0-1", "1/2-1/2", "*"})


def normalize_search_term(value: str | None, *, name: str) -> str | None:
    """Validate and NFKC-normalize one optional user-facing search term."""
    if value is None:
        return None
    if type(value) is not str:
        raise TypeError(f"{name} must be text")
    normalized = " ".join(unicodedata.normalize("NFKC", value).split())
    if len(normalized) > MAX_SEARCH_TERM_CHARS:
        raise ValueError(
            f"{name} exceeds maximum search term length of {MAX_SEARCH_TERM_CHARS} characters"
        )
    return normalized or None


def normalize_search_limit(value: object) -> int:
    """Validate the bounded page size used by game Library/Search surfaces."""
    if type(value) is not int:
        raise TypeError("limit must be an integer")
    if not 1 <= value <= MAX_SEARCH_PAGE_SIZE:
        raise ValueError(
            f"Search limit must be between 1 and {MAX_SEARCH_PAGE_SIZE}"
        )
    return value


def normalize_search_source_id(value: object | None) -> int | None:
    """Validate an optional positive SQLite source identifier without coercion."""
    if value is None:
        return None
    if type(value) is not int:
        raise TypeError("source_id must be an integer")
    if value < 1:
        raise ValueError("source_id must be a positive integer")
    if value > SQLITE_INTEGER_MAX:
        raise ValueError("source_id exceeds SQLite integer range")
    return value


def normalize_search_result(value: object | None) -> object | None:
    """Validate the canonical PGN result tokens accepted by game search."""
    if value is not None and value not in SEARCH_RESULTS:
        raise ValueError(f"Unsupported chess result: {value}")
    return value


def search_fold(value: str | None) -> str | None:
    """Return Unicode NFKC + casefold text for SQLite comparisons."""
    if value is None:
        return None
    return unicodedata.normalize("NFKC", value).casefold()


def escape_like(value: str) -> str:
    """Escape a folded user term for literal SQLite LIKE matching."""
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def literal_like_pattern(value: str, *, prefix: bool = False) -> str:
    folded = search_fold(value)
    assert folded is not None
    escaped = escape_like(folded)
    return f"{escaped}%" if prefix else f"%{escaped}%"


def install_search_fold(connection: sqlite3.Connection) -> None:
    """Install the deterministic Unicode fold function on one SQLite connection."""
    connection.create_function(
        SEARCH_FOLD_SQL_FUNCTION,
        1,
        search_fold,
        deterministic=True,
    )
