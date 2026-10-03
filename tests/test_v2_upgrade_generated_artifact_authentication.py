from __future__ import annotations

import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from acs.version2_upgrade_base import (
    UserDataLayout,
    Version2UpgradeCoordinator,
    Version2UpgradeError,
    _UpgradeLock,
    _atomic_bytes,
)


class V2UpgradeGeneratedArtifactAuthenticationTests(unittest.TestCase):
    def _coordinator(self, root: Path) -> Version2UpgradeCoordinator:
        return Version2UpgradeCoordinator(UserDataLayout(root))

    def _assert_symlink_alias_fails_closed(self, relative: str) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "AccessibleChess"
            root.mkdir()
            target = Path(td) / "outside-user-data.bin"
            target.write_bytes(b"outside-user-data")
            alias = root / relative
            alias.parent.mkdir(parents=True, exist_ok=True)
            try:
                os.symlink(target, alias)
            except (OSError, NotImplementedError):
                self.skipTest("symlink creation is unavailable on this runner")

            with self.assertRaisesRegex(
                Version2UpgradeError,
                "symlink or reparse point",
            ):
                self._coordinator(root)._files()

            self.assertEqual(target.read_bytes(), b"outside-user-data")

    def test_missing_upgrade_lock_create_race_never_adopts_foreign_file(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "AccessibleChess"
            root.mkdir()
            lock = root / ".v2-upgrade.lock"
            real_open = os.open
            injected = False
            foreign_bytes = b"foreign-lock-owner"

            def racing_open(path, flags, mode=0o777):
                nonlocal injected
                if Path(path) == lock and not injected:
                    lock.write_bytes(foreign_bytes)
                    injected = True
                return real_open(path, flags, mode)

            with mock.patch(
                "acs.version2_upgrade_base.os.open",
                side_effect=racing_open,
            ):
                with self.assertRaisesRegex(
                    Version2UpgradeError,
                    "upgrade lock could not be opened safely",
                ):
                    with _UpgradeLock(lock):
                        pass

            self.assertTrue(injected)
            self.assertEqual(lock.read_bytes(), foreign_bytes)

    def test_existing_upgrade_lock_replacement_race_fails_without_mutation(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "AccessibleChess"
            root.mkdir()
            lock = root / ".v2-upgrade.lock"
            lock.write_bytes(b"\0")
            replacement = root / "foreign-lock-replacement.bin"
            replacement_bytes = b"foreign-lock-replacement"
            replacement.write_bytes(replacement_bytes)
            real_open = os.open
            injected = False

            def racing_open(path, flags, mode=0o777):
                nonlocal injected
                if Path(path) == lock and not injected:
                    os.replace(replacement, lock)
                    injected = True
                return real_open(path, flags, mode)

            with mock.patch(
                "acs.version2_upgrade_base.os.open",
                side_effect=racing_open,
            ):
                with self.assertRaisesRegex(
                    Version2UpgradeError,
                    "upgrade lock changed while opening",
                ):
                    with _UpgradeLock(lock):
                        pass

            self.assertTrue(injected)
            self.assertEqual(lock.read_bytes(), replacement_bytes)

    def test_atomic_publication_rejects_substituted_temp_without_deleting_it(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            target = root / "state.json"
            substitute = root / "foreign-substitute.bin"
            substitute_bytes = b"foreign-preservation-bytes"
            substitute.write_bytes(substitute_bytes)
            real_mkstemp = tempfile.mkstemp
            real_lstat = os.lstat
            temp_path: Path | None = None
            injected = False

            def tracking_mkstemp(*args, **kwargs):
                nonlocal temp_path
                descriptor, name = real_mkstemp(*args, **kwargs)
                temp_path = Path(name)
                return descriptor, name

            def substituting_lstat(path, *args, **kwargs):
                nonlocal injected
                candidate = Path(path)
                if (
                    temp_path is not None
                    and candidate == temp_path
                    and not injected
                ):
                    os.replace(substitute, temp_path)
                    injected = True
                return real_lstat(path, *args, **kwargs)

            with mock.patch(
                "acs.version2_upgrade_base.tempfile.mkstemp",
                side_effect=tracking_mkstemp,
            ), mock.patch(
                "acs.version2_upgrade_base.os.lstat",
                side_effect=substituting_lstat,
            ):
                with self.assertRaisesRegex(
                    Version2UpgradeError,
                    "temporary file changed before publication",
                ):
                    _atomic_bytes(target, b"owned-publication")

            self.assertTrue(injected)
            self.assertFalse(target.exists())
            self.assertIsNotNone(temp_path)
            assert temp_path is not None
            self.assertTrue(temp_path.exists())
            self.assertEqual(temp_path.read_bytes(), substitute_bytes)

    def test_atomic_publication_rejects_hardlinked_temp_and_preserves_peer(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            target = root / "state.json"
            peer = root / "foreign-hardlink-peer.bin"
            real_mkstemp = tempfile.mkstemp
            real_lstat = os.lstat
            temp_path: Path | None = None
            injected = False

            def tracking_mkstemp(*args, **kwargs):
                nonlocal temp_path
                descriptor, name = real_mkstemp(*args, **kwargs)
                temp_path = Path(name)
                return descriptor, name

            def hardlinking_lstat(path, *args, **kwargs):
                nonlocal injected
                candidate = Path(path)
                if (
                    temp_path is not None
                    and candidate == temp_path
                    and not injected
                ):
                    try:
                        os.link(temp_path, peer)
                    except (OSError, NotImplementedError):
                        self.skipTest("hard-link creation is unavailable on this runner")
                    injected = True
                return real_lstat(path, *args, **kwargs)

            with mock.patch(
                "acs.version2_upgrade_base.tempfile.mkstemp",
                side_effect=tracking_mkstemp,
            ), mock.patch(
                "acs.version2_upgrade_base.os.lstat",
                side_effect=hardlinking_lstat,
            ):
                with self.assertRaisesRegex(
                    Version2UpgradeError,
                    "temporary file changed before publication",
                ):
                    _atomic_bytes(target, b"owned-publication")

            self.assertTrue(injected)
            self.assertFalse(target.exists())
            self.assertIsNotNone(temp_path)
            assert temp_path is not None
            self.assertTrue(temp_path.exists())
            self.assertTrue(peer.exists())
            self.assertEqual(temp_path.read_bytes(), b"owned-publication")
            self.assertEqual(peer.read_bytes(), b"owned-publication")

    def test_control_name_directory_fails_closed(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "AccessibleChess"
            root.mkdir()
            (root / "book-progress.json.lock").mkdir()

            with self.assertRaisesRegex(
                Version2UpgradeError,
                "control entry must be a regular file",
            ):
                self._coordinator(root)._files()

    @unittest.skipUnless(hasattr(os, "mkfifo"), "FIFO creation is unavailable")
    def test_control_name_special_object_fails_closed(self):
        for relative in (
            ".v2-upgrade.lock",
            ".v2-upgrade-state.json",
            "book-progress.json.lock",
        ):
            with self.subTest(relative=relative), tempfile.TemporaryDirectory() as td:
                root = Path(td) / "AccessibleChess"
                root.mkdir()
                os.mkfifo(root / relative)

                with self.assertRaisesRegex(
                    Version2UpgradeError,
                    "control entry must be a regular file",
                ):
                    self._coordinator(root)._files()

    def test_hardlinked_control_name_fails_closed(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "AccessibleChess"
            root.mkdir()
            source = root / "important-user-data.bin"
            source.write_bytes(b"preserve-control-alias-source")
            control = root / "book-progress.json.lock"
            try:
                os.link(source, control)
            except (OSError, NotImplementedError):
                self.skipTest("hard-link creation is unavailable on this runner")

            with self.assertRaisesRegex(
                Version2UpgradeError,
                "control entry must be a private file",
            ):
                self._coordinator(root)._files()

            self.assertEqual(source.read_bytes(), b"preserve-control-alias-source")
            self.assertEqual(control.read_bytes(), b"preserve-control-alias-source")

    def test_exact_generated_runtime_aliases_fail_closed(self):
        digest = "a" * 64
        generated = (
            "gametree-resume.json.abcd_123.tmp",
            "gametree-resume.json.cas-abcd_123.bak",
            ".book-progress.json.abcd_123.tmp",
            ".book-progress.json.bak.abcd_123.tmp",
            ".education-workspace.json.abcd_123.tmp",
            f"training-progress/.{digest}.json.lock",
            f"training-progress/.{digest}.json.abcd_123.tmp",
            "settings.json.tmp",
            ".settings.json.abcd_123.tmp",
            "..v2-upgrade-state.json.abcd_123.tmp",
            ".settings.json.publish-guard-abcdef123456",
            ".library.acsdb.publish-guard-abcdef123456",
        )
        for relative in generated:
            with self.subTest(relative=relative):
                self._assert_symlink_alias_fails_closed(relative)

    def test_derived_runtime_descendant_aliases_fail_closed(self):
        for relative in (
            "sound-cache/cache-entry.wav",
            ".gametree-resume-discard/" + ("b" * 64) + ".guard",
        ):
            with self.subTest(relative=relative):
                self._assert_symlink_alias_fails_closed(relative)

    def test_hardlinked_private_generated_names_remain_preservation_backed(self):
        digest = "a" * 64
        generated = (
            "gametree-resume.json.abcd_123.tmp",
            "gametree-resume.json.cas-abcd_123.bak",
            ".book-progress.json.abcd_123.tmp",
            ".book-progress.json.bak.abcd_123.tmp",
            ".education-workspace.json.abcd_123.tmp",
            f"training-progress/.{digest}.json.lock",
            f"training-progress/.{digest}.json.abcd_123.tmp",
            "settings.json.tmp",
            ".settings.json.abcd_123.tmp",
            "..v2-upgrade-state.json.abcd_123.tmp",
        )
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "AccessibleChess"
            root.mkdir()
            source = root / "important-user-data.bin"
            source.write_bytes(b"preserve-this-inode")

            created: list[Path] = []
            try:
                for relative in generated:
                    alias = root / relative
                    alias.parent.mkdir(parents=True, exist_ok=True)
                    os.link(source, alias)
                    created.append(alias)
            except (OSError, NotImplementedError):
                self.skipTest("hard-link creation is unavailable on this runner")

            files = {
                path.relative_to(root).as_posix()
                for path in self._coordinator(root)._files()
            }
            self.assertIn(source.name, files)
            for alias in created:
                self.assertIn(alias.relative_to(root).as_posix(), files)
                self.assertEqual(alias.read_bytes(), b"preserve-this-inode")

    def test_publication_guard_hardlink_remains_generated_coordination_state(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "AccessibleChess"
            root.mkdir()
            settings = root / "settings.json"
            settings.write_bytes(b'{"schema_version":1}')
            guard = root / ".settings.json.publish-guard-abcdef123456"
            try:
                os.link(settings, guard)
            except (OSError, NotImplementedError):
                self.skipTest("hard-link creation is unavailable on this runner")

            files = {
                path.relative_to(root).as_posix()
                for path in self._coordinator(root)._files()
            }
            self.assertIn("settings.json", files)
            self.assertNotIn(guard.name, files)
            self.assertEqual(guard.read_bytes(), settings.read_bytes())

    def test_private_publication_guard_lookalike_remains_preservation_backed(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "AccessibleChess"
            root.mkdir()
            settings = root / "settings.json"
            settings.write_bytes(b'{"schema_version":1}')
            guard = root / ".settings.json.publish-guard-abcdef123456"
            guard.write_bytes(b"user-owned-lookalike")

            files = {
                path.relative_to(root).as_posix()
                for path in self._coordinator(root)._files()
            }

            self.assertIn("settings.json", files)
            self.assertIn(guard.name, files)
            self.assertEqual(guard.read_bytes(), b"user-owned-lookalike")

    def test_publication_guard_hardlink_to_unrelated_inode_is_preserved(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "AccessibleChess"
            root.mkdir()
            library = root / "library.acsdb"
            library.write_bytes(b"current-library")
            source = root / "important-user-data.bin"
            source.write_bytes(b"preserve-unrelated-hardlink")
            guard = root / ".library.acsdb.publish-guard-abcdef123456"
            try:
                os.link(source, guard)
            except (OSError, NotImplementedError):
                self.skipTest("hard-link creation is unavailable on this runner")

            files = {
                path.relative_to(root).as_posix()
                for path in self._coordinator(root)._files()
            }

            self.assertIn("library.acsdb", files)
            self.assertIn(source.name, files)
            self.assertIn(guard.name, files)
            self.assertEqual(guard.read_bytes(), source.read_bytes())

    def test_stale_publication_guard_after_target_replace_is_preserved(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "AccessibleChess"
            root.mkdir()
            settings = root / "settings.json"
            settings.write_bytes(b'{"schema_version":1,"old":true}')
            guard = root / ".settings.json.publish-guard-abcdef123456"
            try:
                os.link(settings, guard)
            except (OSError, NotImplementedError):
                self.skipTest("hard-link creation is unavailable on this runner")
            replacement = root / "settings-replacement.json"
            replacement.write_bytes(b'{"schema_version":1,"new":true}')
            os.replace(replacement, settings)

            files = {
                path.relative_to(root).as_posix()
                for path in self._coordinator(root)._files()
            }

            self.assertIn("settings.json", files)
            self.assertIn(guard.name, files)
            self.assertEqual(guard.read_bytes(), b'{"schema_version":1,"old":true}')
            self.assertEqual(settings.read_bytes(), b'{"schema_version":1,"new":true}')

    def test_library_publication_guard_hardlink_to_current_target_is_generated(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "AccessibleChess"
            root.mkdir()
            library = root / "library.acsdb"
            library.write_bytes(b"current-library")
            guard = root / ".library.acsdb.publish-guard-abcdef123456"
            try:
                os.link(library, guard)
            except (OSError, NotImplementedError):
                self.skipTest("hard-link creation is unavailable on this runner")

            files = {
                path.relative_to(root).as_posix()
                for path in self._coordinator(root)._files()
            }

            self.assertIn("library.acsdb", files)
            self.assertNotIn(guard.name, files)
            self.assertEqual(guard.read_bytes(), library.read_bytes())

    @unittest.skipUnless(hasattr(os, "mkfifo"), "FIFO creation is unavailable")
    def test_generated_filename_special_object_is_not_silently_discarded(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "AccessibleChess"
            root.mkdir()
            fifo = root / "gametree-resume.json.abcd_123.tmp"
            os.mkfifo(fifo)

            with self.assertRaisesRegex(
                Version2UpgradeError,
                "non-regular entry",
            ):
                self._coordinator(root)._files()

    @unittest.skipUnless(hasattr(os, "mkfifo"), "FIFO creation is unavailable")
    def test_derived_runtime_special_object_fails_closed(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "AccessibleChess"
            root.mkdir()
            cache = root / "sound-cache"
            cache.mkdir()
            fifo = cache / "cache-entry"
            os.mkfifo(fifo)

            with self.assertRaisesRegex(
                Version2UpgradeError,
                "regular file or directory",
            ):
                self._coordinator(root)._files()


if __name__ == "__main__":
    unittest.main()
