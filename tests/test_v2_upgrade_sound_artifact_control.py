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

    def test_runtime_locks_are_control_state_but_durable_sound_and_resume_data_are_preserved(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "AccessibleChess"
            root.mkdir()
            (root / "settings.json").write_text(
                json.dumps({"language": "en"}), encoding="utf-8"
            )
            (root / "sound-profile.json.lock").write_bytes(b"live-profile-lock")
            (root / "SOUND-PACKS.LOCK").write_bytes(b"live-pack-lock")
            (root / "gametree-resume.json.lock").write_bytes(b"live-resume-lock")
            (root / "BOOK-PROGRESS.JSON.LOCK").write_bytes(b"live-book-progress-lock")
            (root / "sound-profile.json").write_bytes(b'{"profile":"quiet"}\n')
            (root / "book-progress.json").write_bytes(b'{"generation":2}\n')
            (root / "book-progress.json.bak").write_bytes(b'{"generation":1}\n')
            (root / "gametree-resume.json").write_bytes(b'{"resume":"durable"}\n')
            pack = root / "sound-packs" / "classic" / "move.wav"
            pack.parent.mkdir(parents=True)
            pack.write_bytes(b"durable-pack-bytes")

            coordinator = Version2UpgradeCoordinator(UserDataLayout(root))
            coordinator._ensure_roots()
            files = self._relative_files(coordinator)

            self.assertNotIn("sound-profile.json.lock", files)
            self.assertNotIn("SOUND-PACKS.LOCK", files)
            self.assertNotIn("gametree-resume.json.lock", files)
            self.assertNotIn("BOOK-PROGRESS.JSON.LOCK", files)
            self.assertIn("sound-profile.json", files)
            self.assertIn("book-progress.json", files)
            self.assertIn("book-progress.json.bak", files)
            self.assertIn("gametree-resume.json", files)
            self.assertIn("sound-packs/classic/move.wav", files)

            backup, manifest = coordinator._create_backup("sound-lock-controls")
            paths = {str(item["path"]) for item in manifest["entries"]}
            self.assertNotIn("sound-profile.json.lock", paths)
            self.assertNotIn("SOUND-PACKS.LOCK", paths)
            self.assertNotIn("gametree-resume.json.lock", paths)
            self.assertNotIn("BOOK-PROGRESS.JSON.LOCK", paths)
            self.assertIn("sound-profile.json", paths)
            self.assertIn("book-progress.json", paths)
            self.assertIn("book-progress.json.bak", paths)
            self.assertIn("gametree-resume.json", paths)
            self.assertIn("sound-packs/classic/move.wav", paths)
            self.assertFalse((backup / "data" / "sound-profile.json.lock").exists())
            self.assertFalse((backup / "data" / "SOUND-PACKS.LOCK").exists())
            self.assertFalse((backup / "data" / "gametree-resume.json.lock").exists())
            self.assertFalse((backup / "data" / "BOOK-PROGRESS.JSON.LOCK").exists())
            self.assertEqual(
                (backup / "data" / "book-progress.json").read_bytes(),
                b'{"generation":2}\n',
            )
            self.assertEqual(
                (backup / "data" / "book-progress.json.bak").read_bytes(),
                b'{"generation":1}\n',
            )
            self.assertEqual(
                (backup / "data" / "sound-profile.json").read_bytes(),
                b'{"profile":"quiet"}\n',
            )
            self.assertEqual(
                (backup / "data" / "gametree-resume.json").read_bytes(),
                b'{"resume":"durable"}\n',
            )
            self.assertEqual(
                (backup / "data" / "sound-packs" / "classic" / "move.wav").read_bytes(),
                b"durable-pack-bytes",
            )


    def test_generated_root_writer_residue_is_derived_but_nested_lookalikes_are_preserved(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "AccessibleChess"
            root.mkdir()
            generated = (
                "gametree-resume.json.abcd1234.tmp",
                "gametree-resume.json.cas-abcd1234.bak",
                ".book-progress.json.abcd1234.tmp",
                ".book-progress.json.bak.abcd1234.tmp",
            )
            for name in generated:
                (root / name).write_bytes(b"derived-runtime-residue")

            nested = root / "user-content"
            nested.mkdir()
            for name in generated:
                (nested / name).write_bytes(b"nested-user-data")

            near_misses = (
                "gametree-resume.json.abcd1234.tmp.keep",
                "gametree-resume.json.cas-abcd1234.bak.keep",
                ".book-progress.json.abcd1234.tmp.keep",
            )
            for name in near_misses:
                (root / name).write_bytes(b"root-user-data")

            coordinator = Version2UpgradeCoordinator(UserDataLayout(root))
            coordinator._ensure_roots()
            files = self._relative_files(coordinator)

            for name in generated:
                self.assertNotIn(name, files)
                self.assertIn(f"user-content/{name}", files)
            for name in near_misses:
                self.assertIn(name, files)

            backup, manifest = coordinator._create_backup("writer-residue-derived")
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
                ("gametree-resume.json.lock", b"resume-directory-data"),
                ("book-progress.json.lock", b"book-progress-directory-data"),
            ):
                directory = root / name
                directory.mkdir()
                (directory / "keep.bin").write_bytes(payload)

            coordinator = Version2UpgradeCoordinator(UserDataLayout(root))
            coordinator._ensure_roots()
            files = self._relative_files(coordinator)

            self.assertIn("sound-profile.json.lock/keep.bin", files)
            self.assertIn("sound-packs.lock/keep.bin", files)
            self.assertIn("gametree-resume.json.lock/keep.bin", files)
            self.assertIn("book-progress.json.lock/keep.bin", files)
            backup, manifest = coordinator._create_backup("sound-lock-directories")
            paths = {str(item["path"]) for item in manifest["entries"]}
            self.assertIn("sound-profile.json.lock/keep.bin", paths)
            self.assertIn("sound-packs.lock/keep.bin", paths)
            self.assertIn("gametree-resume.json.lock/keep.bin", paths)
            self.assertIn("book-progress.json.lock/keep.bin", paths)
            self.assertEqual(
                (backup / "data" / "sound-profile.json.lock" / "keep.bin").read_bytes(),
                b"profile-directory-data",
            )
            self.assertEqual(
                (backup / "data" / "sound-packs.lock" / "keep.bin").read_bytes(),
                b"packs-directory-data",
            )
            self.assertEqual(
                (backup / "data" / "gametree-resume.json.lock" / "keep.bin").read_bytes(),
                b"resume-directory-data",
            )
            self.assertEqual(
                (backup / "data" / "book-progress.json.lock" / "keep.bin").read_bytes(),
                b"book-progress-directory-data",
            )

    def test_exact_root_gametree_discard_control_subtree_is_derived_and_nested_names_are_preserved(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "AccessibleChess"
            root.mkdir()
            (root / "settings.json").write_text(
                json.dumps({"language": "en"}), encoding="utf-8"
            )

            guard_root = root / ".GaMeTrEe-ReSuMe-DiScArD"
            guard_root.mkdir()
            (guard_root / ("a" * 64 + ".guard")).write_bytes(b"discard-control")
            (guard_root / "unknown-control.bin").write_bytes(b"reserved-control")

            nested_guard = root / "user-content" / ".gametree-resume-discard"
            nested_guard.mkdir(parents=True)
            (nested_guard / "keep.bin").write_bytes(b"nested-user-data")

            near_guard = root / ".gametree-resume-discard.keep"
            near_guard.mkdir()
            (near_guard / "keep.bin").write_bytes(b"near-name-user-data")

            coordinator = Version2UpgradeCoordinator(UserDataLayout(root))
            coordinator._ensure_roots()
            files = self._relative_files(coordinator)

            self.assertFalse(
                any(
                    name.casefold().startswith(".gametree-resume-discard/")
                    for name in files
                )
            )
            self.assertIn("user-content/.gametree-resume-discard/keep.bin", files)
            self.assertIn(".gametree-resume-discard.keep/keep.bin", files)

            backup, manifest = coordinator._create_backup("resume-discard-control")
            paths = {str(item["path"]) for item in manifest["entries"]}
            self.assertFalse(
                any(
                    name.casefold().startswith(".gametree-resume-discard/")
                    for name in paths
                )
            )
            self.assertIn("user-content/.gametree-resume-discard/keep.bin", paths)
            self.assertIn(".gametree-resume-discard.keep/keep.bin", paths)
            self.assertEqual(
                (
                    backup
                    / "data"
                    / "user-content"
                    / ".gametree-resume-discard"
                    / "keep.bin"
                ).read_bytes(),
                b"nested-user-data",
            )
            self.assertEqual(
                (
                    backup
                    / "data"
                    / ".gametree-resume-discard.keep"
                    / "keep.bin"
                ).read_bytes(),
                b"near-name-user-data",
            )

    @unittest.skipIf(os.name == "nt", "POSIX symlink safety regression")
    def test_root_gametree_discard_control_symlink_still_fails_closed(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "AccessibleChess"
            root.mkdir()
            outside = Path(td) / "outside-discard-control"
            outside.mkdir()
            (outside / "foreign.guard").write_bytes(b"outside")
            os.symlink(
                outside,
                root / ".gametree-resume-discard",
                target_is_directory=True,
            )

            coordinator = Version2UpgradeCoordinator(UserDataLayout(root))
            with self.assertRaisesRegex(
                Version2UpgradeError,
                "symlink or reparse point",
            ):
                coordinator._files()

    def test_root_regular_file_named_gametree_discard_control_remains_user_data(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "AccessibleChess"
            root.mkdir()
            payload = root / ".gametree-resume-discard"
            payload.write_bytes(b"user-owned-regular-file")

            coordinator = Version2UpgradeCoordinator(UserDataLayout(root))
            coordinator._ensure_roots()
            self.assertIn(
                ".gametree-resume-discard",
                self._relative_files(coordinator),
            )

            backup, manifest = coordinator._create_backup("resume-discard-file")
            self.assertIn(
                ".gametree-resume-discard",
                {str(item["path"]) for item in manifest["entries"]},
            )
            self.assertEqual(
                (backup / "data" / ".gametree-resume-discard").read_bytes(),
                b"user-owned-regular-file",
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

    def test_interrupted_recovery_never_replays_runtime_locks_or_sound_cache(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "AccessibleChess"
            root.mkdir()
            (root / "settings.json").write_text(
                json.dumps({"language": "en", "volume": 34}), encoding="utf-8"
            )
            profile_lock = root / "sound-profile.json.lock"
            packs_lock = root / "sound-packs.lock"
            resume_lock = root / "gametree-resume.json.lock"
            book_lock = root / "book-progress.json.lock"
            cache_file = root / "sound-cache" / "scaled" / "move.wav"
            profile_lock.write_bytes(b"old-profile-lock")
            packs_lock.write_bytes(b"old-packs-lock")
            resume_lock.write_bytes(b"old-resume-lock")
            book_lock.write_bytes(b"old-book-lock")
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
            resume_lock.write_bytes(b"new-live-resume-lock")
            book_lock.write_bytes(b"new-live-book-lock")
            cache_file.write_bytes(b"new-live-cache")

            recovered = Version2UpgradeCoordinator(UserDataLayout(root)).run()

            self.assertTrue(recovered.recovered_interrupted_upgrade)
            self.assertEqual(profile_lock.read_bytes(), b"new-live-profile-lock")
            self.assertEqual(packs_lock.read_bytes(), b"new-live-packs-lock")
            self.assertEqual(resume_lock.read_bytes(), b"new-live-resume-lock")
            self.assertEqual(book_lock.read_bytes(), b"new-live-book-lock")
            self.assertEqual(cache_file.read_bytes(), b"new-live-cache")

            backup = (
                root.parent
                / "AccessibleChess.upgrade-backups"
                / recovered.backup_name
                / "data"
            )
            self.assertFalse((backup / "sound-profile.json.lock").exists())
            self.assertFalse((backup / "sound-packs.lock").exists())
            self.assertFalse((backup / "gametree-resume.json.lock").exists())
            self.assertFalse((backup / "book-progress.json.lock").exists())
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
            resume_lock = root / "gametree-resume.json.lock"
            book_lock = root / "book-progress.json.lock"
            cache_lock = root / "sound-cache" / ".playback.lock"
            cache_file = root / "sound-cache" / "scaled" / "move.wav"
            discard_guard = (
                root
                / ".gametree-resume-discard"
                / ("b" * 64 + ".guard")
            )
            profile_lock.write_bytes(b"legacy-profile-lock")
            packs_lock.write_bytes(b"legacy-packs-lock")
            resume_lock.write_bytes(b"legacy-resume-lock")
            book_lock.write_bytes(b"legacy-book-lock")
            cache_file.parent.mkdir(parents=True)
            cache_lock.write_bytes(b"legacy-cache-lock")
            cache_file.write_bytes(b"legacy-cache")
            discard_guard.parent.mkdir()
            discard_guard.write_bytes(b"legacy-discard-guard")

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
            self.assertTrue((backup_data / "gametree-resume.json.lock").exists())
            self.assertTrue((backup_data / "book-progress.json.lock").exists())
            self.assertTrue((backup_data / "sound-cache" / ".playback.lock").exists())
            self.assertTrue((backup_data / "sound-cache" / "scaled" / "move.wav").exists())
            self.assertTrue(
                (
                    backup_data
                    / ".gametree-resume-discard"
                    / ("b" * 64 + ".guard")
                ).exists()
            )

            profile_lock.write_bytes(b"new-profile-lock")
            packs_lock.write_bytes(b"new-packs-lock")
            resume_lock.write_bytes(b"new-resume-lock")
            book_lock.write_bytes(b"new-book-lock")
            cache_lock.write_bytes(b"new-cache-lock")
            cache_file.write_bytes(b"new-cache")
            discard_guard.write_bytes(b"new-discard-guard")

            recovered = Version2UpgradeCoordinator(
                UserDataLayout(root)
            ).recover_interrupted()

            self.assertTrue(recovered)
            self.assertEqual(profile_lock.read_bytes(), b"new-profile-lock")
            self.assertEqual(packs_lock.read_bytes(), b"new-packs-lock")
            self.assertEqual(resume_lock.read_bytes(), b"new-resume-lock")
            self.assertEqual(book_lock.read_bytes(), b"new-book-lock")
            self.assertEqual(cache_lock.read_bytes(), b"new-cache-lock")
            self.assertEqual(cache_file.read_bytes(), b"new-cache")
            self.assertEqual(
                discard_guard.read_bytes(),
                b"new-discard-guard",
            )

    def test_disposable_cache_does_not_consume_backup_quota_but_pack_content_does(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "AccessibleChess"
            root.mkdir()
            cache = root / "sound-cache"
            cache.mkdir()
            (cache / "huge.wav").write_bytes(b"x" * 4096)
            (root / "book-progress.json.lock").write_bytes(b"z" * 4096)
            (root / "gametree-resume.json.deadbeef.tmp").write_bytes(b"t" * 4096)
            (root / "gametree-resume.json.cas-deadbeef.bak").write_bytes(b"c" * 4096)
            (root / ".book-progress.json.deadbeef.tmp").write_bytes(b"p" * 4096)
            discard_guard = root / ".gametree-resume-discard" / ("c" * 64 + ".guard")
            discard_guard.parent.mkdir()
            discard_guard.write_bytes(b"g" * 4096)
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
