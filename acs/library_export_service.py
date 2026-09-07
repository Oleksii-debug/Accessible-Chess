from __future__ import annotations

"""Canonical D07 Library -> PGN export application service.

Library selection/search semantics live here; filesystem selection deliberately
does not. A trusted host supplies the destination only after the browser request
has been validated. PGN serialization/publication is delegated to the existing
D06 atomic writer so Library export cannot become a second serializer.
"""

from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass, replace
from enum import Enum
from pathlib import Path
from typing import Final

from .acsdb import AcsDatabase
from .gametree import PgnGame
from .pgn_roundtrip import parse_pgn_text
from .pgn_service import SourceFingerprint, save_pgn_atomic
from .search_service import GameSearchQuery, GameSearchService


_MAX_SELECTED_GAMES: Final = 5000
_EXPORT_PAGE_SIZE: Final = 200
_SQLITE_INTEGER_MAX: Final = (1 << 63) - 1
_FILTER_FIELDS: Final = frozenset(
    {"player", "event", "eco", "opening", "result", "source_id", "source_name"}
)


class LibraryExportScope(str, Enum):
    SELECTED = "selected"
    FILTERED = "filtered"


class LibraryExportError(RuntimeError):
    """Stable application-level failure for invalid/unavailable Library export."""


@dataclass(frozen=True, slots=True)
class LibraryExportRequest:
    scope: LibraryExportScope
    game_ids: tuple[int, ...] = ()
    query: GameSearchQuery | None = None

    @classmethod
    def selected(cls, game_ids: object) -> "LibraryExportRequest":
        if not isinstance(game_ids, (tuple, list)):
            raise TypeError("selected game ids must be a list or tuple")
        if not 1 <= len(game_ids) <= _MAX_SELECTED_GAMES:
            raise ValueError("selected Library export requires one or more bounded games")
        normalized: list[int] = []
        seen: set[int] = set()
        for value in game_ids:
            if type(value) is not int or value <= 0 or value > _SQLITE_INTEGER_MAX:
                raise ValueError("Library export game ids must be positive integers")
            if value in seen:
                raise ValueError("Library export contains a duplicate game id")
            seen.add(value)
            normalized.append(value)
        # Canonical Library identity order, independent of browser click order.
        return cls(scope=LibraryExportScope.SELECTED, game_ids=tuple(sorted(normalized)))

    @classmethod
    def filtered(cls, query: GameSearchQuery) -> "LibraryExportRequest":
        if not isinstance(query, GameSearchQuery):
            raise TypeError("filtered Library export requires GameSearchQuery")
        normalized = query.normalized()
        if normalized.after_game_id is not None:
            raise ValueError("filtered Library export cannot accept a paging cursor")
        # Page size is an execution detail, not part of filtered-set identity.
        normalized = replace(normalized, after_game_id=None, limit=_EXPORT_PAGE_SIZE)
        return cls(scope=LibraryExportScope.FILTERED, query=normalized)

    @classmethod
    def from_payload(cls, payload: object) -> "LibraryExportRequest":
        if not isinstance(payload, Mapping) or len(payload) > 2:
            raise ValueError("invalid Library export request")
        if any(type(key) is not str for key in payload):
            raise ValueError("invalid Library export request")
        scope = payload.get("scope")
        if scope == LibraryExportScope.SELECTED.value:
            if set(payload) != {"scope", "game_ids"}:
                raise ValueError("invalid selected Library export fields")
            return cls.selected(payload["game_ids"])
        if scope == LibraryExportScope.FILTERED.value:
            if set(payload) != {"scope", "filters"}:
                raise ValueError("invalid filtered Library export fields")
            filters = payload["filters"]
            if not isinstance(filters, Mapping) or len(filters) > len(_FILTER_FIELDS):
                raise ValueError("invalid Library export filters")
            if any(type(key) is not str for key in filters):
                raise ValueError("invalid Library export filters")
            if set(filters).difference(_FILTER_FIELDS):
                raise ValueError("unsupported Library export filter")
            query = GameSearchQuery(
                player=filters.get("player"),
                event=filters.get("event"),
                eco=filters.get("eco"),
                opening=filters.get("opening"),
                result=filters.get("result"),
                source_id=filters.get("source_id"),
                source_name=filters.get("source_name"),
                limit=_EXPORT_PAGE_SIZE,
            )
            return cls.filtered(query)
        raise ValueError("unsupported Library export scope")

    def browser_payload(self) -> dict[str, object]:
        """Return path-free JSON-ready authority for the trusted host delegate."""

        if self.scope is LibraryExportScope.SELECTED:
            return {"scope": self.scope.value, "game_ids": self.game_ids}
        if self.query is None:
            raise ValueError("filtered Library export is missing its query")
        q = self.query
        filters = {
            key: value
            for key, value in {
                "player": q.player,
                "event": q.event,
                "eco": q.eco,
                "opening": q.opening,
                "result": q.result,
                "source_id": q.source_id,
                "source_name": q.source_name,
            }.items()
            if value is not None
        }
        return {"scope": self.scope.value, "filters": filters}


