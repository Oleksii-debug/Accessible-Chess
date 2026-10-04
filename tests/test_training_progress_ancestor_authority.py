from __future__ import annotations

import os
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest import mock

from acs.chesscore import Board
from acs.training import ExerciseDefinition, ExerciseSession, ExerciseStep
from acs.training_progress_store import TrainingProgressStore, _windows_open_no_reparse


class TrainingProgressAncestorAuthorityTests(unittest.TestCase):
    @staticmethod
    def _definition() -> ExerciseDefinition:
        return ExerciseDefinition(
            "training-progress-ancestor-authority",
            Board.START,
            (ExerciseStep(frozenset({"e4"})),),
        )

    def test_relative_path_is_bound_to_construction_time_directory(self) -> None:
        original_cwd = Path.cwd()
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            first = root / "first"
            second = root / "second"
            first.mkdir()
            second.mkdir()
            try:
                os.chdir(first)
                store = TrainingProgressStore(
                    Path("training") / "training-progress.json"
                )
                expected_path = first / "training" / "training-progress.json"
                self.assertEqual(expected_path, store.path)

                os.chdir(second)
                revision = store.save(
                    ExerciseSession(self._definition()),
                    expected_revision=None,
                )
            finally:
                os.chdir(original_cwd)

            self.assertEqual(64, len(revision))
            self.assertTrue(expected_path.is_file())
            self.assertFalse(
                (second / "training" / "training-progress.json").exists()
            )

    def test_symlink_ancestor_fails_before_missing_tree_is_read_or_created(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            redirected = root / "redirected"
            redirected.mkdir()
            link = root / "configured"
            try:
                link.symlink_to(redirected, target_is_directory=True)
            except (OSError, NotImplementedError):
                self.skipTest("directory symlink creation is unavailable")

            store = TrainingProgressStore(
                link / "nested" / "training-progress.json"
            )
            with self.assertRaisesRegex(ValueError, "redirected directory"):
                store.load(self._definition())
            self.assertFalse((redirected / "nested").exists())

            with self.assertRaisesRegex(ValueError, "redirected directory"):
                store.save(
                    ExerciseSession(self._definition()),
                    expected_revision=None,
                )
            self.assertFalse((redirected / "nested").exists())

    def test_reparse_ancestor_fails_before_mkdir(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            ancestor = root / "configured"
            ancestor.mkdir()
            store = TrainingProgressStore(
                ancestor / "nested" / "training-progress.json"
            )
            real_lstat = os.lstat

            def reparse_lstat(candidate):
                metadata = real_lstat(candidate)
                if Path(candidate) != ancestor:
                    return metadata
                return SimpleNamespace(
                    st_mode=metadata.st_mode,
                    st_file_attributes=0x400,
                    st_dev=metadata.st_dev,
                    st_ino=metadata.st_ino,
                )

            with mock.patch(
                "acs.training_progress_store.os.lstat",
                side_effect=reparse_lstat,
            ):
                with self.assertRaisesRegex(ValueError, "redirected directory"):
                    store.save(
                        ExerciseSession(self._definition()),
                        expected_revision=None,
                    )

            self.assertFalse((ancestor / "nested").exists())

    def test_existing_ancestor_identity_swap_during_first_save_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            ancestor = root / "configured"
            replacement = root / "replacement"
            ancestor.mkdir()
            replacement.mkdir()
            store = TrainingProgressStore(
                ancestor / "nested" / "training-progress.json"
            )
            real_lstat = os.lstat
            replacement_metadata = real_lstat(replacement)
            ancestor_checks = 0

            def racing_lstat(candidate):
                nonlocal ancestor_checks
                if Path(candidate) == ancestor:
                    ancestor_checks += 1
                    if ancestor_checks >= 2:
                        return replacement_metadata
                return real_lstat(candidate)

            with mock.patch(
                "acs.training_progress_store.os.lstat",
                side_effect=racing_lstat,
            ):
                with self.assertRaisesRegex(ValueError, "changed during the transaction"):
                    store.save(
                        ExerciseSession(self._definition()),
                        expected_revision=None,
                    )

            self.assertGreaterEqual(ancestor_checks, 2)
            self.assertFalse(store.path.exists())

    @unittest.skipUnless(os.name == "nt", "Windows sharing semantics only")
    def test_windows_read_handle_blocks_mutating_second_handles(self) -> None:
        import ctypes
        from ctypes import wintypes

        GENERIC_READ = 0x80000000
        GENERIC_WRITE = 0x40000000
        DELETE = 0x00010000
        FILE_SHARE_READ = 0x00000001
        FILE_SHARE_WRITE = 0x00000002
        FILE_SHARE_DELETE = 0x00000004
        OPEN_EXISTING = 3
        FILE_ATTRIBUTE_NORMAL = 0x00000080
        ERROR_SHARING_VIOLATION = 32

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        create_file = kernel32.CreateFileW
        create_file.argtypes = [
            wintypes.LPCWSTR,
            wintypes.DWORD,
            wintypes.DWORD,
            ctypes.c_void_p,
            wintypes.DWORD,
            wintypes.DWORD,
            wintypes.HANDLE,
        ]
        create_file.restype = wintypes.HANDLE
        close_handle = kernel32.CloseHandle
        close_handle.argtypes = [wintypes.HANDLE]
        close_handle.restype = wintypes.BOOL
        invalid = ctypes.c_void_p(-1).value
        all_shares = FILE_SHARE_READ | FILE_SHARE_WRITE | FILE_SHARE_DELETE

        def second_handle(path: Path, access: int, share: int) -> tuple[int, int]:
            ctypes.set_last_error(0)
            handle = create_file(
                str(path),
                access,
                share,
                None,
                OPEN_EXISTING,
                FILE_ATTRIBUTE_NORMAL,
                None,
            )
            return int(handle), ctypes.get_last_error()

        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "training-progress.json"
            path.write_bytes(b"stable progress bytes")
            descriptor = _windows_open_no_reparse(path, create=False)
            try:
                reader, reader_error = second_handle(
                    path,
                    GENERIC_READ,
                    FILE_SHARE_READ,
                )
                self.assertNotEqual(invalid, reader, reader_error)
                self.assertTrue(close_handle(reader))

                writer, writer_error = second_handle(
                    path,
                    GENERIC_WRITE,
                    all_shares,
                )
                self.assertEqual(invalid, writer)
                self.assertEqual(ERROR_SHARING_VIOLATION, writer_error)

                deleter, delete_error = second_handle(
                    path,
                    DELETE,
                    all_shares,
                )
                self.assertEqual(invalid, deleter)
                self.assertEqual(ERROR_SHARING_VIOLATION, delete_error)
            finally:
                os.close(descriptor)

            preexisting_writer, writer_error = second_handle(
                path,
                GENERIC_WRITE,
                all_shares,
            )
            self.assertNotEqual(invalid, preexisting_writer, writer_error)
            try:
                with self.assertRaises(OSError) as blocked_read:
                    _windows_open_no_reparse(path, create=False)
                self.assertEqual(ERROR_SHARING_VIOLATION, blocked_read.exception.errno)

                store = TrainingProgressStore(path)
                with self.assertRaisesRegex(ValueError, "could not be inspected"):
                    store.load(self._definition())
            finally:
                self.assertTrue(close_handle(preexisting_writer))


if __name__ == "__main__":
    unittest.main()
