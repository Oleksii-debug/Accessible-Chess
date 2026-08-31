from __future__ import annotations

"""Canonical search policy shared by ACSDB and Library/Search services."""

from datetime import date
import re
import sqlite3
import unicodedata

SEARCH_FOLD_SQL_FUNCTION = "ACS_SEARCH_FOLD"
SEARCH_DATE_KEY_SQL_FUNCTION = "ACS_SEARCH_DATE_KEY"
MAX_SEARCH_TERM_CHARS = 256
MAX_SEARCH_PAGE_SIZE = 200
SQLITE_INTEGER_MAX = (1 << 63) - 1
SEARCH_RESULTS = frozenset({"1-0", "0-1", "1/2-1/2", "*"})
_COMPLETE_PGN_DATE_RE = re.compile(r"^(\d{4})\.(\d{2})\.(\d{2})$")


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


def normalize_search_year_bound(value: object | None, *, name: str) -> int | None:
    """Validate one explicit calendar-year bound without scalar coercion.

    PGN Date text remains loss-aware. A year bound is therefore an application
    filter over complete real dates only; it is never used to repair partial or
    malformed source metadata.
    """
    if value is None:
        return None
    if type(value) is not int:
        raise TypeError(f"{name} must be an integer")
    if not 1 <= value <= 9999:
        raise ValueError(f"{name} must be between 1 and 9999")
    return value


def search_fold(value: str | None) -> str | None:
    """Return Unicode NFKC + casefold text for SQLite comparisons.

    This policy is deliberately accent/diacritic preserving. It normalizes
    compatibility forms and case, but it does not strip combining marks or
    transliterate letters; callers that need accent-insensitive search require a
    separate explicit product contract rather than an implicit lossy fold.
    """
    if value is None:
        return None
    return unicodedata.normalize("NFKC", value).casefold()


def search_date_key(value: str | None) -> str | None:
    """Return a sortable key only for a complete, real PGN calendar date.

    Stored PGN Date metadata is loss-aware and may legitimately contain unknown
    components such as ``????.??.??``.  Search must never invent calendar facts
    from such text, so only an exact, valid ``YYYY.MM.DD`` value receives a key.
    """
    if value is None or type(value) is not str:
        return None
    normalized = unicodedata.normalize("NFKC", value)
    match = _COMPLETE_PGN_DATE_RE.fullmatch(normalized)
    if match is None:
        return None
    year, month, day = (int(part) for part in match.groups())
    try:
        date(year, month, day)
    except ValueError:
        return None
    return f"{year:04d}.{month:02d}.{day:02d}"


def normalize_search_date_bound(value: object | None, *, name: str) -> str | None:
    """Validate a complete calendar bound without coercing partial PGN dates."""
    if value is None:
        return None
    if type(value) is not str:
        raise TypeError(f"{name} must be text")
    normalized = unicodedata.normalize("NFKC", value).strip()
    key = search_date_key(normalized)
    if key is None:
        raise ValueError(f"{name} must be a valid complete date in YYYY.MM.DD format")
    return key


def escape_like(value: str) -> str:
    """Escape a folded user term for literal SQLite LIKE matching."""
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def literal_like_pattern(value: str, *, prefix: bool = False) -> str:
    folded = search_fold(value)
    assert folded is not None
    escaped = escape_like(folded)
    return f"{escaped}%" if prefix else f"%{escaped}%"


def install_search_fold(connection: sqlite3.Connection) -> None:
    """Install deterministic search functions when SQLite UDFs are available.

    Some fail-closed schema-preflight tests intentionally wrap a real SQLite
    connection with only the minimal execute/close surface needed to prove that
    an unsupported future ACSDB is rejected and closed without being rewritten.
    Such a proxy does not expose ``create_function``. Skipping registration for
    that narrow proxy is safe: any supported-schema migration/search that really
    needs either UDF will fail closed at SQL execution rather than publishing
    stale or partially migrated data.
    """
    create_function = getattr(connection, "create_function", None)
    if create_function is None:
        return
    create_function(
        SEARCH_FOLD_SQL_FUNCTION,
        1,
        search_fold,
        deterministic=True,
    )
    create_function(
        SEARCH_DATE_KEY_SQL_FUNCTION,
        1,
        search_date_key,
        deterministic=True,
    )
