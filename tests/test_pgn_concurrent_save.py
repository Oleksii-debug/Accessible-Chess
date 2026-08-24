import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from acs.gametree import parse_games
from acs.pgn_service import PgnConcurrentWriteError, open_pgn, save_pgn_atomic


PGN_A = '[Event "A"]\n[Result "*"]\n\n1. e4 *\n'
PGN_B = '[Event "B"]\n[Result "*"]\n\n1. d4 *\n'
PGN_EXTERNAL = '[Event "EXTERNAL"]\n[Result "*"]\n\n1. c4 *\n'


class PgnConcurrentSaveTests(unittest.TestCase):
    """Portable oracles for the current no-clobber/CAS publication primitives."""

    def game(self, text=PGN_B):
        return parse_games(text)[0]

    def assert_no_transaction_debris(self, folder: str, name: str) -> None:
        root = Path(folder)
        self.assertEqual(list(root.glob(name + ".*.tmp")), [])
        self.assertEqual(list(root.glob(name + ".cas-*.bak")), [])

    def test_stale_before_transaction_is_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "game.pgn"
            path.write_text(PGN_A, encoding="utf-8")
            opened = open_pgn(path)
            path.write_text(PGN_EXTERNAL, encoding="utf-8")

            with self.assertRaises(PgnConcurrentWriteError):
                save_pgn_atomic(
                    path,
                    (self.game(),),
                    overwrite=True,
                    expected_sha256=opened.source.sha256,
                )

            self.assertEqual(path.read_text(encoding="utf-8"), PGN_EXTERNAL)
            self.assert_no_transaction_debris(folder, path.name)

    def test_external_write_at_publish_boundary_is_restored(self):
        """The writer that reaches the old inode at ``os.replace`` must win."""

        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "game.pgn"
            path.write_text(PGN_A, encoding="utf-8")
            opened = open_pgn(path)
            real_replace = os.replace
            replace_calls = 0

            def replace_with_race(src, dst):
                nonlocal replace_calls
                replace_calls += 1
                if replace_calls == 1:
                    # The CAS snapshot is a hard link to this inode. Mutating it
                    # here models the last portable boundary before publication.
                    path.write_text(PGN_EXTERNAL, encoding="utf-8")
                return real_replace(src, dst)

            with mock.patch("acs.pgn_service.os.replace", side_effect=replace_with_race):
                with self.assertRaises(PgnConcurrentWriteError):
                    save_pgn_atomic(
                        path,
                        (self.game(),),
                        overwrite=True,
                        expected_sha256=opened.source.sha256,
                    )

            self.assertEqual(replace_calls, 2, "publish plus conflict rollback")
            self.assertEqual(path.read_text(encoding="utf-8"), PGN_EXTERNAL)
            self.assert_no_transaction_debris(folder, path.name)

    def test_no_overwrite_race_uses_actual_link_commit_primitive(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "new-game.pgn"
            real_link = os.link

            def link_with_race(src, dst, *args, **kwargs):
                path.write_text(PGN_EXTERNAL, encoding="utf-8")
                return real_link(src, dst, *args, **kwargs)

            with mock.patch("acs.pgn_service.os.link", side_effect=link_with_race):
                with self.assertRaises(FileExistsError):
                    save_pgn_atomic(path, (self.game(),), overwrite=False)

            self.assertEqual(path.read_text(encoding="utf-8"), PGN_EXTERNAL)
            self.assert_no_transaction_debris(folder, path.name)

    def test_normal_expected_sha_save_round_trips_without_debris(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "game.pgn"
            path.write_text(PGN_A, encoding="utf-8")
            opened = open_pgn(path)

            saved = save_pgn_atomic(
                path,
                (self.game(),),
                overwrite=True,
                expected_sha256=opened.source.sha256,
            )

            self.assertEqual(saved.sha256, open_pgn(path).source.sha256)
            self.assertEqual(open_pgn(path).games[0].tags["Event"], "B")
            self.assert_no_transaction_debris(folder, path.name)


if __name__ == "__main__":
    unittest.main()
