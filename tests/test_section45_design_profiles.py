from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from acs.section45_design_profiles import (
    PRESETS, DEFAULT_STORE, DEFAULT_PREFERENCES,
    DesignProfileError, read_store, save_copy, selected_preferences, serialize_store,
)
from acs.settings import Settings, SettingsError
from acs.stage1_release_ui import Stage1ReleaseAccessibleChessAPI


def ui(folder: Path) -> Stage1ReleaseAccessibleChessAPI:
    api = object.__new__(Stage1ReleaseAccessibleChessAPI)
    api._settings = Settings(folder / "settings.json")
    return api


class Section45ProfilesTests(unittest.TestCase):
    def test_six_presets_and_roundtrip_contract(self):
        self.assertEqual(set(PRESETS), {
            "Classic", "Tournament", "Coach", "Classroom Presentation",
            "Low Vision", "High Contrast",
        })
        for name in PRESETS:
            with self.subTest(name=name):
                store = {**DEFAULT_STORE, "selected": name}
                self.assertEqual(selected_preferences(store), PRESETS[name])
                self.assertEqual(read_store(serialize_store(store)), store)

    def test_copy_export_and_bounded_private_ingress(self):
        copy = save_copy(DEFAULT_STORE, "My classroom", PRESETS["Coach"])
        self.assertEqual(copy["selected"], "My classroom")
        self.assertEqual(selected_preferences(copy), PRESETS["Coach"])
        payload = serialize_store(copy)
        self.assertNotIn("C:\\Users", payload)
        self.assertEqual(read_store(payload), copy)
        for attack in (
            '{"version":1,"selected":"Classic","selected":"High Contrast","profiles":{}}',
            '{"version":true,"selected":"Classic","profiles":{}}',
            '{"version":1,"selected":"Classic","profiles":{"../private":{}}}',
            '{"version":1,"selected":"Classic","profiles":{"Classic":{}}}',
            '{"version":1,"selected":"Missing","profiles":{}}',
            '{"version":1,"selected":"Classic","profiles":{},"secret":"token"}',
            '{"version":1,"selected":"Classic","profiles":{},"score":NaN}',
            "x" * 17000,
        ):
            with self.subTest(attack=attack[:90]):
                with self.assertRaises(DesignProfileError):
                    read_store(attack)
        malicious = dict(DEFAULT_PREFERENCES)
        malicious["font_percent"] = True
        with self.assertRaises(DesignProfileError):
            save_copy(DEFAULT_STORE, "Test", malicious)
        malicious["font_percent"] = 100
        malicious["chess_fen"] = "startpos"
        with self.assertRaises(DesignProfileError):
            save_copy(DEFAULT_STORE, "Test", malicious)

    def test_canonical_settings_durable_recovery_and_conflict(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            first = ui(root)
            one = first.get_design_studio_state()
            self.assertTrue(one["ok"])
            self.assertEqual(one["store"], DEFAULT_STORE)
            payload = save_copy(DEFAULT_STORE, "My tournament", PRESETS["Tournament"])
            changed = first.save_design_studio_state(payload, one["revision"])
            self.assertTrue(changed["ok"])
            self.assertNotEqual(changed["revision"], one["revision"])
            self.assertEqual(ui(root).get_design_studio_state()["store"], payload)
            self.assertEqual(changed["store"], payload)
            self.assertFalse(first.save_design_studio_state(DEFAULT_STORE, one["revision"])["ok"])
            self.assertTrue(first.save_design_studio_state(DEFAULT_STORE, one["revision"])["conflict"])
            self.assertEqual(ui(root).get_design_studio_state()["store"], payload)
            self.assertEqual(ui(root).get_presentation_layout("workspace")["layout"]["version"], 1)
            self.assertNotIn("fen", (root / "settings.json").read_text().lower())

    def test_stale_writer_and_corrupt_payload_do_not_overwrite(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            fresh = ui(root)
            stale = ui(root)
            revision = fresh.get_design_studio_state()["revision"]
            value = save_copy(DEFAULT_STORE, "Work", PRESETS["Low Vision"])
            self.assertTrue(fresh.save_design_studio_state(value, revision)["ok"])
            self.assertFalse(stale.save_design_studio_state(DEFAULT_STORE, revision)["ok"])
            self.assertEqual(ui(root).get_design_studio_state()["store"], value)
            with self.assertRaises(SettingsError):
                fresh._settings.set("design_profiles_json", '{"version":2}')
            self.assertEqual(ui(root).get_design_studio_state()["store"], value)

    def test_selected_profile_changes_never_change_chess_or_other_settings(self):
        with tempfile.TemporaryDirectory() as d:
            first = ui(Path(d))
            before = first._settings.data.copy()
            one = first.get_design_studio_state()
            two = first.save_design_studio_state(
                {**DEFAULT_STORE, "selected": "High Contrast"}, one["revision"]
            )
            self.assertTrue(two["ok"])
            after = first._settings.data
            self.assertEqual({
                key for key in before if before[key] != after[key]
            }, {"design_profiles_json"})
            self.assertEqual(after["workspace_layout_json"], before["workspace_layout_json"])
            self.assertEqual(after["sounds"], before["sounds"])


if __name__ == "__main__":
    unittest.main()
