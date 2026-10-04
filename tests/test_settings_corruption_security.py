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


    def test_mutation_rejects_active_scalar_subclasses_before_hooks(self) -> None:
        class HostileText(str):
            touched = False

            def __hash__(self):
                type(self).touched = True
                raise AssertionError("hostile text hash hook must not execute")

            def __eq__(self, other):
                type(self).touched = True
                raise AssertionError("hostile text equality hook must not execute")

            def strip(self, *args, **kwargs):
                type(self).touched = True
                raise AssertionError("hostile text strip hook must not execute")

        class HostileInt(int):
            touched = False

            def __le__(self, other):
                type(self).touched = True
                raise AssertionError("hostile integer comparison hook must not execute")

            def __ge__(self, other):
                type(self).touched = True
                raise AssertionError("hostile integer comparison hook must not execute")

        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "settings.json"
            settings = Settings(path)
            baseline = dict(settings.data)

            for key, value in (
                ("language", HostileText("en")),
                ("notation", HostileText("san")),
                ("tick_policy", HostileText("both")),
                ("sound_move_variant", HostileText("2")),
                ("engine_path", HostileText("stockfish.exe")),
                ("volume", HostileInt(40)),
                ("tick_last_seconds", HostileInt(5)),
            ):
                with self.subTest(key=key):
                    with self.assertRaises(SettingsError):
                        settings.set(key, value)

            self.assertFalse(HostileText.touched)
            self.assertFalse(HostileInt.touched)
            self.assertEqual(settings.data, baseline)
            self.assertFalse(path.exists())

    def test_mutation_rejects_active_key_subclass_before_hash_or_format_hooks(self) -> None:
        class HostileKey(str):
            touched = False

            def __hash__(self):
                type(self).touched = True
                raise AssertionError("hostile settings key hash hook must not execute")

            def __str__(self):
                type(self).touched = True
                raise AssertionError("hostile settings key string hook must not execute")

        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "settings.json"
            settings = Settings(path)
            baseline = dict(settings.data)
            hostile = HostileKey("volume")

            with self.assertRaises(KeyError):
                settings.set(hostile, 40)
            with self.assertRaises(KeyError):
                settings.reset(hostile)

            self.assertFalse(HostileKey.touched)
            self.assertEqual(settings.data, baseline)
            self.assertFalse(path.exists())

    def test_exact_builtin_scalars_still_persist_and_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "settings.json"
            settings = Settings(path)
            settings.set("language", "en")
            settings.set("notation", "san")
            settings.set("volume", 40)
            settings.set("tick_policy", "both")
            settings.set("tick_last_seconds", 5)
            settings.set("sound_move_variant", "2")
            settings.set("engine_path", "stockfish.exe")

            restored = Settings(path)
            self.assertEqual(restored.get("language"), "en")
            self.assertEqual(restored.get("notation"), "san")
            self.assertEqual(restored.get("volume"), 40)
            self.assertEqual(restored.get("tick_policy"), "both")
            self.assertEqual(restored.get("tick_last_seconds"), 5)
            self.assertEqual(restored.get("sound_move_variant"), "2")
            self.assertEqual(restored.get("engine_path"), "stockfish.exe")


if __name__ == "__main__":
    unittest.main()
