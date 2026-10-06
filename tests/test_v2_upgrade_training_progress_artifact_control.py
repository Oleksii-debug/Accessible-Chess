from __future__ import annotations

import json
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


class V2UpgradeTrainingProgressArtifactControlTests(unittest.TestCase):
    def _relative_files(self, coordinator: Version2UpgradeCoordinator) -> set[str]:
        root = coordinator.layout.root
        return {
            path.relative_to(root).as_posix()
            for path in coordinator._files()
        }

    def test_runtime_artifacts_are_derived_but_durable_progress_is_preserved(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "AccessibleChess"
            root.mkdir()
            progress = root / "training-progress"
            progress.mkdir()
            digest = "a" * 64
            second_digest = "b" * 64

            durable = progress / f"{digest}.json"
            durable.write_bytes(b'{"durable":"training-progress"}\n')
            runtime_lock = progress / f".{digest.upper()}.JSON.LOCK"
            runtime_lock.write_bytes(b"training-lock")
            runtime_temp = progress / f".{digest}.json.abcd_123.tmp"
            runtime_temp.write_bytes(b"training-temp")

            near_misses = (
                progress / f".{digest[:-1]}.json.lock",
                progress / f".{digest}.json.custom.note.tmp",
                progress / f".{digest}.json.abcd.tmp.keep",
            )
            for candidate in near_misses:
                candidate.write_bytes(b"preserve-near-miss")

            nested = progress / "user-content"
            nested.mkdir()
            nested_lock = nested / f".{digest}.json.lock"
            nested_lock.write_bytes(b"nested-user-data")

            lock_named_directory = progress / f".{second_digest}.json.lock"
            lock_named_directory.mkdir()
            (lock_named_directory / "keep.bin").write_bytes(b"directory-user-data")

            coordinator = Version2UpgradeCoordinator(UserDataLayout(root))
            coordinator._ensure_roots()
            files = self._relative_files(coordinator)

            self.assertIn(f"training-progress/{digest}.json", files)
            self.assertNotIn(f"training-progress/.{digest.upper()}.JSON.LOCK", files)
            self.assertNotIn(f"training-progress/.{digest}.json.abcd_123.tmp", files)
            for candidate in near_misses:
                self.assertIn(candidate.relative_to(root).as_posix(), files)
            self.assertIn(
                f"training-progress/user-content/.{digest}.json.lock",
                files,
            )
            self.assertIn(
                f"training-progress/.{second_digest}.json.lock/keep.bin",
                files,
            )

            backup, manifest = coordinator._create_backup("training-progress-derived")
            paths = {str(item["path"]) for item in manifest["entries"]}
            self.assertIn(f"training-progress/{digest}.json", paths)
            self.assertNotIn(f"training-progress/.{digest.upper()}.JSON.LOCK", paths)
            self.assertNotIn(f"training-progress/.{digest}.json.abcd_123.tmp", paths)
            self.assertEqual(
                (backup / "data" / "training-progress" / f"{digest}.json").read_bytes(),
                b'{"durable":"training-progress"}\n',
            )
            self.assertEqual(
                (
                    backup
                    / "data"
                    / "training-progress"
                    / "user-content"
                    / f".{digest}.json.lock"
                ).read_bytes(),
                b"nested-user-data",
            )
            self.assertEqual(
                (
                    backup
                    / "data"
                    / "training-progress"
                    / f".{second_digest}.json.lock"
                    / "keep.bin"
                ).read_bytes(),
                b"directory-user-data",
            )

    def test_interrupted_recovery_never_replays_live_training_coordination(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "AccessibleChess"
            root.mkdir()
            (root / "settings.json").write_text(
                json.dumps({"language": "en", "volume": 34}),
                encoding="utf-8",
            )
            progress = root / "training-progress"
            progress.mkdir()
            digest = "a" * 64
            lock = progress / f".{digest}.json.lock"
            temporary = progress / f".{digest}.json.abcd_123.tmp"
            durable = progress / f"{digest}.json"
            lock.write_bytes(b"old-lock")
            temporary.write_bytes(b"old-temp")
            durable.write_bytes(b'{"generation":1}\n')

            def crash(phase: str) -> None:
                if phase == "settings-migrated":
                    raise _Crash()

            with self.assertRaises(_Crash):
                Version2UpgradeCoordinator(
                    UserDataLayout(root),
                    phase_hook=crash,
                ).run()

            lock.write_bytes(b"new-live-lock")
            temporary.write_bytes(b"new-live-temp")

            recovered = Version2UpgradeCoordinator(UserDataLayout(root)).run()

            self.assertTrue(recovered.recovered_interrupted_upgrade)
            self.assertEqual(lock.read_bytes(), b"new-live-lock")
            self.assertEqual(temporary.read_bytes(), b"new-live-temp")
            backup = (
                root.parent
                / "AccessibleChess.upgrade-backups"
                / recovered.backup_name
                / "data"
            )
            self.assertFalse(
                (backup / "training-progress" / f".{digest}.json.lock").exists()
            )
            self.assertFalse(
                (
                    backup
                    / "training-progress"
                    / f".{digest}.json.abcd_123.tmp"
                ).exists()
            )
            self.assertTrue(
                (backup / "training-progress" / f"{digest}.json").exists()
            )

    def test_legacy_backup_entries_are_accepted_without_replaying_training_artifacts(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "AccessibleChess"
            root.mkdir()
            (root / "settings.json").write_text(
                json.dumps({"language": "en", "volume": 34}),
                encoding="utf-8",
            )
            progress = root / "training-progress"
            progress.mkdir()
            digest = "a" * 64
            lock = progress / f".{digest}.json.lock"
            temporary = progress / f".{digest}.json.abcd_123.tmp"
            lock.write_bytes(b"legacy-lock")
            temporary.write_bytes(b"legacy-temp")

            def crash(phase: str) -> None:
                if phase == "settings-migrated":
                    raise _Crash()

            with (
                patch.object(
                    upgrade_base,
                    "_is_generated_training_progress_file",
                    lambda relative_path: False,
                ),
                self.assertRaises(_Crash),
            ):
                Version2UpgradeCoordinator(
                    UserDataLayout(root),
                    phase_hook=crash,
                ).run()

            journal = json.loads(
                (root / ".v2-upgrade-state.json").read_text(encoding="utf-8")
            )
            backup = (
                root.parent
                / "AccessibleChess.upgrade-backups"
                / str(journal["backup_name"])
                / "data"
                / "training-progress"
            )
            self.assertTrue((backup / f".{digest}.json.lock").exists())
            self.assertTrue((backup / f".{digest}.json.abcd_123.tmp").exists())

            lock.write_bytes(b"new-live-lock")
            temporary.write_bytes(b"new-live-temp")

            recovered = Version2UpgradeCoordinator(
                UserDataLayout(root)
            ).recover_interrupted()

            self.assertTrue(recovered)
            self.assertEqual(lock.read_bytes(), b"new-live-lock")
            self.assertEqual(temporary.read_bytes(), b"new-live-temp")

    def test_runtime_artifacts_do_not_consume_backup_quota(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "AccessibleChess"
            root.mkdir()
            progress = root / "training-progress"
            progress.mkdir()
            digest = "a" * 64
            (progress / f".{digest}.json.lock").write_bytes(b"l" * 4096)
            (progress / f".{digest}.json.abcd_123.tmp").write_bytes(b"t" * 4096)
            durable = progress / f"{digest}.json"
            durable.write_bytes(b"x")

            coordinator = Version2UpgradeCoordinator(
                UserDataLayout(root),
                limits=UpgradeLimits(max_files=1, max_bytes=8),
            )
            self.assertEqual(
                self._relative_files(coordinator),
                {f"training-progress/{digest}.json"},
            )

            durable.write_bytes(b"y" * 16)
            with self.assertRaisesRegex(
                Version2UpgradeError,
                "backup exceeds byte limit",
            ):
                coordinator._files()


if __name__ == "__main__":
    unittest.main()
