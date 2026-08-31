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
import tempfile
from typing import Callable

from .acsdb import AcsDatabase
from .cbv_extractor import (
    CbvExtractCode,
    CbvExtractError,
    ExternalCbvExtractorConfig,
    extract_cbv_external,
)
from .chessbase_decoder import (
    ChessBaseDecodeCode,
    ChessBaseDecodeError,
    ChessBaseDecodeWarning,
    ExternalChessBaseDecoderConfig,
    decode_chessbase_external,
)
from .chessbase_integrity import (
    ChessBaseIntegrityIOError,
    ChessBaseIntegritySnapshot,
    ChessBaseSourceChangedError,
    verify_integrity_snapshot,
)
from .library_import_service import (
    LibraryImportCancelledError,
    LibraryImportControlError,
    LibraryImportProgress,
    LibraryImportResult,
    LibraryImportService,
)
from .import_contract import SourceFingerprint, verify_source_unchanged
from .report_paths import report_safe_name


class ChessBaseLibraryImportStatus(str, Enum):
    IMPORTED = "imported"
    IMPORTED_WITH_WARNINGS = "imported_with_warnings"
    NO_GAMES = "no_games"


@dataclass(frozen=True, slots=True)
class ChessBaseLibraryImportReport:
    """Bounded, path-safe result for one trusted-host CBH/CBV import."""

    status: ChessBaseLibraryImportStatus
    source_name: str
    source_sha256: str
    backend_name: str
    backend_commit: str
    decoded_game_count: int
    warnings: tuple[ChessBaseDecodeWarning, ...]
    library_result: LibraryImportResult | None
    source_format: str = "cbh"
    archive_backend_name: str | None = None
    archive_backend_sha256: str | None = None

    @property
    def imported_game_count(self) -> int:
        return 0 if self.library_result is None else self.library_result.game_count

    @property
    def warning_count(self) -> int:
        return len(self.warnings)


@dataclass(frozen=True, slots=True)
class _PublicationGuard:
    """Read-only evidence that must still match before ACSDB is touched."""

    source_format: str
    cbh_snapshot: ChessBaseIntegritySnapshot | None = None
    cbv_source: SourceFingerprint | None = None


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


def _verify_cbh_publication_snapshot(snapshot: ChessBaseIntegritySnapshot) -> None:
    """Reject any CBH-family drift after backend validation, before publication."""

    try:
        verify_integrity_snapshot(snapshot)
    except (ChessBaseSourceChangedError, ChessBaseIntegrityIOError, OSError, ValueError) as exc:
        raise ChessBaseDecodeError(
            "ChessBase source changed before Library publication; decoded output was discarded",
            code=ChessBaseDecodeCode.SOURCE_CHANGED,
        ) from exc


def _verify_cbv_publication_source(before: SourceFingerprint, path: Path) -> None:
    """Reject archive replacement/mutation after extraction, before publication."""

    try:
        unchanged = verify_source_unchanged(before, path)
    except (OSError, ValueError) as exc:
        raise CbvExtractError(
            "CBV source could not be revalidated before Library publication",
            code=CbvExtractCode.SOURCE_CHANGED,
        ) from exc
    if not unchanged:
        raise CbvExtractError(
            "CBV source changed before Library publication; decoded output was discarded",
            code=CbvExtractCode.SOURCE_CHANGED,
        )


def _verify_publication_guard(path: str | Path, guard: _PublicationGuard) -> None:
    if guard.source_format == "cbh":
        if guard.cbh_snapshot is None:
            raise RuntimeError("CBH publication guard is incomplete")
        _verify_cbh_publication_snapshot(guard.cbh_snapshot)
        return
    if guard.source_format == "cbv":
        if guard.cbv_source is None:
            raise RuntimeError("CBV publication guard is incomplete")
        _verify_cbv_publication_source(guard.cbv_source, Path(path))
        return
    raise RuntimeError("ChessBase publication guard has an unsupported source format")


