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
    _UpgradeLock,
    Version2UpgradeError,
)


class _Crash(BaseException):
    """Simulate abrupt process death so normal rollback cannot run."""


class V2UpgradeSelfCoordinationArtifactControlTests(unittest.TestCase):
    def _relative_files(self, coordinator: Version2UpgradeCoordinator) -> set[str]:
        root = coordinator.layout.root
        return {
            path.relative_to(root).as_posix()
            for path in coordinator._files()
        }

    def test_upgrade_lock_rejects_hardlink_without_mutating_target(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "AccessibleChess"
            root.mkdir()
            target = root / "user-owned.bin"
            target.write_bytes(b"")
            lock = root / ".v2-upgrade.lock"
            try:
                os.link(target, lock)
            except (OSError, NotImplementedError):
                self.skipTest("hard-link creation is unavailable on this runner")

            with self.assertRaisesRegex(
                Version2UpgradeError,
                "private regular file",
            ):
                with _UpgradeLock(lock):
                    pass

            self.assertEqual(target.read_bytes(), b"")
            self.assertEqual(os.lstat(target).st_nlink, 2)

    def test_upgrade_lock_path_swap_to_symlink_fails_before_target_write(self):
        if not hasattr(os, "symlink"):
            self.skipTest("symlink support is unavailable")
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "AccessibleChess"
            root.mkdir()
            lock = root / ".v2-upgrade.lock"
            lock.write_bytes(b"")
            target = root / "user-owned.bin"
            target.write_bytes(b"do-not-touch")
            original_open = upgrade_base.os.open
            swapped = False

            def swap_before_open(path, flags, mode=0o777):
                nonlocal swapped
                if Path(path) == lock and not swapped:
                    swapped = True
                    lock.unlink()
                    try:
                        os.symlink(target, lock)
                    except (OSError, NotImplementedError):
                        self.skipTest(
                            "symlink creation is unavailable on this runner"
                        )
                return original_open(path, flags, mode)

            with patch.object(
                upgrade_base.os,
                "open",
                side_effect=swap_before_open,
            ):
                with self.assertRaisesRegex(
                    Version2UpgradeError,
                    "opened safely|changed while opening",
                ):
                    with _UpgradeLock(lock):
                        pass

            self.assertTrue(swapped)
            self.assertEqual(target.read_bytes(), b"do-not-touch")

    def test_exact_root_settings_and_upgrade_residue_is_derived(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "AccessibleChess"
            root.mkdir()
            (root / "settings.json").write_text(
                json.dumps({"language": "en"}),
                encoding="utf-8",
            )

            derived = (
                root / "settings.json.tmp",
                root / ".settings.json.abcd_123.tmp",
                root / "..v2-upgrade-state.json.xy_987ab.tmp",
            )
            for path in derived:
                path.write_bytes(b"derived-runtime-state")
            settings_guard = root / ".settings.json.publish-guard-a1b2c3d4e5f6"
            try:
                os.link(root / "settings.json", settings_guard)
            except (OSError, NotImplementedError):
                self.skipTest("hard-link creation is unavailable on this runner")
            # Filename grammar alone is not ownership proof. Without a current
            # Library target, this exact-looking guard is preservation-backed.
            library_guard = root / ".library.acsdb.publish-guard-012345abcdef"
            library_guard.write_bytes(b"private-library-guard-lookalike")

            near_misses = (
                root / ".settings.json.publish-guard-a1b2c3d4e5f",
                root / ".settings.json.publish-guard-a1b2c3d4e5fg",
                root / ".library.acsdb.publish-guard-012345abcdef0",
                root / ".settings.json.bad.token.tmp",
                root / "..v2-upgrade-state.json.bad-token!.tmp",
                root / "settings.json.tmp.keep",
            )
            for path in near_misses:
                path.write_bytes(b"user-data")

            nested = root / "user-content"
            nested.mkdir()
            (nested / "settings.json.tmp").write_bytes(b"nested-settings-temp-name")
            (
                nested / ".settings.json.publish-guard-a1b2c3d4e5f6"
            ).write_bytes(b"nested-guard-name")

            directory_named_temp = root / "settings.json.tmp"
            directory_named_temp.unlink()
            directory_named_temp.mkdir()
            (directory_named_temp / "keep.bin").write_bytes(b"directory-user-data")

            coordinator = Version2UpgradeCoordinator(UserDataLayout(root))
            coordinator._ensure_roots()
            files = self._relative_files(coordinator)

            self.assertIn("settings.json", files)
            self.assertNotIn("settings.json.tmp", files)
            self.assertNotIn(".settings.json.abcd_123.tmp", files)
            self.assertNotIn("..v2-upgrade-state.json.xy_987ab.tmp", files)
            self.assertNotIn(
                ".settings.json.publish-guard-a1b2c3d4e5f6",
                files,
            )
            self.assertIn(
                ".library.acsdb.publish-guard-012345abcdef",
                files,
            )
            for path in near_misses:
                self.assertIn(path.relative_to(root).as_posix(), files)
            self.assertIn("user-content/settings.json.tmp", files)
            self.assertIn(
                "user-content/.settings.json.publish-guard-a1b2c3d4e5f6",
                files,
            )
            self.assertIn("settings.json.tmp/keep.bin", files)

            backup, manifest = coordinator._create_backup("self-coordination-derived")
            paths = {str(item["path"]) for item in manifest["entries"]}
            self.assertIn("settings.json", paths)
            self.assertNotIn(".settings.json.abcd_123.tmp", paths)
            self.assertNotIn("..v2-upgrade-state.json.xy_987ab.tmp", paths)
            self.assertNotIn(
                ".settings.json.publish-guard-a1b2c3d4e5f6",
                paths,
            )
            self.assertIn(
                ".library.acsdb.publish-guard-012345abcdef",
                paths,
            )
            self.assertEqual(
                (
                    backup
                    / "data"
                    / ".library.acsdb.publish-guard-012345abcdef"
                ).read_bytes(),
                b"private-library-guard-lookalike",
            )
            self.assertIn("settings.json.tmp/keep.bin", paths)
            self.assertEqual(
                (
                    backup
                    / "data"
                    / "settings.json.tmp"
                    / "keep.bin"
                ).read_bytes(),
                b"directory-user-data",
            )

    def test_custom_layout_names_drive_owned_residue_classification(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "AccessibleChess"
            root.mkdir()
            layout = UserDataLayout(
                root,
                settings_name="prefs.json",
                library_name="games.sqlite",
            )
            (root / "prefs.json").write_bytes(b"{}")
            (root / "prefs.json.tmp").write_bytes(b"settings-writer-temp")
            (root / ".prefs.json.a1_b2c3d.tmp").write_bytes(b"upgrade-temp")
            settings_guard = root / ".prefs.json.publish-guard-abcdef012345"
            library = root / "games.sqlite"
            library.write_bytes(b"current-library")
            library_guard = root / ".games.sqlite.publish-guard-fedcba543210"
            try:
                os.link(root / "prefs.json", settings_guard)
                os.link(library, library_guard)
            except (OSError, NotImplementedError):
                self.skipTest("hard-link creation is unavailable on this runner")
            canonical_name_lookalike = root / "settings.json.tmp"
            canonical_name_lookalike.write_bytes(b"custom-layout-user-data")

            coordinator = Version2UpgradeCoordinator(layout)
            coordinator._ensure_roots()
            files = self._relative_files(coordinator)

            self.assertIn("prefs.json", files)
            self.assertNotIn("prefs.json.tmp", files)
            self.assertNotIn(".prefs.json.a1_b2c3d.tmp", files)
            self.assertNotIn(
                ".prefs.json.publish-guard-abcdef012345",
                files,
            )
            self.assertNotIn(
                ".games.sqlite.publish-guard-fedcba543210",
                files,
            )
            self.assertIn("settings.json.tmp", files)

    def test_legacy_backup_residue_is_not_replayed_over_new_live_bytes(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "AccessibleChess"
            root.mkdir()
            (root / "settings.json").write_text(
                json.dumps({"language": "en", "volume": 34}),
                encoding="utf-8",
            )
            fixed_temp = root / "settings.json.tmp"
            atomic_temp = root / ".settings.json.abcd_123.tmp"
            journal_temp = root / "..v2-upgrade-state.json.xy_987ab.tmp"
            settings_guard = root / ".settings.json.publish-guard-a1b2c3d4e5f6"
            library_guard = root / ".library.acsdb.publish-guard-012345abcdef"
            artifacts = (
                fixed_temp,
                atomic_temp,
                journal_temp,
                settings_guard,
                library_guard,
            )
            for path in artifacts:
                path.write_bytes(b"legacy-residue")

            def crash(phase: str) -> None:
                if phase == "settings-migrated":
                    raise _Crash()

            with (
                patch.object(
                    upgrade_base,
                    "_is_upgrade_generated_root_runtime_file",
                    lambda relative_path, **kwargs: False,
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
            backup_data = (
                root.parent
                / "AccessibleChess.upgrade-backups"
                / str(journal["backup_name"])
                / "data"
            )
            for path in artifacts:
                self.assertTrue(
                    (
                        backup_data
                        / path.relative_to(root)
                    ).exists()
                )

            for index, path in enumerate(artifacts):
                path.write_bytes(f"new-live-{index}".encode("ascii"))

            recovered = Version2UpgradeCoordinator(
                UserDataLayout(root)
            ).recover_interrupted()

            self.assertTrue(recovered)
            for index, path in enumerate(artifacts):
                self.assertEqual(
                    path.read_bytes(),
                    f"new-live-{index}".encode("ascii"),
                )

    def test_runtime_residue_does_not_consume_backup_quota(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "AccessibleChess"
            root.mkdir()
            durable = root / "settings.json"
            durable.write_bytes(b"x")
            for name in (
                "settings.json.tmp",
                ".settings.json.abcd_123.tmp",
                "..v2-upgrade-state.json.xy_987ab.tmp",
            ):
                (root / name).write_bytes(b"z" * 4096)
            try:
                os.link(
                    durable,
                    root / ".settings.json.publish-guard-a1b2c3d4e5f6",
                )
            except (OSError, NotImplementedError):
                self.skipTest("hard-link creation is unavailable on this runner")

            coordinator = Version2UpgradeCoordinator(
                UserDataLayout(root),
                limits=UpgradeLimits(max_files=1, max_bytes=8),
            )
            self.assertEqual(
                self._relative_files(coordinator),
                {"settings.json"},
            )

            durable.write_bytes(b"y" * 16)
            with self.assertRaisesRegex(
                Version2UpgradeError,
                "backup exceeds byte limit",
            ):
                coordinator._files()

    def test_noncanonical_publication_guards_remain_preservation_backed(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "AccessibleChess"
            root.mkdir()
            candidates = (
                ".settings.json.publish-guard-abcdef01234",
                ".settings.json.publish-guard-abcdef0123456",
                ".settings.json.publish-guard-abcdef01234g",
                ".library.acsdb.publish-guard-ABCDEF01234G",
                ".library.acsdb.publish-guard-012345abcdef.keep",
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
