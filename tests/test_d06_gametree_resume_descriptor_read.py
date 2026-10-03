from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
import os
import stat
import tempfile
import unittest
from unittest import mock

import acs.gametree_resume as gametree_resume
from acs.gametree_resume import GameTreeResumeCode, GameTreeResumeError


def _fake_stat(
    *,
    dev: int = 11,
    ino: int = 22,
    size: int = 3,
    mtime_ns: int = 100,
    ctime_ns: int = 90,
    mode: int | None = None,
    reparse: bool = False,
) -> SimpleNamespace:
    if mode is None:
        mode = stat.S_IFREG | 0o600
    return SimpleNamespace(
        st_mode=mode,
        st_dev=dev,
        st_ino=ino,
        st_size=size,
        st_mtime_ns=mtime_ns,
        st_ctime_ns=ctime_ns,
        st_file_attributes=(0x400 if reparse else 0),
    )


class ResumeDescriptorReadTests(unittest.TestCase):
    def test_binary_descriptor_read_preserves_exact_bytes(self) -> None:
        payload = b"line1\r\n\x1a\x00line2\n"
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "resume.json"
            path.write_bytes(payload)

            self.assertEqual(gametree_resume._read_store_bytes(path), payload)

    def test_validated_path_replacement_before_open_is_rejected_before_read(self) -> None:
        path = Path("resume.json")
        validated = _fake_stat(dev=7, ino=10)
        replacement = _fake_stat(dev=7, ino=20)

        with mock.patch.object(
            Path,
            "lstat",
            autospec=True,
            side_effect=[validated, replacement],
        ), mock.patch.object(
            gametree_resume.os,
            "open",
            return_value=123,
        ) as opened, mock.patch.object(
            gametree_resume.os,
            "fstat",
            return_value=replacement,
        ), mock.patch.object(
            gametree_resume.os,
            "read",
        ) as read, mock.patch.object(
            gametree_resume.os,
            "close",
        ) as close:
            with self.assertRaises(GameTreeResumeError) as caught:
                gametree_resume._read_store_bytes(path)

        self.assertEqual(caught.exception.code, GameTreeResumeCode.STALE_WRITER)
        opened.assert_called_once()
        read.assert_not_called()
        close.assert_called_once_with(123)

    def test_postopen_redirect_metadata_is_rejected_before_read(self) -> None:
        path = Path("resume.json")
        validated = _fake_stat()
        redirected = _fake_stat(mode=stat.S_IFLNK | 0o777)

        with mock.patch.object(
            Path,
            "lstat",
            autospec=True,
            side_effect=[validated, redirected],
        ), mock.patch.object(
            gametree_resume.os,
            "open",
            return_value=123,
        ), mock.patch.object(
            gametree_resume.os,
            "fstat",
            return_value=validated,
        ), mock.patch.object(
            gametree_resume.os,
            "read",
        ) as read, mock.patch.object(
            gametree_resume.os,
            "close",
        ):
            with self.assertRaises(GameTreeResumeError) as caught:
                gametree_resume._read_store_bytes(path)

        self.assertEqual(caught.exception.code, GameTreeResumeCode.STALE_WRITER)
        read.assert_not_called()

    def test_in_place_write_during_read_is_rejected(self) -> None:
        path = Path("resume.json")
        before = _fake_stat(size=3, mtime_ns=100, ctime_ns=90)
        after = _fake_stat(size=3, mtime_ns=200, ctime_ns=190)

        with mock.patch.object(
            Path,
            "lstat",
            autospec=True,
            side_effect=[before, before, after],
        ), mock.patch.object(
            gametree_resume.os,
            "open",
            return_value=123,
        ), mock.patch.object(
            gametree_resume.os,
            "fstat",
            side_effect=[before, after],
        ), mock.patch.object(
            gametree_resume.os,
            "read",
            side_effect=[b"abc", b""],
        ), mock.patch.object(
            gametree_resume.os,
            "close",
        ):
            with self.assertRaises(GameTreeResumeError) as caught:
                gametree_resume._read_store_bytes(path)

        self.assertEqual(caught.exception.code, GameTreeResumeCode.STALE_WRITER)

    def test_path_replacement_after_read_is_rejected(self) -> None:
        path = Path("resume.json")
        opened = _fake_stat(dev=4, ino=5)
        replacement = _fake_stat(dev=4, ino=6)

        with mock.patch.object(
            Path,
            "lstat",
            autospec=True,
            side_effect=[opened, opened, replacement],
        ), mock.patch.object(
            gametree_resume.os,
            "open",
            return_value=123,
        ), mock.patch.object(
            gametree_resume.os,
            "fstat",
            side_effect=[opened, opened],
        ), mock.patch.object(
            gametree_resume.os,
            "read",
            side_effect=[b"abc", b""],
        ), mock.patch.object(
            gametree_resume.os,
            "close",
        ):
            with self.assertRaises(GameTreeResumeError) as caught:
                gametree_resume._read_store_bytes(path)

        self.assertEqual(caught.exception.code, GameTreeResumeCode.STALE_WRITER)

    def test_growth_past_limit_after_validation_is_rejected_before_read(self) -> None:
        path = Path("resume.json")
        validated = _fake_stat(size=1)
        oversized = _fake_stat(
            size=gametree_resume.MAX_RESUME_RECORD_BYTES + 2
        )

        with mock.patch.object(
            Path,
            "lstat",
            autospec=True,
            side_effect=[validated, oversized],
        ), mock.patch.object(
            gametree_resume.os,
            "open",
            return_value=123,
        ), mock.patch.object(
            gametree_resume.os,
            "fstat",
            return_value=oversized,
        ), mock.patch.object(
            gametree_resume.os,
            "read",
        ) as read, mock.patch.object(
            gametree_resume.os,
            "close",
        ):
            with self.assertRaises(GameTreeResumeError) as caught:
                gametree_resume._read_store_bytes(path)

        self.assertEqual(caught.exception.code, GameTreeResumeCode.RESOURCE_LIMIT)
        read.assert_not_called()

    @unittest.skipIf(os.name == "nt", "POSIX no-follow descriptor regression")
    def test_symlink_swap_before_open_never_reads_target(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            path = root / "resume.json"
            target = root / "foreign.json"
            path.write_bytes(b"old")
            target.write_bytes(b"foreign")
            original_open = gametree_resume.os.open
            original_read = gametree_resume.os.read
            read_called = False

            def swap_then_open(candidate: os.PathLike[str] | str, flags: int) -> int:
                nonlocal read_called
                path.unlink()
                path.symlink_to(target)
                return original_open(candidate, flags)

            def observe_read(fd: int, amount: int) -> bytes:
                nonlocal read_called
                read_called = True
                return original_read(fd, amount)

            with mock.patch.object(
                gametree_resume.os,
                "open",
                side_effect=swap_then_open,
            ), mock.patch.object(
                gametree_resume.os,
                "read",
                side_effect=observe_read,
            ):
                with self.assertRaises(GameTreeResumeError) as caught:
                    gametree_resume._read_store_bytes(path)

            self.assertEqual(caught.exception.code, GameTreeResumeCode.IO_FAILURE)
            self.assertFalse(read_called)


if __name__ == "__main__":
    unittest.main()
