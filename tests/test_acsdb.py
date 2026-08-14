import unittest

from acs.acsdb import AcsDatabase


class AcsDatabaseTests(unittest.TestCase):
    def setUp(self):
        self.db = AcsDatabase(':memory:')

    def tearDown(self):
        self.db.close()

    def test_import_report_and_provenance_are_explicit(self):
        text = '''[Event "Match"]
[White "Alpha"]
[Black "Beta"]
[Result "1-0"]
[ECO "C20"]

1. e4 e5 1-0

[Event "Warning game"]
[White "Gamma"]
[Black "Delta"]
[Result "1-0"]

1. d4 0-1
'''
        report = self.db.import_pgn_text(text, 'sample.pgn')
        self.assertEqual(report.total, 2)
        self.assertEqual(report.full, 1)
        self.assertEqual(report.warning, 1)
        self.assertEqual(report.partial, 0)
        self.assertEqual(report.damaged, 0)
        source = self.db.get_source(report.source_id)
        self.assertEqual(source['source_name'], 'sample.pgn')
        self.assertEqual(source['source_format'], 'pgn')
        self.assertEqual(len(source['sha256']), 64)
        warning_game = self.db.get_game(report.game_ids[1])
        self.assertEqual(warning_game['import_status'], 'warning')
        self.assertIn('differs', warning_game['warnings_json'])

    def test_tag_search_is_case_insensitive_and_indexable(self):
        text = '''[Event "Candidates"]
[White "Carlsen, Magnus"]
[Black "Nepomniachtchi, Ian"]
[Result "1/2-1/2"]
[ECO "B30"]

1. e4 c5 1/2-1/2
'''
        self.db.import_pgn_text(text, 'players.pgn')
        self.assertEqual(len(self.db.search_games(player='carlsen')), 1)
        self.assertEqual(len(self.db.search_games(event='candidates', eco='B3')), 1)
        self.assertEqual(len(self.db.search_games(result='1-0')), 0)

    def test_exact_position_reference_ignores_move_counters_only(self):
        report = self.db.import_pgn_text('[Event "P"]\n[Result "*"]\n\n1. e4 *', 'position.pgn')
        game_id = report.game_ids[0]
        fen = 'rnbqkbnr/pppp1ppp/8/4p3/4P3/8/PPPP1PPP/RNBQKBNR w KQkq e6 0 2'
        self.db.record_position(game_id, 2, fen)
        same_position_different_counters = 'rnbqkbnr/pppp1ppp/8/4p3/4P3/8/PPPP1PPP/RNBQKBNR w KQkq e6 17 99'
        matches = self.db.search_position(same_position_different_counters)
        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0]['matched_ply'], 2)
        different_turn = 'rnbqkbnr/pppp1ppp/8/4p3/4P3/8/PPPP1PPP/RNBQKBNR b KQkq e6 0 2'
        self.assertEqual(self.db.search_position(different_turn), [])

    def test_blank_import_is_reported_as_damaged_not_silent_success(self):
        report = self.db.import_pgn_text('', 'empty.pgn')
        self.assertEqual(report.total, 1)
        self.assertEqual(report.damaged, 1)
        self.assertEqual(report.game_ids, [])

    def test_invalid_status_is_rejected(self):
        from acs.gametree import parse_games
        game = parse_games('[Result "*"]\n\n1. e4 *')[0]
        source_id = self.db.add_source('x.pgn', 'pgn')
        with self.assertRaises(ValueError):
            self.db.store_game(game, source_id, import_status='magic')


if __name__ == '__main__':
    unittest.main()
