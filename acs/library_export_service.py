from __future__ import annotations

"""Canonical D07 Library -> PGN export application service.

Library selection/search semantics live here; filesystem selection deliberately
does not. A trusted host supplies the destination only after the browser request
has been validated. PGN serialization/publication is delegated to the existing
D06 atomic writer so Library export cannot become a second serializer.
"""

from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass, replace
from enum import Enum
import hashlib
import os
from pathlib import Path
import stat
from typing import Final

from .acsdb import AcsDatabase
from .gametree import PgnGame
from .import_contract import (
    _open_readonly_no_reparse,
    _publish_opened_fingerprint,
    _validate_source_path,
    fingerprint,
)
from .pgn_roundtrip import parse_pgn_text
from .pgn_service import SourceFingerprint, save_pgn_atomic
from .search_service import (
    GameSearchItem,
    GameSearchPage,
    GameSearchQuery,
    GameSearchService,
    SearchCancelledError,
    SearchControlError,
)


_MAX_SELECTED_GAMES: Final = 5000
_EXPORT_PAGE_SIZE: Final = 200
_SQLITE_INTEGER_MAX: Final = (1 << 63) - 1
_FINGERPRINT_CHUNK_SIZE: Final = 1024 * 1024
_FILTER_FIELDS: Final = frozenset(
    {"player", "event", "eco", "opening", "result", "source_id", "source_name", "date_from", "date_to", "game_date"}
)


class LibraryExportScope(str, Enum):
    SELECTED = "selected"
    FILTERED = "filtered"


class LibraryExportError(RuntimeError):
    """Stable application-level failure for invalid/unavailable Library export."""


class LibraryExportCancelledError(LibraryExportError):
    """Cooperative cancellation before the D06 publication point."""


class LibraryExportControlError(LibraryExportError):
    """A cancellation callback violated the bounded control contract."""


CancelCheck = Callable[[], bool]


def _poll_cancel(cancel_check: CancelCheck | None) -> None:
    if cancel_check is None:
        return
    try:
        cancelled = cancel_check()
    except LibraryExportCancelledError:
        raise
    except Exception as exc:
        raise LibraryExportControlError("Library export cancellation check failed") from exc
    if type(cancelled) is not bool:
        raise LibraryExportControlError("Library export cancel_check must return a boolean")
    if cancelled:
        raise LibraryExportCancelledError("Library export cancelled")


def _cancellable_fingerprint(
    path: str | Path,
    *,
    cancel_check: CancelCheck | None,
    chunk_size: int = _FINGERPRINT_CHUNK_SIZE,
) -> SourceFingerprint:
    """Fingerprint one direct file with canonical two-pass authority checks.

    ``import_contract.fingerprint`` remains the canonical non-cancellable path.
    This control adapter reuses its no-follow/opened-object/publication primitives
    and differs only by polling cancellation between finite hash chunks.
    """
    if cancel_check is None:
        return fingerprint(path, chunk_size=chunk_size)
    if type(chunk_size) is not int or chunk_size <= 0:
        raise ValueError("chunk_size must be positive")

    _poll_cancel(cancel_check)
    submitted = Path(path)
    absolute, path_before = _validate_source_path(submitted)
    descriptor = _open_readonly_no_reparse(absolute)
    try:
        fd_before = os.fstat(descriptor)
        if not stat.S_ISREG(fd_before.st_mode):
            raise ValueError("Library export destination must be a regular file")
        if (fd_before.st_dev, fd_before.st_ino) != (path_before.st_dev, path_before.st_ino):
            raise ValueError("Library export destination changed before fingerprinting")

        def digest_open_inode() -> str:
            digest = hashlib.sha256()
            while True:
                _poll_cancel(cancel_check)
                chunk = os.read(descriptor, chunk_size)
                if not chunk:
                    _poll_cancel(cancel_check)
                    return digest.hexdigest()
                digest.update(chunk)

        first_sha256 = digest_open_inode()
        os.lseek(descriptor, 0, os.SEEK_SET)
        verified_sha256 = digest_open_inode()
        if first_sha256 != verified_sha256:
            raise ValueError("Library export destination changed while fingerprinting")
        fd_after = os.fstat(descriptor)
    finally:
        os.close(descriptor)

    _poll_cancel(cancel_check)
    return _publish_opened_fingerprint(
        submitted,
        absolute,
        path_before,
        fd_before,
        fd_after,
        verified_sha256,
    )


