from __future__ import annotations

from pathlib import Path
import tempfile
import unittest
from unittest import mock

from acs.stage1_native_menu_router import Stage1NativeMenuActionProxy
from acs.stage1_release_ui import Stage1ReleaseAccessibleChessAPI


class _RecordingAPI:
    def __init__(self) -> None:
        self.calls: list[str] = []
        self.lang = "uk"

    def dispatch_action(self, action_id: str):
        self.calls.append(action_id)
        return {"ok": True, "announcement": action_id}

    def toggle_engine(self):
        self.calls.append("direct.toggle_engine")
        return {"ok": True}


class Stage1NativeMenuActionRoutingTests(unittest.TestCase):
    def test_registered_native_menu_methods_converge_on_dispatch_action(self) -> None:
        api = _RecordingAPI()
        proxy = Stage1NativeMenuActionProxy(api)
        proxy.undo()
        proxy.redo()
        proxy.review_previous()
        proxy.review_next()
        proxy.restart_analysis()
        proxy.select_relative_analysis_pv(-1)
        proxy.select_relative_analysis_pv(1)
        proxy.toggle_analysis_lock()
        proxy.explore_analysis_pv()
        proxy.return_from_analysis()
        proxy.insert_analysis_move()
        proxy.insert_analysis_line()
        self.assertEqual(
            api.calls,
            [
                "edit.undo", "edit.redo", "history.previous", "history.next",
                "analysis.restart", "analysis.previous_pv", "analysis.next_pv",
                "analysis.lock_target", "analysis.explore_pv", "analysis.return",
                "analysis.insert_move", "analysis.insert_line",
            ],
        )

    def test_menu_only_nonregistered_operation_delegates_without_fake_action_id(self) -> None:
        api = _RecordingAPI()
        proxy = Stage1NativeMenuActionProxy(api)
        result = proxy.toggle_engine()
        self.assertTrue(result["ok"])
        self.assertEqual(api.calls, ["direct.toggle_engine"])

    def test_invalid_relative_pv_delta_fails_before_dispatch(self) -> None:
        api = _RecordingAPI()
        proxy = Stage1NativeMenuActionProxy(api)
        for invalid in (0, 2, -2, True, "1", None):
            with self.subTest(invalid=invalid):
                with self.assertRaises(ValueError):
                    proxy.select_relative_analysis_pv(invalid)
        self.assertEqual(api.calls, [])

    def test_real_release_dispatch_global_and_history_actions_use_canonical_state(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            api = Stage1ReleaseAccessibleChessAPI(keymap_path=Path(td) / "keymap.json")
            start = api.board.fen()
            self.assertTrue(api.make_move("e4")["ok"])
            moved = api.board.fen()
            self.assertNotEqual(moved, start)

            self.assertTrue(api.dispatch_action("edit.undo")["ok"])
            self.assertEqual(api.board.fen(), start)
            self.assertTrue(api.dispatch_action("edit.redo")["ok"])
            self.assertEqual(api.board.fen(), moved)

            previous = api.dispatch_action("history.previous")
            self.assertTrue(previous["ok"])
            self.assertEqual(previous["fen"], start)
            self.assertEqual(api.board.fen(), moved)
            current = api.dispatch_action("history.next")
            self.assertTrue(current["ok"])
            self.assertEqual(current["fen"], moved)

    def test_release_window_installs_native_menu_with_router_not_second_js_api(self) -> None:
        from acs import stage1_release_ui as release_ui

        class _Event:
            def __init__(self): self.handlers = []
            def __iadd__(self, handler): self.handlers.append(handler); return self
            def fire(self):
                for handler in tuple(self.handlers): handler()

        class _Window:
            def __init__(self):
                self.events = type("Events", (), {"before_show": _Event(), "loaded": _Event()})()
            def evaluate_js(self, source): pass

        window = _Window()
        class _Webview:
            def create_window(self, *args, **kwargs):
                self.js_api = kwargs["js_api"]
                return window
            def start(self, **kwargs):
                window.events.before_show.fire()
                window.events.loaded.fire()

        webview = _Webview()
        with tempfile.TemporaryDirectory() as td:
            api = Stage1ReleaseAccessibleChessAPI(keymap_path=Path(td) / "keymap.json")
            captured = []
            with mock.patch.dict("sys.modules", {"webview": webview}):
                with mock.patch.object(release_ui, "install_windows_native_menu", side_effect=lambda window, menu_api: captured.append(menu_api) or True):
                    release_ui.run_release_window(api)
            self.assertIs(webview.js_api, api)
            self.assertEqual(len(captured), 1)
            self.assertIsInstance(captured[0], Stage1NativeMenuActionProxy)
            self.assertIs(captured[0].wrapped_api, api)


if __name__ == "__main__":
    unittest.main()
