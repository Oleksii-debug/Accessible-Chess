from __future__ import annotations

import builtins
from pathlib import Path
from types import SimpleNamespace
import stat
import tempfile
import unittest
from unittest import mock

import acs.gametree_resume as gametree_resume
from acs.gametree_resume import GameTreeResumeCode, GameTreeResumeError


def _fake_stat(
    *,
    mode: int | None = None,
    dev: int = 11,
    ino: int = 22,
    nlink: int = 1,
    size: int = 0,
    mtime_ns: int = 100,
    ctime_ns: int = 90,
    reparse: bool = False,
) -> SimpleNamespace:
    if mode is None:
        mode = stat.S_IFREG | 0o600
    return SimpleNamespace(
        st_mode=mode,
        st_dev=dev,
        st_ino=ino,
        st_nlink=nlink,
        st_size=size,
        st_mtime_ns=mtime_ns,
        st_ctime_ns=ctime_ns,
        st_file_attributes=(0x400 if reparse else 0),
    )


class _ProbeHandle:
    def __init__(self) -> None:
        self.closed = False
        self.write_calls = 0

    def fileno(self) -> int:
        return 123

    def write(self, payload: bytes) -> int:
        self.write_calls += 1
        raise AssertionError("identity gate must run before any lock-file write")

    def close(self) -> None:
        self.closed = True


