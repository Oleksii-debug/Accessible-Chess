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


def _exact_int(value: object, *, name: str) -> int:
    if type(value) is not int:
        raise TypeError(f"{name} must be an integer")
    return value


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
            normalized = " ".join(value.split())
            return normalized or None

        limit = _exact_int(self.limit, name="limit")
        if not 1 <= limit <= 200:
            raise ValueError("Search limit must be between 1 and 200")

        source_id: int | None = None
        if self.source_id is not None:
            source_id = _exact_int(self.source_id, name="source_id")
            if source_id <= 0:
                raise ValueError("source_id must be a positive integer")

        after_game_id: int | None = None
        if self.after_game_id is not None:
            after_game_id = _exact_int(self.after_game_id, name="after_game_id")
            if after_game_id < 0:
                raise ValueError("after_game_id must be zero or a positive integer")

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

    def search(self, query: GameSearchQuery | None = None) -> GameSearchPage:
        q = (query or GameSearchQuery()).normalized()
        clauses: list[str] = []
        params: list[object] = []

        if q.player:
            clauses.append("(g.white LIKE ? COLLATE NOCASE OR g.black LIKE ? COLLATE NOCASE)")
            needle = f"%{q.player}%"
            params.extend((needle, needle))
        if q.event:
            clauses.append("g.event LIKE ? COLLATE NOCASE")
            params.append(f"%{q.event}%")
        if q.eco:
            clauses.append("g.eco LIKE ? COLLATE NOCASE")
            params.append(f"{q.eco}%")
        if q.opening:
            clauses.append("g.opening LIKE ? COLLATE NOCASE")
            params.append(f"%{q.opening}%")
        if q.result:
            clauses.append("g.result=?")
            params.append(q.result)
        if q.source_id is not None:
            clauses.append("g.source_id=?")
            params.append(q.source_id)
        if q.source_name:
            clauses.append("s.source_name LIKE ? COLLATE NOCASE")
            params.append(f"%{q.source_name}%")
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
