from __future__ import annotations

"""Current-runtime Windows composition for large PGN Library imports.

The trusted Windows file host continues to own file selection, threading,
cancellation, bounded path-free events and shutdown. This successor changes
only the ``.pgn`` worker path: it delegates incremental framing/parsing to the
canonical D06 ``StreamingPgnLibraryImporter`` and publication to the same D07
Library service supplied by the existing worker factory. CBH/CBV remain owned
by the base delegate; PGN Open shares that delegate's single worker authority.

No PGN semantics, chess rules, database transaction semantics or browser path
authority are implemented here.
"""

import logging
from pathlib import Path
import threading

from .pgn_streaming_import import (
    StreamingPgnFailurePolicy,
    StreamingPgnImportCancelledError,
    StreamingPgnImportError,
    StreamingPgnImportResult,
    StreamingPgnLibraryImporter,
    StreamingPgnPhase,
    StreamingPgnProgress,
)
from .import_contract import SourceFingerprint
from .library_import_service import LibraryImportResult
from .report_paths import report_safe_name
from .version2_windows_file_workflows import (
    FileWorkflowEvent,
    FileWorkflowEventKind,
    Version2ImportWorkerServices,
    Version2WindowsFileActionDelegate,
)


_LOG = logging.getLogger(__name__)


def _safe_warning(message: str) -> None:
    """Best-effort fixed telemetry with no worker lifecycle authority."""

    try:
        _LOG.warning(message)
    except BaseException:
        pass


def _snapshot_streaming_progress(value: StreamingPgnProgress) -> StreamingPgnProgress:
    if type(value) is not StreamingPgnProgress:
        raise TypeError("canonical streaming PGN progress object is invalid")
    return StreamingPgnProgress(
        value.phase,
        value.bytes_read,
        value.total_bytes,
        value.accepted_games,
        value.imported_games,
        value.total_games,
    )


def _snapshot_streaming_result(value: StreamingPgnImportResult) -> StreamingPgnImportResult:
    if type(value) is not StreamingPgnImportResult:
        raise TypeError("streaming PGN importer returned an invalid result")
    source = value.source
    library = value.library
    accepted_games = value.accepted_games
    complete = value.complete
    failure_code = value.failure_code
    if type(source) is not SourceFingerprint:
        raise TypeError("streaming PGN result source is invalid")
    if type(library) is not LibraryImportResult:
        raise TypeError("streaming PGN Library result is invalid")
    if type(failure_code) is not str and failure_code is not None:
        raise TypeError("streaming PGN failure code is invalid")
    canonical_library = LibraryImportResult(
        library.attempt_id,
        library.source_id,
        library.game_count,
        library.warning_count,
        library.first_game_id,
        library.last_game_id,
        library.reused,
    )
    canonical = StreamingPgnImportResult(
        source,
        canonical_library,
        accepted_games,
        complete,
        failure_code,
    )
    if not canonical.complete or canonical.failure_code is not None:
        raise TypeError("source-atomic streaming PGN import returned a partial result")
    return canonical


class Version2WindowsStreamingFileActionDelegate(Version2WindowsFileActionDelegate):
    """Use bounded streaming D06 ingress for the real Windows PGN import action."""

    def _run_import(
        self,
        generation: int,
        source_path: Path,
        suffix: str,
        cancel_event: threading.Event,
    ) -> None:
        if suffix != ".pgn":
            super()._run_import(generation, source_path, suffix, cancel_event)
            return

        services: Version2ImportWorkerServices | None = None
        progress_started = False

        def cancelled() -> bool:
            return cancel_event.is_set()

        def streaming_progress(value: StreamingPgnProgress) -> None:
            nonlocal progress_started
            canonical = _snapshot_streaming_progress(value)
            total_games = 0 if canonical.total_games is None else canonical.total_games
            if not progress_started:
                progress_started = True
                self._emit_if_current(
                    generation,
                    FileWorkflowEvent(
                        FileWorkflowEventKind.IMPORT_STARTED,
                        "library.import",
                        focus_target="library-import-cancel",
                        total_games=total_games,
                    ),
                )
            processed = (
                canonical.imported_games
                if canonical.phase is StreamingPgnPhase.IMPORTING
                else canonical.accepted_games
            )
            self._emit_if_current(
                generation,
                FileWorkflowEvent(
                    FileWorkflowEventKind.IMPORT_PROGRESS,
                    "library.import",
                    processed_games=processed,
                    total_games=total_games,
                    source_parsing=canonical.phase is StreamingPgnPhase.PARSING,
                    source_bytes_read=canonical.bytes_read,
                    source_total_bytes=canonical.total_bytes,
                ),
            )

        try:
            services = self._import_services_factory()
            if type(services) is not Version2ImportWorkerServices:
                raise TypeError("import_services_factory returned an invalid service bundle")
            if cancelled():
                raise StreamingPgnImportCancelledError()

            # Preserve the existing host's zero-byte empty-source UX. Non-empty
            # malformed or whitespace-only sources remain canonical D06 failures;
            # no permissive fallback is introduced.
            try:
                if source_path.stat().st_size == 0:
                    self._emit_if_current(
                        generation,
                        FileWorkflowEvent(
                            FileWorkflowEventKind.IMPORT_EMPTY,
                            "library.import",
                            focus_target="library-import-file",
                        ),
                    )
                    return
            except OSError:
                # The streaming importer owns stable source-unavailable/change
                # classification and must see the original path.
                pass

            imported = StreamingPgnLibraryImporter(services.library).import_file(
                source_path,
                failure_policy=StreamingPgnFailurePolicy.SOURCE_ATOMIC,
                source_name=report_safe_name(source_path),
                cancel_check=cancelled,
                progress_callback=streaming_progress,
            )
            imported = _snapshot_streaming_result(imported)
            library_result = imported.library
            game_count = library_result.game_count
            warning_count = library_result.warning_count
            self._emit_if_current(
                generation,
                FileWorkflowEvent(
                    FileWorkflowEventKind.IMPORT_COMPLETED,
                    "library.import",
                    focus_target="library-import-file",
                    processed_games=game_count,
                    total_games=game_count,
                    game_count=game_count,
                    warning_count=warning_count,
                ),
            )
        except StreamingPgnImportCancelledError:
            self._emit_if_current(
                generation,
                FileWorkflowEvent(
                    FileWorkflowEventKind.IMPORT_CANCELLED,
                    "library.import",
                    focus_target="library-import-file",
                ),
            )
        except StreamingPgnImportError:
            # Error text can contain parser/source details. The user-facing
            # boundary receives only the existing stable path-free host code.
            self._emit_if_current(
                generation,
                FileWorkflowEvent(
                    FileWorkflowEventKind.FAILED,
                    "library.import",
                    focus_target="library-import-file",
                    error_code="pgn_import_failed",
                ),
            )
        except BaseException:
            _safe_warning("Version 2 streaming PGN Library import failed")
            self._emit_if_current(
                generation,
                FileWorkflowEvent(
                    FileWorkflowEventKind.FAILED,
                    "library.import",
                    focus_target="library-import-file",
                    error_code="library_import_failed",
                ),
            )
        finally:
            if services is not None:
                try:
                    services.close()
                except BaseException:
                    _safe_warning("Version 2 streaming PGN worker cleanup failed")
            with self._lock:
                if generation == self._generation and self._worker_kind == "import":
                    self._clear_worker_locked()


__all__ = ["Version2WindowsStreamingFileActionDelegate"]
