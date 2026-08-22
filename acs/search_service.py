from __future__ import annotations

"""Presentation-neutral ACSDB search application service.

UI and accessibility layers consume DTOs from this module instead of SQLite rows.
The service deliberately depends only on the public :class:`AcsDatabase` object and
keeps SQL/database identity inside the data layer.
"""

from dataclasses import dataclass
from typing import Literal
import unicodedata

from .acsdb import AcsDatabase

SearchResult = Literal["1-0", "0-1", "1/2-1/2", "*"]
_SQLITE_INTEGER_MAX = (1 << 63) - 1
_MAX_SEARCH_TERM_CHARS = 256
_SEARCH_FOLD_SQL_FUNCTION = "ACS_SEARCH_FOLD"


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


def _search_fold(value: str | None) -> str | None:
    """Return a canonical Unicode form for case-insensitive literal searching.

    SQLite's built-in ``NOCASE`` collation is ASCII-only. Chess libraries routinely
    contain player, event and opening names in Cyrillic and accented Latin scripts,
    so application search uses Unicode NFKC + ``casefold`` on both stored values and
    query terms instead. ``None`` is preserved for nullable ACSDB text columns.
    """

    if value is None:
        return None
    return unicodedata.normalize("NFKC", value).casefold()


def _escape_like(value: str) -> str:
    """Escape a normalized user term for literal SQLite ``LIKE`` matching."""

    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


@dataclass(frozen=True, slots=True)
class GameSearchQuery:
    """Stable, neutral query contract for a page of ACSDB games.

    ``after_game_id`` is a keyset cursor rather than a row offset. This keeps paging
    deterministic while imports append games to the database. Text filters are
    intentionally explicit so callers do not pass raw SQL fragments.
    """

    player: str | None = None
    event: str | None = None
    eco: str | None = None
    opening: str | None = None
    result: SearchResult | None = None
    source_id: int | None = None
    source_name: str | None = None
    after_game_id: int | None = None
    limit: int = 50

    def normalized(self) -> "GameSearchQuery":
        def clean(value: str | None, *, name: str) -> str | None:
            if value is None:
                return None
            if type(value) is not str:
                raise TypeError(f"{name} must be text")
            normalized = " ".join(unicodedata.normalize("NFKC", value).split())
            if len(normalized) > _MAX_SEARCH_TERM_CHARS:
                raise ValueError(
                    f"{name} exceeds maximum search term length of {_MAX_SEARCH_TERM_CHARS} characters"
                )
            return normalized or None

        limit = _exact_int(self.limit, name="limit")
        if not 1 <= limit <= 200:
            raise ValueError("Search limit must be between 1 and 200")

        source_id: int | None = None
        if self.source_id is not None:
            source_id = _sqlite_integer(self.source_id, name="source_id", minimum=1)

        after_game_id: int | None = None
        if self.after_game_id is not None:
            after_game_id = _sqlite_integer(
                self.after_game_id,
                name="after_game_id",
                minimum=0,
            )

        if self.result is not None and self.result not in {"1-0", "0-1", "1/2-1/2", "*"}:
            raise ValueError(f"Unsupported chess result: {self.result}")

        return GameSearchQuery(
            player=clean(self.player, name="player"),
            event=clean(self.event, name="event"),
            eco=clean(self.eco, name="eco"),
            opening=clean(self.opening, name="opening"),
            result=self.result,
            source_id=source_id,
            source_name=clean(self.source_name, name="source_name"),
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
        self._database.conn.create_function(
            _SEARCH_FOLD_SQL_FUNCTION,
            1,
            _search_fold,
            deterministic=True,
        )

    def search(self, query: GameSearchQuery | None = None) -> GameSearchPage:
        q = (query or GameSearchQuery()).normalized()
        clauses: list[str] = []
        params: list[object] = []

        def folded_pattern(value: str, *, prefix: bool = False) -> str:
            folded = _search_fold(value)
            assert folded is not None
            escaped = _escape_like(folded)
            return f"{escaped}%" if prefix else f"%{escaped}%"

        if q.player:
            clauses.append(
                f"({_SEARCH_FOLD_SQL_FUNCTION}(g.white) LIKE ? ESCAPE '\\' OR "
                f"{_SEARCH_FOLD_SQL_FUNCTION}(g.black) LIKE ? ESCAPE '\\')"
            )
            needle = folded_pattern(q.player)
            params.extend((needle, needle))
        if q.event:
            clauses.append(f"{_SEARCH_FOLD_SQL_FUNCTION}(g.event) LIKE ? ESCAPE '\\'")
            params.append(folded_pattern(q.event))
        if q.eco:
            clauses.append(f"{_SEARCH_FOLD_SQL_FUNCTION}(g.eco) LIKE ? ESCAPE '\\'")
            params.append(folded_pattern(q.eco, prefix=True))
        if q.opening:
            clauses.append(f"{_SEARCH_FOLD_SQL_FUNCTION}(g.opening) LIKE ? ESCAPE '\\'")
            params.append(folded_pattern(q.opening))
        if q.result:
            clauses.append("g.result=?")
            params.append(q.result)
        if q.source_id is not None:
            clauses.append("g.source_id=?")
            params.append(q.source_id)
        if q.source_name:
            clauses.append(f"{_SEARCH_FOLD_SQL_FUNCTION}(s.source_name) LIKE ? ESCAPE '\\'")
            params.append(folded_pattern(q.source_name))
        if q.after_game_id is not None:
            clauses.append("g.id>?")
            params.append(q.after_game_id)

        sql = """
            SELECT
                g.id AS game_id,
                g.source_id,
                s.source_name,
                s.source_format,
                g.source_index,
                g.import_status,
                g.white,
                g.black,
                g.event,
                g.site,
                g.game_date,
                g.round,
                g.result,
                g.eco,
                g.opening,
                g.start_fen
            FROM games g
            JOIN sources s ON s.id = g.source_id
        """
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY g.id LIMIT ?"
        params.append(q.limit + 1)

        rows = self._database.conn.execute(sql, params).fetchall()
        has_more = len(rows) > q.limit
        visible_rows = rows[: q.limit]
        items = tuple(
            GameSearchItem(
                game_id=int(row["game_id"]),
                source_id=int(row["source_id"]),
                source_name=str(row["source_name"]),
                source_format=str(row["source_format"]),
                source_index=int(row["source_index"]),
                import_status=str(row["import_status"]),
                white=row["white"],
                black=row["black"],
                event=row["event"],
                site=row["site"],
                game_date=row["game_date"],
                round=row["round"],
                result=row["result"],
                eco=row["eco"],
                opening=row["opening"],
                start_fen=row["start_fen"],
            )
            for row in visible_rows
        )
        next_cursor = items[-1].game_id if has_more and items else None
        return GameSearchPage(items=items, next_after_game_id=next_cursor, has_more=has_more)
