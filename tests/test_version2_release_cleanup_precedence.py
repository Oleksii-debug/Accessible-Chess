from __future__ import annotations

from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from acs.stage1_release_ui import Stage1ReleaseAccessibleChessAPI
from acs.version2_profile import (
    build_version2_router,
    build_version2_shell,
    build_version2_webview_adapter,
)
from acs.version2_release_ui import (
    Version2ReleaseAccessibleChessAPI,
    run_version2_release_window,
)


class _PrimaryFailure(RuntimeError):
    pass


class _CleanupFailure(RuntimeError):
    pass


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
    def __init__(
        self,
        *,
        start_error: BaseException | None = None,
        create_error: BaseException | None = None,
    ) -> None:
        self.window = _Window()
        self.start_error = start_error
        self.create_error = create_error

    def create_window(self, _title, **_kwargs):
        if self.create_error is not None:
            raise self.create_error
        return self.window

    def start(self, **_kwargs) -> None:
        self.window.events.before_show.fire()
        self.window.events.loaded.fire()
        if self.start_error is not None:
            raise self.start_error


class _Application:
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
    def __init__(self, calls: list[str], error: BaseException | None = None) -> None:
        self.calls = calls
        self.error = error
        self.close_count = 0

    def close(self) -> None:
        self.calls.append("runtime-close")
        self.close_count += 1
        if self.error is not None:
            raise self.error


class Version2ReleaseCleanupPrecedenceTests(unittest.TestCase):
    def make_api(self) -> Version2ReleaseAccessibleChessAPI:
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        api = Version2ReleaseAccessibleChessAPI(
            keymap_path=Path(temp.name) / "keymap.json"
        )
        # Tests may replace the production cleanup method with a fault injector;
        # run the real Stage1 cleanup after the patch context has exited.
        self.addCleanup(Stage1ReleaseAccessibleChessAPI.close_analysis, api)
        return api

    @staticmethod
    def capture(callback):
        try:
            callback()
        except BaseException as error:
            return error
        return None

    def test_create_window_failure_still_runs_complete_cleanup_chain(self) -> None:
        calls: list[str] = []
        primary = _PrimaryFailure("CREATE_WINDOW")
        app = _Application(calls)
        runtime = _Runtime(calls)
        api = self.make_api()

        def close_analysis(_api) -> None:
            calls.append("analysis-close")

        with patch.object(Stage1ReleaseAccessibleChessAPI, "close_analysis", close_analysis):
            caught = self.capture(
                lambda: run_version2_release_window(
                    api,
                    app,
                    runtime,
                    webview_module=_WebView(create_error=primary),
                    menu_installer=lambda *_args: True,
                )
            )

        self.assertIs(caught, primary)
        self.assertEqual(
            calls,
            ["application-shutdown", "analysis-close", "runtime-close"],
        )
        self.assertEqual(app.shutdown_count, 1)
        self.assertEqual(runtime.close_count, 1)

    def test_runtime_failure_remains_primary_when_all_cleanup_layers_fail(self) -> None:
        calls: list[str] = []
        primary = _PrimaryFailure("WEBVIEW_RUNTIME")
        app_failure = _CleanupFailure("APPLICATION_CLEANUP")
        analysis_failure = _CleanupFailure("ANALYSIS_CLEANUP")
        runtime_failure = _CleanupFailure("RUNTIME_CLEANUP")
        app = _Application(calls, app_failure)
        runtime = _Runtime(calls, runtime_failure)
        api = self.make_api()

        def close_analysis(_api) -> None:
            calls.append("analysis-close")
            raise analysis_failure

        with patch.object(Stage1ReleaseAccessibleChessAPI, "close_analysis", close_analysis):
            caught = self.capture(
                lambda: run_version2_release_window(
                    api,
                    app,
                    runtime,
                    webview_module=_WebView(start_error=primary),
                    menu_installer=lambda *_args: True,
                )
            )

        self.assertIs(caught, primary)
        self.assertEqual(
            calls,
            ["application-shutdown", "analysis-close", "runtime-close"],
        )
        self.assertEqual(app.shutdown_count, 1)
        self.assertEqual(runtime.close_count, 1)

    def test_first_cleanup_failure_remains_primary_and_later_cleanup_runs(self) -> None:
        calls: list[str] = []
        app_failure = _CleanupFailure("APPLICATION_CLEANUP")
        analysis_failure = _CleanupFailure("ANALYSIS_CLEANUP")
        runtime_failure = _CleanupFailure("RUNTIME_CLEANUP")
        app = _Application(calls, app_failure)
        runtime = _Runtime(calls, runtime_failure)
        api = self.make_api()

        def close_analysis(_api) -> None:
            calls.append("analysis-close")
            raise analysis_failure

        with patch.object(Stage1ReleaseAccessibleChessAPI, "close_analysis", close_analysis):
            caught = self.capture(
                lambda: run_version2_release_window(
                    api,
                    app,
                    runtime,
                    webview_module=_WebView(),
                    menu_installer=lambda *_args: True,
                )
            )

        self.assertIs(caught, app_failure)
        self.assertEqual(
            calls,
            ["application-shutdown", "analysis-close", "runtime-close"],
        )
        self.assertEqual(app.shutdown_count, 1)
        self.assertEqual(runtime.close_count, 1)

    def test_analysis_failure_remains_primary_while_runtime_cleanup_runs(self) -> None:
        calls: list[str] = []
        analysis_failure = _CleanupFailure("ANALYSIS_CLEANUP")
        runtime_failure = _CleanupFailure("RUNTIME_CLEANUP")
        app = _Application(calls)
        runtime = _Runtime(calls, runtime_failure)
        api = self.make_api()

        def close_analysis(_api) -> None:
            calls.append("analysis-close")
            raise analysis_failure

        with patch.object(Stage1ReleaseAccessibleChessAPI, "close_analysis", close_analysis):
            caught = self.capture(
                lambda: run_version2_release_window(
                    api,
                    app,
                    runtime,
                    webview_module=_WebView(),
                    menu_installer=lambda *_args: True,
                )
            )

        self.assertIs(caught, analysis_failure)
        self.assertEqual(
            calls,
            ["application-shutdown", "analysis-close", "runtime-close"],
        )
        self.assertEqual(app.shutdown_count, 1)
        self.assertEqual(runtime.close_count, 1)


if __name__ == "__main__":
    unittest.main()
