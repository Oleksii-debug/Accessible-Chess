from __future__ import annotations

import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from acs.gametree import parse_games
from acs.pgn_service import PgnFileError, open_pgn, save_pgn_atomic


class Dev4PgnExportFailureRecoveryTests(unittest.TestCase):
    """QA evidence for atomic-export failure cleanup and original-file safety."""

    def _games(self):
        return parse_games('[Event "Recovery"]\n[Result "*"]\n\n1. e4 *\n')

    def test_replace_failure_preserves_existing_destination_and_cleans_temp(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            destination = root / "existing.pgn"
            original = '[Event "Original"]\n[Result "*"]\n\n1. d4 *\n'
            destination.write_text(original, encoding="utf-8")

            with mock.patch("acs.pgn_service.os.replace", side_effect=OSError("replace failed")):
                with self.assertRaises(OSError):
                    save_pgn_atomic(destination, self._games(), overwrite=True)

            self.assertEqual(destination.read_text(encoding="utf-8"), original)
            self.assertEqual(
                list(root.glob(destination.name + ".*.tmp")),
                [],
                "A failed atomic replace must not leave a stale PGN temp file behind.",
            )

    def test_expected_hash_replace_failure_cleans_temp_and_cas_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            destination = root / "expected.pgn"
            original = '[Event "Original"]\n[Result "*"]\n\n1. d4 *\n'
            destination.write_text(original, encoding="utf-8")
            expected_sha256 = open_pgn(destination).source.sha256

            with mock.patch("acs.pgn_service.os.replace", side_effect=OSError("replace failed")):
                with self.assertRaises(OSError):
                    save_pgn_atomic(
                        destination,
                        self._games(),
                        overwrite=True,
                        expected_sha256=expected_sha256,
                    )

            self.assertEqual(destination.read_text(encoding="utf-8"), original)
            self.assertEqual(list(root.glob(destination.name + ".*.tmp")), [])
            self.assertEqual(
                list(root.glob(destination.name + ".cas-*.bak")),
                [],
                "A failed expected-hash publication must remove its recoverable CAS snapshot.",
            )

    def test_no_clobber_link_failure_cleans_temp_and_publishes_nothing(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            destination = root / "new.pgn"

            with mock.patch("acs.pgn_service.os.link", side_effect=OSError("hard links unavailable")):
                with self.assertRaises(PgnFileError):
                    save_pgn_atomic(destination, self._games(), overwrite=False)

            self.assertFalse(destination.exists())
            self.assertEqual(
                list(root.glob(destination.name + ".*.tmp")),
                [],
                "A failed no-clobber publication must clean its complete temp file.",
            )

    def test_fsync_failure_preserves_existing_destination_and_cleans_temp(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            destination = root / "existing.pgn"
            original = '[Event "Original"]\n[Result "*"]\n\n1. c4 *\n'
            destination.write_text(original, encoding="utf-8")

            with mock.patch("acs.pgn_service.os.fsync", side_effect=OSError("fsync failed")):
                with self.assertRaises(OSError):
                    save_pgn_atomic(destination, self._games(), overwrite=True)

            self.assertEqual(destination.read_text(encoding="utf-8"), original)
            self.assertEqual(
                list(root.glob(destination.name + ".*.tmp")),
                [],
                "A failed temp-file fsync must clean the incomplete PGN temp file.",
            )

    @unittest.skipIf(os.name == "nt", "POSIX temp-mode assertion is not portable to Windows ACL semantics")
    def test_temp_file_is_not_group_or_world_readable_before_commit(self) -> None:
        observed_mode = None
        real_link = os.link

        def inspect_then_link(src, dst, *args, **kwargs):
            nonlocal observed_mode
            observed_mode = Path(src).stat().st_mode & 0o777
            return real_link(src, dst, *args, **kwargs)

        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / "private.pgn"
            with mock.patch("acs.pgn_service.os.link", side_effect=inspect_then_link):
                save_pgn_atomic(destination, self._games())

        self.assertIsNotNone(observed_mode)
        self.assertEqual(
            observed_mode & 0o077,
            0,
            f"PGN temp file exposed group/world permission bits: {observed_mode:o}",
        )


if __name__ == "__main__":
    unittest.main()
