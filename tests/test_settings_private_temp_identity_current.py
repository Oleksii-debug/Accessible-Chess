from __future__ import annotations

import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock

import acs.settings as settings_module
from acs.settings import Settings, SettingsError


class SettingsPrivateTempIdentityCurrentTests(unittest.TestCase):
    def test_save_rejects_hardlinked_private_temp_without_deleting_peer(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            path = root / "settings.json"
            real_mkstemp = settings_module.tempfile.mkstemp
            temp_path: Path | None = None
            peer = root / "settings-temp-peer.bin"

            def hardlinking_mkstemp(*args, **kwargs):
                nonlocal temp_path
                descriptor, raw = real_mkstemp(*args, **kwargs)
                temp_path = Path(raw)
                try:
                    os.link(temp_path, peer)
                except (OSError, NotImplementedError):
                    os.close(descriptor)
                    self.skipTest("hard links are unavailable on this runner")
                return descriptor, raw

            settings = Settings(path)
            with mock.patch.object(
                settings_module.tempfile,
                "mkstemp",
                side_effect=hardlinking_mkstemp,
            ):
                with self.assertRaisesRegex(
                    SettingsError,
                    "temporary file must be one private regular file",
                ):
                    settings.set("volume", 44)

            self.assertIsNotNone(temp_path)
            assert temp_path is not None
            self.assertTrue(temp_path.exists())
            self.assertTrue(peer.exists())
            self.assertTrue(os.path.samefile(temp_path, peer))
            self.assertFalse(path.exists())

    def test_save_rejects_temp_inode_substitution_before_publication(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            path = root / "settings.json"
            real_mkstemp = settings_module.tempfile.mkstemp
            real_lstat = settings_module.os.lstat
            temp_path: Path | None = None
            injected = False
            foreign_bytes = b"foreign-settings-temp"

            def tracking_mkstemp(*args, **kwargs):
                nonlocal temp_path
                descriptor, raw = real_mkstemp(*args, **kwargs)
                temp_path = Path(raw)
                return descriptor, raw

            def substituting_lstat(candidate, *args, **kwargs):
                nonlocal injected
                candidate_path = Path(candidate)
                if (
                    temp_path is not None
                    and candidate_path == temp_path
                    and not injected
                ):
                    foreign = root / "foreign-settings-temp.bin"
                    foreign.write_bytes(foreign_bytes)
                    os.replace(foreign, temp_path)
                    injected = True
                return real_lstat(candidate, *args, **kwargs)

            settings = Settings(path)
            with mock.patch.object(
                settings_module.tempfile,
                "mkstemp",
                side_effect=tracking_mkstemp,
            ), mock.patch.object(
                settings_module.os,
                "lstat",
                side_effect=substituting_lstat,
            ):
                with self.assertRaisesRegex(
                    SettingsError,
                    "temporary file changed before publication",
                ):
                    settings.set("volume", 45)

            self.assertTrue(injected)
            self.assertIsNotNone(temp_path)
            assert temp_path is not None
            self.assertEqual(foreign_bytes, temp_path.read_bytes())
            self.assertFalse(path.exists())


if __name__ == "__main__":
    unittest.main()
