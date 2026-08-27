from __future__ import annotations

"""Trusted-host ChessBase decoding to atomic ACSDB publication.

The external decoder owns only the read-only source adapter.  This module is
the narrow application seam that hands its already validated canonical
``PgnGame`` objects to the existing Library import transaction.  It never
exposes ChessBase records to ACSDB or presentation code and never writes to the
source family.
"""

from dataclasses import dataclass
from enum import Enum
from hashlib import sha256
from pathlib import Path
from typing import Callable

from .acsdb import AcsDatabase
from .chessbase_decoder import (
    ChessBaseDecodeWarning,
    ExternalChessBaseDecoderConfig,
    decode_chessbase_external,
)
from .chessbase_integrity import ChessBaseIntegritySnapshot
from .library_import_service import (
    LibraryImportCancelledError,
    LibraryImportControlError,
    LibraryImportProgress,
    LibraryImportResult,
    LibraryImportService,
)
from .report_paths import report_safe_name


class ChessBaseLibraryImportStatus(str, Enum):
    IMPORTED = "imported"
    IMPORTED_WITH_WARNINGS = "imported_with_warnings"
    NO_GAMES = "no_games"


@dataclass(frozen=True, slots=True)
class ChessBaseLibraryImportReport:
    """Bounded, path-safe result for one trusted-host CBH import."""

    status: ChessBaseLibraryImportStatus
    source_name: str
    source_sha256: str
    backend_name: str
    backend_commit: str
    decoded_game_count: int
    warnings: tuple[ChessBaseDecodeWarning, ...]
    library_result: LibraryImportResult | None

    @property
    def imported_game_count(self) -> int:
        return 0 if self.library_result is None else self.library_result.game_count

    @property
    def warning_count(self) -> int:
        return len(self.warnings)


CancelCheck = Callable[[], bool]
ProgressCallback = Callable[[LibraryImportProgress], None]


def chessbase_family_sha256(snapshot: ChessBaseIntegritySnapshot) -> str:
    """Return one deterministic digest for the complete observed source family."""

    if not isinstance(snapshot, ChessBaseIntegritySnapshot):
        raise TypeError("snapshot must be a ChessBaseIntegritySnapshot")
    digest = sha256(b"Accessible-Chess-CBH-family-v1\0")
    evidence = sorted(
        snapshot.files,
        key=lambda item: (item.extension, item.role, item.size_bytes, item.sha256),
    )
    for item in evidence:
        digest.update(item.extension.encode("utf-8"))
        digest.update(b"\0")
        digest.update(item.role.encode("utf-8"))
        digest.update(b"\0")
        digest.update(str(item.size_bytes).encode("ascii"))
        digest.update(b"\0")
        digest.update(item.sha256.encode("ascii"))
        digest.update(b"\0")
    return digest.hexdigest()


def _poll_cancel(cancel_check: CancelCheck | None) -> None:
    if cancel_check is None:
        return
    if not callable(cancel_check):
        raise TypeError("cancel_check must be callable")
    try:
        cancelled = cancel_check()
    except LibraryImportCancelledError:
        raise
    except Exception as exc:
        raise LibraryImportControlError(
            "ChessBase import cancellation check failed"
        ) from exc
    if type(cancelled) is not bool:
        raise LibraryImportControlError("cancel_check must return a boolean")
    if cancelled:
        raise LibraryImportCancelledError("ChessBase import cancelled")


class ChessBaseLibraryImportService:
    """Decode a classic CBH family and publish it through one ACSDB transaction."""

    def __init__(
        self,
        database: AcsDatabase,
        decoder_config: ExternalChessBaseDecoderConfig,
    ) -> None:
        if not isinstance(database, AcsDatabase):
            raise TypeError("database must be an AcsDatabase")
        if not isinstance(decoder_config, ExternalChessBaseDecoderConfig):
            raise TypeError(
                "decoder_config must be an ExternalChessBaseDecoderConfig"
            )
        self._library = LibraryImportService(database)
        self._decoder_config = decoder_config

    def import_database(
        self,
        path: str | Path,
        *,
        cancel_check: CancelCheck | None = None,
        progress_callback: ProgressCallback | None = None,
    ) -> ChessBaseLibraryImportReport:
        """Decode fully, then atomically publish canonical games to the Library.

        Cancellation is checked before external decoding and again before any
        ACSDB attempt is created.  The existing Library transaction continues
        polling through staging and immediately before commit, so cancellation
        can never publish a partial source.
        """

        _poll_cancel(cancel_check)
        decoded = decode_chessbase_external(path, self._decoder_config)
        _poll_cancel(cancel_check)

        source_name = report_safe_name(decoded.source.primary_path)
        source_digest = chessbase_family_sha256(decoded.source)
        warnings = tuple(decoded.warnings)
        if not decoded.games:
            return ChessBaseLibraryImportReport(
                status=ChessBaseLibraryImportStatus.NO_GAMES,
                source_name=source_name,
                source_sha256=source_digest,
                backend_name=decoded.backend_name,
                backend_commit=decoded.backend_commit,
                decoded_game_count=0,
                warnings=warnings,
                library_result=None,
            )

        imported = self._library.import_games(
            decoded.games,
            source_name=source_name,
            source_format="cbh",
            source_sha256=source_digest,
            source_warning_count=len(warnings),
            cancel_check=cancel_check,
            progress_callback=progress_callback,
        )
        status = (
            ChessBaseLibraryImportStatus.IMPORTED_WITH_WARNINGS
            if imported.warning_count
            else ChessBaseLibraryImportStatus.IMPORTED
        )
        return ChessBaseLibraryImportReport(
            status=status,
            source_name=source_name,
            source_sha256=source_digest,
            backend_name=decoded.backend_name,
            backend_commit=decoded.backend_commit,
            decoded_game_count=len(decoded.games),
            warnings=warnings,
            library_result=imported,
        )