class ChessBaseLibraryImportService:
    """Decode a classic CBH family and publish it through one ACSDB transaction."""

    def __init__(
        self,
        database: AcsDatabase,
        decoder_config: ExternalChessBaseDecoderConfig,
        cbv_extractor_config: ExternalCbvExtractorConfig | None = None,
    ) -> None:
        if not isinstance(database, AcsDatabase):
            raise TypeError("database must be an AcsDatabase")
        if not isinstance(decoder_config, ExternalChessBaseDecoderConfig):
            raise TypeError(
                "decoder_config must be an ExternalChessBaseDecoderConfig"
            )
        if cbv_extractor_config is not None and not isinstance(
            cbv_extractor_config,
            ExternalCbvExtractorConfig,
        ):
            raise TypeError(
                "cbv_extractor_config must be an ExternalCbvExtractorConfig or None"
            )
        self._library = LibraryImportService(database)
        self._decoder_config = decoder_config
        self._cbv_extractor_config = cbv_extractor_config

    def _decode_source(self, path: str | Path):
        """Return decoded games plus path-safe provenance and publication evidence."""

        source_path = Path(path)
        suffix = source_path.suffix.lower()
        if suffix == ".cbh":
            decoded = decode_chessbase_external(source_path, self._decoder_config)
            return (
                decoded,
                report_safe_name(decoded.source.primary_path),
                chessbase_family_sha256(decoded.source),
                "cbh",
                None,
                None,
                _PublicationGuard("cbh", cbh_snapshot=decoded.source),
            )
        if suffix != ".cbv":
            raise CbvExtractError(
                "ChessBase Library import currently supports .cbh and .cbv sources only",
                code=CbvExtractCode.UNSUPPORTED_SOURCE,
            )
        if self._cbv_extractor_config is None:
            raise CbvExtractError(
                "CBV import requires a configured trusted external extractor",
                code=CbvExtractCode.BACKEND_INVALID,
            )

        with tempfile.TemporaryDirectory(prefix="accessible-chess-cbv-") as temporary:
            extracted = extract_cbv_external(
                source_path,
                Path(temporary),
                self._cbv_extractor_config,
            )
            decoded = decode_chessbase_external(
                extracted.primary_path,
                self._decoder_config,
            )
            # The decoder verifies the extracted family immediately after its
            # backend exits, then performs bounded JSON/GameTree conversion.  A
            # hostile or crashing external process must not be able to mutate or
            # delete a companion in that later window and have stale decoded data
            # escape the private temporary workspace.
            _verify_cbh_publication_snapshot(decoded.source)
            _verify_cbv_publication_source(extracted.source, source_path)
            return (
                decoded,
                report_safe_name(extracted.source.path),
                extracted.source.sha256,
                "cbv",
                extracted.backend_name,
                extracted.backend_sha256,
                _PublicationGuard("cbv", cbv_source=extracted.source),
            )

    def import_database(
        self,
        path: str | Path,
        *,
        cancel_check: CancelCheck | None = None,
        progress_callback: ProgressCallback | None = None,
    ) -> ChessBaseLibraryImportReport:
        """Decode fully, then atomically publish canonical games to the Library.

        Cancellation is checked before external decoding and again before any
        ACSDB attempt is created.  Immediately after that final callback, the
        exact source evidence is revalidated so source-family corruption or
        mutation cannot create an ACSDB source/import-attempt row.  The existing
        Library transaction continues polling through staging and immediately
        before commit, so cancellation can never publish a partial source.
        """

        _poll_cancel(cancel_check)
        (
            decoded,
            source_name,
            source_digest,
            source_format,
            archive_backend_name,
            archive_backend_sha256,
            publication_guard,
        ) = self._decode_source(path)
        _poll_cancel(cancel_check)

        warnings = tuple(decoded.warnings)
        _verify_publication_guard(path, publication_guard)
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
                source_format=source_format,
                archive_backend_name=archive_backend_name,
                archive_backend_sha256=archive_backend_sha256,
            )

        imported = self._library.import_games(
            decoded.games,
            source_name=source_name,
            source_format=source_format,
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
            source_format=source_format,
            archive_backend_name=archive_backend_name,
            archive_backend_sha256=archive_backend_sha256,
        )