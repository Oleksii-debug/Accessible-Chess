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
    Version2UpgradeBusy,
    Version2UpgradeCoordinator,
    Version2UpgradeError,
)


class _Crash(BaseException):
    """Simulate abrupt process death so normal rollback cannot run."""


class V2UpgradeEducationWorkspaceArtifactControlTests(unittest.TestCase):
    def _relative_files(self, coordinator: Version2UpgradeCoordinator) -> set[str]:
        root = coordinator.layout.root
        return {
            path.relative_to(root).as_posix()
            for path in coordinator._files()
        }

    def test_runtime_temp_is_derived_but_durable_workspace_is_preserved(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "AccessibleChess"
            root.mkdir()
            durable = root / "education-workspace.json"
            durable.write_bytes(b'{"durable":"education"}\n')
            runtime_temp = root / ".EDUCATION-WORKSPACE.JSON.abcd_123.TMP"
            runtime_temp.write_bytes(b"workspace-temp")

            near_misses = (
                root / ".education-workspace.json.bad.token.tmp",
                root / ".education-workspace.json.abcd.tmp.keep",
                root / "education-workspace.json.abcd_123.tmp",
            )
            for path in near_misses:
                path.write_bytes(b"user-data")

            nested = root / "user-content"
            nested.mkdir()
            (
                nested / ".education-workspace.json.abcd_123.tmp"
            ).write_bytes(b"nested-user-data")

            temp_named_directory = root / ".education-workspace.json.zz_123.tmp"
            temp_named_directory.mkdir()
            (temp_named_directory / "keep.bin").write_bytes(b"directory-user-data")

            coordinator = Version2UpgradeCoordinator(UserDataLayout(root))
            coordinator._ensure_roots()
            files = self._relative_files(coordinator)

            self.assertIn("education-workspace.json", files)
            self.assertNotIn(".EDUCATION-WORKSPACE.JSON.abcd_123.TMP", files)
            for path in near_misses:
                self.assertIn(path.relative_to(root).as_posix(), files)
            self.assertIn(
                "user-content/.education-workspace.json.abcd_123.tmp",
                files,
            )
            self.assertIn(
                ".education-workspace.json.zz_123.tmp/keep.bin",
                files,
            )

            backup, manifest = coordinator._create_backup("education-temp-derived")
            paths = {str(item["path"]) for item in manifest["entries"]}
            self.assertIn("education-workspace.json", paths)
            self.assertNotIn(".EDUCATION-WORKSPACE.JSON.abcd_123.TMP", paths)
            self.assertIn(
                ".education-workspace.json.zz_123.tmp/keep.bin",
                paths,
            )
            self.assertEqual(
                (backup / "data" / "education-workspace.json").read_bytes(),
                b'{"durable":"education"}\n',
            )

    def test_active_workspace_lock_directory_blocks_upgrade_scan(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "AccessibleChess"
            root.mkdir()
            lock = root / ".education-workspace.json.lock"
            lock.mkdir()
            durable = root / "education-workspace.json"
            durable.write_bytes(b'{"durable":"education"}\n')

            coordinator = Version2UpgradeCoordinator(UserDataLayout(root))
            with self.assertRaisesRegex(
                Version2UpgradeBusy,
                "education workspace store is busy during upgrade",
            ):
                coordinator._files()

            self.assertTrue(lock.is_dir())
            self.assertEqual(
                durable.read_bytes(),
                b'{"durable":"education"}\n',
            )

    def test_regular_workspace_lock_lookalike_remains_preservation_backed(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "AccessibleChess"
            root.mkdir()
            lookalike = root / ".education-workspace.json.lock"
            lookalike.write_bytes(b"user-owned-regular-file")

            coordinator = Version2UpgradeCoordinator(UserDataLayout(root))
            coordinator._ensure_roots()
            files = self._relative_files(coordinator)
            self.assertIn(".education-workspace.json.lock", files)

            backup, manifest = coordinator._create_backup(
                "education-lock-regular-lookalike"
            )
            paths = {str(item["path"]) for item in manifest["entries"]}
            self.assertIn(".education-workspace.json.lock", paths)
            self.assertEqual(
                (
                    backup
                    / "data"
                    / ".education-workspace.json.lock"
                ).read_bytes(),
                b"user-owned-regular-file",
            )

    def test_exact_control_symlink_fails_closed(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "AccessibleChess"
            root.mkdir()
            target = root / "user-owned.bin"
            target.write_bytes(b"user-data")
            alias = root / ".education-workspace.json.lock"
            try:
                alias.symlink_to(target)
            except (OSError, NotImplementedError):
                self.skipTest("symlink creation is unavailable on this runner")

            with self.assertRaisesRegex(
                Version2UpgradeError,
                "symlink or reparse point",
            ):
                Version2UpgradeCoordinator(UserDataLayout(root))._files()

    def test_legacy_backup_temp_is_not_replayed_over_new_live_bytes(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "AccessibleChess"
            root.mkdir()
            (root / "settings.json").write_text(
                json.dumps({"language": "en", "volume": 34}),
                encoding="utf-8",
            )
            temporary = root / ".education-workspace.json.abcd_123.tmp"
            temporary.write_bytes(b"legacy-workspace-temp")

            def crash(phase: str) -> None:
                if phase == "settings-migrated":
                    raise _Crash()

            with (
                patch.object(
                    upgrade_base,
                    "_is_generated_education_workspace_file",
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
            )
            self.assertTrue(
                (backup / ".education-workspace.json.abcd_123.tmp").exists()
            )

            temporary.write_bytes(b"new-live-workspace-temp")

            recovered = Version2UpgradeCoordinator(
                UserDataLayout(root)
            ).recover_interrupted()

            self.assertTrue(recovered)
            self.assertEqual(
                temporary.read_bytes(),
                b"new-live-workspace-temp",
            )

    def test_runtime_temp_does_not_consume_backup_quota(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "AccessibleChess"
            root.mkdir()
            durable = root / "education-workspace.json"
            durable.write_bytes(b"x")
            (
                root / ".education-workspace.json.abcd_123.tmp"
            ).write_bytes(b"z" * 4096)

            coordinator = Version2UpgradeCoordinator(
                UserDataLayout(root),
                limits=UpgradeLimits(max_files=1, max_bytes=8),
            )
            self.assertEqual(
                self._relative_files(coordinator),
                {"education-workspace.json"},
            )

            durable.write_bytes(b"y" * 16)
            with self.assertRaisesRegex(
                Version2UpgradeError,
                "backup exceeds byte limit",
            ):
                coordinator._files()

    def test_noncanonical_workspace_temp_names_remain_preservation_backed(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "AccessibleChess"
            root.mkdir()
            candidates = (
                ".education-workspace.json..tmp",
                ".education-workspace.json.bad-token!.tmp",
                ".education-workspace.json.a.b.tmp",
                ".education-workspace.json.abcd_123.tmp.keep",
                ".education-workspace-json.abcd_123.tmp",
            )
            for name in candidates:
                (root / name).write_bytes(b"user-data")

            coordinator = Version2UpgradeCoordinator(UserDataLayout(root))
            coordinator._ensure_roots()
            files = self._relative_files(coordinator)

            for name in candidates:
                self.assertIn(name, files)


if __name__ == "__main__":
    unittest.main()
