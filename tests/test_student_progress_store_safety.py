from __future__ import annotations

import os
from pathlib import Path
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from acs.student_progress import (
    ReviewKind,
    StudentProgressLedger,
    StudentReviewRecord,
)
from acs.student_progress_store import StudentProgressStore
from acs import student_progress_store as persistence


class StudentProgressStoreSafetyTests(unittest.TestCase):
    @staticmethod
    def _ledger() -> StudentProgressLedger:
        ledger = StudentProgressLedger()
        ledger.append(
            StudentReviewRecord(
                record_id="review-1",
                student_id="student-1",
                session_id="session-1",
                kind=ReviewKind.GAME,
                source_id="game-1",
                source_revision="revision-1",
                sequence=1,
                attempts=0,
                mistakes=0,
                hints_used=0,
                completed=True,
            )
        )
        return ledger

    def test_only_windows_cross_interface_ctime_is_incomparable(self) -> None:
        common = dict(st_dev=1, st_ino=2, st_size=3, st_mtime_ns=4)
        descriptor = SimpleNamespace(**common, st_ctime_ns=5)
        pathname = SimpleNamespace(**common, st_ctime_ns=6)
        with patch.object(persistence.os, 'name', 'nt'):
            self.assertTrue(persistence._same_file_version(descriptor, pathname, cross_interface=True))
            self.assertFalse(persistence._same_file_version(descriptor, pathname))
        with patch.object(persistence.os, 'name', 'posix'):
            self.assertFalse(persistence._same_file_version(descriptor, pathname, cross_interface=True))

    def test_same_size_mutation_with_restored_mtime_fails_and_releases_handle(self) -> None:
        with tempfile.TemporaryDirectory() as raw_dir:
            path = Path(raw_dir) / 'student-progress.json'
            store = StudentProgressStore(path)
            store.save(self._ledger(), expected_revision=None)
            original = path.read_bytes()
            info = path.stat()
            changed = original.replace(b'review-1', b'review-2')
            self.assertNotEqual(original, changed)
            self.assertEqual(len(original), len(changed))
            seek = os.lseek
            descriptors = []
            def mutate(descriptor, offset, whence):
                descriptors.append(descriptor)
                path.write_bytes(changed)
                os.utime(path, ns=(info.st_atime_ns, info.st_mtime_ns))
                return seek(descriptor, offset, whence)
            with patch.object(persistence.os, 'lseek', side_effect=mutate):
                with self.assertRaisesRegex(ValueError, 'changed while reading'):
                    store.load()
            self.assertEqual(1, len(descriptors))
            with self.assertRaises(OSError):
                os.fstat(descriptors[0])
            self.assertEqual(changed, path.read_bytes())
            path.unlink()

    def test_confirmation_read_remains_bounded_after_source_growth(self) -> None:
        with tempfile.TemporaryDirectory() as raw_dir:
            path = Path(raw_dir) / 'student-progress.json'
            path.write_bytes(b'12345678')
            seek = os.lseek
            def grow(descriptor, offset, whence):
                path.write_bytes(b'123456789')
                return seek(descriptor, offset, whence)
            with patch.object(persistence, 'STUDENT_PROGRESS_STORE_MAX_BYTES', 8):
                with patch.object(persistence.os, 'lseek', side_effect=grow):
                    with self.assertRaisesRegex(ValueError, 'maximum size'):
                        persistence._read_bounded_file(path)
            path.unlink()

    def test_relative_path_is_bound_at_construction_time(self) -> None:
        with tempfile.TemporaryDirectory() as first, tempfile.TemporaryDirectory() as second:
            previous = Path.cwd()
            try:
                os.chdir(first)
                store = StudentProgressStore("student-progress.json")
                expected = Path(first) / "student-progress.json"
                os.chdir(second)
                store.save(self._ledger(), expected_revision=None)
            finally:
                os.chdir(previous)
            self.assertEqual(expected, store.path)
            self.assertTrue(expected.is_file())
            self.assertFalse((Path(second) / "student-progress.json").exists())

    def test_load_rejects_symlink_instead_of_following_target(self) -> None:
        with tempfile.TemporaryDirectory() as raw_dir:
            root = Path(raw_dir)
            canonical = StudentProgressStore(root / "canonical.json")
            canonical.save(self._ledger(), expected_revision=None)
            link = root / "student-progress.json"
            try:
                link.symlink_to(canonical.path)
            except (OSError, NotImplementedError):
                self.skipTest("symlinks are unavailable on this platform")
            with self.assertRaisesRegex(ValueError, "private regular file"):
                StudentProgressStore(link).load()

    def test_load_rejects_hard_linked_progress_file(self) -> None:
        with tempfile.TemporaryDirectory() as raw_dir:
            root = Path(raw_dir)
            canonical = StudentProgressStore(root / "canonical.json")
            canonical.save(self._ledger(), expected_revision=None)
            linked = root / "student-progress.json"
            try:
                os.link(canonical.path, linked)
            except (OSError, NotImplementedError):
                self.skipTest("hard links are unavailable on this platform")
            with self.assertRaisesRegex(ValueError, "private regular file"):
                StudentProgressStore(linked).load()

    def test_save_never_adopts_existing_symlink_target(self) -> None:
        with tempfile.TemporaryDirectory() as raw_dir:
            root = Path(raw_dir)
            target = root / "target.json"
            target.write_text("sentinel", encoding="utf-8")
            link = root / "student-progress.json"
            try:
                link.symlink_to(target)
            except (OSError, NotImplementedError):
                self.skipTest("symlinks are unavailable on this platform")
            with self.assertRaisesRegex(ValueError, "private regular file"):
                StudentProgressStore(link).save(
                    self._ledger(),
                    expected_revision=None,
                )
            self.assertEqual("sentinel", target.read_text(encoding="utf-8"))

    def test_duplicate_json_keys_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as raw_dir:
            path = Path(raw_dir) / "student-progress.json"
            store = StudentProgressStore(path)
            cases = (
                '{"schema_version":1,"schema_version":1,"snapshot":{"schema_version":1,"records":[]}}',
                '{"schema_version":1,"snapshot":{"schema_version":1,"records":[],"records":[]}}',
            )
            for raw in cases:
                with self.subTest(raw=raw):
                    path.write_text(raw, encoding="utf-8")
                    with self.assertRaisesRegex(ValueError, "invalid student progress file"):
                        store.load()

    def test_nonfinite_json_constant_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as raw_dir:
            path = Path(raw_dir) / "student-progress.json"
            path.write_text(
                '{"schema_version":NaN,"snapshot":{"schema_version":1,"records":[]}}',
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "invalid student progress file"):
                StudentProgressStore(path).load()


if __name__ == "__main__":
    unittest.main()
