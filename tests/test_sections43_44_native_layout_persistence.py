from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from acs.settings import Settings, SettingsError
from acs.stage1_release_ui import Stage1ReleaseAccessibleChessAPI


def _ui(root: Path) -> Stage1ReleaseAccessibleChessAPI:
    # Tests exercise the production facade methods against production Settings
    # without instantiating chess engines, sound devices or Windows WebView.
    api = object.__new__(Stage1ReleaseAccessibleChessAPI)
    api._settings = Settings(root / "settings.json")
    return api


def _workspace() -> dict:
    return {
        "version": 1,
        "collapsed": ["h-moves", "h-engine"],
        "sizes": {"h-board": "large", "h-engine": "medium"},
        "density": "compact",
        "layout": "single",
    }


class NativeLayoutPersistenceTests(unittest.TestCase):
    def test_actual_private_settings_restart_and_separate_product_modes(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            api = _ui(root)
            self.assertTrue(api.save_presentation_layout("workspace", _workspace())["ok"])
            self.assertTrue(api.save_presentation_layout("product", {
                "version": 1, "routes": {"books": "reading", "teacher": "compact"}
            })["ok"])
            persisted = json.loads((root / "settings.json").read_text(encoding="utf-8"))
            self.assertEqual(persisted["schema_version"], 2)
            self.assertIn("workspace_layout_json", persisted["values"])
            self.assertIn("product_layout_json", persisted["values"])
            restarted = _ui(root)
            self.assertEqual(restarted.get_presentation_layout("workspace")["layout"], _workspace())
            self.assertEqual(
                restarted.get_presentation_layout("product")["layout"]["routes"],
                {"books": "reading", "teacher": "compact"},
            )

    def test_bad_request_kind_structure_poisoning_and_size_are_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            api = _ui(Path(folder))
            self.assertFalse(api.get_presentation_layout([])["ok"])
            self.assertFalse(api.save_presentation_layout({}, _workspace())["ok"])
            cases = (
                {**_workspace(), "version": True},
                {**_workspace(), "collapsed": ["__proto__"]},
                {**_workspace(), "collapsed": ["h-moves", "h-moves"]},
                {**_workspace(), "sizes": {"__proto__": "large"}},
                {**_workspace(), "sizes": {"h-board": "<script>"}},
                {**_workspace(), "density": ["compact"]},
                {**_workspace(), "layout": "untrusted"},
                {**_workspace(), "unauthorized": "chess"},
            )
            for candidate in cases:
                with self.subTest(candidate=candidate):
                    self.assertFalse(api.save_presentation_layout("workspace", candidate)["ok"])
            self.assertFalse(api.save_presentation_layout(
                "product", {"version": 1, "routes": {"chess-engine": "reading"}}
            )["ok"])
            self.assertFalse(api.save_presentation_layout(
                "product", {"version": 1, "routes": {"books": "<svg onload=evil()>"}}
            )["ok"])
            self.assertFalse(api.save_presentation_layout(
                "product", {"version": 1, "routes": {"books": "compact"}, "position": "fen"}
            )["ok"])
            self.assertEqual(api.get_presentation_layout("workspace")["layout"]["collapsed"], [])
            self.assertEqual(api.get_presentation_layout("product")["layout"]["routes"], {})

    def test_product_panel_collapse_size_restart_and_untrusted_data(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            api = _ui(root)
            accepted = {"version": 1, "routes": {"books": "reading"},
                        "panels": {"books": {"collapsed": True, "size": "large"},
                                   "training": {"collapsed": False, "size": "medium"}}}
            self.assertTrue(api.save_presentation_layout("product", accepted)["ok"])
            self.assertEqual(_ui(root).get_presentation_layout("product")["layout"], accepted)
            malicious = (
                {"version": 1, "routes": {}, "panels": {"books": {"collapsed": "true", "size": "large"}}},
                {"version": 1, "routes": {}, "panels": {"books": {"collapsed": True, "size": "<script>"}}},
                {"version": 1, "routes": {}, "panels": {"__proto__": {"collapsed": True, "size": "auto"}}},
                {"version": 1, "routes": {}, "panels": {"books": {"collapsed": True, "size": "auto", "private": "fen"}}},
            )
            for candidate in malicious:
                with self.subTest(candidate=candidate):
                    self.assertFalse(api.save_presentation_layout("product", candidate)["ok"])
            self.assertEqual(_ui(root).get_presentation_layout("product")["layout"], accepted)

    def test_preexisting_stale_writer_rejected_and_recovered_without_data_loss(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            first = _ui(root)
            stale = _ui(root)
            self.assertTrue(first.save_presentation_layout("workspace", _workspace())["ok"])
            other = {
                "version": 1, "collapsed": [], "sizes": {},
                "density": "comfortable", "layout": "auto",
            }
            self.assertFalse(stale.save_presentation_layout("workspace", other)["ok"])
            self.assertEqual(_ui(root).get_presentation_layout("workspace")["layout"], _workspace())

    def test_settings_are_upgrade_locked_and_invalid_json_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            api = _ui(Path(folder))
            api._settings._write_blocked_reason = "newer settings schema"
            self.assertFalse(api.save_presentation_layout("workspace", _workspace())["ok"])
            self.assertFalse(api.get_presentation_layout("workspace")["ok"])
            api._settings._write_blocked_reason = None
            with self.assertRaises(SettingsError):
                api._settings.set("workspace_layout_json", '{"version":true}')
            with self.assertRaises(SettingsError):
                api._settings.set("product_layout_json", "x" * 2049)
            self.assertTrue(api.get_presentation_layout("workspace")["ok"])

    def test_layout_only_changes_do_not_change_chess_or_sound_preferences(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            api = _ui(Path(folder))
            before = dict(api._settings.data)
            self.assertTrue(api.save_presentation_layout("workspace", _workspace())["ok"])
            after = dict(api._settings.data)
            changed = {k for k in after if after[k] != before[k]}
            self.assertEqual(changed, {"workspace_layout_json"})


if __name__ == "__main__":
    unittest.main()