@dataclass(frozen=True, slots=True)
class LibraryExportRequest:
    scope: LibraryExportScope
    game_ids: tuple[int, ...] = ()
    query: GameSearchQuery | None = None

    @classmethod
    def selected(cls, game_ids: object) -> "LibraryExportRequest":
        if type(game_ids) not in {tuple, list}:
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
        return cls(scope=LibraryExportScope.SELECTED, game_ids=tuple(sorted(normalized)))

    @classmethod
    def filtered(cls, query: GameSearchQuery) -> "LibraryExportRequest":
        if type(query) is not GameSearchQuery:
            raise TypeError("filtered Library export requires GameSearchQuery")
        normalized = query.normalized()
        if normalized.after_game_id is not None:
            raise ValueError("filtered Library export cannot accept a paging cursor")
        normalized = replace(normalized, after_game_id=None, limit=_EXPORT_PAGE_SIZE)
        return cls(scope=LibraryExportScope.FILTERED, query=normalized)

    @classmethod
    def from_payload(cls, payload: object) -> "LibraryExportRequest":
        if type(payload) is not dict or len(payload) > 2:
            raise ValueError("invalid Library export request")
        if any(type(key) is not str for key in payload):
            raise ValueError("invalid Library export request")
        scope = payload.get("scope")
        if type(scope) is not str:
            raise ValueError("unsupported Library export scope")
        if scope == LibraryExportScope.SELECTED.value:
            if set(payload) != {"scope", "game_ids"}:
                raise ValueError("invalid selected Library export fields")
            return cls.selected(payload["game_ids"])
        if scope == LibraryExportScope.FILTERED.value:
            if set(payload) != {"scope", "filters"}:
                raise ValueError("invalid filtered Library export fields")
            filters = payload["filters"]
            if type(filters) is not dict or len(filters) > len(_FILTER_FIELDS):
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
                date_from=filters.get("date_from"),
                date_to=filters.get("date_to"),
                game_date=filters.get("game_date"),
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
                "date_from": q.date_from,
                "date_to": q.date_to,
                "game_date": q.game_date,
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
        self._snapshot_cleanup_failed = False

    @staticmethod
    def expected_destination_sha256(
        destination: str | Path,
        *,
        cancel_check: CancelCheck | None = None,
    ) -> str | None:
        """Bind the post-dialog destination generation without blocking Cancel."""
        _poll_cancel(cancel_check)
        path = Path(destination)
        if not path.exists():
            _poll_cancel(cancel_check)
            return None
        return _cancellable_fingerprint(path, cancel_check=cancel_check).sha256

    @staticmethod
    def _canonical_request(request: LibraryExportRequest) -> LibraryExportRequest:
        """Validate direct construction through the same public request policy."""
        if type(request) is not LibraryExportRequest:
            raise TypeError("request must be LibraryExportRequest")
        if type(request.scope) is not LibraryExportScope:
            raise LibraryExportError("invalid Library export scope")
        if request.scope is LibraryExportScope.SELECTED:
            if request.query is not None:
                raise LibraryExportError(
                    "selected Library export cannot include a search query"
                )
            if type(request.game_ids) is tuple:
                if not request.game_ids:
                    raise LibraryExportError(
                        "selected Library export contains no games"
                    )
                if len(request.game_ids) > _MAX_SELECTED_GAMES:
                    raise LibraryExportError("selected Library export is too large")
            try:
                return LibraryExportRequest.selected(request.game_ids)
            except (TypeError, ValueError) as exc:
                raise LibraryExportError("invalid selected Library export request") from exc
        if request.scope is LibraryExportScope.FILTERED:
            if type(request.game_ids) is not tuple or request.game_ids:
                raise LibraryExportError(
                    "filtered Library export cannot include selected game ids"
                )
            try:
                return LibraryExportRequest.filtered(request.query)
            except (TypeError, ValueError) as exc:
                raise LibraryExportError("invalid filtered Library export request") from exc
        raise LibraryExportError("invalid Library export scope")

    def _iter_selected_ids(
        self,
        request: LibraryExportRequest,
        *,
        cancel_check: CancelCheck | None = None,
    ) -> Iterator[int]:
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
            _poll_cancel(cancel_check)
            try:
                page = self._search.search(
                    page_query,
                    cancel_check=cancel_check,
                )
            except SearchCancelledError:
                raise LibraryExportCancelledError("Library export cancelled") from None
            except SearchControlError as exc:
                raise LibraryExportControlError(
                    "Library export cancellation check failed"
                ) from exc
            _poll_cancel(cancel_check)
            if (
                type(page) is not GameSearchPage
                or type(page.items) is not tuple
                or type(page.has_more) is not bool
            ):
                raise LibraryExportError("Library export search page is invalid")

            previous_id = 0 if cursor is None else cursor
            for item in page.items:
                if type(item) is not GameSearchItem:
                    raise LibraryExportError("Library export search item is invalid")
                game_id = item.game_id
                if (
                    type(game_id) is not int
                    or game_id <= previous_id
                    or game_id > _SQLITE_INTEGER_MAX
                ):
                    raise LibraryExportError(
                        "Library export search ids are not strictly increasing"
                    )
                previous_id = game_id
                found = True
                yield game_id

            next_cursor = page.next_after_game_id
            if not page.has_more:
                if next_cursor is not None:
                    raise LibraryExportError(
                        "Library export terminal search page has a cursor"
                    )
                break
            if (
                not page.items
                or type(next_cursor) is not int
                or next_cursor <= (0 if cursor is None else cursor)
                or next_cursor != previous_id
                or next_cursor > _SQLITE_INTEGER_MAX
            ):
                raise LibraryExportError("Library export paging did not advance")
            cursor = next_cursor
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

    def _iter_games(
        self,
        request: LibraryExportRequest,
        *,
        cancel_check: CancelCheck | None = None,
    ) -> Iterator[PgnGame]:
        for game_id in self._iter_selected_ids(
            request,
            cancel_check=cancel_check,
        ):
            yield self._load_game(game_id)

    @contextmanager
    def _read_snapshot(self, *, post_publish_success_wins: bool = False):
        if self._snapshot_cleanup_failed:
            raise LibraryExportError("Library database snapshot cleanup previously failed")
        if type(post_publish_success_wins) is not bool:
            raise TypeError("post_publish_success_wins must be a boolean")
        if self._database.conn.in_transaction:
            raise LibraryExportError("Library database is busy")
        self._database.conn.execute("BEGIN")
        body_error: BaseException | None = None
        try:
            yield
        except BaseException as exc:
            body_error = exc
            raise
        finally:
            try:
                self._database.conn.rollback()
            except BaseException:
                # Never replace a primary parser/serialization/publication error
                # with a secondary SQLite cleanup failure. If D06 already
                # returned successfully, the filesystem publication is durable
                # authority and must also win over this later cleanup failure.
                # Poison this service so a reused synchronous embedding cannot
                # silently continue on a connection with uncertain transaction
                # state; the normal Windows worker closes it immediately.
                self._snapshot_cleanup_failed = True
                if body_error is None and not post_publish_success_wins:
                    raise

    def resolve_games(self, request: LibraryExportRequest) -> tuple[PgnGame, ...]:
        """Resolve one immutable export snapshot in deterministic Library-id order."""
        request = self._canonical_request(request)
        with self._read_snapshot():
            games = tuple(self._iter_games(request))
            if len(games) > _MAX_SELECTED_GAMES and request.scope is LibraryExportScope.SELECTED:
                raise LibraryExportError("selected Library export is too large")
            return games

    def export_to(
        self,
        destination: str | Path,
        request: LibraryExportRequest,
        *,
        expected_sha256: str | None = None,
        cancel_check: CancelCheck | None = None,
    ) -> LibraryExportResult:
        """Stream a stable Library snapshot through D06 with cooperative Cancel.

        Cancellation is observed between bounded game loads/serializations and once
        after the complete temporary file is flushed+fsynced but before D06 can
        publish it. Once D06 publication commits, success wins over a later Cancel.
        """
        request = self._canonical_request(request)
        _poll_cancel(cancel_check)
        game_count = 0

        def counted_games() -> Iterator[PgnGame]:
            nonlocal game_count
            for game in self._iter_games(
                request,
                cancel_check=cancel_check,
            ):
                _poll_cancel(cancel_check)
                game_count += 1
                yield game
                _poll_cancel(cancel_check)

        with self._read_snapshot(post_publish_success_wins=True):
            published = save_pgn_atomic(
                destination,
                counted_games(),
                overwrite=expected_sha256 is not None,
                expected_sha256=expected_sha256,
                pre_publish_check=(
                    None if cancel_check is None else lambda: _poll_cancel(cancel_check)
                ),
            )
        return LibraryExportResult(
            game_count=game_count,
            destination_fingerprint=published,
        )


__all__ = [
    "LibraryExportCancelledError",
    "LibraryExportControlError",
    "LibraryExportError",
    "LibraryExportRequest",
    "LibraryExportResult",
    "LibraryExportScope",
    "LibraryExportService",
]
