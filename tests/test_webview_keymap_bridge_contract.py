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
        ):
            self.assertIn(marker, html)
        self.assertNotIn("localStorage.setItem", html)
        self.assertNotIn("localStorage.getItem", html)
        self.assertNotIn("function conflictsFor", html)
        self.assertNotIn("const alias=keymap.find", html)

    def test_board_grid_remap_uses_same_persisted_registry(self):
        with tempfile.TemporaryDirectory() as td:
            api = KeymapAwareAccessibleChessAPI(keymap_path=Path(td) / "keymap.json")
            self.assertEqual(api.keymap_resolve_binding("board", "ArrowLeft")["actionId"], "board.cursor_left")
            changed = api.keymap_save("board.cursor_left", "Ctrl+Alt+Left")
            self.assertTrue(changed["ok"])
            self.assertIsNone(api.keymap_resolve_binding("board", "ArrowLeft"))
            self.assertEqual(
                api.keymap_resolve_binding("board", "Ctrl+Alt+Left")["actionId"],
                "board.cursor_left",
            )

    def test_input_submission_keys_use_persisted_registry(self):
        with tempfile.TemporaryDirectory() as td:
            api = KeymapAwareAccessibleChessAPI(keymap_path=Path(td) / "keymap.json")
            self.assertEqual(api.keymap_resolve_binding("move_entry", "Enter")["actionId"], "move.submit")
            self.assertEqual(api.keymap_resolve_binding("history", "Enter")["actionId"], "history.commit_go_to_move")
            self.assertTrue(api.keymap_save("move.submit", "Ctrl+Enter")["ok"])
            self.assertTrue(api.keymap_save("history.commit_go_to_move", "Alt+Enter")["ok"])
            self.assertIsNone(api.keymap_resolve_binding("move_entry", "Enter"))
            self.assertIsNone(api.keymap_resolve_binding("history", "Enter"))
            self.assertEqual(api.keymap_resolve_binding("move_entry", "Ctrl+Enter")["actionId"], "move.submit")
            self.assertEqual(api.keymap_resolve_binding("history", "Alt+Enter")["actionId"], "history.commit_go_to_move")

    def test_runtime_resolution_follows_persisted_remap_without_js_cache(self):
        with tempfile.TemporaryDirectory() as td:
            api = KeymapAwareAccessibleChessAPI(keymap_path=Path(td) / "keymap.json")
            self.assertEqual(api.keymap_resolve_binding("history", "Shift+D")["actionId"], "history.next")
            changed = api.keymap_save("history.next", "Ctrl+Shift+J")
            self.assertTrue(changed["ok"])
            self.assertIsNone(api.keymap_resolve_binding("history", "Shift+D"))
            self.assertEqual(api.keymap_resolve_binding("history", "Ctrl+Shift+J")["actionId"], "history.next")

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
            self.assertTrue(api.make_move("e4")["ok"])
            self.assertEqual(len(api.sans), 1)
            self.assertTrue(api.make_move("z")["ok"])
            self.assertEqual(len(api.sans), 0)


if __name__ == "__main__":
    unittest.main()
