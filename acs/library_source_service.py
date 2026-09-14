from __future__ import annotations

"""Presentation-neutral browsing of canonical ACSDB source provenance.

The source catalog is deliberately separate from game metadata Search.  It reads
canonical ``sources`` plus bounded aggregate facts from ``games`` and
``import_attempts``.  Source -> game browsing delegates to ``GameSearchService``
so there is still exactly one application game-search implementation.
"""

from collections.abc import Callable
from dataclasses import dataclass
import sqlite3

from .acsdb import AcsDatabase
from .search_service import GameSearchPage, GameSearchQuery, GameSearchService

_SQLITE_INTEGER_MAX = (1 << 63) - 1
_MAX_PAGE_SIZE = 200
_MAX_SOURCE_FORMAT_LENGTH = 64
_SQLITE_PROGRESS_OPCODES = 1000


class SourceCatalogCancelledError(RuntimeError):
    """Raised when a caller cooperatively cancels a source-catalog query."""


class SourceCatalogControlError(RuntimeError):
    """Raised when the caller's cancellation callback violates its contract."""


def _positive_integer(value: object, *, name: str) -> int:
    if type(value) is not int:
        raise TypeError(f"{name} must be an integer")
    if value < 1:
        raise ValueError(f"{name} must be positive")
    if value > _SQLITE_INTEGER_MAX:
        raise ValueError(f"{name} exceeds SQLite integer range")
    return value


def _page_limit(value: object) -> int:
    value = _positive_integer(value, name="limit")
    if value > _MAX_PAGE_SIZE:
        raise ValueError(f"limit must not exceed {_MAX_PAGE_SIZE}")
    return value


def _source_format(value: object) -> str | None:
    if value is None:
        return None
    if type(value) is not str:
        raise TypeError("source_format must be text")
    normalized = value.strip().lower()
    if not normalized:
        return None
    if len(normalized) > _MAX_SOURCE_FORMAT_LENGTH:
        raise ValueError(
            f"source_format must not exceed {_MAX_SOURCE_FORMAT_LENGTH} characters"
        )
    if "\x00" in normalized:
        raise ValueError("source_format must not contain NUL")
    return normalized


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
        raise SourceCatalogControlError("Source catalog cancellation check failed") from exc
    if type(cancelled) is not bool:
        raise SourceCatalogControlError("cancel_check must return a boolean")
    return cancelled


@dataclass(frozen=True, slots=True)
class SourceCatalogQuery:
    """Bounded keyset query for canonical Library sources."""

    source_format: str | None = None
    after_source_id: int | None = None
    limit: int = 50

    def normalized(self) -> "SourceCatalogQuery":
        cursor: int | None = None
        if self.after_source_id is not None:
            cursor = _positive_integer(self.after_source_id, name="after_source_id")
        return SourceCatalogQuery(
            source_format=_source_format(self.source_format),
            after_source_id=cursor,
            limit=_page_limit(self.limit),
        )


@dataclass(frozen=True, slots=True)
class SourceCatalogItem:
    """Detached aggregate view of one immutable ACSDB source."""

    source_id: int
    source_name: str
    source_format: str
    source_sha256: str | None
    imported_at: str
    game_count: int
    full_game_count: int
    warning_game_count: int
    partial_game_count: int
    damaged_game_count: int
    first_game_id: int | None
    last_game_id: int | None
    attempt_count: int
    latest_attempt_id: int | None
    latest_attempt_status: str | None


@dataclass(frozen=True, slots=True)
class SourceCatalogPage:
    items: tuple[SourceCatalogItem, ...]
    next_after_source_id: int | None
    has_more: bool


