"""Isolated and application-level Section 45.5-45.6 regression contracts."""
import json
from pathlib import Path
import tempfile
import unittest

from acs.visual_profile_sync import (
    CHOICES, VisualProfileSyncError, export_document, import_document,
    reconcile_import, revision,
)
from acs.settings import Settings
from acs.webapp import AccessibleChessAPI


class VisualSyncTests(unittest.TestCase):
    def setUp(self):
        self.base = {
            "profile": "classic", "theme": "system",
            "board_theme": "wood", "density": "comfortable",
        }

    def test_all_300_current_profile_theme_board_density_combinations(self):
        count = 0
        for name in CHOICES["profile"]:
            for theme in CHOICES["theme"]:
                for board in CHOICES["board_theme"]:
                    for density in CHOICES["density"]:
                        values = dict(profile=name, theme=theme, board_theme=board, density=density)
                        self.assertEqual(import_document(export_document(values)), values)
                        self.assertEqual(reconcile_import(
                            export_document(values), self.base, revision(self.base)
                        ), values)
                        count += 1
        self.assertEqual(count, 300)

    def test_revision_is_order_independent_and_private_fields_rejected(self):
        self.assertEqual(revision(self.base), revision(dict(reversed(list(self.base.items())))))
        for extra in ("engine_path", "library_path", "api_key", "settings_path", "position"):
            with self.subTest(extra=extra):
                with self.assertRaises(VisualProfileSyncError):
                    export_document({**self.base, extra: "C:/Private"})
        self.assertNotIn("path", export_document(self.base).lower())

    def test_fail_closed_invalid_versions_duplicates_tampering_and_stale_preview(self):
        document = export_document(self.base)
        attacks = [
            "", "{", "[]" * 5000, "null",
            document.replace('"schema_version":1', '"schema_version":2'),
            document.replace('"classic"', '"tournament"'),
            document.replace('"classic"', '"classic","engine_path":"C:/secret"'),
            document.replace('"kind":', '"kind":"spoof","kind":'),
            document.replace('"profile":', '"profile":{},"profile":'),
            document + " trailing",
        ]
        for value in attacks:
            with self.subTest(value=value[:80]), self.assertRaises(VisualProfileSyncError):
                import_document(value)
        with self.assertRaisesRegex(VisualProfileSyncError, "conflict"):
            reconcile_import(document, {**self.base, "theme": "dark"}, revision(self.base))
        with self.assertRaises(VisualProfileSyncError):
            reconcile_import(document, self.base, "0" * 64)

    def test_application_bridge_export_import_recovery_and_chess_isolation(self):
        with tempfile.TemporaryDirectory() as directory:
            settings_path = Path(directory) / "settings.json"
            app = AccessibleChessAPI("en")
            app._settings = Settings(settings_path)
            original_fen = app.get_state()["fen"]
            exported = app.visual_profile_sync_export()
            self.assertTrue(exported["ok"])
            self.assertNotIn("engine_path", exported["document"])
            changed = dict(profile="low-vision", theme="contrast",
                           board_theme="high-contrast", density="spacious")
            incoming = export_document(changed)
            applied = app.visual_profile_sync_import(incoming, exported["revision"])
            self.assertTrue(applied["ok"], applied)
            self.assertEqual(app.get_state()["fen"], original_fen)
            self.assertEqual(app.visual_profile_get()["theme"], "contrast")
            rejected = app.visual_profile_sync_import(
                export_document(self.base), exported["revision"]
            )
            self.assertFalse(rejected["ok"])
            self.assertEqual(rejected["reason"], "conflict")
            self.assertEqual(app.visual_profile_get()["theme"], "contrast")
            restarted = AccessibleChessAPI("en")
            restarted._settings = Settings(settings_path)
            self.assertEqual(restarted.visual_profile_get()["theme"], "contrast")
            self.assertEqual(restarted.get_state()["fen"], original_fen)
            bad = restarted.visual_profile_sync_import(
                '{"kind":"bad","schema_version":1,"profile":{},"revision":"0"}',
                restarted.visual_profile_sync_export()["revision"],
            )
            self.assertFalse(bad["ok"])
            self.assertEqual(restarted.visual_profile_get()["theme"], "contrast")

    def test_keyboard_accessible_import_export_controls_have_single_bridge(self):
        html = (Path(__file__).resolve().parents[1] / "web" / "index.html").read_text(encoding="utf-8")
        for fragment in ('id="visual-sync-export"', 'id="visual-sync-import"',
                         'visual_profile_sync_export', 'visual_profile_sync_import',
                         'aria-live="off"', 'wireVisualSync()'):
            self.assertIn(fragment, html)


if __name__ == "__main__":
    unittest.main()
