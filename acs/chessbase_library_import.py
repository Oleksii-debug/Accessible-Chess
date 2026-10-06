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
from .chessbase_integrity import ChessBaseIntegritySnapshot
from .library_import_service import (
    LibraryImportCancelledError,
    LibraryImportControlError,
    LibraryImportProgress,
    LibraryImportResult,
    LibraryImportService,
)
from .import_contract import SourceFingerprint, fingerprint, verify_source_unchanged
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

    def __post_init__(self) -> None:
        # This object crosses from the trusted ChessBase service into host/UI
        # orchestration. Reject derived roots before *any* field access so a
        # subclass cannot execute active descriptor hooks during validation.
        if type(self) is not ChessBaseLibraryImportReport:
            raise TypeError(
                "ChessBase import report must be an exact passive DTO"
            )

        if type(self.status) is not ChessBaseLibraryImportStatus:
            raise TypeError("ChessBase import report status is invalid")
        for name, value in (
            ("source_name", self.source_name),
            ("source_sha256", self.source_sha256),
            ("backend_name", self.backend_name),
            ("backend_commit", self.backend_commit),
            ("source_format", self.source_format),
        ):
            if type(value) is not str:
                raise TypeError(f"{name} must be exact text")
        if self.source_format not in {"cbh", "cbv"}:
            raise ValueError("ChessBase import source format is invalid")

        for name, value in (
            ("archive_backend_name", self.archive_backend_name),
            ("archive_backend_sha256", self.archive_backend_sha256),
        ):
            if value is not None and type(value) is not str:
                raise TypeError(f"{name} must be exact text or None")

        decoded_game_count = self.decoded_game_count
        if type(decoded_game_count) is not int:
            raise TypeError("decoded_game_count must be an integer")
        if decoded_game_count < 0:
            raise ValueError("decoded_game_count must be non-negative")

        warnings = self.warnings
        if type(warnings) is not tuple:
            raise TypeError("ChessBase import warnings must be an exact tuple")
        if any(type(item) is not ChessBaseDecodeWarning for item in warnings):
            raise TypeError(
                "ChessBase import warnings must contain exact decode warnings"
            )

        library_result = self.library_result
        if library_result is not None and type(library_result) is not LibraryImportResult:
            raise TypeError(
                "ChessBase import library result must be an exact LibraryImportResult or None"
            )

        if self.status is ChessBaseLibraryImportStatus.NO_GAMES:
            if decoded_game_count != 0 or library_result is not None:
                raise ValueError(
                    "no-games ChessBase report must contain no decoded/imported games"
                )
            return

        if library_result is None:
            raise ValueError(
                "imported ChessBase report must contain a Library import result"
            )
        game_count = library_result.game_count
        warning_count = library_result.warning_count
        if type(game_count) is not int or game_count < 1:
            raise TypeError("ChessBase Library result game count is invalid")
        if type(warning_count) is not int or warning_count < 0:
            raise TypeError("ChessBase Library result warning count is invalid")
        if decoded_game_count != game_count:
            raise ValueError(
                "ChessBase decoded and imported game counts must match"
            )
        expected_status = (
            ChessBaseLibraryImportStatus.IMPORTED_WITH_WARNINGS
            if warning_count
            else ChessBaseLibraryImportStatus.IMPORTED
        )
        if self.status is not expected_status:
            raise ValueError(
                "ChessBase import status does not match Library warning count"
            )

    @property
    def imported_game_count(self) -> int:
        return 0 if self.library_result is None else self.library_result.game_count

    @property
    def warning_count(self) -> int:
        return len(self.warnings)


CancelCheck = Callable[[], bool]
ProgressCallback = Callable[[LibraryImportProgress], None]
_LIBCBH_UNSUPPORTED_CHESS960_RECORD = 960


