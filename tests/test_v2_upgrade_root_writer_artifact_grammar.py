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


class V2UpgradeRootWriterArtifactGrammarTests(unittest.TestCase):
    def _relative_files(self, coordinator: Version2UpgradeCoordinator) -> set[str]:
        root = coordinator.layout.root
        return {
            path.relative_to(root).as_posix()
            for path in coordinator._files()
        }

    def test_exact_generated_shapes_are_derived_but_near_misses_are_preserved(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "AccessibleChess"
            root.mkdir()

            generated = (
                "gametree-resume.json.abcd_123.tmp",
                "gametree-resume.json.cas-xy_98765.bak",
                ".book-progress.json.abcd_123.tmp",
                ".book-progress.json.bak.xy_98765.tmp",
            )
            for name in generated:
                (root / name).write_bytes(b"generated-runtime-residue")

            near_misses = (
                "gametree-resume.json.bad.token.tmp",
                "gametree-resume.json.cas-bad.token.bak",
                "gametree-resume.json..tmp",
                "gametree-resume.json.cas-.bak",
                "gametree-resume.json.bad-token!.tmp",
                "gametree-resume.json.abc1234.tmp",
                "gametree-resume.json.abc123456.tmp",
                "gametree-resume.json.cas-abc1234.bak",
                "gametree-resume.json.cas-abc123456.bak",
                ".book-progress.json.bad.token.tmp",
                ".book-progress.json.bak.bad.token.tmp",
                ".book-progress.json..tmp",
                ".book-progress.json.bak..tmp",
                ".book-progress.json.bad-token!.tmp",
                ".book-progress.json.abc1234.tmp",
                ".book-progress.json.abc123456.tmp",
                ".book-progress.json.bak.abc1234.tmp",
                ".book-progress.json.bak.abc123456.tmp",
            )
            for name in near_misses:
                (root / name).write_bytes(b"user-data")

            nested = root / "user-content"
            nested.mkdir()
            for name in generated:
                (nested / name).write_bytes(b"nested-user-data")

            directory = root / "gametree-resume.json.dir_token.tmp"
            directory.mkdir()
            (directory / "keep.bin").write_bytes(b"directory-user-data")

            coordinator = Version2UpgradeCoordinator(UserDataLayout(root))
            coordinator._ensure_roots()
            files = self._relative_files(coordinator)

            for name in generated:
                self.assertNotIn(name, files)
                self.assertIn(f"user-content/{name}", files)
            for name in near_misses:
                self.assertIn(name, files)
            self.assertIn(
                "gametree-resume.json.dir_token.tmp/keep.bin",
                files,
            )

            backup, manifest = coordinator._create_backup("root-writer-token-grammar")
            paths = {str(item["path"]) for item in manifest["entries"]}
            for name in generated:
                self.assertNotIn(name, paths)
                self.assertIn(f"user-content/{name}", paths)
                self.assertEqual(
                    (backup / "data" / "user-content" / name).read_bytes(),
                    b"nested-user-data",
                )
            for name in near_misses:
                self.assertIn(name, paths)
                self.assertEqual(
                    (backup / "data" / name).read_bytes(),
                    b"user-data",
                )
            self.assertEqual(
                (
                    backup
                    / "data"
                    / "gametree-resume.json.dir_token.tmp"
                    / "keep.bin"
                ).read_bytes(),
                b"directory-user-data",
            )

    @unittest.skipIf(
        os.name == "nt",
        "Windows symlink creation requires environment-specific privileges",
    )
    def test_exact_generated_name_symlink_fails_closed_before_classification(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "AccessibleChess"
            root.mkdir()
            target = Path(td) / "outside.bin"
            target.write_bytes(b"user-owned-target")
            link = root / ".book-progress.json.abcd_123.tmp"
            link.symlink_to(target)

            coordinator = Version2UpgradeCoordinator(UserDataLayout(root))
            with self.assertRaisesRegex(
                Version2UpgradeError,
                "must not be a symlink or reparse point",
            ):
                coordinator._files()

            self.assertTrue(link.is_symlink())
            self.assertEqual(target.read_bytes(), b"user-owned-target")

    @unittest.skipIf(
        os.name == "nt",
        "Windows symlink creation requires environment-specific privileges",
    )
    def test_exact_control_name_symlink_fails_closed_before_exclusion(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "AccessibleChess"
            root.mkdir()
            target = Path(td) / "outside-control.bin"
            target.write_bytes(b"user-owned-control-target")
            link = root / "book-progress.json.lock"
            link.symlink_to(target)

            coordinator = Version2UpgradeCoordinator(UserDataLayout(root))
            with self.assertRaisesRegex(
                Version2UpgradeError,
                "must not be a symlink or reparse point",
            ):
                coordinator._files()

            self.assertTrue(link.is_symlink())
            self.assertEqual(target.read_bytes(), b"user-owned-control-target")

    def test_exact_control_name_directory_is_traversed_as_user_data(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "AccessibleChess"
            root.mkdir()
            control_directory = root / "book-progress.json.lock"
            control_directory.mkdir()
            child = control_directory / "keep.bin"
            child.write_bytes(b"directory-user-data")

            regular_control = root / "gametree-resume.json.lock"
            regular_control.write_bytes(b"canonical-control")

            coordinator = Version2UpgradeCoordinator(UserDataLayout(root))
            coordinator._ensure_roots()
            files = self._relative_files(coordinator)

            self.assertIn("book-progress.json.lock/keep.bin", files)
            self.assertNotIn("gametree-resume.json.lock", files)

            backup, manifest = coordinator._create_backup(
                "control-object-shape-validation"
            )
            paths = {str(item["path"]) for item in manifest["entries"]}
            self.assertIn("book-progress.json.lock/keep.bin", paths)
            self.assertNotIn("gametree-resume.json.lock", paths)
            self.assertEqual(
                (
                    backup
                    / "data"
                    / "book-progress.json.lock"
                    / "keep.bin"
                ).read_bytes(),
                b"directory-user-data",
            )

    def test_foreign_hardlinked_lookalikes_are_preserved_but_writer_hardlinks_stay_derived(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "AccessibleChess"
            root.mkdir()

            outside = Path(td) / "outside-user.bin"
            outside.write_bytes(b"user-owned-hardlink-bytes")
            temp_lookalike = root / ".book-progress.json.abcd_123.tmp"
            control_lookalike = root / "book-progress.json.lock"
            foreign_resume_guard = root / "gametree-resume.json.cas-abcd_123.bak"
            foreign_settings_guard = (
                root / ".settings.json.publish-guard-deadbeefcafe"
            )
            os.link(outside, temp_lookalike)
            os.link(outside, control_lookalike)
            os.link(outside, foreign_resume_guard)
            os.link(outside, foreign_settings_guard)

            resume = root / "gametree-resume.json"
            resume.write_bytes(b"canonical-resume")
            resume_guard = root / "gametree-resume.json.cas-xy_98765.bak"
            os.link(resume, resume_guard)

            settings = root / "settings.json"
            settings.write_bytes(b"canonical-settings")
            settings_guard = root / ".settings.json.publish-guard-abcdef123456"
            os.link(settings, settings_guard)

            coordinator = Version2UpgradeCoordinator(UserDataLayout(root))
            coordinator._ensure_roots()
            files = self._relative_files(coordinator)

            self.assertIn(".book-progress.json.abcd_123.tmp", files)
            self.assertIn("book-progress.json.lock", files)
            self.assertIn("gametree-resume.json.cas-abcd_123.bak", files)
            self.assertIn(".settings.json.publish-guard-deadbeefcafe", files)
            self.assertIn("gametree-resume.json", files)
            self.assertIn("settings.json", files)
            self.assertNotIn("gametree-resume.json.cas-xy_98765.bak", files)
            self.assertNotIn(".settings.json.publish-guard-abcdef123456", files)

            backup, manifest = coordinator._create_backup(
                "hardlink-shape-authentication"
            )
            paths = {str(item["path"]) for item in manifest["entries"]}
            self.assertIn(".book-progress.json.abcd_123.tmp", paths)
            self.assertIn("book-progress.json.lock", paths)
            self.assertIn("gametree-resume.json.cas-abcd_123.bak", paths)
            self.assertIn(".settings.json.publish-guard-deadbeefcafe", paths)
            self.assertNotIn("gametree-resume.json.cas-xy_98765.bak", paths)
            self.assertNotIn(".settings.json.publish-guard-abcdef123456", paths)
            self.assertEqual(
                (
                    backup
                    / "data"
                    / ".book-progress.json.abcd_123.tmp"
                ).read_bytes(),
                b"user-owned-hardlink-bytes",
            )
            self.assertEqual(
                (backup / "data" / "book-progress.json.lock").read_bytes(),
                b"user-owned-hardlink-bytes",
            )
            self.assertEqual(
                (
                    backup
                    / "data"
                    / "gametree-resume.json.cas-abcd_123.bak"
                ).read_bytes(),
                b"user-owned-hardlink-bytes",
            )
            self.assertEqual(
                (
                    backup
                    / "data"
                    / ".settings.json.publish-guard-deadbeefcafe"
                ).read_bytes(),
                b"user-owned-hardlink-bytes",
            )

    def test_casefolded_exact_generated_shapes_still_match_writer_grammar(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "AccessibleChess"
            root.mkdir()
            generated = (
                "GAMETREE-RESUME.JSON.ABCD_123.TMP",
                "GAMETREE-RESUME.JSON.CAS-XY_98765.BAK",
                ".BOOK-PROGRESS.JSON.ABCD_123.TMP",
                ".BOOK-PROGRESS.JSON.BAK.XY_98765.TMP",
            )
            for name in generated:
                (root / name).write_bytes(b"generated-runtime-residue")

            files = self._relative_files(
                Version2UpgradeCoordinator(UserDataLayout(root))
            )
            for name in generated:
                self.assertNotIn(name, files)

    def test_generated_residue_does_not_consume_quota_but_near_miss_does(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "AccessibleChess"
            root.mkdir()
            durable = root / "settings.json"
            durable.write_bytes(b"x")
            for name in (
                "gametree-resume.json.abcd_123.tmp",
                "gametree-resume.json.cas-xy_98765.bak",
                ".book-progress.json.abcd_123.tmp",
                ".book-progress.json.bak.xy_98765.tmp",
            ):
                (root / name).write_bytes(b"z" * 4096)

            coordinator = Version2UpgradeCoordinator(
                UserDataLayout(root),
                limits=UpgradeLimits(max_files=1, max_bytes=8),
            )
            self.assertEqual(
                self._relative_files(coordinator),
                {"settings.json"},
            )

            (root / ".book-progress.json.user.note.tmp").write_bytes(b"u")
            with self.assertRaisesRegex(
                Version2UpgradeError,
                "user-data backup exceeds file count limit",
            ):
                coordinator._files()

    def test_legacy_backup_generated_entries_are_not_replayed_over_live_residue(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "AccessibleChess"
            root.mkdir()
            (root / "settings.json").write_text(
                json.dumps({"language": "en", "volume": 34}),
                encoding="utf-8",
            )
            generated = (
                root / "gametree-resume.json.abcd_123.tmp",
                root / "gametree-resume.json.cas-xy_98765.bak",
                root / ".book-progress.json.abcd_123.tmp",
                root / ".book-progress.json.bak.xy_98765.tmp",
            )
            for path in generated:
                path.write_bytes(b"legacy-residue")

            def crash(phase: str) -> None:
                if phase == "settings-migrated":
                    raise _Crash()

            with (
                patch.object(
                    upgrade_base,
                    "_is_generated_root_runtime_file",
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
            backup_data = (
                root.parent
                / "AccessibleChess.upgrade-backups"
                / str(journal["backup_name"])
                / "data"
            )
            for path in generated:
                self.assertTrue((backup_data / path.name).exists())

            for index, path in enumerate(generated):
                path.write_bytes(f"new-live-{index}".encode("ascii"))

            recovered = Version2UpgradeCoordinator(
                UserDataLayout(root)
            ).recover_interrupted()

            self.assertTrue(recovered)
            for index, path in enumerate(generated):
                self.assertEqual(
                    path.read_bytes(),
                    f"new-live-{index}".encode("ascii"),
                )


if __name__ == "__main__":
    unittest.main()
