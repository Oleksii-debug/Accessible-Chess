from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from acs.webapp_keymap import KeymapAwareAccessibleChessAPI


class WebviewKeymapBridgeIntegrationTests(unittest.TestCase):
    def test_release_html_uses_python_keymap_bridge_as_authority(self):
        html = (Path(__file__).resolve().parents[1] / "web" / "index.html").read_text(encoding="utf-8")
        for marker in (
            "keymap_snapshot", "keymap_preview", "keymap_capture_shortcut", "keymap_save",
            "keymap_reset_action", "keymap_reset_context", "keymap_reset_all",
            "keymap_export_profile", "keymap_import_profile", "keymap_resolve_binding",
            "await apiAction('make_move',v)",
            "for(const context of ['board','analysis','global'])",
            "resolveBinding(chord,'board','board')",
        ):
            self.assertIn(marker, html)
        self.assertNotIn("localStorage.setItem", html)
        self.assertNotIn("localStorage.getItem", html)
        self.assertNotIn("function conflictsFor", html)
        self.assertNotIn("const alias=keymap.find", html)

    def test_runtime_resolution_follows_persisted_remap_without_js_cache(self):
        with tempfile.TemporaryDirectory() as td:
            api = KeymapAwareAccessibleChessAPI(keymap_path=Path(td) / "keymap.json")
            self.assertEqual(api.keymap_resolve_binding("history", "Shift+D")["actionId"], "history.next")
            changed = api.keymap_save("history.next", "Ctrl+Shift+J")
            self.assertTrue(changed["ok"])
            self.assertIsNone(api.keymap_resolve_binding("history", "Shift+D"))
            self.assertEqual(api.keymap_resolve_binding("history", "Ctrl+Shift+J")["actionId"], "history.next")

    def test_board_focus_resolution_includes_analysis_before_global_fallback(self):
        with tempfile.TemporaryDirectory() as td:
            api = KeymapAwareAccessibleChessAPI(keymap_path=Path(td) / "keymap.json")

            board = api.keymap_resolve_binding("board", "Left")
            self.assertIsNotNone(board)
            self.assertEqual(board["actionId"], "board.cursor_left")
            self.assertEqual(board["context"], "board")

            analysis = api.keymap_resolve_binding("board", "Alt+1")
            self.assertIsNotNone(analysis)
            self.assertEqual(analysis["actionId"], "analysis.pv1")
            self.assertEqual(analysis["context"], "analysis")

            global_action = api.keymap_resolve_binding("board", "Ctrl+Z")
            self.assertIsNotNone(global_action)
            self.assertEqual(global_action["actionId"], "edit.undo")
            self.assertEqual(global_action["context"], "global")

            self.assertIsNone(api.keymap_resolve_binding("history", "Alt+1"))

    def test_board_focus_collision_prefers_board_over_analysis_and_global(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "keymap.json"
            api = KeymapAwareAccessibleChessAPI(keymap_path=path)

            self.assertTrue(api.keymap_save("analysis.pv1", "Left")["ok"])
            self.assertTrue(api.keymap_save("edit.undo", "Left")["ok"])

            resolved = api.keymap_resolve_binding("board", "Left")
            self.assertIsNotNone(resolved)
            self.assertEqual(resolved["actionId"], "board.cursor_left")
            self.assertEqual(resolved["context"], "board")

            restarted = KeymapAwareAccessibleChessAPI(keymap_path=path)
            persisted = restarted.keymap_resolve_binding("board", "Left")
            self.assertIsNotNone(persisted)
            self.assertEqual(persisted["actionId"], "board.cursor_left")
            self.assertEqual(persisted["context"], "board")

    def test_board_focus_collision_prefers_analysis_over_global_without_context_leak(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "keymap.json"
            api = KeymapAwareAccessibleChessAPI(keymap_path=path)
            collision = "Ctrl+Shift+J"

            self.assertTrue(api.keymap_save("analysis.pv1", collision)["ok"])
            self.assertTrue(api.keymap_save("edit.undo", collision)["ok"])

            board = api.keymap_resolve_binding("board", collision)
            self.assertIsNotNone(board)
            self.assertEqual(board["actionId"], "analysis.pv1")
            self.assertEqual(board["context"], "analysis")

            history = api.keymap_resolve_binding("history", collision)
            self.assertIsNotNone(history)
            self.assertEqual(history["actionId"], "edit.undo")
            self.assertEqual(history["context"], "global")

            restarted = KeymapAwareAccessibleChessAPI(keymap_path=path)
            persisted_board = restarted.keymap_resolve_binding("board", collision)
            self.assertIsNotNone(persisted_board)
            self.assertEqual(persisted_board["actionId"], "analysis.pv1")
            self.assertEqual(persisted_board["context"], "analysis")
            persisted_history = restarted.keymap_resolve_binding("history", collision)
            self.assertIsNotNone(persisted_history)
            self.assertEqual(persisted_history["actionId"], "edit.undo")
            self.assertEqual(persisted_history["context"], "global")

    def test_board_focus_analysis_resolution_tracks_persisted_remap(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "keymap.json"
            api = KeymapAwareAccessibleChessAPI(keymap_path=path)
            changed = api.keymap_save("analysis.pv1", "Ctrl+Shift+J")
            self.assertTrue(changed["ok"], changed)
            self.assertIsNone(api.keymap_resolve_binding("board", "Alt+1"))
            resolved = api.keymap_resolve_binding("board", "Ctrl+Shift+J")
            self.assertIsNotNone(resolved)
            self.assertEqual(resolved["actionId"], "analysis.pv1")
            self.assertEqual(resolved["context"], "analysis")

            restarted = KeymapAwareAccessibleChessAPI(keymap_path=path)
            self.assertIsNone(restarted.keymap_resolve_binding("board", "Alt+1"))
            persisted = restarted.keymap_resolve_binding("board", "Ctrl+Shift+J")
            self.assertIsNotNone(persisted)
            self.assertEqual(persisted["actionId"], "analysis.pv1")
            self.assertEqual(persisted["context"], "analysis")

    def test_bridge_resolution_fails_closed_for_malformed_inputs(self):
        with tempfile.TemporaryDirectory() as td:
            api = KeymapAwareAccessibleChessAPI(keymap_path=Path(td) / "keymap.json")
            malformed = (
                ("board", None),
                ("board", 7),
                ("unknown-context", "Left"),
                (None, "Left"),
            )
            for context, binding in malformed:
                with self.subTest(context=context, binding=binding):
                    self.assertIsNone(api.keymap_resolve_binding(context, binding))

    def test_import_warning_requires_explicit_bridge_confirmation(self):
        with tempfile.TemporaryDirectory() as td:
            api = KeymapAwareAccessibleChessAPI(keymap_path=Path(td) / "keymap.json")
            exported = json.loads(api.keymap_export_profile())
            exported["bindings"]["history.next"] = "Ctrl+L"
            text = json.dumps(exported)
            before = api.keymap_resolve_binding("history", "Shift+D")
            first = api.keymap_import_profile(text, False)
            self.assertFalse(first["ok"])
            self.assertTrue(first["requiresConfirmation"])
            self.assertEqual(api.keymap_resolve_binding("history", "Shift+D"), before)
            self.assertIsNone(api.keymap_resolve_binding("history", "Ctrl+L"))
            confirmed = api.keymap_import_profile(text, True)
            self.assertTrue(confirmed["ok"])
            self.assertIsNone(api.keymap_resolve_binding("history", "Shift+D"))
            self.assertEqual(api.keymap_resolve_binding("history", "Ctrl+L")["actionId"], "history.next")

    def test_move_alias_remap_is_resolved_only_by_release_api(self):
        with tempfile.TemporaryDirectory() as td:
            api = KeymapAwareAccessibleChessAPI(keymap_path=Path(td) / "keymap.json")
            self.assertTrue(api.keymap_save("move.undo", "z")["ok"])
            initial_fen = api.get_state()["fen"]
            moved = api.make_move("e4")
            self.assertTrue(moved["ok"], moved)
            self.assertNotEqual(moved["fen"], initial_fen)
            self.assertEqual(api.get_state()["fen"], moved["fen"])
            self.assertEqual(len(api.sans), 1)
            self.assertTrue(api.make_move("z")["ok"])
            self.assertEqual(len(api.sans), 0)
            self.assertEqual(api.get_state()["fen"], initial_fen)


if __name__ == "__main__":
    unittest.main()
