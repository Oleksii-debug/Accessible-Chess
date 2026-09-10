from __future__ import annotations

from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

from acs.stage1_release_ui import Stage1ReleaseAccessibleChessAPI
from acs.version2_application import Version2Application
from acs.version2_profile import (
    build_version2_router,
    build_version2_shell,
    build_version2_webview_adapter,
)
from acs.version2_release_ui import (
    Version2ReleaseAccessibleChessAPI,
    run_version2_release_window,
)
from acs.version2_windows_file_workflows import (
    Version2ImportWorkerServices,
    Version2WindowsFileActionDelegate,
)


class _PrimaryFailure(RuntimeError):
    pass


class _CleanupFailure(RuntimeError):
    pass


class _ProgressStore:
    def __init__(self, calls: list[str], error: BaseException | None = None) -> None:
        self.calls = calls
        self.error = error

    def save(self, _book_key, _reader) -> None:
        self.calls.append("book-progress")
        if self.error is not None:
            raise self.error


class _Database:
    def __init__(self, calls: list[str], error: BaseException | None = None) -> None:
        self.calls = calls
        self.error = error
        self.close_count = 0

    def close(self) -> None:
        self.calls.append("acsdb-close")
        self.close_count += 1
        if self.error is not None:
            raise self.error


class _Files:
    def __init__(self, calls: list[str], result: bool = True) -> None:
        self.calls = calls
        self.result = result
        self.shutdown_count = 0

    def shutdown(self, timeout: float | None = None) -> bool:
        self.calls.append("import-worker-shutdown")
        self.shutdown_count += 1
        return self.result


class _Event:
    def __init__(self) -> None:
        self.handlers = []

    def __iadd__(self, handler):
        self.handlers.append(handler)
        return self

    def fire(self) -> None:
        for handler in tuple(self.handlers):
            handler()


class _Events:
    def __init__(self) -> None:
        self.before_show = _Event()
        self.loaded = _Event()


class _Window:
    def __init__(self) -> None:
        self.events = _Events()
        self.sources: list[str] = []
        self.destroyed = False

    def evaluate_js(self, source: str) -> None:
        self.sources.append(source)

    def destroy(self) -> None:
        self.destroyed = True


class _WebView:
    def __init__(self, error: BaseException | None = None) -> None:
        self.window = _Window()
        self.error = error

    def create_window(self, _title, **_kwargs):
        return self.window

    def start(self, **_kwargs) -> None:
        self.window.events.before_show.fire()
        self.window.events.loaded.fire()
        if self.error is not None:
            raise self.error


class _ReleaseApplication:
    def __init__(self, calls: list[str], error: BaseException | None = None) -> None:
        self.calls = calls
        self.error = error
        self.shutdown_count = 0
        self.shell = build_version2_shell()
        self.router = build_version2_router(self.shell, lambda _action, _payload: None)
        self.adapter = build_version2_webview_adapter(self.shell, self.router)
        self._focus = ""
        self._events = []

    def snapshot(self):
        return {**self.adapter.snapshot(), "pgn": None, "library": {}, "books": None}

    def browser_command(self, _area, _command, _payload=None):
        return {"kind": "noop", "payload": {}}

    def drain_events(self):
        values = tuple(self._events)
        self._events.clear()
        return values

    def record_focus(self, token):
        self._focus = token

    def native_command(self, value):
        self._events.append(value)

    def shutdown(self):
        self.calls.append("application-shutdown")
        self.shutdown_count += 1
        if self.error is not None:
            raise self.error
        return True


class _Runtime:
    def __init__(self, calls: list[str]) -> None:
        self.calls = calls
        self.close_count = 0

    def close(self) -> None:
        self.calls.append("stockfish-runtime-close")
        self.close_count += 1


class _Dialogs:
    def __init__(self, source: Path) -> None:
        self.source = source

    def open_pgn(self):
        return None

    def save_pgn_as(self, _suggested="game.pgn"):
        return None

    def select_library_import(self):
        return self.source


class _Library:
    def import_games(self, *_args, **_kwargs):
        raise AssertionError("nonexistent PGN must fail before canonical import")


