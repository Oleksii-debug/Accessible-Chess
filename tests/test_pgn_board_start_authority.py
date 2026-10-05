import unittest

from acs.analysis_service import AnalysisService
from acs.book_board_workflow import BookBoardWorkflow, BookBoardWorkflowError
from acs.bookdocument import BookDocument, Game
from acs.bookreader import BookReader
from acs.chesscore import Board
from acs.engine_assisted_workflows import EngineAssistedWorkflowService
from acs.gametree_legality import GameTreeLegalityCode, validate_game_legality
from acs.pgn_roundtrip import parse_pgn_text, serialize_pgn_text


CUSTOM_FEN = '7k/8/8/8/8/8/5K2/8 b - - 0 23'


class PgnBoardStartAuthorityTests(unittest.TestCase):
    def test_fen_without_setup_never_substitutes_standard_start(self):
        for setup in ('', '[SetUp "0"]\n'):
            with self.subTest(setup=setup):
                game = parse_pgn_text('[Event "Ambiguous"]\n' + setup
                                      + '[FEN "' + CUSTOM_FEN + '"]\n*')[0]
                report = validate_game_legality(game)
                self.assertFalse(report.complete)
                self.assertIsNone(report.start_fen)
                self.assertEqual(report.moves, ())
                self.assertEqual(report.issues[0].code, GameTreeLegalityCode.FEN_WITHOUT_SETUP)
                self.assertEqual(game.tags['FEN'], CUSTOM_FEN)

    def test_invalid_setup_and_missing_fen_fail_closed(self):
        for header in ('[SetUp "2"]', '[SetUp ""]', '[SetUp "1"]', '[SetUp "1"]\n[FEN "bad"]'):
            with self.subTest(header=header):
                report = validate_game_legality(parse_pgn_text(header + '\n*')[0])
                self.assertFalse(report.complete)
                self.assertIsNone(report.start_fen)
                self.assertEqual(report.issues[0].code, GameTreeLegalityCode.INVALID_START_POSITION)

    def test_nonstandard_variants_cannot_reach_standard_board(self):
        for variant in ('Chess960', 'Fischer Random', 'Atomic', 'Unknown', ''):
            with self.subTest(variant=variant):
                game = parse_pgn_text('[Variant "' + variant + '"]\n1. e4 *')[0]
                before = serialize_pgn_text((game,))
                report = validate_game_legality(game)
                self.assertFalse(report.complete)
                self.assertIsNone(report.start_fen)
                self.assertEqual(report.moves, ())
                self.assertEqual(report.issues[0].code, GameTreeLegalityCode.UNSUPPORTED_VARIANT)
                self.assertEqual(serialize_pgn_text((game,)), before)

    def test_explicit_standard_variants_and_setup_zero_remain_legal(self):
        for tags in ('', '[Variant "Standard"]', '[Variant "Chess"]', '[Variant " standard "]', '[SetUp "0"]'):
            with self.subTest(tags=tags):
                report = validate_game_legality(parse_pgn_text(tags + '\n1. e4 *')[0])
                expected = Board(); expected.push_text('e4')
                self.assertTrue(report.complete)
                self.assertEqual(report.start_fen, Board.START)
                self.assertEqual(report.moves[0].fen_after, expected.fen())

    def test_valid_custom_black_start_is_exact_with_nested_variation(self):
        source = '[SetUp "1"]\n[FEN "' + CUSTOM_FEN + '"]\n23... Kg7 (23... Kh7) 24. Ke3 *'
        game = parse_pgn_text(source)[0]
        report = validate_game_legality(game)
        self.assertTrue(report.complete)
        self.assertEqual(report.start_fen, CUSTOM_FEN)
        self.assertEqual(len(report.moves), 3)

    def test_book_failure_keeps_reading_location_and_no_active_board(self):
        for source in ('[FEN "' + CUSTOM_FEN + '"]\n*', '[Variant "Chess960"]\n1. e4 *'):
            with self.subTest(source=source):
                reader = BookReader(BookDocument(title='Study', blocks=[Game(pgn=source, block_id='game')]))
                before = reader.snapshot()
                analysis = AnalysisService(lambda: self.fail('invalid source must not start engine'))
                self.addCleanup(analysis.close)
                workflow = BookBoardWorkflow(reader, EngineAssistedWorkflowService(analysis))
                with self.assertRaises(BookBoardWorkflowError):
                    workflow.open_current()
                self.assertFalse(workflow.active)
                self.assertEqual(reader.snapshot(), before)


if __name__ == '__main__':
    unittest.main()