@dataclass(frozen=True, slots=True)
class LibraryExportResult:
    game_count: int
    destination_fingerprint: SourceFingerprint


class LibraryExportService:
    """Read canonical ACSDB games and publish one atomic PGN file."""

    def __init__(
        self,
        database: AcsDatabase,
        *,
        search_service: GameSearchService | None = None,
    ) -> None:
        if not isinstance(database, AcsDatabase):
            raise TypeError("database must be AcsDatabase")
        if search_service is not None and not isinstance(search_service, GameSearchService):
            raise TypeError("search_service must be GameSearchService")
        self._database = database
        self._search = search_service or GameSearchService(database)

    def _iter_selected_ids(self, request: LibraryExportRequest) -> Iterator[int]:
        if request.scope is LibraryExportScope.SELECTED:
            yield from request.game_ids
            return
        if request.scope is not LibraryExportScope.FILTERED or request.query is None:
            raise LibraryExportError("invalid Library export request")

        cursor: int | None = None
        found = False
        while True:
            page_query = replace(
                request.query,
                after_game_id=cursor,
                limit=_EXPORT_PAGE_SIZE,
            )
            page = self._search.search(page_query)
            for item in page.items:
                found = True
                yield item.game_id
            if not page.has_more:
                break
            if page.next_after_game_id is None or page.next_after_game_id == cursor:
                raise LibraryExportError("Library export paging did not advance")
            cursor = page.next_after_game_id
        if not found:
            raise LibraryExportError("Library export contains no games")

    def _selected_ids(self, request: LibraryExportRequest) -> tuple[int, ...]:
        """Compatibility helper for callers that explicitly request materialized ids."""

        return tuple(self._iter_selected_ids(request))

    def _load_game(self, game_id: int) -> PgnGame:
        row = self._database.get_game(game_id)
        if row is None:
            raise LibraryExportError("Library export game is unavailable")
        text = row.get("pgn_text")
        if type(text) is not str or not text.strip():
            raise LibraryExportError("Library export game has no canonical PGN")
        try:
            games = parse_pgn_text(text, strict=True)
        except Exception as exc:
            raise LibraryExportError("Library export game is not lossless-PGN safe") from exc
        if len(games) != 1:
            raise LibraryExportError("Library export record must contain exactly one game")
        return games[0]

    def _iter_games(self, request: LibraryExportRequest) -> Iterator[PgnGame]:
        for game_id in self._iter_selected_ids(request):
            yield self._load_game(game_id)

    @contextmanager
    def _read_snapshot(self):
        if self._database.conn.in_transaction:
            raise LibraryExportError("Library database is busy")
        # Hold one SQLite read transaction for the whole D06 consumption. This
        # preserves the exact filtered set while avoiding all-game materialization.
        self._database.conn.execute("BEGIN")
        try:
            yield
        finally:
            self._database.conn.rollback()

    def resolve_games(self, request: LibraryExportRequest) -> tuple[PgnGame, ...]:
        """Resolve one immutable export snapshot in deterministic Library-id order.

        This compatibility API intentionally materializes its result. The normal
        end-user export path below is incremental and should be used for large sets.
        """

        if not isinstance(request, LibraryExportRequest):
            raise TypeError("request must be LibraryExportRequest")
        with self._read_snapshot():
            games = tuple(self._iter_games(request))
            if len(games) > _MAX_SELECTED_GAMES and request.scope is LibraryExportScope.SELECTED:
                raise LibraryExportError("selected Library export is too large")
            return games

    def export_to(
        self,
        destination: str | Path,
        request: LibraryExportRequest,
    ) -> LibraryExportResult:
        """Stream one stable Library snapshot into the canonical D06 writer."""

        if not isinstance(request, LibraryExportRequest):
            raise TypeError("request must be LibraryExportRequest")
        game_count = 0

        def counted_games() -> Iterator[PgnGame]:
            nonlocal game_count
            for game in self._iter_games(request):
                game_count += 1
                yield game

        # The transaction stays open while save_pgn_atomic consumes the lazy
        # iterable, so paging and row loads all observe one exact read snapshot.
        # D06 still owns temp-file writing, cleanup and atomic publication.
        with self._read_snapshot():
            fingerprint = save_pgn_atomic(
                destination,
                counted_games(),
                overwrite=True,
            )
        return LibraryExportResult(
            game_count=game_count,
            destination_fingerprint=fingerprint,
        )


__all__ = [
    "LibraryExportError",
    "LibraryExportRequest",
    "LibraryExportResult",
    "LibraryExportScope",
    "LibraryExportService",
]
