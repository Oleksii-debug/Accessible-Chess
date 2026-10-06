from __future__ import annotations

"""Presentation-neutral ACSDB search application service.

UI and accessibility layers consume DTOs from this module instead of SQLite rows.
The service deliberately depends only on the public :class:`AcsDatabase` object and
keeps SQL/database identity inside the data layer.
"""

from collections.abc import Callable
from dataclasses import dataclass
import sqlite3
from typing import Literal

from .acsdb import AcsDatabase
from .search_policy import (
    normalize_search_date_bound,
    normalize_search_limit,
    normalize_search_result,
    normalize_search_source_id,
    normalize_search_term,
)

SearchResult = Literal["1-0", "0-1", "1/2-1/2", "*"]
_SQLITE_INTEGER_MAX = (1 << 63) - 1
_SQLITE_PROGRESS_OPCODES = 1000


class SearchCancelledError(RuntimeError):
    """Raised when a caller cancels a Library/Search query."""


class SearchControlError(RuntimeError):
    """Raised when the cancellation contract itself is invalid or fails."""


def _exact_int(value: object, *, name: str) -> int:
    if type(value) is not int:
        raise TypeError(f"{name} must be an integer")
    return value


def _sqlite_integer(value: object, *, name: str, minimum: int) -> int:
    """Validate an application scalar before it reaches a SQLite INTEGER bind."""

    integer = _exact_int(value, name=name)
    if integer < minimum:
        if minimum == 1:
            raise ValueError(f"{name} must be a positive integer")
        raise ValueError(f"{name} must be zero or a positive integer")
    if integer > _SQLITE_INTEGER_MAX:
        raise ValueError(f"{name} exceeds SQLite integer range")
    return integer


def _canonical_search_row(row: object) -> dict:
    """Accept only the exact row container published by the ACSDB API."""

    if type(row) is not dict:
        raise TypeError("search row must be a dictionary")
    return row


def _row_required_integer(
    row: dict,
    key: str,
    *,
    minimum: int,
) -> int:
    """Read one canonical SQLite integer without presentation-side coercion."""

    if key not in row:
        raise ValueError(f"search row is missing {key}")
    return _sqlite_integer(row[key], name=key, minimum=minimum)


def _row_required_text(row: dict, key: str) -> str:
    """Read required persisted text without converting malformed scalars."""

    if key not in row:
        raise ValueError(f"search row is missing {key}")
    value = row[key]
    if type(value) is not str:
        raise TypeError(f"{key} must be text")
    return value


def _row_optional_text(row: dict, key: str) -> str | None:
    """Read optional persisted text while preserving SQL NULL exactly."""

    if key not in row:
        raise ValueError(f"search row is missing {key}")
    value = row[key]
    if value is None:
        return None
    if type(value) is not str:
        raise TypeError(f"{key} must be text or null")
    return value


def _validate_cancel_check(
    cancel_check: Callable[[], bool] | None,
) -> Callable[[], bool] | None:
    if cancel_check is not None and not callable(cancel_check):
        raise TypeError("cancel_check must be callable")
    return cancel_check


def _poll_cancel(cancel_check: Callable[[], bool]) -> bool:
    try:
        cancelled = cancel_check()
    except Exception as exc:
        raise SearchControlError("Search cancellation check failed") from exc
    if type(cancelled) is not bool:
        raise SearchControlError("cancel_check must return a boolean")
    return cancelled


@dataclass(frozen=True, slots=True)
class GameSearchQuery:
    """Stable, neutral query contract for a page of ACSDB games.

    ``game_date`` matches the stored loss-aware PGN Date tag exactly after the
    normal text normalization policy. ``date_from`` and ``date_to`` are strict
    calendar bounds and accept only complete real ``YYYY.MM.DD`` dates; partial
    or unknown source dates remain stored but do not become invented range facts.

    ``after_game_id`` is a keyset cursor rather than a row offset. This keeps paging
    deterministic while imports append games to the database. Filters are
    intentionally explicit so callers do not pass raw SQL fragments.
    """

    player: str | None = None
    event: str | None = None
    eco: str | None = None
    opening: str | None = None
    game_date: str | None = None
    date_from: str | None = None
    date_to: str | None = None
    result: SearchResult | None = None
    source_id: int | None = None
    source_name: str | None = None
    after_game_id: int | None = None
    limit: int = 50

    def normalized(self) -> "GameSearchQuery":
        limit = normalize_search_limit(self.limit)
        source_id = normalize_search_source_id(self.source_id)

        after_game_id: int | None = None
        if self.after_game_id is not None:
            after_game_id = _sqlite_integer(
                self.after_game_id,
                name="after_game_id",
                minimum=0,
            )

        result = normalize_search_result(self.result)
        date_from = normalize_search_date_bound(self.date_from, name="date_from")
        date_to = normalize_search_date_bound(self.date_to, name="date_to")
        if date_from is not None and date_to is not None and date_from > date_to:
            raise ValueError("date_from must not be later than date_to")

        return GameSearchQuery(
            player=normalize_search_term(self.player, name="player"),
            event=normalize_search_term(self.event, name="event"),
            eco=normalize_search_term(self.eco, name="eco"),
            opening=normalize_search_term(self.opening, name="opening"),
            game_date=normalize_search_term(self.game_date, name="game_date"),
            date_from=date_from,
            date_to=date_to,
            result=result,  # type: ignore[arg-type]
            source_id=source_id,
            source_name=normalize_search_term(self.source_name, name="source_name"),
            after_game_id=after_game_id,
            limit=limit,
        )


