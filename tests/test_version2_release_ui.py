from __future__ import annotations

from pathlib import Path
import tempfile
import unittest
from unittest import mock

from acs.full_product_webview_adapter import WebViewCommand
from acs.stage1_release_ui import Stage1ReleaseAccessibleChessAPI
from acs.version2_profile import build_version2_router, build_version2_shell, build_version2_webview_adapter
from acs.version2_release_ui import Version2ReleaseAccessibleChessAPI, run_version2_release_window


class _Event:
    def __init__(self):
        self.handlers = []

    def __iadd__(self, handler):
        self.handlers.append(handler)
        return self

    def fire(self):
        for handler in tuple(self.handlers):
            handler()


class _Events:
    def __init__(self):
        self.before_show = _Event()
        self.loaded = _Event()


class _Window:
    def __init__(self):
        self.events = _Events()
        self.sources = []
        self.destroyed = False

    def evaluate_js(self, source):
        self.sources.append(source)

    def destroy(self):
        self.destroyed = True


class _WebView:
    def __init__(self):
        self.window = _Window()
        self.created = None
        self.started = None

    def create_window(self, title, **kwargs):
        self.created = (title, kwargs)
        return self.window

    def start(self, **kwargs):
        self.started = kwargs
        self.window.events.before_show.fire()
        self.window.events.loaded.fire()


class _CreateWindowFailureWebView(_WebView):
    def create_window(self, title, **kwargs):
        raise RuntimeError("window creation failed")


class _FailingStartWebView(_WebView):
    def __init__(self, error):
        super().__init__()
        self.error = error

    def start(self, **kwargs):
        self.started = kwargs
        self.window.events.before_show.fire()
        self.window.events.loaded.fire()
        raise self.error


class _Runtime:
    def __init__(self, error=None):
        self.closed = 0
        self.error = error

    def close(self):
        self.closed += 1
        if self.error is not None:
            raise self.error


class _Application:
    def __init__(self):
        self.shell = build_version2_shell()
        self.router = build_version2_router(self.shell, lambda action, payload: {"action": action})
        self.adapter = build_version2_webview_adapter(self.shell, self.router)
        self._focus = ""
        self.events = []
        self.closed = False
        self.files = None

    def snapshot(self):
        return {**self.adapter.snapshot(), "pgn": None, "library": {}, "books": None}

    def browser_command(self, area, command, payload=None):
        if area == "shell":
            value = self.adapter.activate_action(command, payload or {}, current_focus_id=self._focus)
            return {"kind": value.kind, "payload": dict(value.payload)}
        return {"kind": "delegated", "payload": {"area": area, "command": command}}

    def drain_events(self):
        values = tuple(self.events)
        self.events.clear()
        return values

    def record_focus(self, token):
        self._focus = token

    def native_command(self, value: WebViewCommand):
        self.events.append({"kind": value.kind, "payload": dict(value.payload)})

    def bind_files(self, runtime):
        self.files = runtime

    def shutdown(self):
        self.closed = True
        return True


class _FailingApplication(_Application):
    def __init__(self, error):
        super().__init__()
        self.error = error
        self.shutdown_count = 0

    def shutdown(self):
        self.closed = True
        self.shutdown_count += 1
        raise self.error


