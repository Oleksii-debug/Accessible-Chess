from __future__ import annotations

"""Canonical Library-subset -> PGN export application service.

The Library remains the owner of stored game identities and PGN snapshots.
This service does not implement a second PGN parser/serializer. It resolves the
requested Library game IDs, validates each stored PGN through the canonical D06
strict parser, and streams those canonical GameTrees into ``save_pgn_atomic``.

Filesystem destinations enter only through a trusted host/application call.
No browser payload or WebView path is accepted here.
"""

from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from .acsdb import AcsDatabase
from .import_contract import SourceFingerprint, fingerprint
from .pgn_roundtrip import PgnRoundTripError, parse_pgn_text
from .pgn_service import save_pgn_atomic


MAX_LIBRARY_EXPORT_GAMES = 100_000


class LibraryPgnExportErrorCode(str, Enum):
    INVALID_SELECTION = "invalid_selection"
    GAME_NOT_FOUND = "game_not_found"
    INVALID_STORED_PGN = "invalid_stored_pgn"


class LibraryPgnExportError(RuntimeError):
    def __init__(self, message: str, *, code: LibraryPgnExportErrorCode) -> None:
        super().__init__(message)
        self.code = LibraryPgnExportErrorCode(code)


@dataclass(frozen=True, slots=True)
class LibraryPgnExportResult:
    game_count: int
    destination: SourceFingerprint


def _validate_game_ids(game_ids: object) -> tuple[int, ...]:
    if type(game_ids) is not tuple:
        raise LibraryPgnExportError(
            "library export selection must be a tuple",
            code=LibraryPgnExportErrorCode.INVALID_SELECTION,
        )
    if not game_ids or len(game_ids) > MAX_LIBRARY_EXPORT_GAMES:
        raise LibraryPgnExportError(
            "library export selection size is invalid",
            code=LibraryPgnExportErrorCode.INVALID_SELECTION,
        )
    if any(type(game_id) is not int or game_id <= 0 for game_id in game_ids):
        raise LibraryPgnExportError(
            "library export contains an invalid game identity",
            code=LibraryPgnExportErrorCode.INVALID_SELECTION,
        )
    if len(set(game_ids)) != len(game_ids):
        raise LibraryPgnExportError(
            "library export selection contains duplicate games",
            code=LibraryPgnExportErrorCode.INVALID_SELECTION,
        )
    return game_ids


class LibraryPgnExportService:
    """Export a deterministic ordered subset of canonical Library games."""

    def __init__(self, database: AcsDatabase) -> None:
        if not isinstance(database, AcsDatabase):
            raise TypeError("database must be AcsDatabase")
        self._database = database

    def _games(self, game_ids: tuple[int, ...]):
        for game_id in game_ids:
            row = self._database.get_game(game_id)
            if row is None:
                raise LibraryPgnExportError(
                    "library game no longer exists",
                    code=LibraryPgnExportErrorCode.GAME_NOT_FOUND,
                )
            raw_pgn = row.get("pgn_text")
            if type(raw_pgn) is not str:
                raise LibraryPgnExportError(
                    "library game has no valid PGN snapshot",
                    code=LibraryPgnExportErrorCode.INVALID_STORED_PGN,
                )
            try:
                parsed = parse_pgn_text(raw_pgn, strict=True)
            except (PgnRoundTripError, TypeError, ValueError) as exc:
                raise LibraryPgnExportError(
                    "library game is not strictly exportable as PGN",
                    code=LibraryPgnExportErrorCode.INVALID_STORED_PGN,
                ) from exc
            if len(parsed) != 1:
                raise LibraryPgnExportError(
                    "library game snapshot must contain exactly one PGN game",
                    code=LibraryPgnExportErrorCode.INVALID_STORED_PGN,
                )
            yield parsed[0]

    @staticmethod
    def expected_destination_sha256(path: str | Path) -> str | None:
        destination = Path(path)
        if not destination.exists():
            return None
        return fingerprint(destination).sha256

    def export_subset(
        self,
        game_ids: object,
        destination: str | Path,
    ) -> LibraryPgnExportResult:
        """Atomically export the selected games in the supplied stable order.

        Existing destinations are protected by an optimistic fingerprint captured
        after the trusted host confirms overwrite. If another process changes the
        file before publication, the canonical PGN CAS path fails closed.
        """

        selected = _validate_game_ids(game_ids)
        path = Path(destination)
        expected = self.expected_destination_sha256(path)
        saved = save_pgn_atomic(
            path,
            self._games(selected),
            overwrite=expected is not None,
            expected_sha256=expected,
        )
        return LibraryPgnExportResult(len(selected), saved)


__all__ = [
    "LibraryPgnExportError",
    "LibraryPgnExportErrorCode",
    "LibraryPgnExportResult",
    "LibraryPgnExportService",
    "MAX_LIBRARY_EXPORT_GAMES",
]
