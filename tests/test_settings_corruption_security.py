from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from acs.settings import DEFAULTS, SCHEMA_VERSION, Settings, SettingsError


class SettingsCorruptionSecurityTests(unittest.TestCase):
    def test_load_rejects_coercive_schema_scalars_and_recovers_defaults(self) -> None:
        for schema in (True, False, 1.0, 2.5, "1", "2", None, -1):
            with self.subTest(schema=schema):
                with tempfile.TemporaryDirectory() as td:
                    path = Path(td) / "settings.json"
                    path.write_text(
                        json.dumps({"schema_version": schema, "values": {"language": "en", "volume": 1}}),
                        encoding="utf-8",
                    )
                    settings = Settings(path)
                    self.assertEqual(settings.data, DEFAULTS)
                    self.assertIn("settings recovery", settings.warning or "")
                    self.assertNotEqual(settings.get("language"), "en")
                    self.assertNotEqual(settings.get("volume"), 1)

    def test_import_rejects_coercive_schema_without_mutation_or_persistence(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "settings.json"
            settings = Settings(path)
            settings.set("language", "en")
            settings.set("volume", 33)
            baseline = dict(settings.data)
            persisted = path.read_bytes()
            for schema in (True, 2.5, "2", None, -1):
                with self.subTest(schema=schema):
                    with self.assertRaises(SettingsError):
                        settings.import_json(
                            json.dumps({"schema_version": schema, "values": {"language": "uk", "volume": 1}})
                        )
                    self.assertEqual(settings.data, baseline)
                    self.assertEqual(path.read_bytes(), persisted)

    def test_unversioned_legacy_profile_is_still_the_only_schema_zero_path(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "settings.json"
            settings = Settings(path)
            warnings = settings.import_json(json.dumps({"language": "en", "volume": 55}), persist=False)
            self.assertEqual(settings.get("language"), "en")
            self.assertEqual(settings.get("volume"), 55)
            self.assertIn("migrated unversioned settings to schema 1", warnings)
            self.assertEqual(settings.to_profile()["schema_version"], SCHEMA_VERSION)


if __name__ == "__main__":
    unittest.main()
