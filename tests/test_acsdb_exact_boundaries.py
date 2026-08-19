import unittest

from acs.acsdb import AcsDatabase
from acs.gametree import parse_games


PGN = '[Event "Exact"]\n[White "Alice"]\n[Black "Bob"]\n[Result "*"]\n\n1. e4 *\n'
VALID_FEN = '8/8/8/8/8/8/8/8 w - - 0 1'
VALID_FEN_COUNTERS = '8/8/8/8/8/8/8/8 w - - 17 42'
VALID_FEN_BLACK = '8/8/8/8/8/8/8/8 b - - 0 1'


class AcsDatabaseExactBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.db = AcsDatabase()
        self.source_id = self.db.add_source('source.pgn', 'pgn')
        self.game = parse_games(PGN)[0]
        self.game_id = self.db.store_game(self.game, self.source_id)
        report = self.db.import_pgn_text(PGN, 'attempt.pgn')
        self.attempt_id = report.attempt_id

    def tearDown(self):
        self.db.close()

    def test_public_ids_reject_python_scalar_coercion(self):
        invalid = (True, 1.0, '1')
        for value in invalid:
            with self.subTest(api='get_game', value=value):
                with self.assertRaises(TypeError):
                    self.db.get_game(value)
            with self.subTest(api='get_source', value=value):
                with self.assertRaises(TypeError):
                    self.db.get_source(value)
            with self.subTest(api='get_import_attempt', value=value):
                with self.assertRaises(TypeError):
                    self.db.get_import_attempt(value)
            with self.subTest(api='store_game', value=value):
                with self.assertRaises(TypeError):
                    self.db.store_game(self.game, value)
            with self.subTest(api='record_position', value=value):
                with self.assertRaises(TypeError):
                    self.db.record_position(value, 0, VALID_FEN)
            with self.subTest(api='record_positions', value=value):
                with self.assertRaises(TypeError):
                    self.db.record_positions(value, [(0, VALID_FEN)])
            with self.subTest(api='search_games', value=value):
                with self.assertRaises(TypeError):
                    self.db.search_games(source_id=value)

    def test_nonpositive_ids_fail_before_sql(self):
        for value in (0, -1):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    self.db.get_game(value)
                with self.assertRaises(ValueError):
                    self.db.record_position(value, 0, VALID_FEN)

    def test_limits_reject_coercible_values_but_keep_integer_clamp(self):
        for value in (True, 2.5, '2'):
            with self.subTest(value=value):
                with self.assertRaises(TypeError):
                    self.db.list_import_attempts(limit=value)
                with self.assertRaises(TypeError):
                    self.db.search_games(limit=value)
                with self.assertRaises(TypeError):
                    self.db.search_position(VALID_FEN, limit=value)
        self.assertLessEqual(len(self.db.search_games(limit=0)), 1)
        self.assertLessEqual(len(self.db.search_games(limit=5000)), 1000)

    def test_ply_rejects_bool_float_string_and_negative(self):
        for value in (True, 1.0, '1'):
            with self.subTest(value=value):
                with self.assertRaises(TypeError):
                    self.db.record_position(self.game_id, value, VALID_FEN)
        with self.assertRaises(ValueError):
            self.db.record_position(self.game_id, -1, VALID_FEN)

    def test_position_key_requires_structurally_valid_full_fen(self):
        invalid = (
            '8/8/8/8/8/8/8/7X w - - 0 1',
            '8/8/8/8/8/8/8/8 x - - 0 1',
            '8/8/8/8/8/8/8/8 w KZ - 0 1',
            '8/8/8/8/8/8/8/8 w - z9 0 1',
            '8/8/8/8/8/8/8/8 w - - -1 1',
            '8/8/8/8/8/8/8/8 w - - 0 0',
            '8/8/8/8/8/8/8/8 w - -',
        )
        for fen in invalid:
            with self.subTest(fen=fen):
                with self.assertRaises(ValueError):
                    self.db.position_key(fen)
                with self.assertRaises(ValueError):
                    self.db.record_position(self.game_id, 0, fen)
                with self.assertRaises(ValueError):
                    self.db.search_position(fen)
        for fen in (None, True, b'fen'):
            with self.subTest(fen=fen):
                with self.assertRaises(TypeError):
                    self.db.position_key(fen)

    def test_position_index_ignores_only_move_counters(self):
        self.db.record_position(self.game_id, 0, VALID_FEN)
        matches = self.db.search_position(VALID_FEN_COUNTERS)
        self.assertEqual([row['id'] for row in matches], [self.game_id])
        self.assertEqual(matches[0]['matched_fen'], VALID_FEN)

    def test_batch_position_validation_is_atomic_before_database_write(self):
        before = self.db.conn.execute(
            'SELECT COUNT(*) FROM positions WHERE game_id=?',
            (self.game_id,),
        ).fetchone()[0]
        with self.assertRaises(ValueError):
            self.db.record_positions(
                self.game_id,
                [(0, VALID_FEN), (1, 'not a fen')],
            )
        after = self.db.conn.execute(
            'SELECT COUNT(*) FROM positions WHERE game_id=?',
            (self.game_id,),
        ).fetchone()[0]
        self.assertEqual(after, before)

    def test_batch_rows_and_ply_values_are_exact(self):
        with self.assertRaises(TypeError):
            self.db.record_positions(self.game_id, [[0, VALID_FEN]])
        with self.assertRaises(TypeError):
            self.db.record_positions(self.game_id, [(True, VALID_FEN)])

    def test_batch_rejects_conflicting_duplicate_ply_before_sql(self):
        with self.assertRaisesRegex(ValueError, 'duplicate ply'):
            self.db.record_positions(
                self.game_id,
                [(0, VALID_FEN), (0, VALID_FEN_BLACK)],
            )
        count = self.db.conn.execute(
            'SELECT COUNT(*) FROM positions WHERE game_id=?',
            (self.game_id,),
        ).fetchone()[0]
        self.assertEqual(count, 0)

    def test_batch_rejects_identical_duplicate_ply_before_sql(self):
        with self.assertRaisesRegex(ValueError, 'duplicate ply'):
            self.db.record_positions(
                self.game_id,
                [(0, VALID_FEN), (0, VALID_FEN)],
            )
        count = self.db.conn.execute(
            'SELECT COUNT(*) FROM positions WHERE game_id=?',
            (self.game_id,),
        ).fetchone()[0]
        self.assertEqual(count, 0)

    def test_duplicate_batch_preserves_preexisting_position_rows(self):
        self.db.record_positions(
            self.game_id,
            [(4, VALID_FEN), (5, VALID_FEN_BLACK)],
        )
        before = self.db.conn.execute(
            'SELECT ply, fen, position_key FROM positions WHERE game_id=? ORDER BY ply',
            (self.game_id,),
        ).fetchall()

        with self.assertRaisesRegex(ValueError, 'duplicate ply'):
            self.db.record_positions(
                self.game_id,
                [(4, VALID_FEN_BLACK), (4, VALID_FEN)],
            )

        after = self.db.conn.execute(
            'SELECT ply, fen, position_key FROM positions WHERE game_id=? ORDER BY ply',
            (self.game_id,),
        ).fetchall()
        self.assertEqual([tuple(row) for row in after], [tuple(row) for row in before])

    def test_batch_with_unique_ply_values_still_succeeds(self):
        self.db.record_positions(
            self.game_id,
            [(0, VALID_FEN), (1, VALID_FEN_BLACK)],
        )
        rows = self.db.conn.execute(
            'SELECT ply, fen FROM positions WHERE game_id=? ORDER BY ply',
            (self.game_id,),
        ).fetchall()
        self.assertEqual(
            [tuple(row) for row in rows],
            [(0, VALID_FEN), (1, VALID_FEN_BLACK)],
        )

    def test_text_filters_and_import_entry_points_do_not_coerce(self):
        for kwargs in ({'player': True}, {'event': 3}, {'eco': b'C20'}, {'source_name': []}):
            with self.subTest(kwargs=kwargs):
                with self.assertRaises(TypeError):
                    self.db.search_games(**kwargs)
        with self.assertRaises(TypeError):
            self.db.import_pgn_text(b'not text')
        with self.assertRaises(TypeError):
            self.db.add_source('name', 7)

    def test_store_game_validates_mutated_gametree_even_with_raw_pgn(self):
        game = parse_games(PGN)[0]
        game.line.moves[0].san = ''
        with self.assertRaises(ValueError):
            self.db.store_game(game, self.source_id, raw_pgn=PGN)


if __name__ == '__main__':
    unittest.main()
