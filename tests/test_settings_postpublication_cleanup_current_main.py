from __future__ import annotations

import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from acs.settings import Settings, SettingsError, _SettingsSaveLock


class SettingsPostPublicationCleanupCurrentMainTests(unittest.TestCase):
    def test_unlock_failure_after_publication_does_not_turn_save_into_failure(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "settings.json"
            settings = Settings(path)
            lock_target = "msvcrt.locking" if os.name == "nt" else "fcntl.flock"

            with mock.patch(
                lock_target,
                side_effect=[None, OSError("simulated post-publication unlock failure")],
            ):
                settings.set("language", "en")

            self.assertEqual("en", settings.get("language"))
            self.assertEqual("en", Settings(path).get("language"))

    def test_body_failure_still_propagates_when_unlock_also_fails(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            lock = _SettingsSaveLock(Path(td) / "settings.json")
            lock_target = "msvcrt.locking" if os.name == "nt" else "fcntl.flock"

            with mock.patch(
                lock_target,
                side_effect=[None, OSError("simulated cleanup failure")],
            ):
                with self.assertRaisesRegex(SettingsError, "protected body failed"):
                    with lock:
                        raise SettingsError("protected body failed")

    def test_close_failure_is_best_effort_and_detaches_internal_handle(self) -> None:
        lock = _SettingsSaveLock(Path("settings.json"))
        handle = mock.Mock()
        handle.fileno.return_value = 123
        handle.close.side_effect = OSError("simulated close failure")
        lock.handle = handle
        lock.identity = (1, 2)
        lock_target = "msvcrt.locking" if os.name == "nt" else "fcntl.flock"

        with mock.patch(lock_target, return_value=None):
            lock.__exit__(None, None, None)

        self.assertIsNone(lock.handle)
        self.assertIsNone(lock.identity)
        handle.close.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
