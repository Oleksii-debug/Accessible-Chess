from __future__ import annotations

"""Lossless internal observer seam for Version 2 Windows Library imports.

The trusted Windows host intentionally exposes only bounded, path-free
``FileWorkflowEvent`` objects to browser/native presentation.  Those events are
not a replacement for the canonical D07 import DTOs: ``LibraryImportProgress``
and ``LibraryImportResult`` carry the stable attempt identity needed by the
existing Library projection to reject stale/mixed attempts.

This module decorates the per-worker service factory used by
``Version2WindowsFileActionDelegate``. It snapshots exact canonical DTO
values into detached, revalidated observer objects without changing the import
transaction, parser/decoder, database, or browser event contract. Observer
failures and mutations are non-authoritative: they are contained and cannot
alter the worker-visible DTO or turn a valid canonical import into a rollback.
"""

from collections.abc import Callable
import logging
from typing import Any

from .chessbase_library_import import ChessBaseLibraryImportReport
from .library_import_service import LibraryImportProgress, LibraryImportResult
from .version2_windows_file_workflows import Version2ImportWorkerServices


_LOG = logging.getLogger(__name__)

ProgressSink = Callable[[LibraryImportProgress], Any]
ResultSink = Callable[[LibraryImportResult], Any]
ServicesFactory = Callable[[], Version2ImportWorkerServices]


def _safe_warning(message: str, *args: object) -> None:
    """Best-effort observer diagnostics with no transaction authority."""

    try:
        _LOG.warning(message, *args)
    except BaseException:
        pass


def _snapshot_progress(value: LibraryImportProgress) -> LibraryImportProgress:
    if type(value) is not LibraryImportProgress:
        raise TypeError("canonical Library progress object is invalid")
    return LibraryImportProgress(
        value.attempt_id,
        value.processed_games,
        value.total_games,
    )


def _snapshot_result(value: LibraryImportResult) -> LibraryImportResult:
    if type(value) is not LibraryImportResult:
        raise TypeError("canonical Library import result is invalid")
    return LibraryImportResult(
        value.attempt_id,
        value.source_id,
        value.game_count,
        value.warning_count,
        value.first_game_id,
        value.last_game_id,
        value.reused,
    )


def _safe_observe(callback: Callable[[Any], Any], value: Any, *, kind: str) -> None:
    try:
        callback(value)
    except BaseException:
        # Accessibility projection is an observer boundary. A failed or aborted
        # UI sink is never canonical transaction authority. Do not attach the
        # observer exception to logging: formatting arbitrary exception objects
        # may execute active __str__ hooks after the failure has been contained.
        _safe_warning("Version 2 Library %s observer failed", kind)


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
            canonical = _snapshot_progress(value)
            observer_value = _snapshot_progress(canonical)
            _safe_observe(self._progress_sink, observer_value, kind="progress")
            if original_progress is not None:
                original_progress(canonical)

        call_kwargs = dict(kwargs)
        call_kwargs["progress_callback"] = progress
        result = self._service.import_games(*args, **call_kwargs)
        canonical = _snapshot_result(result)
        _safe_observe(
            self._result_sink,
            _snapshot_result(canonical),
            kind="result",
        )
        return canonical


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
            canonical = _snapshot_progress(value)
            observer_value = _snapshot_progress(canonical)
            _safe_observe(self._progress_sink, observer_value, kind="progress")
            if original_progress is not None:
                original_progress(canonical)

        call_kwargs = dict(kwargs)
        call_kwargs["progress_callback"] = progress
        report = self._service.import_database(*args, **call_kwargs)
        if type(report) is not ChessBaseLibraryImportReport:
            raise TypeError("canonical ChessBase import report is invalid")
        result = report.library_result
        if result is not None:
            canonical = _snapshot_result(result)
            _safe_observe(
                self._result_sink,
                _snapshot_result(canonical),
                kind="result",
            )
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
        if type(services) is not Version2ImportWorkerServices:
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
