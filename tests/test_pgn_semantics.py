import unittest

from acs.gametree import PgnGame, parse_games
from acs.pgn_semantics import (
    DiagnosticSeverity,
    PgnDiagnosticCode,
    analyze_game,
    analyze_games,
)


class PgnSemanticTests(unittest.TestCase):
    def test_setup_fen_is_projected_without_mutating_game(self):
        game = parse_games(
            '[SetUp "1"]\n[FEN "8/8/8/8/8/8/8/K6k w - - 0 1"]\n[Result "*"]\n\n*\n'
        )[0]
        before = dict(game.tags)
        record = analyze_game(game)
        self.assertTrue(record.setup.enabled)
        self.assertEqual(record.setup.fen, '8/8/8/8/8/8/8/K6k w - - 0 1')
        self.assertEqual(game.tags, before)
        self.assertTrue(record.usable)

    def test_setup_without_fen_is_error(self):
        game = parse_games('[SetUp "1"]\n[Result "*"]\n\n*\n')[0]
        record = analyze_game(game)
        self.assertFalse(record.usable)
        error = next(d for d in record.diagnostics if d.code is PgnDiagnosticCode.SETUP_REQUIRES_FEN)
        self.assertIs(error.severity, DiagnosticSeverity.ERROR)
        self.assertEqual(error.field, 'FEN')
        self.assertEqual(record.error_count, 1)

    def test_fen_without_setup_is_preserved_but_not_silently_enabled(self):
        game = parse_games('[FEN "8/8/8/8/8/8/8/K6k w - - 0 1"]\n[Result "*"]\n\n*\n')[0]
        record = analyze_game(game)
        self.assertFalse(record.setup.enabled)
        self.assertIsNotNone(record.setup.fen)
        self.assertTrue(record.usable)
        self.assertIn(PgnDiagnosticCode.FEN_WITHOUT_SETUP, {d.code for d in record.diagnostics})

    def test_invalid_setup_value_fails_closed(self):
        game = parse_games('[SetUp "yes"]\n[FEN "8/8/8/8/8/8/8/K6k w - - 0 1"]\n[Result "*"]\n\n*\n')[0]
        record = analyze_game(game)
        self.assertFalse(record.setup.enabled)
        self.assertFalse(record.usable)
        self.assertIn(PgnDiagnosticCode.INVALID_SETUP, {d.code for d in record.diagnostics})

    def test_invalid_result_tag_is_typed_error(self):
        game = parse_games('[Result "abandoned"]\n\n1. e4 *\n')[0]
        record = analyze_game(game)
        self.assertFalse(record.usable)
        diagnostic = next(d for d in record.diagnostics if d.code is PgnDiagnosticCode.INVALID_RESULT)
        self.assertEqual(diagnostic.field, 'Result')

    def test_result_mismatch_keeps_parser_evidence_with_stable_code(self):
        game = parse_games('[Result "1-0"]\n\n1. e4 0-1\n')[0]
        record = analyze_game(game)
        mismatch = next(d for d in record.diagnostics if d.code is PgnDiagnosticCode.RESULT_MISMATCH)
        self.assertIn('differs', mismatch.message)
        self.assertEqual(mismatch.field, 'Result')
        self.assertEqual(record.result, '0-1')
        self.assertEqual(record.tags.get('Result'), '1-0')

    def test_parser_diagnostics_are_projected_without_string_scraping(self):
        game = parse_games(
            '[Event "A"]\n[Event "B"]\n[Result "*"]\n\n'
            '$1 1. e4 ) e5 (1... c5 2. Nf3\n'
        )[0]
        record = analyze_game(game)
        codes = {d.code for d in record.diagnostics}
        self.assertIn(PgnDiagnosticCode.DUPLICATE_TAG, codes)
        self.assertIn(PgnDiagnosticCode.ORPHAN_ANNOTATION, codes)
        self.assertIn(PgnDiagnosticCode.UNMATCHED_PARENTHESES, codes)
        self.assertIn(PgnDiagnosticCode.UNTERMINATED_VARIATION, codes)
        self.assertTrue(record.usable)
        self.assertGreaterEqual(record.warning_count, 4)

    def test_unterminated_comment_has_specific_code(self):
        game = parse_games('[Result "*"]\n\n1. e4 {unterminated\n')[0]
        record = analyze_game(game)
        self.assertIn(PgnDiagnosticCode.UNTERMINATED_COMMENT, {d.code for d in record.diagnostics})

    def test_unsupported_and_trailing_tokens_have_stable_codes(self):
        game = parse_games('[Result "1-0"]\n\n1. e4 $x 1-0 trailing\n')[0]
        record = analyze_game(game)
        codes = {d.code for d in record.diagnostics}
        self.assertIn(PgnDiagnosticCode.UNSUPPORTED_TOKEN, codes)
        self.assertIn(PgnDiagnosticCode.TRAILING_MOVETEXT, codes)

    def test_tag_projection_is_immutable_copy_and_preserves_extensions(self):
        game = parse_games('[Event "X"]\n[CustomTag "value"]\n[Result "*"]\n\n*\n')[0]
        record = analyze_game(game)
        self.assertEqual(record.tags.get('CustomTag'), 'value')
        copied = record.tags.as_dict()
        copied['CustomTag'] = 'changed'
        self.assertEqual(record.tags.get('CustomTag'), 'value')
        self.assertEqual(game.tags['CustomTag'], 'value')

    def test_source_index_and_token_index_are_carried_into_diagnostics(self):
        games = parse_games(
            '[Event "First"]\n[Result "*"]\n\n*\n\n'
            '[Event "Second"]\n[Result "*"]\n\n1. e4 ) *\n'
        )
        record = analyze_game(games[1])
        self.assertEqual(record.source_index, 1)
        self.assertTrue(record.diagnostics)
        self.assertTrue(all(d.source_index == 1 for d in record.diagnostics))
        unmatched = next(d for d in record.diagnostics if d.code is PgnDiagnosticCode.UNMATCHED_PARENTHESES)
        self.assertIsNotNone(unmatched.token_index)

    def test_analyze_games_preserves_collection_order(self):
        games = parse_games(
            '[Event "A"]\n[Result "*"]\n\n*\n\n'
            '[Event "B"]\n[Result "*"]\n\n*\n'
        )
        records = analyze_games(games)
        self.assertEqual([r.source_index for r in records], [0, 1])
        self.assertEqual([r.tags.get('Event') for r in records], ['A', 'B'])

    def test_legacy_constructed_game_warnings_still_project(self):
        game = PgnGame(tags={'Result': '*'}, warnings=['legacy malformed source'])
        record = analyze_game(game)
        self.assertIn(PgnDiagnosticCode.MALFORMED_RECORD, {d.code for d in record.diagnostics})


if __name__ == '__main__':
    unittest.main()
