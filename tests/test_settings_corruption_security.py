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

    def test_read_rejects_active_key_subclass_without_invoking_hooks(self) -> None:
        class HostileKey(str):
            touched = False

            def __hash__(self):
                type(self).touched = True
                raise AssertionError("hostile settings read hash hook must not execute")

            def __eq__(self, other):
                type(self).touched = True
                raise AssertionError("hostile settings read equality hook must not execute")

            def __str__(self):
                type(self).touched = True
                raise AssertionError("hostile settings read string hook must not execute")

        with tempfile.TemporaryDirectory() as td:
            settings = Settings(Path(td) / "settings.json")
            sentinel = object()
            hostile = HostileKey("volume")

            self.assertIs(settings.get(hostile, sentinel), sentinel)
            self.assertFalse(HostileKey.touched)
            self.assertEqual(settings.get("volume"), DEFAULTS["volume"])
            self.assertIs(settings.get("unknown", sentinel), sentinel)

    def test_every_current_default_has_an_explicit_validation_policy(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            settings = Settings(Path(td) / "settings.json")
            for key, value in DEFAULTS.items():
                with self.subTest(key=key):
                    settings.set(key, value)
                    self.assertEqual(settings.get(key), value)

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


    def test_direct_import_rejects_active_or_oversized_text_before_json_parse(self) -> None:
        class HostileProfile(str):
            touched = False

            def encode(self, *args, **kwargs):
                type(self).touched = True
                raise AssertionError("hostile profile encode hook must not execute")

        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "settings.json"
            settings = Settings(path)
            settings.set("volume", 37)
            baseline = dict(settings.data)
            persisted = path.read_bytes()

            with self.assertRaisesRegex(SettingsError, "profile must be text"):
                settings.import_json(HostileProfile('{"schema_version": 2, "values": {}}'))
            self.assertFalse(HostileProfile.touched)

            class TruthBomb:
                touched = False

                def __bool__(self):
                    type(self).touched = True
                    raise AssertionError("persist truthiness hook must not execute")

            with self.assertRaisesRegex(SettingsError, "persist flag must be boolean"):
                settings.import_json(
                    '{"schema_version": 2, "values": {}}',
                    persist=TruthBomb(),
                )
            self.assertFalse(TruthBomb.touched)

            with self.assertRaisesRegex(SettingsError, "profile is too large"):
                settings.import_json("x" * (1024 * 1024 + 1), persist=False)

            # Character count alone is insufficient: this remains below one
            # million Python characters but exceeds the one-MiB UTF-8 envelope.
            with self.assertRaisesRegex(SettingsError, "profile is too large"):
                settings.import_json("😀" * 300_000, persist=False)

            with self.assertRaisesRegex(SettingsError, "not valid UTF-8"):
                settings.import_json('{"values":{"engine_path":"\ud800"}}', persist=False)

            self.assertEqual(settings.data, baseline)
            self.assertEqual(path.read_bytes(), persisted)


if __name__ == "__main__":
    unittest.main()
