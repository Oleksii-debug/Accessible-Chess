import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock

import acs.settings as settings_module
from acs.settings import DEFAULTS, SCHEMA_VERSION, Settings, SettingsError
from acs.version2_upgrade_base import _UpgradeLock


class SettingsTests(unittest.TestCase):
    def test_defaults_preserve_existing_runtime_contract(self):
        with tempfile.TemporaryDirectory() as td:
            settings = Settings(Path(td) / "settings.json")
            self.assertEqual(settings.get("language"), "uk")
            self.assertEqual(settings.get("notation"), "uk_literal")
            self.assertTrue(settings.get("sounds"))
            self.assertEqual(settings.data["volume"], 80)

    def test_legacy_flat_settings_migrate_without_losing_known_values(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "settings.json"
            path.write_text(json.dumps({"language": "en", "volume": 55, "future": "ignore"}), encoding="utf-8")
            settings = Settings(path)
            self.assertEqual(settings.get("language"), "en")
            self.assertEqual(settings.get("volume"), 55)
            self.assertNotIn("future", settings.data)
            self.assertIn("migrated unversioned", settings.warning)

    def test_schema_one_migrates_to_current(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "settings.json"
            path.write_text(json.dumps({"schema_version": 1, "values": {"notation": "san"}}), encoding="utf-8")
            settings = Settings(path)
            self.assertEqual(settings.get("notation"), "san")
            self.assertIn("schema 1 to schema 2", settings.warning)

    def test_save_is_versioned_atomic_shape(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "settings.json"
            settings = Settings(path)
            settings.set("volume", 42)
            raw = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(raw["schema_version"], SCHEMA_VERSION)
            self.assertEqual(raw["values"]["volume"], 42)
            self.assertFalse(path.with_suffix(".json.tmp").exists())

    def test_save_is_blocked_by_active_version2_upgrade_lock(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            path = root / "settings.json"
            settings = Settings(path)

            with _UpgradeLock(root / ".v2-upgrade.lock"):
                with self.assertRaisesRegex(
                    SettingsError,
                    "temporarily locked for Version 2 upgrade",
                ):
                    settings.set("volume", 41)

            self.assertFalse(path.exists())
            self.assertEqual(
                80,
                settings.get("volume"),
                "failed locked save left runtime Settings ahead of disk",
            )

    def test_reset_failure_reloads_durable_runtime_state(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            path = root / "settings.json"
            settings = Settings(path)
            settings.set("volume", 31)

            with _UpgradeLock(root / ".v2-upgrade.lock"):
                with self.assertRaises(SettingsError):
                    settings.reset("volume")

            self.assertEqual(31, settings.get("volume"))
            self.assertEqual(
                31,
                json.loads(path.read_text(encoding="utf-8"))["values"]["volume"],
            )

    def test_import_failure_reloads_durable_runtime_state(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            path = root / "settings.json"
            settings = Settings(path)
            settings.set("volume", 32)
            payload = json.dumps(
                {
                    "schema_version": SCHEMA_VERSION,
                    "values": {"volume": 99, "language": "en"},
                }
            )

            with _UpgradeLock(root / ".v2-upgrade.lock"):
                with self.assertRaises(SettingsError):
                    settings.import_json(payload)

            self.assertEqual(32, settings.get("volume"))
            self.assertEqual("uk", settings.get("language"))
            durable = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(32, durable["values"]["volume"])
            self.assertEqual("uk", durable["values"]["language"])

    def test_postpublication_failure_reloads_what_is_actually_durable(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "settings.json"
            settings = Settings(path)
            settings.set("volume", 33)

            def publish_then_signal_failure():
                path.write_text(settings.export_json() + "\n", encoding="utf-8")
                raise SettingsError("simulated post-publication coordination failure")

            with mock.patch.object(
                settings,
                "save",
                side_effect=publish_then_signal_failure,
            ):
                with self.assertRaisesRegex(
                    SettingsError,
                    "post-publication coordination failure",
                ):
                    settings.set("volume", 55)

            self.assertEqual(
                55,
                settings.get("volume"),
                "runtime state did not resync to the durable post-publication file",
            )
            self.assertEqual(
                55,
                json.loads(path.read_text(encoding="utf-8"))["values"]["volume"],
            )

    def test_save_rejects_symlink_upgrade_lock(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            path = root / "settings.json"
            target = root / "lock-target.bin"
            target.write_bytes(b"do-not-touch")
            lock = root / ".v2-upgrade.lock"
            try:
                lock.symlink_to(target.name)
            except (OSError, NotImplementedError):
                self.skipTest("symlink creation is unavailable on this platform")

            settings = Settings(path)
            with self.assertRaisesRegex(
                SettingsError,
                "private regular file",
            ):
                settings.set("volume", 42)

            self.assertEqual(target.read_bytes(), b"do-not-touch")
            self.assertFalse(path.exists())

    def test_save_rejects_lock_inode_swap_between_lstat_and_open(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            path = root / "settings.json"
            lock = root / ".v2-upgrade.lock"
            lock.write_bytes(b"\0")
            replacement = root / "replacement-lock.bin"
            replacement.write_bytes(b"\0")
            settings = Settings(path)

            real_open = settings_module.os.open
            injected = False

            def swap_before_open(target, flags, *args):
                nonlocal injected
                candidate = Path(target)
                if candidate == lock and not injected:
                    os.replace(replacement, lock)
                    injected = True
                return real_open(target, flags, *args)

            with mock.patch.object(
                settings_module.os,
                "open",
                side_effect=swap_before_open,
            ):
                with self.assertRaisesRegex(
                    SettingsError,
                    "changed while opening",
                ):
                    settings.set("volume", 43)

            self.assertTrue(injected)
            self.assertFalse(path.exists())

    def test_save_ignores_preplanted_fixed_temp_symlink(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            path = root / "settings.json"
            victim = root / "victim.txt"
            victim.write_bytes(b"foreign-bytes")
            old_fixed_temp = path.with_suffix(path.suffix + ".tmp")
            try:
                old_fixed_temp.symlink_to(victim.name)
            except (OSError, NotImplementedError):
                self.skipTest("symlink creation is unavailable on this platform")

            settings = Settings(path)
            settings.set("volume", 44)

            self.assertEqual(victim.read_bytes(), b"foreign-bytes")
            self.assertTrue(old_fixed_temp.is_symlink())
            raw = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(raw["values"]["volume"], 44)
            self.assertFalse(
                any(
                    candidate.name.startswith(".settings.json.")
                    and candidate.name.endswith(".tmp")
                    for candidate in root.iterdir()
                    if candidate != old_fixed_temp
                ),
                "successful Settings.save left a private temp artifact",
            )

    def test_invalid_value_does_not_persist_or_mutate(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "settings.json"
            settings = Settings(path)
            with self.assertRaises(SettingsError):
                settings.set("volume", 101)
            self.assertEqual(settings.get("volume"), 80)
            self.assertFalse(path.exists())

    def test_malformed_file_recovers_to_defaults_with_warning(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "settings.json"
            path.write_text("{bad-json", encoding="utf-8")
            settings = Settings(path)
            self.assertEqual(settings.data, DEFAULTS)
            self.assertIn("settings recovery", settings.warning)

    def test_future_schema_recovers_instead_of_guessing(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "settings.json"
            path.write_text(json.dumps({"schema_version": 999, "values": {}}), encoding="utf-8")
            settings = Settings(path)
            self.assertEqual(settings.data, DEFAULTS)
            self.assertIn("newer than supported", settings.warning)

    def test_import_export_round_trip_and_unknown_keys_are_ignored(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "settings.json"
            settings = Settings(path)
            payload = {
                "schema_version": SCHEMA_VERSION,
                "values": {"language": "en", "notation": "en_literal", "unknown": 123},
            }
            settings.import_json(json.dumps(payload))
            clone = Settings(path)
            self.assertEqual(clone.get("language"), "en")
            self.assertEqual(clone.get("notation"), "en_literal")
            self.assertNotIn("unknown", clone.data)

    def test_reset_one_or_all(self):
        with tempfile.TemporaryDirectory() as td:
            settings = Settings(Path(td) / "settings.json")
            settings.set("language", "en")
            settings.set("volume", 10)
            settings.reset("volume")
            self.assertEqual(settings.get("volume"), 80)
            self.assertEqual(settings.get("language"), "en")
            settings.reset()
            self.assertEqual(settings.data, DEFAULTS)

    def test_newgame_animation_defaults_on_persists_and_requires_boolean(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "settings.json"
            settings = Settings(path)
            self.assertIs(settings.get("newgame_animation"), True)

            settings.set("newgame_animation", False)
            restored = Settings(path)
            self.assertIs(restored.get("newgame_animation"), False)

            with self.assertRaises(SettingsError):
                restored.set("newgame_animation", 1)
            with self.assertRaises(SettingsError):
                restored.set("newgame_animation", "false")

    def test_sound_variants_default_to_one_and_persist_per_event(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "settings.json"
            settings = Settings(path)
            self.assertEqual(settings.get("sound_move_variant"), "1")
            self.assertEqual(settings.get("sound_capture_variant"), "1")
            self.assertEqual(settings.get("sound_mate_variant"), "1")
            self.assertEqual(settings.get("sound_draw_variant"), "1")
            self.assertEqual(settings.get("sound_low_time_variant"), "1")
            self.assertEqual(settings.get("low_time_policy"), "my_turn")
            self.assertEqual(settings.get("low_time_seconds"), 30)

            settings.set("sound_move_variant", "4")
            settings.set("sound_capture_variant", "5")

            clone = Settings(path)
            self.assertEqual(clone.get("sound_move_variant"), "4")
            self.assertEqual(clone.get("sound_capture_variant"), "5")
            self.assertEqual(clone.get("sound_start_variant"), "1")

    def test_sound_variant_id_rejects_path_or_empty_values(self):
        with tempfile.TemporaryDirectory() as td:
            settings = Settings(Path(td) / "settings.json")
            for value in ("", "../2", "two/2", " 2", "2 "):
                with self.subTest(value=value):
                    with self.assertRaises(SettingsError):
                        settings.set("sound_move_variant", value)

    def test_unknown_key_is_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            settings = Settings(Path(td) / "settings.json")
            with self.assertRaises(KeyError):
                settings.set("future", True)


if __name__ == "__main__":
    unittest.main()
