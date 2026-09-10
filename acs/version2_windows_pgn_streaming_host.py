from __future__ import annotations

"""Current-runtime Windows composition for large PGN Library imports.

The trusted Windows file host continues to own file selection, threading,
cancellation, bounded path-free events and shutdown.  This successor changes
only the ``.pgn`` worker path: it delegates incremental framing/parsing to the
canonical D06 ``StreamingPgnLibraryImporter`` and publication to the same D07
Library service supplied by the existing worker factory.  CBH/CBV and ordinary
PGN Open/Save remain owned by their existing delegates.

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
from .report_paths import report_safe_name
from .version2_windows_file_workflows import (
    FileWorkflowEvent,
    FileWorkflowEventKind,
    Version2ImportWorkerServices,
    Version2WindowsFileActionDelegate,
)


_LOG = logging.getLogger(__name__)


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

        def cancelled() -> bool:
            return cancel_event.is_set()

        def streaming_progress(value: StreamingPgnProgress) -> None:
            if not isinstance(value, StreamingPgnProgress):
                raise TypeError("canonical streaming PGN progress object is invalid")
            processed = (
                value.imported_games
                if value.phase is StreamingPgnPhase.IMPORTING
                else value.accepted_games
            )
            self._emit_if_current(
                generation,
                FileWorkflowEvent(
                    FileWorkflowEventKind.IMPORT_PROGRESS,
                    "library.import",
                    processed_games=processed,
                    total_games=value.total_games or 0,
                ),
            )

        try:
            services = self._import_services_factory()
            if not isinstance(services, Version2ImportWorkerServices):
                raise TypeError("import_services_factory returned an invalid service bundle")
            if cancelled():
                raise StreamingPgnImportCancelledError()

            # Preserve the existing host's zero-byte empty-source UX.  Non-empty
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
            if not isinstance(imported, StreamingPgnImportResult):
                raise TypeError("streaming PGN importer returned an invalid result")

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
            # Error text can contain parser/source details.  The user-facing
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
        except Exception:
            _LOG.warning("Version 2 streaming PGN Library import failed", exc_info=True)
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
                except Exception:
                    _LOG.warning("Version 2 streaming PGN worker cleanup failed", exc_info=True)
            with self._lock:
                if generation == self._generation:
                    self._worker = None
                    self._cancel_event = None


__all__ = ["Version2WindowsStreamingFileActionDelegate"]