class ResumeLockToctouTests(unittest.TestCase):
    def test_initial_unsafe_lock_path_is_rejected_before_open(self) -> None:
        cases = {
            "symlink": _fake_stat(mode=stat.S_IFLNK | 0o777),
            "reparse": _fake_stat(reparse=True),
            "nonregular": _fake_stat(mode=stat.S_IFDIR | 0o700),
            "multilink": _fake_stat(nlink=2),
        }
        for label, metadata in cases.items():
            with self.subTest(case=label), tempfile.TemporaryDirectory() as folder:
                destination = Path(folder) / "resume.json"
                with mock.patch.object(
                    Path,
                    "lstat",
                    autospec=True,
                    return_value=metadata,
                ), mock.patch.object(Path, "open", autospec=True) as opened:
                    with self.assertRaises(GameTreeResumeError) as raised:
                        with gametree_resume._exclusive_store_lock(destination):
                            self.fail("unsafe pre-existing lock path must be rejected")

                self.assertEqual(raised.exception.code, GameTreeResumeCode.IO_FAILURE)
                opened.assert_not_called()

    def test_existing_lock_replacement_between_validation_and_open_is_rejected_before_io(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            destination = Path(folder) / "resume.json"
            validated = _fake_stat(dev=101, ino=202)
            replacement = _fake_stat(dev=101, ino=303)
            handle = _ProbeHandle()

            with mock.patch.object(
                Path,
                "lstat",
                autospec=True,
                side_effect=[validated, replacement],
            ), mock.patch.object(
                Path,
                "open",
                autospec=True,
                return_value=handle,
            ), mock.patch.object(
                gametree_resume.os,
                "fstat",
                return_value=replacement,
            ):
                with self.assertRaises(GameTreeResumeError) as raised:
                    with gametree_resume._exclusive_store_lock(destination):
                        self.fail("replacement lock inode must never become authoritative")

            self.assertEqual(raised.exception.code, GameTreeResumeCode.IO_FAILURE)
            self.assertEqual(handle.write_calls, 0)
            self.assertTrue(handle.closed)

    def test_existing_lock_same_inode_state_drift_is_rejected_before_io(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            destination = Path(folder) / "resume.json"
            validated = _fake_stat(dev=101, ino=202, mtime_ns=100, ctime_ns=90)
            changed = _fake_stat(dev=101, ino=202, mtime_ns=200, ctime_ns=190)
            handle = _ProbeHandle()

            with mock.patch.object(
                Path,
                "lstat",
                autospec=True,
                side_effect=[validated, changed],
            ), mock.patch.object(
                Path,
                "open",
                autospec=True,
                return_value=handle,
            ), mock.patch.object(
                gametree_resume.os,
                "fstat",
                return_value=changed,
            ):
                with self.assertRaises(GameTreeResumeError) as raised:
                    with gametree_resume._exclusive_store_lock(destination):
                        self.fail("changed existing lock state must be rejected")

            self.assertEqual(raised.exception.code, GameTreeResumeCode.IO_FAILURE)
            self.assertEqual(handle.write_calls, 0)
            self.assertTrue(handle.closed)

    def test_missing_lock_postopen_unsafe_metadata_is_rejected_before_write(self) -> None:
        safe = _fake_stat()
        cases = {
            "current-symlink": (safe, _fake_stat(mode=stat.S_IFLNK | 0o777)),
            "current-reparse": (safe, _fake_stat(reparse=True)),
            "current-nonregular": (safe, _fake_stat(mode=stat.S_IFDIR | 0o700)),
            "opened-nonregular": (_fake_stat(mode=stat.S_IFDIR | 0o700), safe),
            "current-multilink": (safe, _fake_stat(nlink=2)),
            "opened-multilink": (_fake_stat(nlink=2), safe),
            "identity-mismatch": (
                _fake_stat(dev=11, ino=22),
                _fake_stat(dev=11, ino=23),
            ),
        }

        for label, (opened_metadata, current_metadata) in cases.items():
            with self.subTest(case=label), tempfile.TemporaryDirectory() as folder:
                destination = Path(folder) / "resume.json"
                handle = _ProbeHandle()
                with mock.patch.object(
                    Path,
                    "lstat",
                    autospec=True,
                    side_effect=[FileNotFoundError(), current_metadata],
                ), mock.patch.object(
                    Path,
                    "open",
                    autospec=True,
                    return_value=handle,
                ), mock.patch.object(
                    gametree_resume.os,
                    "fstat",
                    return_value=opened_metadata,
                ):
                    with self.assertRaises(GameTreeResumeError) as raised:
                        with gametree_resume._exclusive_store_lock(destination):
                            self.fail("unsafe post-open lock object must be rejected")

                self.assertEqual(raised.exception.code, GameTreeResumeCode.IO_FAILURE)
                self.assertEqual(handle.write_calls, 0)
                self.assertTrue(handle.closed)

    def test_raced_missing_lock_handle_is_rejected_before_foreign_file_write(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            destination = root / "resume.json"
            lock_path = root / "resume.json.lock"
            foreign = root / "foreign-empty-file.bin"
            foreign.write_bytes(b"")
            original_open = builtins.open

            def open_foreign_for_raced_lock(
                path: Path,
                mode: str = "r",
                buffering: int = -1,
                encoding: str | None = None,
                errors: str | None = None,
                newline: str | None = None,
            ):
                if path == lock_path and mode == "a+b":
                    lock_path.write_bytes(b"legitimate-looking-lock-name")
                    return original_open(foreign, mode, buffering=buffering)
                return original_open(
                    path,
                    mode,
                    buffering=buffering,
                    encoding=encoding,
                    errors=errors,
                    newline=newline,
                )

            with mock.patch.object(
                Path,
                "open",
                autospec=True,
                side_effect=open_foreign_for_raced_lock,
            ):
                with self.assertRaises(GameTreeResumeError) as raised:
                    with gametree_resume._exclusive_store_lock(destination):
                        self.fail("raced foreign lock handle must never become authoritative")

            self.assertEqual(raised.exception.code, GameTreeResumeCode.IO_FAILURE)
            self.assertEqual(
                foreign.read_bytes(),
                b"",
                "lock acquisition must not write through a raced foreign handle",
            )

    def test_real_lock_can_be_reacquired_without_inode_replacement(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            destination = Path(folder) / "resume.json"
            lock_path = destination.with_name(destination.name + ".lock")

            with gametree_resume._exclusive_store_lock(destination):
                self.assertTrue(lock_path.exists())
            first = lock_path.stat()

            with gametree_resume._exclusive_store_lock(destination):
                self.assertTrue(lock_path.exists())
            second = lock_path.stat()

            self.assertEqual(
                (first.st_dev, first.st_ino),
                (second.st_dev, second.st_ino),
            )


if __name__ == "__main__":
    unittest.main()
