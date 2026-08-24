from pathlib import Path
import tempfile
import unittest
from unittest import mock

from acs.gametree import parse_games
from acs.pgn_service import (
    PgnConcurrentWriteError,
    _save_lock_path,
    open_pgn,
    save_pgn_atomic,
)


PGN_A = '[Event "A"]\n[Result "*"]\n\n1. e4 *\n'
PGN_B = '[Event "B"]\n[Result "*"]\n\n1. d4 *\n'
PGN_EXTERNAL = '[Event "EXTERNAL"]\n[Result "*"]\n\n1. c4 *\n'


class PgnConcurrentSaveTests(unittest.TestCase):
    def game(self, text=PGN_B):
        return parse_games(text)[0]

    def test_stale_before_transaction_is_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'game.pgn'
            path.write_text(PGN_A, encoding='utf-8')
            opened = open_pgn(path)
            path.write_text(PGN_EXTERNAL, encoding='utf-8')

            with self.assertRaises(PgnConcurrentWriteError):
                save_pgn_atomic(
                    path,
                    (self.game(),),
                    overwrite=True,
                    expected_sha256=opened.source.sha256,
                )

            self.assertEqual(path.read_text(encoding='utf-8'), PGN_EXTERNAL)
            self.assertFalse(_save_lock_path(path).exists())

    def test_external_write_after_preflight_before_commit_is_not_lost(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'game.pgn'
            path.write_text(PGN_A, encoding='utf-8')
            opened = open_pgn(path)
            from acs import pgn_service

            real_verify = pgn_service._verify_expected_version
            injected = {'done': False}
            verify_calls = {'count': 0}

            def verify_with_race(destination, expected_sha256):
                verify_calls['count'] += 1
                # The first call is transaction preflight. Inject immediately
                # before the second, commit-time check so this oracle has the
                # same exact timing on Windows and POSIX without /proc or fd
                # path introspection.
                if verify_calls['count'] == 2:
                    injected['done'] = True
                    path.write_text(PGN_EXTERNAL, encoding='utf-8')
                return real_verify(destination, expected_sha256)

            with mock.patch(
                'acs.pgn_service._verify_expected_version',
                side_effect=verify_with_race,
            ):
                with self.assertRaises(PgnConcurrentWriteError):
                    save_pgn_atomic(
                        path,
                        (self.game(),),
                        overwrite=True,
                        expected_sha256=opened.source.sha256,
                    )

            self.assertTrue(injected['done'])
            self.assertEqual(verify_calls['count'], 2)
            self.assertEqual(path.read_text(encoding='utf-8'), PGN_EXTERNAL)
            self.assertFalse(_save_lock_path(path).exists())
            self.assertEqual(list(Path(folder).glob('game.pgn.*.tmp')), [])

    def test_active_sidecar_lock_fails_closed_without_touching_destination(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'game.pgn'
            path.write_text(PGN_A, encoding='utf-8')
            opened = open_pgn(path)
            lock = _save_lock_path(path)
            lock.write_text('pid=someone-else\n', encoding='ascii')

            with self.assertRaises(PgnConcurrentWriteError):
                save_pgn_atomic(
                    path,
                    (self.game(),),
                    overwrite=True,
                    expected_sha256=opened.source.sha256,
                )

            self.assertEqual(path.read_text(encoding='utf-8'), PGN_A)
            self.assertTrue(lock.exists())

    def test_normal_expected_sha_save_releases_lock_and_round_trips(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'game.pgn'
            path.write_text(PGN_A, encoding='utf-8')
            opened = open_pgn(path)

            saved = save_pgn_atomic(
                path,
                (self.game(),),
                overwrite=True,
                expected_sha256=opened.source.sha256,
            )

            self.assertEqual(saved.sha256, open_pgn(path).source.sha256)
            self.assertEqual(open_pgn(path).games[0].tags['Event'], 'B')
            self.assertFalse(_save_lock_path(path).exists())


if __name__ == '__main__':
    unittest.main()
