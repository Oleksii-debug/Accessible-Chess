from __future__ import annotations

import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from acs.gametree import parse_games
from acs.pgn_service import save_pgn_atomic


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
        real_replace = os.replace

        def inspect_then_replace(src, dst):
            nonlocal observed_mode
            observed_mode = Path(src).stat().st_mode & 0o777
            return real_replace(src, dst)

        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / "private.pgn"
            with mock.patch("acs.pgn_service.os.replace", side_effect=inspect_then_replace):
                save_pgn_atomic(destination, self._games())

        self.assertIsNotNone(observed_mode)
        self.assertEqual(
            observed_mode & 0o077,
            0,
            f"PGN temp file exposed group/world permission bits: {observed_mode:o}",
        )


if __name__ == "__main__":
    unittest.main()