class Version2ReleaseUiTests(unittest.TestCase):
    def make_api(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        return Version2ReleaseAccessibleChessAPI(keymap_path=Path(temp.name) / "keymap.json")

    def test_shared_api_keeps_canonical_stage1_board_dispatch(self):
        api = self.make_api()
        app = _Application()
        api.bind_version2_application(app)

        result = api.v2_board_dispatch("board.current", {"square": "e2"})
        self.assertTrue(result["ok"])
        self.assertEqual(result["focusSquare"], "e2")
        self.assertEqual(api.v2_snapshot()["screen"]["route_id"], "board")

        api.v2_browser_command("shell", "screen.library", {})
        self.assertEqual(api.v2_snapshot()["screen"]["route_id"], "library")

    def test_release_window_uses_original_document_one_api_and_v2_surfaces(self):
        api = self.make_api()
        app = _Application()
        webview = _WebView()
        menus = []

        run_version2_release_window(
            api,
            app,
            webview_module=webview,
            menu_installer=lambda window, controller: menus.append((window, controller)) or True,
        )

        title, kwargs = webview.created
        self.assertEqual(title, "Accessible Chess")
        self.assertIs(kwargs["js_api"], api)
        self.assertEqual(Path(kwargs["url"]).parts[-2:], ("web", "index.html"))
        self.assertEqual(webview.started, {"gui": "edgechromium", "private_mode": True})
        self.assertEqual(len(menus), 1)
        self.assertTrue(app.closed)

        combined = "\n".join(webview.window.sources)
        self.assertIn("AccessibleChessPgnSurface", combined)
        self.assertIn("AccessibleChessLibrarySurface", combined)
        self.assertIn("AccessibleChessBookSurface", combined)
        self.assertIn("v2-navigation", combined)
        self.assertIn("board-launcher", combined)

    def test_release_window_binds_file_runtime_to_exact_menu_owner(self):
        api = self.make_api()
        app = _Application()
        webview = _WebView()
        owner = object()
        runtime = object()
        seen_owners = []

        def install_menu(window, _controller):
            window._accessible_chess_native_menu_host = owner
            return True

        def build_files(value):
            seen_owners.append(value)
            return runtime

        run_version2_release_window(
            api,
            app,
            webview_module=webview,
            menu_installer=install_menu,
            file_runtime_factory=build_files,
        )

        self.assertEqual(seen_owners, [owner])
        self.assertIs(app.files, runtime)

    def test_release_window_fails_closed_when_native_owner_is_missing(self):
        api = self.make_api()
        app = _Application()
        webview = _WebView()
        built = []

        with self.assertRaisesRegex(RuntimeError, "native Windows owner"):
            run_version2_release_window(
                api,
                app,
                webview_module=webview,
                menu_installer=lambda *_: True,
                file_runtime_factory=lambda owner: built.append(owner),
            )

        self.assertEqual(built, [])
        self.assertTrue(app.closed)

    def test_release_window_cleans_resources_when_create_window_fails(self):
        api = self.make_api()
        app = _Application()
        runtime = _Runtime()

        with self.assertRaisesRegex(RuntimeError, "window creation failed"):
            run_version2_release_window(
                api,
                app,
                runtime,
                webview_module=_CreateWindowFailureWebView(),
            )

        self.assertTrue(app.closed)
        self.assertEqual(runtime.closed, 1)

    def test_release_window_cleans_resources_when_packaged_document_is_missing(self):
        api = self.make_api()
        app = _Application()
        runtime = _Runtime()
        with tempfile.TemporaryDirectory() as directory:
            missing_root = Path(directory)
            with mock.patch("acs.version2_release_ui._asset_root", return_value=missing_root):
                with self.assertRaisesRegex(RuntimeError, "Accessible HTML UI not found"):
                    run_version2_release_window(api, app, runtime, webview_module=_WebView())

        self.assertTrue(app.closed)
        self.assertEqual(runtime.closed, 1)

    def test_active_webview_failure_remains_primary_across_all_cleanup_failures(self):
        api = self.make_api()
        primary = RuntimeError("PRIMARY_WEBVIEW_RUNTIME")
        app_cleanup = RuntimeError("SECONDARY_APPLICATION_SHUTDOWN")
        analysis_cleanup = RuntimeError("SECONDARY_ANALYSIS_CLOSE")
        runtime_cleanup = RuntimeError("SECONDARY_RUNTIME_CLOSE")
        app = _FailingApplication(app_cleanup)
        runtime = _Runtime(runtime_cleanup)

        with mock.patch.object(
            Stage1ReleaseAccessibleChessAPI,
            "close_analysis",
            side_effect=analysis_cleanup,
        ):
            with self.assertRaises(RuntimeError) as caught:
                run_version2_release_window(
                    api,
                    app,
                    runtime,
                    webview_module=_FailingStartWebView(primary),
                )

        self.assertIs(caught.exception, primary)
        self.assertEqual(app.shutdown_count, 1)
        self.assertEqual(runtime.closed, 1)

    def test_application_cleanup_failure_remains_primary_over_later_cleanup(self):
        api = self.make_api()
        application_failure = RuntimeError("PRIMARY_APPLICATION_SHUTDOWN")
        analysis_cleanup = RuntimeError("SECONDARY_ANALYSIS_CLOSE")
        runtime_cleanup = RuntimeError("SECONDARY_RUNTIME_CLOSE")
        app = _FailingApplication(application_failure)
        runtime = _Runtime(runtime_cleanup)

        with mock.patch.object(
            Stage1ReleaseAccessibleChessAPI,
            "close_analysis",
            side_effect=analysis_cleanup,
        ):
            with self.assertRaises(RuntimeError) as caught:
                run_version2_release_window(
                    api,
                    app,
                    runtime,
                    webview_module=_WebView(),
                )

        self.assertIs(caught.exception, application_failure)
        self.assertEqual(app.shutdown_count, 1)
        self.assertEqual(runtime.closed, 1)


if __name__ == "__main__":
    unittest.main()
