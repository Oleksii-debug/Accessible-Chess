from __future__ import annotations

import builtins
from pathlib import Path
import tempfile
import unittest
from unittest import mock

import acs.gametree_resume as gametree_resume
from acs.gametree_resume import GameTreeResumeCode, GameTreeResumeError


class ResumeLockToctouTests(unittest.TestCase):
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