def _library_warnings(
    warnings: tuple[ChessBaseDecodeWarning, ...] | list[ChessBaseDecodeWarning],
) -> tuple[ChessBaseDecodeWarning, ...]:
    """Project one reserved transport loss into a stable user-facing warning."""
    projected: list[ChessBaseDecodeWarning] = []
    expected_message = (
        f"backend record skipped with code {_LIBCBH_UNSUPPORTED_CHESS960_RECORD}"
    )
    for warning in warnings:
        if (
            warning.code == "backend_record_skipped"
            and warning.message == expected_message
        ):
            projected.append(
                ChessBaseDecodeWarning(
                    warning.game_index,
                    "unsupported_variant",
                    "Chess960/Fischer Random record is unsupported and was not imported",
                )
            )
        else:
            projected.append(warning)
    return tuple(projected)


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


class _BackendFingerprintControlError(RuntimeError):
    def __init__(self, cause: Exception) -> None:
        super().__init__("backend fingerprint control checkpoint failed")
        self.cause = cause


def _backend_fingerprint_cancel_check(
    control_checkpoint: Callable[[], None] | None,
) -> Callable[[], bool] | None:
    if control_checkpoint is None:
        return None

    def poll() -> bool:
        try:
            control_checkpoint()
        except Exception as exc:
            raise _BackendFingerprintControlError(exc) from exc
        return False

    return poll


def _capture_decoder_backend(
    config: ExternalChessBaseDecoderConfig,
    *,
    control_checkpoint: Callable[[], None] | None = None,
) -> SourceFingerprint:
    """Fingerprint the exact external decoder before consuming its output."""

    try:
        return fingerprint(
            config.executable,
            cancel_check=_backend_fingerprint_cancel_check(control_checkpoint),
        )
    except _BackendFingerprintControlError as exc:
        raise exc.cause
    except (OSError, ValueError) as exc:
        raise ChessBaseDecodeError(
            "ChessBase decoder backend failed read-only validation",
            code=ChessBaseDecodeCode.BACKEND_INVALID,
        ) from exc


def _verify_decoder_backend_unchanged(
    before: SourceFingerprint,
    *,
    control_checkpoint: Callable[[], None] | None = None,
) -> None:
    """Reject decoded data if the executable changed during the operation."""

    try:
        after = fingerprint(
            before.path,
            cancel_check=_backend_fingerprint_cancel_check(control_checkpoint),
        )
        unchanged = before.size == after.size and before.sha256 == after.sha256
    except _BackendFingerprintControlError as exc:
        raise exc.cause
    except (OSError, ValueError):
        unchanged = False
    if not unchanged:
        raise ChessBaseDecodeError(
            "ChessBase decoder backend changed while it was running",
            code=ChessBaseDecodeCode.BACKEND_INVALID,
        )


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

    def _decode_with_immutable_backend(
        self,
        source_path: Path,
        *,
        control_checkpoint: Callable[[], None] | None = None,
    ):
        backend = _capture_decoder_backend(
            self._decoder_config,
            control_checkpoint=control_checkpoint,
        )
        control = (
            {}
            if control_checkpoint is None
            else {"control_checkpoint": control_checkpoint}
        )
        decoded = decode_chessbase_external(
            source_path,
            self._decoder_config,
            **control,
        )
        _verify_decoder_backend_unchanged(
            backend,
            control_checkpoint=control_checkpoint,
        )
        return decoded

    def _decode_source(self, path: str | Path, *, cancel_check: CancelCheck | None = None):
        """Return decoded games plus path-safe provenance for CBH or CBV."""

        source_path = Path(path)
        control = {} if cancel_check is None else {
            "control_checkpoint": lambda: _poll_cancel(cancel_check)
        }
        suffix = source_path.suffix.lower()
        if suffix == ".cbh":
            decoded = self._decode_with_immutable_backend(source_path, **control)
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
            extracted = extract_cbv_external(
                source_path,
                Path(temporary),
                self._cbv_extractor_config,
                **control,
            )
            decoded = self._decode_with_immutable_backend(
                extracted.primary_path,
                **control,
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

        Cancellation is checked before and during external listing/extraction/
        decoding and again before any ACSDB attempt is created. The existing
        Library transaction continues
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

        warnings = _library_warnings(decoded.warnings)
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
