from __future__ import annotations

"""Canonical text-search policy shared by ACSDB and Library/Search services."""

import sqlite3
import unicodedata

SEARCH_FOLD_SQL_FUNCTION = "ACS_SEARCH_FOLD"
MAX_SEARCH_TERM_CHARS = 256


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
