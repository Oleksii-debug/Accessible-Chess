from __future__ import annotations

"""Trusted-host ChessBase decoding to atomic ACSDB publication.

The external decoder owns only the read-only source adapter. This module is
the narrow application seam that hands its already validated canonical
``PgnGame`` objects to the existing Library import transaction. It never
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
from .import_contract import verify_source_unchanged
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

    def _decode_source(
        self,
        path: str | Path,
        *,
        cancel_check: CancelCheck | None = None,
    ):
        """Return decoded games plus path-safe provenance for CBH or CBV."""

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
            try:
                extracted = extract_cbv_external(
                    source_path,
                    Path(temporary),
                    self._cbv_extractor_config,
                    cancel_check=cancel_check,
                )
            except CbvExtractError as exc:
                if exc.code is CbvExtractCode.CANCELLED:
                    raise LibraryImportCancelledError(
                        "ChessBase import cancelled"
                    ) from None
                if exc.code is CbvExtractCode.CONTROL_INVALID:
                    raise LibraryImportControlError(
                        "ChessBase import cancellation check failed"
                    ) from exc
                raise

            _poll_cancel(cancel_check)
            decoded = decode_chessbase_external(
                extracted.primary_path,
                self._decoder_config,
            )
            if not verify_source_unchanged(extracted.source, source_path):
                raise CbvExtractError(
                    "CBV source changed while its extracted database was decoded",
                    code=CbvExtractCode.SOURCE_CHANGED,
                )
            return (
                decoded,
                report_safe_name(extracted.source.path),
                extracted.source.sha256,
                "cbv",
                extracted.backend_name,
                extracted.backend_sha256,
            )

    def import_database(
        self,
        path: str | Path,
        *,
        cancel_check: CancelCheck | None = None,
        progress_callback: ProgressCallback | None = None,
    ) -> ChessBaseLibraryImportReport:
        """Decode fully, then atomically publish canonical games to the Library.

        Cancellation is checked before external decoding, during delegated CBV
        extraction, after extraction/before CBH decode, and again before any
        ACSDB attempt is created. The existing Library transaction continues
        polling through staging and immediately before commit, so cancellation
        can never publish a partial source.
        """

        _poll_cancel(cancel_check)
        (
            decoded,
            source_name,
            source_digest,
            source_format,
            archive_backend_name,
            archive_backend_sha256,
        ) = self._decode_source(path, cancel_check=cancel_check)
        _poll_cancel(cancel_check)

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
