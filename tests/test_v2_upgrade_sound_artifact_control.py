from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import acs.version2_upgrade_base as upgrade_base

from acs.version2_upgrade_base import (
    UpgradeLimits,
    UserDataLayout,
    Version2UpgradeCoordinator,
    Version2UpgradeError,
)


class _Crash(BaseException):
    """Simulate abrupt process death so normal rollback cannot run."""


class V2UpgradeSoundArtifactControlTests(unittest.TestCase):
    def _relative_files(self, coordinator: Version2UpgradeCoordinator) -> set[str]:
        root = coordinator.layout.root
        return {
            path.relative_to(root).as_posix()
            for path in coordinator._files()
        }

    def test_sound_locks_are_control_state_but_durable_sound_data_is_preserved(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "AccessibleChess"
            root.mkdir()
            (root / "settings.json").write_text(
                json.dumps({"language": "en"}), encoding="utf-8"
            )
            (root / "sound-profile.json.lock").write_bytes(b"live-profile-lock")
            (root / "SOUND-PACKS.LOCK").write_bytes(b"live-pack-lock")
            (root / "sound-profile.json").write_bytes(b'{"profile":"quiet"}\n')
            pack = root / "sound-packs" / "classic" / "move.wav"
            pack.parent.mkdir(parents=True)
            pack.write_bytes(b"durable-pack-bytes")

            coordinator = Version2UpgradeCoordinator(UserDataLayout(root))
            coordinator._ensure_roots()
            files = self._relative_files(coordinator)

            self.assertNotIn("sound-profile.json.lock", files)
            self.assertNotIn("SOUND-PACKS.LOCK", files)
            self.assertIn("sound-profile.json", files)
            self.assertIn("sound-packs/classic/move.wav", files)

            backup, manifest = coordinator._create_backup("sound-lock-controls")
            paths = {str(item["path"]) for item in manifest["entries"]}
            self.assertNotIn("sound-profile.json.lock", paths)
            self.assertNotIn("SOUND-PACKS.LOCK", paths)
            self.assertIn("sound-profile.json", paths)
            self.assertIn("sound-packs/classic/move.wav", paths)
            self.assertFalse((backup / "data" / "sound-profile.json.lock").exists())
            self.assertFalse((backup / "data" / "SOUND-PACKS.LOCK").exists())
            self.assertEqual(
                (backup / "data" / "sound-profile.json").read_bytes(),
                b'{"profile":"quiet"}\n',
            )
            self.assertEqual(
                (backup / "data" / "sound-packs" / "classic" / "move.wav").read_bytes(),
                b"durable-pack-bytes",
            )

    def test_exact_root_sound_cache_subtree_is_derived_and_nested_names_are_preserved(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "AccessibleChess"
            root.mkdir()
            (root / "settings.json").write_text(
                json.dumps({"language": "en"}), encoding="utf-8"
            )

            cache = root / "SoUnD-CaChE"
            cache.mkdir()
            (cache / ".playback.lock").write_bytes(b"cache-lock")
            (cache / "scaled" / "move.wav").parent.mkdir()
            (cache / "scaled" / "move.wav").write_bytes(b"derived-wave")

            nested_cache = root / "user-content" / "sound-cache"
            nested_cache.mkdir(parents=True)
            (nested_cache / "keep.bin").write_bytes(b"keep-cache-name")
            nested_profile_lock = root / "user-content" / "sound-profile.json.lock"
            nested_profile_lock.write_bytes(b"keep-profile-lock-name")
            nested_pack_lock = root / "user-content" / "sound-packs.lock"
            nested_pack_lock.write_bytes(b"keep-pack-lock-name")

            coordinator = Version2UpgradeCoordinator(UserDataLayout(root))
            coordinator._ensure_roots()
            files = self._relative_files(coordinator)

            self.assertFalse(any(name.casefold().startswith("sound-cache/") for name in files))
            self.assertIn("user-content/sound-cache/keep.bin", files)
            self.assertIn("user-content/sound-profile.json.lock", files)
            self.assertIn("user-content/sound-packs.lock", files)

            backup, manifest = coordinator._create_backup("sound-cache-derived")
            paths = {str(item["path"]) for item in manifest["entries"]}
            self.assertFalse(
                any(name.casefold().startswith("sound-cache/") for name in paths)
            )
            self.assertIn("user-content/sound-cache/keep.bin", paths)
            self.assertEqual(
                (backup / "data" / "user-content" / "sound-cache" / "keep.bin").read_bytes(),
                b"keep-cache-name",
            )

    def test_root_lock_named_directories_remain_user_data(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "AccessibleChess"
            root.mkdir()
            for name, payload in (
                ("sound-profile.json.lock", b"profile-directory-data"),
                ("sound-packs.lock", b"packs-directory-data"),
            ):
                directory = root / name
                directory.mkdir()
                (directory / "keep.bin").write_bytes(payload)

            coordinator = Version2UpgradeCoordinator(UserDataLayout(root))
            coordinator._ensure_roots()
            files = self._relative_files(coordinator)

            self.assertIn("sound-profile.json.lock/keep.bin", files)
            self.assertIn("sound-packs.lock/keep.bin", files)
            backup, manifest = coordinator._create_backup("sound-lock-directories")
            paths = {str(item["path"]) for item in manifest["entries"]}
            self.assertIn("sound-profile.json.lock/keep.bin", paths)
            self.assertIn("sound-packs.lock/keep.bin", paths)
            self.assertEqual(
                (backup / "data" / "sound-profile.json.lock" / "keep.bin").read_bytes(),
                b"profile-directory-data",
            )
            self.assertEqual(
                (backup / "data" / "sound-packs.lock" / "keep.bin").read_bytes(),
                b"packs-directory-data",
            )

    @unittest.skipIf(os.name == "nt", "POSIX symlink safety regression")
    def test_root_sound_cache_symlink_still_fails_closed(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "AccessibleChess"
            root.mkdir()
            outside = Path(td) / "outside"
            outside.mkdir()
            (outside / "do-not-read.wav").write_bytes(b"outside")
            os.symlink(outside, root / "sound-cache", target_is_directory=True)

            coordinator = Version2UpgradeCoordinator(UserDataLayout(root))
            with self.assertRaisesRegex(
                Version2UpgradeError,
                "symlink or reparse point",
            ):
                coordinator._files()

    def test_root_regular_file_named_sound_cache_remains_user_data(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "AccessibleChess"
            root.mkdir()
            payload = root / "sound-cache"
            payload.write_bytes(b"user-owned-regular-file")

            coordinator = Version2UpgradeCoordinator(UserDataLayout(root))
            coordinator._ensure_roots()
            self.assertIn("sound-cache", self._relative_files(coordinator))

            backup, manifest = coordinator._create_backup("sound-cache-file")
            self.assertIn(
                "sound-cache",
                {str(item["path"]) for item in manifest["entries"]},
            )
            self.assertEqual(
                (backup / "data" / "sound-cache").read_bytes(),
                b"user-owned-regular-file",
            )

    def test_interrupted_recovery_never_replays_sound_locks_or_cache(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "AccessibleChess"
            root.mkdir()
            (root / "settings.json").write_text(
                json.dumps({"language": "en", "volume": 34}), encoding="utf-8"
            )
            profile_lock = root / "sound-profile.json.lock"
            packs_lock = root / "sound-packs.lock"
            cache_file = root / "sound-cache" / "scaled" / "move.wav"
            profile_lock.write_bytes(b"old-profile-lock")
            packs_lock.write_bytes(b"old-packs-lock")
            cache_file.parent.mkdir(parents=True)
            cache_file.write_bytes(b"old-cache")

            def crash(phase: str) -> None:
                if phase == "settings-migrated":
                    raise _Crash()

            with self.assertRaises(_Crash):
                Version2UpgradeCoordinator(
                    UserDataLayout(root), phase_hook=crash
                ).run()

            profile_lock.write_bytes(b"new-live-profile-lock")
            packs_lock.write_bytes(b"new-live-packs-lock")
            cache_file.write_bytes(b"new-live-cache")

            recovered = Version2UpgradeCoordinator(UserDataLayout(root)).run()

            self.assertTrue(recovered.recovered_interrupted_upgrade)
            self.assertEqual(profile_lock.read_bytes(), b"new-live-profile-lock")
            self.assertEqual(packs_lock.read_bytes(), b"new-live-packs-lock")
            self.assertEqual(cache_file.read_bytes(), b"new-live-cache")

            backup = (
                root.parent
                / "AccessibleChess.upgrade-backups"
                / recovered.backup_name
                / "data"
            )
            self.assertFalse((backup / "sound-profile.json.lock").exists())
            self.assertFalse((backup / "sound-packs.lock").exists())
            self.assertFalse((backup / "sound-cache").exists())

    def test_recovery_accepts_legacy_backup_entries_without_replaying_sound_artifacts(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "AccessibleChess"
            root.mkdir()
            (root / "settings.json").write_text(
                json.dumps({"language": "en", "volume": 34}), encoding="utf-8"
            )
            profile_lock = root / "sound-profile.json.lock"
            packs_lock = root / "sound-packs.lock"
            cache_lock = root / "sound-cache" / ".playback.lock"
            cache_file = root / "sound-cache" / "scaled" / "move.wav"
            profile_lock.write_bytes(b"legacy-profile-lock")
            packs_lock.write_bytes(b"legacy-packs-lock")
            cache_file.parent.mkdir(parents=True)
            cache_lock.write_bytes(b"legacy-cache-lock")
            cache_file.write_bytes(b"legacy-cache")

            old_control_keys = frozenset(
                name.casefold()
                for name in {
                    ".v2-upgrade.lock",
                    ".v2-upgrade-state.json",
                    "profile.json.lock",
                }
            )

            def crash(phase: str) -> None:
                if phase == "settings-migrated":
                    raise _Crash()

            # Simulate the immediately preceding upgrader: sound artifacts were
            # still ordinary preservation entries when its snapshot was made.
            with (
                patch.object(upgrade_base, "_CONTROL_NAME_KEYS", old_control_keys),
                patch.object(
                    upgrade_base,
                    "_DERIVED_ROOT_DIRECTORY_KEYS",
                    frozenset(),
                ),
                self.assertRaises(_Crash),
            ):
                Version2UpgradeCoordinator(
                    UserDataLayout(root), phase_hook=crash
                ).run()

            journal = json.loads(
                (root / ".v2-upgrade-state.json").read_text(encoding="utf-8")
            )
            backup_data = (
                root.parent
                / "AccessibleChess.upgrade-backups"
                / str(journal["backup_name"])
                / "data"
            )
            self.assertTrue((backup_data / "sound-profile.json.lock").exists())
            self.assertTrue((backup_data / "sound-packs.lock").exists())
            self.assertTrue((backup_data / "sound-cache" / ".playback.lock").exists())
            self.assertTrue((backup_data / "sound-cache" / "scaled" / "move.wav").exists())

            profile_lock.write_bytes(b"new-profile-lock")
            packs_lock.write_bytes(b"new-packs-lock")
            cache_lock.write_bytes(b"new-cache-lock")
            cache_file.write_bytes(b"new-cache")

            recovered = Version2UpgradeCoordinator(
                UserDataLayout(root)
            ).recover_interrupted()

            self.assertTrue(recovered)
            self.assertEqual(profile_lock.read_bytes(), b"new-profile-lock")
            self.assertEqual(packs_lock.read_bytes(), b"new-packs-lock")
            self.assertEqual(cache_lock.read_bytes(), b"new-cache-lock")
            self.assertEqual(cache_file.read_bytes(), b"new-cache")

    def test_disposable_cache_does_not_consume_backup_quota_but_pack_content_does(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "AccessibleChess"
            root.mkdir()
            cache = root / "sound-cache"
            cache.mkdir()
            (cache / "huge.wav").write_bytes(b"x" * 4096)
            durable_profile = root / "sound-profile.json"
            durable_profile.write_bytes(b"x")

            coordinator = Version2UpgradeCoordinator(
                UserDataLayout(root),
                limits=UpgradeLimits(max_files=2, max_bytes=8),
            )
            self.assertEqual(
                self._relative_files(coordinator),
                {"sound-profile.json"},
            )

            durable_pack = root / "sound-packs" / "custom" / "move.wav"
            durable_pack.parent.mkdir(parents=True)
            durable_pack.write_bytes(b"y" * 16)
            with self.assertRaisesRegex(
                Version2UpgradeError,
                "backup exceeds byte limit",
            ):
                coordinator._files()


if __name__ == "__main__":
    unittest.main()
