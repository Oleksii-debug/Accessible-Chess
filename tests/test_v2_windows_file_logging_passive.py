from __future__ import annotations

import tempfile
from pathlib import Path
import unittest
from unittest import mock

import acs.version2_windows_file_workflows as workflows
from acs.library_import_service import LibraryImportProgress, LibraryImportResult
from acs.version2_windows_file_workflows import (
    FileWorkflowEvent,
    FileWorkflowEventKind,
    Version2ImportWorkerServices,
    Version2WindowsFileActionDelegate,
)


PGN_ONE = """[Event "Logging"]
[Site "?"]
[Date "2026.10.06"]
[Round "1"]
[White "White"]
[Black "Black"]
[Result "*"]

1. e4 e5 *
"""


class _Dialogs:
    def __init__(self, import_path: Path | None = None) -> None:
        self.import_path = import_path

    def open_pgn(self):
        return None

    def save_pgn_as(self, suggested_filename: str = "game.pgn"):
        return None

    def select_library_import(self):
        return self.import_path


class _UnusedLibrary:
    def import_games(self, *args, **kwargs):
        raise AssertionError("unexpected Library import")


class Version2WindowsFileLoggingPassiveTests(unittest.TestCase):
    def _delegate(
        self,
        *,
        dialogs=None,
        import_services_factory=None,
        event_sink=None,
        owner_async_event_sink=None,
    ) -> Version2WindowsFileActionDelegate:
        return Version2WindowsFileActionDelegate(
            dialogs=dialogs or _Dialogs(),
            get_pgn_session=lambda: None,
            set_pgn_session=lambda value: None,
            import_services_factory=import_services_factory
            or (
                lambda: Version2ImportWorkerServices(
                    _UnusedLibrary(),
                    None,
                    lambda: None,
                )
            ),
            event_sink=event_sink or (lambda event: None),
            owner_async_event_sink=owner_async_event_sink,
            next_delegate=lambda action_id, payload: None,
        )

    def test_safe_warning_swallows_logging_handler_abort(self) -> None:
        class LoggingAbort(BaseException):
            pass

        with mock.patch.object(
            workflows._LOG,
            "warning",
            side_effect=LoggingAbort("handler abort"),
        ) as warning:
            workflows._safe_warning("fixed telemetry")

        warning.assert_called_once_with("fixed telemetry")

    def test_event_sink_exception_is_not_formatted(self) -> None:
        touched = []

        class ActiveSinkError(BaseException):
            def __str__(self):
                touched.append("str")
                raise AssertionError("sink exception string hook executed")

        def sink(_event):
            raise ActiveSinkError()

        delegate = self._delegate(event_sink=sink)
        event = FileWorkflowEvent(
            FileWorkflowEventKind.FAILED,
            "library.import",
            error_code="library_import_failed",
        )

        with mock.patch.object(workflows._LOG, "warning") as warning:
            returned = delegate._emit(event)

        self.assertIs(returned, event)
        self.assertEqual(touched, [])
        warning.assert_called_once_with("Version 2 file workflow event sink failed")

    def test_event_sink_and_logging_abort_cannot_escape(self) -> None:
        class SinkAbort(BaseException):
            pass

        class LoggingAbort(BaseException):
            pass

        def sink(_event):
            raise SinkAbort("sink abort")

        delegate = self._delegate(event_sink=sink)
        event = FileWorkflowEvent(
            FileWorkflowEventKind.FAILED,
            "library.import",
            error_code="library_import_failed",
        )

        with mock.patch.object(
            workflows._LOG,
            "warning",
            side_effect=LoggingAbort("logger abort"),
        ):
            returned = delegate._emit(event)

        self.assertIs(returned, event)

    def test_owner_async_sink_and_logging_abort_cannot_escape(self) -> None:
        class SinkAbort(BaseException):
            pass

        class LoggingAbort(BaseException):
            pass

        def sink(_event):
            raise SinkAbort("owner sink abort")

        delegate = self._delegate(
            event_sink=lambda event: None,
            owner_async_event_sink=sink,
        )
        event = FileWorkflowEvent(
            FileWorkflowEventKind.PGN_OPENED,
            "pgn.open",
            game_count=1,
        )

        with mock.patch.object(
            workflows._LOG,
            "warning",
            side_effect=LoggingAbort("logger abort"),
        ):
            returned = delegate._emit_owner_async(event)

        self.assertIs(returned, event)

    def test_import_failure_keeps_path_free_terminal_when_logging_aborts(self) -> None:
        touched = []

        class ActiveImportError(BaseException):
            def __str__(self):
                touched.append("str")
                raise AssertionError("import exception string hook executed")

        class LoggingAbort(BaseException):
            pass

        class FailingLibrary:
            def import_games(self, *_args, **_kwargs):
                raise ActiveImportError()

        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "private-logging-source.pgn"
            source.write_text(PGN_ONE, encoding="utf-8")
            events = []
            delegate = self._delegate(
                dialogs=_Dialogs(source),
                import_services_factory=lambda: Version2ImportWorkerServices(
                    FailingLibrary(),
                    None,
                    lambda: None,
                ),
                event_sink=events.append,
            )

            with mock.patch.object(
                workflows._LOG,
                "warning",
                side_effect=LoggingAbort("logger abort"),
            ):
                delegate("library.import", {})
                self.assertTrue(delegate.wait_for_import(5.0))

            self.assertEqual(touched, [])
            self.assertFalse(delegate.import_running)
            self.assertEqual(events[-1].kind, FileWorkflowEventKind.FAILED)
            self.assertEqual(events[-1].error_code, "library_import_failed")
            self.assertNotIn(str(source), repr(events[-1]))

    def test_cleanup_abort_and_logging_abort_cannot_strand_worker(self) -> None:
        touched = []

        class ActiveCleanupError(BaseException):
            def __str__(self):
                touched.append("str")
                raise AssertionError("cleanup exception string hook executed")

        class LoggingAbort(BaseException):
            pass

        class SuccessfulLibrary:
            def import_games(self, *_args, **kwargs):
                progress = kwargs["progress_callback"]
                progress(LibraryImportProgress(1, 0, 1))
                progress(LibraryImportProgress(1, 1, 1))
                return LibraryImportResult(1, 1, 1, 0, 1, 1)

        def close():
            raise ActiveCleanupError()

        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "cleanup-logging.pgn"
            source.write_text(PGN_ONE, encoding="utf-8")
            events = []
            delegate = self._delegate(
                dialogs=_Dialogs(source),
                import_services_factory=lambda: Version2ImportWorkerServices(
                    SuccessfulLibrary(),
                    None,
                    close,
                ),
                event_sink=events.append,
            )

            with mock.patch.object(
                workflows._LOG,
                "warning",
                side_effect=LoggingAbort("logger abort"),
            ):
                delegate("library.import", {})
                self.assertTrue(delegate.wait_for_import(5.0))

            self.assertEqual(touched, [])
            self.assertFalse(delegate.import_running)
            self.assertEqual(events[-1].kind, FileWorkflowEventKind.IMPORT_COMPLETED)
            self.assertEqual(events[-1].game_count, 1)


if __name__ == "__main__":
    unittest.main()
