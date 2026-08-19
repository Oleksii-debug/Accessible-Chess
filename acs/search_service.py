from __future__ import annotations

"""Presentation-neutral ACSDB search application service.

UI and accessibility layers consume DTOs from this module instead of SQLite rows.
The service deliberately depends only on the public :class:`AcsDatabase` object and
keeps SQL/database identity inside the data layer.
"""

from dataclasses import dataclass
from typing import Literal

from .acsdb import AcsDatabase

SearchResult = Literal["1-0", "0-1", "1/2-1/2", "*"]
_RESULTS = frozenset({"1-0", "0-1", "1/2-1/2", "*"})
_IMPORT_STATUSES = frozenset({"full", "partial", "damaged", "warning"})


def _clean_filter(value: str | None, *, field_name: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise TypeError(f"{field_name} must be text or None")
    normalized = " ".join(value.split())
    return normalized or None


def _escape_like(value: str) -> str:
    """Escape one literal value for a parameter bound to LIKE ... ESCAPE '!'."""
    return value.replace("!", "!!").replace("%", "!%").replace("_", "!_")


def _validate_optional_text(value: str | None, *, field_name: str) -> None:
    if value is not None and not isinstance(value, str):
        raise TypeError(f"{field_name} must be text or None")


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
        if type(self.limit) is not int:
            raise TypeError("Search limit must be an integer")
        if not 1 <= self.limit <= 200:
            raise ValueError("Search limit must be between 1 and 200")
        if self.source_id is not None:
            if type(self.source_id) is not int:
                raise TypeError("source_id must be an integer or None")
            if self.source_id <= 0:
                raise ValueError("source_id must be a positive integer")
        if self.after_game_id is not None:
            if type(self.after_game_id) is not int:
                raise TypeError("after_game_id must be an integer or None")
            if self.after_game_id < 0:
                raise ValueError("after_game_id must be zero or a positive integer")
        if self.result is not None:
            if not isinstance(self.result, str):
                raise TypeError("result must be text or None")
            if self.result not in _RESULTS:
                raise ValueError(f"Unsupported chess result: {self.result}")

        return GameSearchQuery(
            player=_clean_filter(self.player, field_name="player"),
            event=_clean_filter(self.event, field_name="event"),
            eco=_clean_filter(self.eco, field_name="eco"),
            opening=_clean_filter(self.opening, field_name="opening"),
            result=self.result,
            source_id=self.source_id,
            source_name=_clean_filter(self.source_name, field_name="source_name"),
            after_game_id=self.after_game_id,
            limit=self.limit,
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

    def __post_init__(self) -> None:
        for field_name, value in (
            ("game_id", self.game_id),
            ("source_id", self.source_id),
        ):
            if type(value) is not int or value <= 0:
                raise ValueError(f"{field_name} must be a positive integer")
        if type(self.source_index) is not int or self.source_index < 0:
            raise ValueError("source_index must be a non-negative integer")
        for field_name, value in (
            ("source_name", self.source_name),
            ("source_format", self.source_format),
            ("import_status", self.import_status),
        ):
            if not isinstance(value, str) or not value:
                raise TypeError(f"{field_name} must be non-empty text")
        if self.import_status not in _IMPORT_STATUSES:
            raise ValueError("import_status must be a canonical import status")
        for field_name, value in (
            ("white", self.white),
            ("black", self.black),
            ("event", self.event),
            ("site", self.site),
            ("game_date", self.game_date),
            ("round", self.round),
            ("eco", self.eco),
            ("opening", self.opening),
            ("start_fen", self.start_fen),
        ):
            _validate_optional_text(value, field_name=field_name)
        if self.result is not None and (
            not isinstance(self.result, str) or self.result not in _RESULTS
        ):
            raise ValueError("result must be a canonical chess result or None")


@dataclass(frozen=True, slots=True)
class GameSearchPage:
    items: tuple[GameSearchItem, ...]
    next_after_game_id: int | None
    has_more: bool

    def __post_init__(self) -> None:
        if (
            not isinstance(self.items, tuple)
            or any(not isinstance(item, GameSearchItem) for item in self.items)
        ):
            raise TypeError("items must be a tuple of GameSearchItem")
        if self.next_after_game_id is not None and (
            type(self.next_after_game_id) is not int
            or self.next_after_game_id <= 0
        ):
            raise ValueError("next_after_game_id must be a positive integer or None")
        if not isinstance(self.has_more, bool):
            raise TypeError("has_more must be boolean")
        game_ids = tuple(item.game_id for item in self.items)
        if any(left >= right for left, right in zip(game_ids, game_ids[1:])):
            raise ValueError("search page game IDs must be strictly increasing")
        if self.has_more:
            if not self.items or self.next_after_game_id != self.items[-1].game_id:
                raise ValueError("paged results must expose the final visible game ID")
        elif self.next_after_game_id is not None:
            raise ValueError("final search page must not expose a next cursor")


class GameSearchService:
    """Read-only application service for database/browser UI consumers."""

    def __init__(self, database: AcsDatabase) -> None:
        if not isinstance(database, AcsDatabase):
            raise TypeError("database must be AcsDatabase")
        self._database = database

    def search(self, query: GameSearchQuery | None = None) -> GameSearchPage:
        if query is not None and not isinstance(query, GameSearchQuery):
            raise TypeError("query must be GameSearchQuery or None")
        q = (GameSearchQuery() if query is None else query).normalized()
        clauses: list[str] = []
        params: list[object] = []

        if q.player:
            clauses.append(
                "(g.white LIKE ? ESCAPE '!' COLLATE NOCASE "
                "OR g.black LIKE ? ESCAPE '!' COLLATE NOCASE)"
            )
            needle = f"%{_escape_like(q.player)}%"
            params.extend((needle, needle))
        if q.event:
            clauses.append("g.event LIKE ? ESCAPE '!' COLLATE NOCASE")
            params.append(f"%{_escape_like(q.event)}%")
        if q.eco:
            clauses.append("g.eco LIKE ? ESCAPE '!' COLLATE NOCASE")
            params.append(f"{_escape_like(q.eco)}%")
        if q.opening:
            clauses.append("g.opening LIKE ? ESCAPE '!' COLLATE NOCASE")
            params.append(f"%{_escape_like(q.opening)}%")
        if q.result:
            clauses.append("g.result=?")
            params.append(q.result)
        if q.source_id is not None:
            clauses.append("g.source_id=?")
            params.append(q.source_id)
        if q.source_name:
            clauses.append("s.source_name LIKE ? ESCAPE '!' COLLATE NOCASE")
            params.append(f"%{_escape_like(q.source_name)}%")
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
                game_id=row["game_id"],
                source_id=row["source_id"],
                source_name=row["source_name"],
                source_format=row["source_format"],
                source_index=row["source_index"],
                import_status=row["import_status"],
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
