from __future__ import annotations

"""Lossless internal observer seam for Version 2 Windows Library imports.

The trusted Windows host intentionally exposes only bounded, path-free
``FileWorkflowEvent`` objects to browser/native presentation.  Those events are
not a replacement for the canonical D07 import DTOs: ``LibraryImportProgress``
and ``LibraryImportResult`` carry the stable attempt identity needed by the
existing Library projection to reject stale/mixed attempts.

This module decorates the per-worker service factory used by
``Version2WindowsFileActionDelegate``.  It observes the exact canonical DTO
objects without changing the import transaction, parser/decoder, database, or
browser event contract.  Observer failures are non-authoritative: they are
logged and never turn an otherwise valid canonical import into a rollback.
"""

from collections.abc import Callable
import logging
from typing import Any

from .library_import_service import LibraryImportProgress, LibraryImportResult
from .version2_windows_file_workflows import Version2ImportWorkerServices


_LOG = logging.getLogger(__name__)

ProgressSink = Callable[[LibraryImportProgress], Any]
ResultSink = Callable[[LibraryImportResult], Any]
ServicesFactory = Callable[[], Version2ImportWorkerServices]


def _safe_observe(callback: Callable[[Any], Any], value: Any, *, kind: str) -> None:
    try:
        callback(value)
    except Exception:
        # Accessibility projection is an observer boundary.  A failed UI sink
        # must not alter the canonical D07 transaction or its returned result.
        _LOG.warning("Version 2 Library %s observer failed", kind, exc_info=True)


class _ObservedLibraryService:
    def __init__(self, service: object, progress_sink: ProgressSink, result_sink: ResultSink) -> None:
        import_games = getattr(service, "import_games", None)
        if not callable(import_games):
            raise TypeError("Library observer requires import_games")
        self._service = service
        self._progress_sink = progress_sink
        self._result_sink = result_sink

    def import_games(self, *args, **kwargs):
        original_progress = kwargs.get("progress_callback")
        if original_progress is not None and not callable(original_progress):
            raise TypeError("progress_callback must be callable")

        def progress(value: LibraryImportProgress) -> None:
            if not isinstance(value, LibraryImportProgress):
                raise TypeError("canonical Library progress object is invalid")
            _safe_observe(self._progress_sink, value, kind="progress")
            if original_progress is not None:
                original_progress(value)

        call_kwargs = dict(kwargs)
        call_kwargs["progress_callback"] = progress
        result = self._service.import_games(*args, **call_kwargs)
        if not isinstance(result, LibraryImportResult):
            raise TypeError("canonical Library import result is invalid")
        _safe_observe(self._result_sink, result, kind="result")
        return result


class _ObservedChessBaseService:
    def __init__(self, service: object, progress_sink: ProgressSink, result_sink: ResultSink) -> None:
        import_database = getattr(service, "import_database", None)
        if not callable(import_database):
            raise TypeError("ChessBase observer requires import_database")
        self._service = service
        self._progress_sink = progress_sink
        self._result_sink = result_sink

    def import_database(self, *args, **kwargs):
        original_progress = kwargs.get("progress_callback")
        if original_progress is not None and not callable(original_progress):
            raise TypeError("progress_callback must be callable")

        def progress(value: LibraryImportProgress) -> None:
            if not isinstance(value, LibraryImportProgress):
                raise TypeError("canonical ChessBase Library progress object is invalid")
            _safe_observe(self._progress_sink, value, kind="progress")
            if original_progress is not None:
                original_progress(value)

        call_kwargs = dict(kwargs)
        call_kwargs["progress_callback"] = progress
        report = self._service.import_database(*args, **call_kwargs)
        result = getattr(report, "library_result", None)
        if result is not None:
            if not isinstance(result, LibraryImportResult):
                raise TypeError("canonical ChessBase Library result is invalid")
            _safe_observe(self._result_sink, result, kind="result")
        return report


class Version2ObservedImportServicesFactory:
    """Decorate #300 worker services with exact, non-browser D07 DTO observers."""

    def __init__(
        self,
        factory: ServicesFactory,
        *,
        progress_sink: ProgressSink,
        result_sink: ResultSink,
    ) -> None:
        if not callable(factory):
            raise TypeError("base import services factory must be callable")
        if not callable(progress_sink):
            raise TypeError("progress_sink must be callable")
        if not callable(result_sink):
            raise TypeError("result_sink must be callable")
        self._factory = factory
        self._progress_sink = progress_sink
        self._result_sink = result_sink

    def __call__(self) -> Version2ImportWorkerServices:
        services = self._factory()
        if not isinstance(services, Version2ImportWorkerServices):
            raise TypeError("base import services factory returned an invalid bundle")
        observed_library = _ObservedLibraryService(
            services.library,
            self._progress_sink,
            self._result_sink,
        )
        observed_chessbase = None
        if services.chessbase is not None:
            observed_chessbase = _ObservedChessBaseService(
                services.chessbase,
                self._progress_sink,
                self._result_sink,
            )
        return Version2ImportWorkerServices(
            observed_library,
            observed_chessbase,
            services.close,
        )


__all__ = ["Version2ObservedImportServicesFactory"]
