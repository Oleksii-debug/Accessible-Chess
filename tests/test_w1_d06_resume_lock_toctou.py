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
    reparse: bool = False,
) -> SimpleNamespace:
    if mode is None:
        mode = stat.S_IFREG | 0o600
    return SimpleNamespace(
        st_mode=mode,
        st_dev=dev,
        st_ino=ino,
        st_nlink=nlink,
        st_size=0,
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
    def test_preopen_validation_rejects_unsafe_path_before_open(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            destination = Path(folder) / "resume.json"
            lock_path = destination.with_name(destination.name + ".lock")
            cases = {
                "symlink": _fake_stat(mode=stat.S_IFLNK | 0o777),
                "reparse": _fake_stat(reparse=True),
                "nonregular": _fake_stat(mode=stat.S_IFDIR | 0o700),
            }
            for label, metadata in cases.items():
                with self.subTest(case=label), mock.patch.object(
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

            self.assertEqual(lock_path.name, "resume.json.lock")

    def test_open_identity_gate_orders_fstat_then_postopen_lstat_before_io(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            destination = Path(folder) / "resume.json"
            events: list[str] = []
            handle = _ProbeHandle()
            opened = _fake_stat(dev=101, ino=202)
            replaced = _fake_stat(dev=101, ino=303)

            def validate(path: Path, *, allow_missing: bool) -> bool:
                events.append("validate")
                self.assertTrue(allow_missing)
                return False

            def open_lock(path: Path, *args: object, **kwargs: object) -> _ProbeHandle:
                events.append("open")
                return handle

            def fstat(fd: int) -> SimpleNamespace:
                events.append("fstat")
                self.assertEqual(fd, 123)
                return opened

            def lstat(path: Path) -> SimpleNamespace:
                events.append("lstat")
                return replaced

            with mock.patch.object(
                gametree_resume,
                "_validate_regular_path",
                side_effect=validate,
            ), mock.patch.object(Path, "open", autospec=True, side_effect=open_lock), mock.patch.object(
                gametree_resume.os,
                "fstat",
                side_effect=fstat,
            ), mock.patch.object(Path, "lstat", autospec=True, side_effect=lstat):
                with self.assertRaises(GameTreeResumeError) as raised:
                    with gametree_resume._exclusive_store_lock(destination):
                        self.fail("replaced lock path must never become authoritative")

            self.assertEqual(raised.exception.code, GameTreeResumeCode.IO_FAILURE)
            self.assertEqual(events, ["validate", "open", "fstat", "lstat"])
            self.assertEqual(handle.write_calls, 0)
            self.assertTrue(handle.closed)

    def test_postopen_gate_rejects_unsafe_metadata_before_write(self) -> None:
        safe = _fake_stat()
        cases = {
            "current-symlink": (safe, _fake_stat(mode=stat.S_IFLNK | 0o777)),
            "current-reparse": (safe, _fake_stat(reparse=True)),
            "current-nonregular": (safe, _fake_stat(mode=stat.S_IFDIR | 0o700)),
            "opened-nonregular": (_fake_stat(mode=stat.S_IFDIR | 0o700), safe),
            "current-multilink": (safe, _fake_stat(nlink=2)),
            "opened-multilink": (_fake_stat(nlink=2), safe),
            "identity-mismatch": (_fake_stat(dev=11, ino=22), _fake_stat(dev=11, ino=23)),
        }

        for label, (opened_metadata, current_metadata) in cases.items():
            with self.subTest(case=label), tempfile.TemporaryDirectory() as folder:
                destination = Path(folder) / "resume.json"
                handle = _ProbeHandle()
                with mock.patch.object(
                    gametree_resume,
                    "_validate_regular_path",
                    return_value=False,
                ), mock.patch.object(Path, "open", autospec=True, return_value=handle), mock.patch.object(
                    gametree_resume.os,
                    "fstat",
                    return_value=opened_metadata,
                ), mock.patch.object(
                    Path,
                    "lstat",
                    autospec=True,
                    return_value=current_metadata,
                ):
                    with self.assertRaises(GameTreeResumeError) as raised:
                        with gametree_resume._exclusive_store_lock(destination):
                            self.fail("unsafe post-open lock object must be rejected")

                self.assertEqual(raised.exception.code, GameTreeResumeCode.IO_FAILURE)
                self.assertEqual(handle.write_calls, 0)
                self.assertTrue(handle.closed)

    def test_raced_lock_handle_is_rejected_before_foreign_file_write(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            destination = root / "resume.json"
            lock_path = root / "resume.json.lock"
            foreign = root / "foreign-empty-file.bin"
            foreign.write_bytes(b"")

            original_validate = gametree_resume._validate_regular_path

            def validate_then_race(path: Path, *, allow_missing: bool) -> bool:
                result = original_validate(path, allow_missing=allow_missing)
                if path == lock_path and allow_missing and result is False:
                    # Model another process replacing the previously-missing lock
                    # name after lstat validation but before the open call.
                    lock_path.write_bytes(b"legitimate-looking-lock-name")
                return result

            def open_foreign_for_raced_lock(
                path: Path,
                mode: str = "r",
                buffering: int = -1,
                encoding: str | None = None,
                errors: str | None = None,
                newline: str | None = None,
            ):
                if path == lock_path and mode == "a+b":
                    return builtins.open(foreign, mode, buffering=buffering)
                return builtins.open(
                    path,
                    mode,
                    buffering=buffering,
                    encoding=encoding,
                    errors=errors,
                    newline=newline,
                )

            with mock.patch.object(
                gametree_resume,
                "_validate_regular_path",
                side_effect=validate_then_race,
            ), mock.patch.object(Path, "open", autospec=True, side_effect=open_foreign_for_raced_lock):
                with self.assertRaises(GameTreeResumeError) as raised:
                    with gametree_resume._exclusive_store_lock(destination):
                        self.fail("raced lock handle must never become authoritative")

            self.assertEqual(raised.exception.code, GameTreeResumeCode.IO_FAILURE)
            self.assertEqual(
                foreign.read_bytes(),
                b"",
                "lock acquisition must not write through a raced foreign handle",
            )


if __name__ == "__main__":
    unittest.main()
