from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock

import acs.settings as settings_module
from acs.settings import DEFAULTS, SCHEMA_VERSION, Settings, SettingsError


def _payload(*, language: str = "uk", volume: int = 80, schema: int = SCHEMA_VERSION) -> str:
    return json.dumps(
        {
            "schema_version": schema,
            "values": {"language": language, "volume": volume},
        },
        ensure_ascii=False,
        sort_keys=True,
    )


class SettingsStaleWriterCurrentTests(unittest.TestCase):
    def test_stale_instance_cannot_overwrite_newer_settings(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "settings.json"
            seed = Settings(path)
            seed.set("volume", 20)

            first = Settings(path)
            stale = Settings(path)

            first.set("volume", 31)
            with self.assertRaisesRegex(
                SettingsError,
                "changed since this Settings instance was loaded",
            ):
                stale.set("language", "en")

            # Failed stale publication reloads the actual durable winner.
            self.assertEqual(31, stale.get("volume"))
            self.assertEqual("uk", stale.get("language"))
            durable = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(31, durable["values"]["volume"])
            self.assertEqual("uk", durable["values"]["language"])

            # A deliberate retry now starts from the winner and preserves it.
            stale.set("language", "en")
            durable = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(31, durable["values"]["volume"])
            self.assertEqual("en", durable["values"]["language"])

    def test_future_schema_remains_read_only_and_exact_bytes_are_preserved(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "settings.json"
            original = (_payload(language="en", volume=73, schema=SCHEMA_VERSION + 5) + "\n").encode(
                "utf-8"
            )
            path.write_bytes(original)

            settings = Settings(path)
            self.assertEqual(DEFAULTS, settings.data)
            self.assertIn("newer than supported", settings.warning or "")

            with self.assertRaisesRegex(SettingsError, "newer schema is present"):
                settings.set("volume", 22)

            self.assertEqual(original, path.read_bytes())
            self.assertEqual(DEFAULTS, settings.data)
            self.assertIn("newer than supported", settings.warning or "")

    @unittest.skipIf(os.name == "nt", "rename injection is deterministic on POSIX")
    def test_ambiguous_load_race_blocks_first_write_until_clean_reload(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            path = root / "settings.json"
            replacement = root / "replacement.json"
            path.write_text(_payload(volume=17), encoding="utf-8")
            replacement.write_text(_payload(volume=18), encoding="utf-8")
            real_open = settings_module.os.open
            injected = False

            def swap_before_open(target, flags, *args):
                nonlocal injected
                candidate = Path(target)
                if candidate == path and not injected:
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
            replacement_bytes = path.read_bytes()

            with self.assertRaisesRegex(
                SettingsError,
                "canonical storage is loaded safely",
            ):
                settings.set("language", "en")

            # _persist_or_reload() performs a clean reread after the blocked write.
            self.assertEqual(replacement_bytes, path.read_bytes())
            self.assertEqual(18, settings.get("volume"))
            self.assertEqual("uk", settings.get("language"))

            settings.set("language", "en")
            durable = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(18, durable["values"]["volume"])
            self.assertEqual("en", durable["values"]["language"])


    def test_same_bytes_inode_substitution_blocks_stale_writer(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            path = root / "settings.json"
            replacement = root / "replacement.json"
            original = (_payload(language="uk", volume=17) + "\n").encode("utf-8")
            path.write_bytes(original)

            settings = Settings(path)
            replacement.write_bytes(original)
            os.replace(replacement, path)

            with self.assertRaisesRegex(
                SettingsError,
                "changed since this Settings instance was loaded",
            ):
                settings.set("volume", 19)

            # Failed stale publication reloads the exact replacement inode.
            self.assertEqual(original, path.read_bytes())
            self.assertEqual(17, settings.get("volume"))
            self.assertEqual("uk", settings.get("language"))


if __name__ == "__main__":
    unittest.main()
