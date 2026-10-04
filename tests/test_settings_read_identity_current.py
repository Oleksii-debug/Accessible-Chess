from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock

import acs.settings as settings_module
from acs.settings import DEFAULTS, SCHEMA_VERSION, Settings, SettingsError


def _valid_payload(*, language: str = "en", volume: int = 17) -> str:
    return json.dumps(
        {
            "schema_version": SCHEMA_VERSION,
            "values": {"language": language, "volume": volume},
        }
    )


class SettingsReadIdentityCurrentTests(unittest.TestCase):
    def test_regular_private_settings_still_load(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "settings.json"
            path.write_text(_valid_payload(), encoding="utf-8")

            settings = Settings(path)

            self.assertEqual("en", settings.get("language"))
            self.assertEqual(17, settings.get("volume"))
            self.assertIsNone(settings.warning)

    def test_symlink_settings_is_not_consumed(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            victim = root / "victim.json"
            victim.write_text(_valid_payload(), encoding="utf-8")
            path = root / "settings.json"
            try:
                path.symlink_to(victim.name)
            except (OSError, NotImplementedError):
                self.skipTest("symlink creation is unavailable on this platform")

            settings = Settings(path)

            self.assertEqual(DEFAULTS, settings.data)
            self.assertIn("private regular file", settings.warning or "")
            self.assertEqual(_valid_payload(), victim.read_text(encoding="utf-8"))

    def test_hardlinked_settings_is_not_consumed(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            victim = root / "victim.json"
            victim.write_text(_valid_payload(), encoding="utf-8")
            path = root / "settings.json"
            try:
                os.link(victim, path)
            except (OSError, NotImplementedError):
                self.skipTest("hard-link creation is unavailable on this platform")

            settings = Settings(path)

            self.assertEqual(DEFAULTS, settings.data)
            self.assertIn("private regular file", settings.warning or "")

    def test_settings_inode_swap_between_lstat_and_open_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            path = root / "settings.json"
            replacement = root / "replacement.json"
            path.write_text(_valid_payload(volume=17), encoding="utf-8")
            replacement.write_text(_valid_payload(volume=18), encoding="utf-8")
            real_open = settings_module.os.open
            injected = False

            def swap_before_open(target, flags, *args):
                nonlocal injected
                if Path(target) == path and not injected:
                    os.replace(replacement, path)
                    injected = True
                return real_open(target, flags, *args)

            with mock.patch.object(
                settings_module.os,
                "open",
                side_effect=swap_before_open,
            ):
                settings = Settings(path)

            self.assertTrue(injected)
            self.assertEqual(DEFAULTS, settings.data)
            self.assertIn("changed while opening", settings.warning or "")

    def test_redirected_settings_directory_is_rejected_for_load_and_save(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            outside = root / "outside"
            outside.mkdir()
            outside_settings = outside / "settings.json"
            outside_settings.write_text(_valid_payload(), encoding="utf-8")
            redirected = root / "profile"
            try:
                redirected.symlink_to(outside.name, target_is_directory=True)
            except (OSError, NotImplementedError):
                self.skipTest("directory symlink creation is unavailable on this platform")

            settings = Settings(redirected / "settings.json")

            self.assertEqual(DEFAULTS, settings.data)
            self.assertIn("private directory", settings.warning or "")
            foreign_before = outside_settings.read_bytes()
            with self.assertRaises(SettingsError):
                settings.set("volume", 42)
            self.assertEqual(foreign_before, outside_settings.read_bytes())
            self.assertFalse((outside / ".v2-upgrade.lock").exists())

    def test_oversized_settings_is_rejected_before_json_parse(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "settings.json"
            path.write_bytes(b"{" + b"x" * (1024 * 1024) + b"}")

            settings = Settings(path)

            self.assertEqual(DEFAULTS, settings.data)
            self.assertIn("too large", settings.warning or "")


if __name__ == "__main__":
    unittest.main()
