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

        Mutating the destination immediately before the replacement models the
        final publication window. A safe implementation must detect the newer
        bytes, preserve them, and reject the stale save.
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

    def test_no_overwrite_mode_is_atomic_at_real_publication_boundary(self):
        """``overwrite=False`` must preserve a destination won by another writer.

        The Product implementation now uses same-directory hard-link creation as
        its atomic no-clobber primitive. Inject the competing create immediately
        before that primitive rather than patching the obsolete replace path.
        The safety assertion is unchanged: the competing file must survive and
        our save must fail with ``FileExistsError``.
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