class LibrarySourceCatalogService:
    """Read-only canonical Library source/provenance browser."""

    def __init__(self, database: AcsDatabase) -> None:
        if not isinstance(database, AcsDatabase):
            raise TypeError("database must be an AcsDatabase")
        self._database = database
        self._game_search = GameSearchService(database)

    @staticmethod
    def _item(row: sqlite3.Row) -> SourceCatalogItem:
        game_count = int(row["game_count"])
        status_counts = (
            int(row["full_game_count"]),
            int(row["warning_game_count"]),
            int(row["partial_game_count"]),
            int(row["damaged_game_count"]),
        )
        if sum(status_counts) != game_count:
            raise RuntimeError("ACSDB source status aggregate is inconsistent")
        first_game_id = row["first_game_id"]
        last_game_id = row["last_game_id"]
        if game_count == 0:
            if first_game_id is not None or last_game_id is not None:
                raise RuntimeError("ACSDB source game aggregate is inconsistent")
        elif first_game_id is None or last_game_id is None:
            raise RuntimeError("ACSDB source game aggregate is inconsistent")
        return SourceCatalogItem(
            source_id=int(row["id"]),
            source_name=str(row["source_name"]),
            source_format=str(row["source_format"]),
            source_sha256=None if row["sha256"] is None else str(row["sha256"]),
            imported_at=str(row["imported_at"]),
            game_count=game_count,
            full_game_count=status_counts[0],
            warning_game_count=status_counts[1],
            partial_game_count=status_counts[2],
            damaged_game_count=status_counts[3],
            first_game_id=None if first_game_id is None else int(first_game_id),
            last_game_id=None if last_game_id is None else int(last_game_id),
            attempt_count=int(row["attempt_count"]),
            latest_attempt_id=(
                None if row["latest_attempt_id"] is None else int(row["latest_attempt_id"])
            ),
            latest_attempt_status=(
                None
                if row["latest_attempt_status"] is None
                else str(row["latest_attempt_status"])
            ),
        )

    def _query_rows(
        self,
        *,
        source_id: int | None = None,
        source_format: str | None = None,
        after_source_id: int | None = None,
        limit: int,
        cancel_check: Callable[[], bool] | None,
    ) -> list[sqlite3.Row]:
        clauses: list[str] = []
        params: list[object] = []
        if source_id is not None:
            clauses.append("s.id=?")
            params.append(source_id)
        else:
            if source_format is not None:
                clauses.append("s.source_format=? COLLATE NOCASE")
                params.append(source_format)
            if after_source_id is not None:
                clauses.append("s.id>?")
                params.append(after_source_id)
        where = ""
        if clauses:
            where = " WHERE " + " AND ".join(clauses)
        params.append(limit)

        # Critically, ``page`` is bounded before either child table is aggregated.
        # This keeps result memory O(page-size) and prevents a catalog page from
        # accidentally materializing every source/game/attempt aggregate at once.
        sql = f"""
            WITH page AS MATERIALIZED (
                SELECT s.id, s.source_name, s.source_format, s.sha256, s.imported_at
                  FROM sources AS s{where}
                 ORDER BY s.id
                 LIMIT ?
            ),
            game_rollup AS (
                SELECT g.source_id,
                       COUNT(*) AS game_count,
                       SUM(CASE WHEN g.import_status='full' THEN 1 ELSE 0 END) AS full_game_count,
                       SUM(CASE WHEN g.import_status='warning' THEN 1 ELSE 0 END) AS warning_game_count,
                       SUM(CASE WHEN g.import_status='partial' THEN 1 ELSE 0 END) AS partial_game_count,
                       SUM(CASE WHEN g.import_status='damaged' THEN 1 ELSE 0 END) AS damaged_game_count,
                       MIN(g.id) AS first_game_id,
                       MAX(g.id) AS last_game_id
                  FROM games AS g
                  JOIN page AS p ON p.id=g.source_id
                 GROUP BY g.source_id
            ),
            attempt_rollup AS (
                SELECT a.source_id,
                       COUNT(*) AS attempt_count,
                       MAX(a.id) AS latest_attempt_id
                  FROM import_attempts AS a
                  JOIN page AS p ON p.id=a.source_id
                 GROUP BY a.source_id
            )
            SELECT p.id, p.source_name, p.source_format, p.sha256, p.imported_at,
                   COALESCE(g.game_count,0) AS game_count,
                   COALESCE(g.full_game_count,0) AS full_game_count,
                   COALESCE(g.warning_game_count,0) AS warning_game_count,
                   COALESCE(g.partial_game_count,0) AS partial_game_count,
                   COALESCE(g.damaged_game_count,0) AS damaged_game_count,
                   g.first_game_id, g.last_game_id,
                   COALESCE(a.attempt_count,0) AS attempt_count,
                   a.latest_attempt_id,
                   latest.status AS latest_attempt_status
              FROM page AS p
              LEFT JOIN game_rollup AS g ON g.source_id=p.id
              LEFT JOIN attempt_rollup AS a ON a.source_id=p.id
              LEFT JOIN import_attempts AS latest ON latest.id=a.latest_attempt_id
             ORDER BY p.id
        """

        connection = self._database.conn
        if cancel_check is None:
            return connection.execute(sql, params).fetchall()

        progress_cancelled = False
        progress_error: SourceCatalogControlError | None = None

        def progress_handler() -> int:
            nonlocal progress_cancelled, progress_error
            try:
                progress_cancelled = _poll_cancel(cancel_check)
            except SourceCatalogControlError as exc:
                progress_error = exc
                return 1
            return 1 if progress_cancelled else 0

        connection.set_progress_handler(progress_handler, _SQLITE_PROGRESS_OPCODES)
        try:
            return connection.execute(sql, params).fetchall()
        except sqlite3.OperationalError:
            if progress_error is not None:
                raise progress_error from None
            if progress_cancelled:
                raise SourceCatalogCancelledError("Source catalog query cancelled") from None
            raise
        finally:
            connection.set_progress_handler(None, 0)

    def list_sources(
        self,
        query: SourceCatalogQuery | None = None,
        *,
        cancel_check: Callable[[], bool] | None = None,
    ) -> SourceCatalogPage:
        q = (query or SourceCatalogQuery()).normalized()
        cancel_check = _validate_cancel_check(cancel_check)
        if cancel_check is not None and _poll_cancel(cancel_check):
            raise SourceCatalogCancelledError("Source catalog query cancelled")

        rows = self._query_rows(
            source_format=q.source_format,
            after_source_id=q.after_source_id,
            limit=q.limit + 1,
            cancel_check=cancel_check,
        )
        if cancel_check is not None and _poll_cancel(cancel_check):
            raise SourceCatalogCancelledError("Source catalog query cancelled")
        has_more = len(rows) > q.limit
        items = tuple(self._item(row) for row in rows[: q.limit])
        next_cursor = items[-1].source_id if has_more and items else None
        return SourceCatalogPage(
            items=items,
            next_after_source_id=next_cursor,
            has_more=has_more,
        )

    def get_source(
        self,
        source_id: int,
        *,
        cancel_check: Callable[[], bool] | None = None,
    ) -> SourceCatalogItem | None:
        source_id = _positive_integer(source_id, name="source_id")
        cancel_check = _validate_cancel_check(cancel_check)
        if cancel_check is not None and _poll_cancel(cancel_check):
            raise SourceCatalogCancelledError("Source catalog query cancelled")
        rows = self._query_rows(
            source_id=source_id,
            limit=1,
            cancel_check=cancel_check,
        )
        if cancel_check is not None and _poll_cancel(cancel_check):
            raise SourceCatalogCancelledError("Source catalog query cancelled")
        return self._item(rows[0]) if rows else None

    def source_games(
        self,
        source_id: int,
        *,
        after_game_id: int | None = None,
        limit: int = 50,
        cancel_check: Callable[[], bool] | None = None,
    ) -> GameSearchPage:
        """Browse games from one source through the canonical game Search service."""

        source_id = _positive_integer(source_id, name="source_id")
        return self._game_search.search(
            GameSearchQuery(
                source_id=source_id,
                after_game_id=after_game_id,
                limit=limit,
            ),
            cancel_check=cancel_check,
        )
