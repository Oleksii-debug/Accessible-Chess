import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock

import acs.settings as settings_module
from acs.settings import DEFAULTS, SCHEMA_VERSION, Settings, SettingsError


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

    def test_save_rejects_symlink_upgrade_lock_without_touching_target(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            path = root / "settings.json"
            lock = root / ".v2-upgrade.lock"
            target = root / "foreign-lock-target.bin"
            target_bytes = b"foreign-lock-target"
            target.write_bytes(target_bytes)
            try:
                os.symlink(target, lock)
            except (OSError, NotImplementedError):
                self.skipTest("symlink creation is unavailable on this runner")

            settings = Settings(path)
            with self.assertRaises(SettingsError):
                settings.set("volume", 41)

            self.assertEqual(target_bytes, target.read_bytes())
            self.assertTrue(lock.is_symlink())
            self.assertFalse(path.exists())

    def test_save_rejects_lock_path_swap_after_open(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            path = root / "settings.json"
            lock = root / ".v2-upgrade.lock"
            lock.write_bytes(b"\0")
            foreign = root / "foreign-lock.bin"
            foreign_bytes = b"foreign-lock-path"
            foreign.write_bytes(foreign_bytes)
            real_open = settings_module.os.open
            injected = False

            def swap_after_open(candidate, flags, mode=0o777):
                nonlocal injected
                descriptor = real_open(candidate, flags, mode)
                if Path(candidate) == lock and not injected:
                    os.replace(foreign, lock)
                    injected = True
                return descriptor

            settings = Settings(path)
            with mock.patch.object(
                settings_module.os,
                "open",
                side_effect=swap_after_open,
            ):
                with self.assertRaisesRegex(
                    SettingsError,
                    "lock changed while held|lock changed while opening",
                ):
                    settings.set("volume", 42)

            self.assertTrue(injected)
            self.assertEqual(foreign_bytes, lock.read_bytes())
            self.assertFalse(path.exists())

    def test_save_rechecks_lock_identity_before_final_settings_replace(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            path = root / "settings.json"
            settings = Settings(path)
            original_assert = settings_module._SettingsSaveLock.assert_current
            checks = 0
            injected = False
            foreign_bytes = b"foreign-mid-save-lock"

            def racing_assert(lock_self):
                nonlocal checks, injected
                checks += 1
                if checks == 5 and not injected:
                    replacement = root / "replacement-lock.bin"
                    replacement.write_bytes(foreign_bytes)
                    os.replace(replacement, lock_self.path)
                    injected = True
                return original_assert(lock_self)

            with mock.patch.object(
                settings_module._SettingsSaveLock,
                "assert_current",
                autospec=True,
                side_effect=racing_assert,
            ):
                with self.assertRaisesRegex(
                    SettingsError,
                    "lock changed while held",
                ):
                    settings.set("volume", 43)

            self.assertTrue(injected)
            self.assertEqual(
                foreign_bytes,
                (root / ".v2-upgrade.lock").read_bytes(),
            )
            self.assertFalse(
                path.exists(),
                "Settings payload was published after lock continuity was lost",
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

    def test_unknown_key_is_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            settings = Settings(Path(td) / "settings.json")
            with self.assertRaises(KeyError):
                settings.set("future", True)


if __name__ == "__main__":
    unittest.main()
