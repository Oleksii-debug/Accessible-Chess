import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from acs.gametree import parse_games
from acs.pgn_service import PgnConcurrentWriteError, open_pgn, save_pgn_atomic


class Dev4PgnExportConcurrencySecurityTests(unittest.TestCase):
    def test_expected_hash_rechecks_at_atomic_commit_boundary(self):
        """A writer racing after preflight must not be silently overwritten.

        The public contract says ``expected_sha256`` protects a file opened
        earlier from lost updates.  Mutating the destination immediately before
        the atomic replacement deterministically models the TOCTOU window
        between the current implementation's preflight hash and ``os.replace``.
        A safe implementation must detect that newer content and preserve it.
        """

        games = parse_games('[Event "Original"]\n[Result "*"]\n\n1. e4 *\n')
        with tempfile.TemporaryDirectory() as tmp:
            destination = Path(tmp) / "shared.pgn"
            destination.write_text(
                '[Event "Original"]\n[Result "*"]\n\n1. e4 *\n',
                encoding="utf-8",
            )
            opened = open_pgn(destination)
            real_replace = os.replace

            def concurrent_replace(src, dst):
                Path(dst).write_text(
                    '[Event "Concurrent writer"]\n[Result "*"]\n\n1. d4 *\n',
                    encoding="utf-8",
                )
                return real_replace(src, dst)

            with mock.patch("acs.pgn_service.os.replace", side_effect=concurrent_replace):
                with self.assertRaises(PgnConcurrentWriteError):
                    save_pgn_atomic(
                        destination,
                        games,
                        overwrite=True,
                        expected_sha256=opened.source.sha256,
                    )

            self.assertIn(
                "Concurrent writer",
                destination.read_text(encoding="utf-8"),
                "A concurrent destination update must survive a rejected stale save.",
            )

    def test_no_overwrite_mode_rechecks_nonexistence_at_commit_boundary(self):
        """``overwrite=False`` must not clobber a file created after preflight.

        The implementation publishes through ``os.link``. Creating the
        destination immediately before that exact commit primitive models a
        second writer winning the race after the initial ``exists()`` check.
        A safe implementation must preserve that file and refuse the commit.
        """

        games = parse_games('[Event "Our export"]\n[Result "*"]\n\n1. e4 *\n')
        with tempfile.TemporaryDirectory() as tmp:
            destination = Path(tmp) / "new-shared.pgn"
            real_link = os.link

            def concurrent_create(src, dst, *args, **kwargs):
                Path(dst).write_text(
                    '[Event "Created by another writer"]\n[Result "*"]\n\n1. d4 *\n',
                    encoding="utf-8",
                )
                return real_link(src, dst, *args, **kwargs)

            with mock.patch("acs.pgn_service.os.link", side_effect=concurrent_create):
                with self.assertRaises(FileExistsError):
                    save_pgn_atomic(destination, games, overwrite=False)

            self.assertIn(
                "Created by another writer",
                destination.read_text(encoding="utf-8"),
                "Default no-overwrite mode must preserve a destination created by a racing writer.",
            )


if __name__ == "__main__":
    unittest.main()