class RuntimeCleanupFailureMatrixEvidenceTests(unittest.TestCase):
    def _application(
        self,
        calls: list[str],
        *,
        progress_error: BaseException | None = None,
        database_error: BaseException | None = None,
        worker_result: bool = True,
    ) -> tuple[Version2Application, _Files, _Database]:
        application = Version2Application.__new__(Version2Application)
        application._thread = threading.get_ident()
        files = _Files(calls, worker_result)
        database = _Database(calls, database_error)
        application._files = files
        application.reader = object()
        application.book_key = "cleanup-matrix-book"
        application.progress_store = _ProgressStore(calls, progress_error)
        application.database = database
        return application, files, database

    @staticmethod
    def _capture(callback):
        try:
            callback()
        except BaseException as error:  # evidence needs exact exception identity
            return error
        return None

    def _api(self) -> Version2ReleaseAccessibleChessAPI:
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        return Version2ReleaseAccessibleChessAPI(
            keymap_path=Path(temp.name) / "keymap.json"
        )

    def test_518_progress_failure_still_closes_acsdb_once(self) -> None:
        calls: list[str] = []
        primary = _PrimaryFailure("PRIMARY_PROGRESS")
        application, files, database = self._application(
            calls, progress_error=primary
        )

        caught = self._capture(application.shutdown)

        self.assertIs(caught, primary)
        self.assertEqual(
            calls,
            ["import-worker-shutdown", "book-progress", "acsdb-close"],
        )
        self.assertEqual(files.shutdown_count, 1)
        self.assertEqual(database.close_count, 1)

    def test_518_cleanup_failure_must_not_replace_progress_failure(self) -> None:
        calls: list[str] = []
        primary = _PrimaryFailure("PRIMARY_PROGRESS")
        secondary = _CleanupFailure("SECONDARY_ACSDB_CLOSE")
        application, files, database = self._application(
            calls,
            progress_error=primary,
            database_error=secondary,
        )

        caught = self._capture(application.shutdown)

        self.assertEqual(
            calls,
            ["import-worker-shutdown", "book-progress", "acsdb-close"],
        )
        self.assertEqual(files.shutdown_count, 1)
        self.assertEqual(database.close_count, 1)
        self.assertIs(
            caught,
            primary,
            "the original meaningful Book progress failure must remain observable",
        )

    def test_bounded_live_worker_keeps_shared_acsdb_open_for_retry(self) -> None:
        calls: list[str] = []
        application, files, database = self._application(
            calls,
            worker_result=False,
        )

        self.assertFalse(application.shutdown(timeout=0.01))
        self.assertEqual(calls, ["import-worker-shutdown"])
        self.assertEqual(files.shutdown_count, 1)
        self.assertEqual(database.close_count, 0)

    def test_import_worker_service_close_failure_does_not_orphan_worker(self) -> None:
        calls: list[str] = []
        missing = Path(tempfile.gettempdir()) / "accessible-chess-cleanup-matrix-missing.pgn"
        try:
            missing.unlink()
        except FileNotFoundError:
            pass

        def services():
            def close() -> None:
                calls.append("worker-service-close")
                raise _CleanupFailure("WORKER_SERVICE_CLOSE")

            return Version2ImportWorkerServices(_Library(), None, close)

        delegate = Version2WindowsFileActionDelegate(
            dialogs=_Dialogs(missing),
            get_pgn_session=lambda: None,
            set_pgn_session=lambda _session: None,
            import_services_factory=services,
            event_sink=lambda _event: None,
            next_delegate=lambda _action, _payload: None,
        )

        delegate("library.import", {})
        self.assertTrue(delegate.wait_for_import(timeout=5.0))
        self.assertFalse(delegate.import_running)
        self.assertTrue(delegate.shutdown(timeout=0.01))
        self.assertEqual(calls, ["worker-service-close"])

    def test_release_application_failure_still_runs_analysis_and_stockfish_cleanup_once(self) -> None:
        calls: list[str] = []
        primary = _PrimaryFailure("PRIMARY_APPLICATION_SHUTDOWN")
        application = _ReleaseApplication(calls, primary)
        runtime = _Runtime(calls)
        api = self._api()

        def close_analysis(_self) -> None:
            calls.append("analysis-close")

        with patch.object(Version2ReleaseAccessibleChessAPI, "close_analysis", close_analysis):
            caught = self._capture(
                lambda: run_version2_release_window(
                    api,
                    application,
                    runtime,
                    webview_module=_WebView(),
                    menu_installer=lambda *_args: True,
                )
            )

        # Release the real Stage1 analysis service hidden by the injected method.
        Stage1ReleaseAccessibleChessAPI.close_analysis(api)
        self.assertIs(caught, primary)
        self.assertEqual(
            calls,
            ["application-shutdown", "analysis-close", "stockfish-runtime-close"],
        )
        self.assertEqual(application.shutdown_count, 1)
        self.assertEqual(runtime.close_count, 1)

    def test_release_analysis_cleanup_failure_does_not_skip_stockfish_cleanup(self) -> None:
        calls: list[str] = []
        analysis_failure = _CleanupFailure("ANALYSIS_CLOSE")
        application = _ReleaseApplication(calls)
        runtime = _Runtime(calls)
        api = self._api()

        def close_analysis(_self) -> None:
            calls.append("analysis-close")
            raise analysis_failure

        with patch.object(Version2ReleaseAccessibleChessAPI, "close_analysis", close_analysis):
            caught = self._capture(
                lambda: run_version2_release_window(
                    api,
                    application,
                    runtime,
                    webview_module=_WebView(),
                    menu_installer=lambda *_args: True,
                )
            )

        Stage1ReleaseAccessibleChessAPI.close_analysis(api)
        self.assertIs(caught, analysis_failure)
        self.assertEqual(
            calls,
            ["application-shutdown", "analysis-close", "stockfish-runtime-close"],
        )
        self.assertEqual(application.shutdown_count, 1)
        self.assertEqual(runtime.close_count, 1)

    def test_release_later_analysis_failure_must_not_replace_application_failure(self) -> None:
        calls: list[str] = []
        primary = _PrimaryFailure("PRIMARY_APPLICATION_SHUTDOWN")
        secondary = _CleanupFailure("SECONDARY_ANALYSIS_CLOSE")
        application = _ReleaseApplication(calls, primary)
        runtime = _Runtime(calls)
        api = self._api()

        def close_analysis(_self) -> None:
            calls.append("analysis-close")
            raise secondary

        with patch.object(Version2ReleaseAccessibleChessAPI, "close_analysis", close_analysis):
            caught = self._capture(
                lambda: run_version2_release_window(
                    api,
                    application,
                    runtime,
                    webview_module=_WebView(),
                    menu_installer=lambda *_args: True,
                )
            )

        Stage1ReleaseAccessibleChessAPI.close_analysis(api)
        self.assertEqual(
            calls,
            ["application-shutdown", "analysis-close", "stockfish-runtime-close"],
        )
        self.assertEqual(application.shutdown_count, 1)
        self.assertEqual(runtime.close_count, 1)
        self.assertIs(
            caught,
            primary,
            "a later analysis cleanup failure must not replace application shutdown failure",
        )

    def test_release_cleanup_failures_must_not_replace_running_application_failure(self) -> None:
        calls: list[str] = []
        primary = _PrimaryFailure("PRIMARY_WEBVIEW_RUNTIME")
        cleanup = _CleanupFailure("SECONDARY_APPLICATION_SHUTDOWN")
        application = _ReleaseApplication(calls, cleanup)
        runtime = _Runtime(calls)
        api = self._api()

        def close_analysis(_self) -> None:
            calls.append("analysis-close")

        with patch.object(Version2ReleaseAccessibleChessAPI, "close_analysis", close_analysis):
            caught = self._capture(
                lambda: run_version2_release_window(
                    api,
                    application,
                    runtime,
                    webview_module=_WebView(primary),
                    menu_installer=lambda *_args: True,
                )
            )

        Stage1ReleaseAccessibleChessAPI.close_analysis(api)
        self.assertEqual(
            calls,
            ["application-shutdown", "analysis-close", "stockfish-runtime-close"],
        )
        self.assertEqual(application.shutdown_count, 1)
        self.assertEqual(runtime.close_count, 1)
        self.assertIs(
            caught,
            primary,
            "the active application/runtime failure must remain primary after cleanup",
        )


if __name__ == "__main__":
    unittest.main()
