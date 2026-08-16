import unittest

from acs.gametree import parse_games
from acs.pgn_semantics import (
    DiagnosticSeverity,
    PgnDiagnosticCode,
    analyze_game,
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
        self.assertEqual(record.result, '0-1')
        self.assertEqual(record.tags.get('Result'), '1-0')

    def test_other_malformed_parser_warning_is_not_discarded(self):
        game = parse_games('[Result "*"]\n\n1. e4 {unterminated\n')[0]
        record = analyze_game(game)
        malformed = [d for d in record.diagnostics if d.code is PgnDiagnosticCode.MALFORMED_RECORD]
        self.assertTrue(malformed)
        self.assertTrue(any('unterminated brace comment' in d.message for d in malformed))

    def test_tag_projection_is_immutable_copy_and_preserves_extensions(self):
        game = parse_games('[Event "X"]\n[CustomTag "value"]\n[Result "*"]\n\n*\n')[0]
        record = analyze_game(game)
        self.assertEqual(record.tags.get('CustomTag'), 'value')
        copied = record.tags.as_dict()
        copied['CustomTag'] = 'changed'
        self.assertEqual(record.tags.get('CustomTag'), 'value')
        self.assertEqual(game.tags['CustomTag'], 'value')

    def test_source_index_is_carried_into_all_diagnostics(self):
        games = parse_games(
            '[Event "First"]\n[Result "*"]\n\n*\n\n'
            '[Event "Second"]\n[SetUp "1"]\n[Result "*"]\n\n*\n'
        )
        record = analyze_game(games[1])
        self.assertEqual(record.source_index, 1)
        self.assertTrue(record.diagnostics)
        self.assertTrue(all(d.source_index == 1 for d in record.diagnostics))


if __name__ == '__main__':
    unittest.main()
