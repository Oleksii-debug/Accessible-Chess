import unittest

from acs.acsdb import AcsDatabase


class Dev3AcsdbPositionProvenanceTests(unittest.TestCase):
    def setUp(self):
        self.db = AcsDatabase(':memory:')

    def tearDown(self):
        self.db.close()

    def _import_game(self, source_name: str, event: str, move: str):
        return self.db.import_pgn_text(
            f'[Event "{event}"]\n[Result "*"]\n\n1. {move} *',
            source_name,
        )

    def test_game_search_rows_include_source_provenance(self):
        report = self._import_game('provenance.pgn', 'Provenance', 'e4')
        row = self.db.search_games(event='provenance')[0]

        source = self.db.get_source(report.source_id)
        self.assertEqual(row['source_name'], 'provenance.pgn')
        self.assertEqual(row['source_format'], 'pgn')
        self.assertEqual(row['source_sha256'], source['sha256'])
        self.assertEqual(row['source_imported_at'], source['imported_at'])

    def test_exact_position_keyset_paging_is_stable_under_late_rows(self):
        first = self._import_game('one.pgn', 'One', 'e4')
        second = self._import_game('two.pgn', 'Two', 'd4')
        third = self._import_game('three.pgn', 'Three', 'c4')
        fen = '8/8/8/8/8/8/8/8 w - - 0 1'

        self.db.record_position(first.game_ids[0], 1, fen)
        self.db.record_position(second.game_ids[0], 1, fen)
        self.db.record_position(third.game_ids[0], 1, fen)

        page1 = self.db.search_position(fen, limit=2)
        self.assertEqual(
            [(row['id'], row['matched_ply']) for row in page1],
            [(first.game_ids[0], 1), (second.game_ids[0], 1)],
        )

        # Insert a matching row behind the cursor and another one ahead of it.
        self.db.record_position(first.game_ids[0], 2, fen)
        later = self._import_game('later.pgn', 'Later', 'Nf3')
        self.db.record_position(later.game_ids[0], 1, fen)

        cursor = page1[-1]
        page2 = self.db.search_position(
            fen,
            after_game_id=cursor['id'],
            after_ply=cursor['matched_ply'],
            limit=10,
        )
        self.assertEqual(
            [(row['id'], row['matched_ply']) for row in page2],
            [(third.game_ids[0], 1), (later.game_ids[0], 1)],
        )
        self.assertTrue(
            set((row['id'], row['matched_ply']) for row in page1).isdisjoint(
                (row['id'], row['matched_ply']) for row in page2
            )
        )

    def test_position_search_rows_include_source_provenance(self):
        report = self._import_game('position-source.pgn', 'Position', 'e4')
        fen = '8/8/8/8/8/8/8/8 b - - 0 1'
        self.db.record_position(report.game_ids[0], 7, fen)

        row = self.db.search_position(fen)[0]
        source = self.db.get_source(report.source_id)
        self.assertEqual(row['source_name'], 'position-source.pgn')
        self.assertEqual(row['source_format'], 'pgn')
        self.assertEqual(row['source_sha256'], source['sha256'])
        self.assertEqual(row['source_imported_at'], source['imported_at'])

    def test_position_cursor_requires_complete_non_boolean_pair(self):
        fen = '8/8/8/8/8/8/8/8 w - - 0 1'
        with self.assertRaises(ValueError):
            self.db.search_position(fen, after_game_id=1)
        with self.assertRaises(ValueError):
            self.db.search_position(fen, after_ply=1)
        with self.assertRaises(TypeError):
            self.db.search_position(fen, after_game_id=True, after_ply=0)
        with self.assertRaises(TypeError):
            self.db.search_position(fen, after_game_id=1, after_ply=False)
        with self.assertRaises(ValueError):
            self.db.search_position(fen, after_game_id=-1, after_ply=0)


if __name__ == '__main__':
    unittest.main()