@dataclass(frozen=True, slots=True)
class GameSearchItem:
    game_id: int
    source_id: int
    source_name: str
    source_format: str
    source_index: int
    import_status: str
    white: str | None
    black: str | None
    event: str | None
    site: str | None
    game_date: str | None
    round: str | None
    result: str | None
    eco: str | None
    opening: str | None
    start_fen: str | None


@dataclass(frozen=True, slots=True)
class GameSearchPage:
    items: tuple[GameSearchItem, ...]
    next_after_game_id: int | None
    has_more: bool


class GameSearchService:
    """Read-only application service for database/browser UI consumers."""

    def __init__(self, database: AcsDatabase) -> None:
        self._database = database

    def search(
        self,
        query: GameSearchQuery | None = None,
        *,
        cancel_check: Callable[[], bool] | None = None,
    ) -> GameSearchPage:
        """Return one bounded keyset page, optionally cancellable while SQLite runs.

        Cancellation is cooperative and presentation-neutral. A caller supplies a
        cheap zero-argument predicate returning an exact boolean. The predicate is
        polled before execution, from SQLite's VM progress hook during potentially
        large scans, and once before publishing a completed page. SQLite's
        connection-global progress hook is always removed before returning or
        raising so a cancelled query cannot poison later Library operations.

        Query construction and Unicode/literal/date semantics are delegated to
        :meth:`AcsDatabase.search_games`. This keeps the application service on the
        same schema-v5 search/index path, ordering and provenance contract as the
        direct database API instead of maintaining a second SQL implementation.

        The VM hook is deliberately not exposed as a percentage: SQLite opcode
        counts are implementation details and are not a meaningful row/progress
        denominator for users.
        """

        q = (query or GameSearchQuery()).normalized()
        cancel_check = _validate_cancel_check(cancel_check)
        if cancel_check is not None and _poll_cancel(cancel_check):
            raise SearchCancelledError("Search cancelled")

        def execute_search() -> list[dict]:
            return self._database.search_games(
                player=q.player,
                event=q.event,
                eco=q.eco,
                opening=q.opening,
                game_date=q.game_date,
                date_from=q.date_from,
                date_to=q.date_to,
                result=q.result,
                source_id=q.source_id,
                source_name=q.source_name,
                after_id=q.after_game_id,
                limit=q.limit + 1,
            )

        if cancel_check is None:
            rows = execute_search()
        else:
            progress_cancelled = False
            progress_error: SearchControlError | None = None

            def progress_handler() -> int:
                nonlocal progress_cancelled, progress_error
                try:
                    progress_cancelled = _poll_cancel(cancel_check)
                except SearchControlError as exc:
                    progress_error = exc
                    return 1
                return 1 if progress_cancelled else 0

            self._database.conn.set_progress_handler(
                progress_handler,
                _SQLITE_PROGRESS_OPCODES,
            )
            try:
                rows = execute_search()
            except sqlite3.OperationalError:
                if progress_error is not None:
                    raise progress_error from None
                if progress_cancelled:
                    raise SearchCancelledError("Search cancelled") from None
                raise
            finally:
                self._database.conn.set_progress_handler(None, 0)

            if _poll_cancel(cancel_check):
                raise SearchCancelledError("Search cancelled")

        if type(rows) is not list:
            raise TypeError("search result must be a list")
        canonical_rows = tuple(_canonical_search_row(row) for row in rows)
        projected_items = tuple(
            GameSearchItem(
                game_id=_row_required_integer(row, "id", minimum=1),
                source_id=_row_required_integer(row, "source_id", minimum=1),
                source_name=_row_required_text(row, "source_name"),
                source_format=_row_required_text(row, "source_format"),
                source_index=_row_required_integer(row, "source_index", minimum=0),
                import_status=_row_required_text(row, "import_status"),
                white=_row_optional_text(row, "white"),
                black=_row_optional_text(row, "black"),
                event=_row_optional_text(row, "event"),
                site=_row_optional_text(row, "site"),
                game_date=_row_optional_text(row, "game_date"),
                round=_row_optional_text(row, "round"),
                result=_row_optional_text(row, "result"),
                eco=_row_optional_text(row, "eco"),
                opening=_row_optional_text(row, "opening"),
                start_fen=_row_optional_text(row, "start_fen"),
            )
            for row in canonical_rows
        )
        has_more = len(projected_items) > q.limit
        items = projected_items[: q.limit]
        next_cursor = items[-1].game_id if has_more and items else None
        return GameSearchPage(items=items, next_after_game_id=next_cursor, has_more=has_more)
