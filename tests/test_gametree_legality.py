import unittest
from unittest import mock

import acs.gametree_legality as legality
from acs.gametree import MoveNode, PgnGame, VariationLine, parse_games, serialize_game
from acs.gametree_legality import (
    DiagnosticSeverity,
    GameTreeLegalityContractError,
    LegalityContractCode,
    LegalityDiagnosticCode,
    MoveLinkStatus,
    link_game_legality,
)


def one(source: str) -> PgnGame:
    games = parse_games(source)
    assert len(games) == 1
    return games[0]


class GameTreeLegalityTests(unittest.TestCase):
    def test_nested_rav_uses_position_before_its_parent_move(self):
        game = one(
            '[Result "*"]\n\n'
            '1. e4 (1. d4 d5 2. c4) e5 2. Nf3 Nc6 *\n'
        )
        original = serialize_game(game)

        report = link_game_legality(game)

        self.assertTrue(report.complete)
        self.assertTrue(report.all_moves_legal)
        self.assertTrue(report.canonical)
        self.assertEqual(report.diagnostics, ())
        self.assertEqual(
            [move.location.label for move in report.moves],
            [
                'root/move[0]',
                'root/move[0]/variation[0]/move[0]',
                'root/move[0]/variation[0]/move[1]',
                'root/move[0]/variation[0]/move[2]',
                'root/move[1]',
                'root/move[2]',
                'root/move[3]',
            ],
        )
        self.assertEqual(report.moves[0].before_fen, report.moves[1].before_fen)
        self.assertEqual(report.moves[0].uci, 'e2e4')
        self.assertEqual(report.moves[1].uci, 'd2d4')
        self.assertEqual(serialize_game(game), original)

    def test_illegal_mainline_does_not_block_valid_sibling_variation(self):
        game = one(
            '[Result "*"]\n\n'
            '1. e4 e5 2. Bh6 (2. Bc4) Nf6 *\n'
        )
        original = serialize_game(game)

        report = link_game_legality(game)

        self.assertEqual(
            [(move.location.label, move.status) for move in report.moves],
            [
                ('root/move[0]', MoveLinkStatus.LEGAL),
                ('root/move[1]', MoveLinkStatus.LEGAL),
                ('root/move[2]', MoveLinkStatus.ILLEGAL),
                ('root/move[2]/variation[0]/move[0]', MoveLinkStatus.LEGAL),
                ('root/move[3]', MoveLinkStatus.UNVERIFIED),
            ],
        )
        self.assertEqual(report.moves[2].before_fen, report.moves[3].before_fen)
        self.assertEqual(
            [item.code for item in report.diagnostics],
            [
                LegalityDiagnosticCode.ILLEGAL_SAN,
                LegalityDiagnosticCode.POSITION_UNAVAILABLE,
            ],
        )
        self.assertTrue(report.has_errors)
        self.assertFalse(report.complete)
        self.assertEqual(serialize_game(game), original)

    def test_legal_coordinate_spelling_and_wrong_move_number_remain_diagnostics(self):
        game = one('[Result "*"]\n\n1. e2e4 9... e7e5 *\n')

        report = link_game_legality(game)

        self.assertTrue(report.complete)
        self.assertTrue(report.all_moves_legal)
        self.assertFalse(report.canonical)
        self.assertFalse(report.has_errors)
        self.assertEqual(
            [move.status for move in report.moves],
            [MoveLinkStatus.LEGAL_NONCANONICAL, MoveLinkStatus.LEGAL_NONCANONICAL],
        )
        self.assertEqual(
            [item.code for item in report.diagnostics],
            [
                LegalityDiagnosticCode.NONCANONICAL_SAN,
                LegalityDiagnosticCode.MOVE_NUMBER_MISMATCH,
                LegalityDiagnosticCode.NONCANONICAL_SAN,
            ],
        )
        self.assertTrue(
            all(item.severity is DiagnosticSeverity.WARNING for item in report.diagnostics)
        )
        self.assertEqual([move.canonical_san for move in report.moves], ['e4', 'e5'])

    def test_setup_fen_contract_and_semantic_validation_fail_closed(self):
        standard_fen = 'rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1'
        cases = (
            (
                '[SetUp "1"]\n[Result "*"]\n\n1. e4 *',
                LegalityDiagnosticCode.MISSING_FEN,
            ),
            (
                f'[FEN "{standard_fen}"]\n[Result "*"]\n\n1. e4 *',
                LegalityDiagnosticCode.FEN_REQUIRES_SETUP,
            ),
            (
                '[SetUp "maybe"]\n[Result "*"]\n\n1. e4 *',
                LegalityDiagnosticCode.INVALID_SETUP_TAG,
            ),
            (
                '[SetUp "1"]\n[FEN "not a fen"]\n[Result "*"]\n\n1. e4 *',
                LegalityDiagnosticCode.INVALID_FEN,
            ),
            (
                '[SetUp "1"]\n'
                '[FEN "4k3/8/8/8/8/8/4R3/4K3 w - - 0 1"]\n'
                '[Result "*"]\n\n1. e4 *',
                LegalityDiagnosticCode.INVALID_FEN,
            ),
            (
                '[SetUp "1"]\n'
                '[FEN "7k/8/8/8/8/8/8/7K w - e6 0 1"]\n'
                '[Result "*"]\n\n1. Kh2 *',
                LegalityDiagnosticCode.INVALID_FEN,
            ),
        )

        for source, expected_code in cases:
            with self.subTest(code=expected_code):
                game = one(source)
                original_sans = [move.san for move in game.line.moves]
                report = link_game_legality(game)
                self.assertIsNone(report.start_fen)
                self.assertIsNone(report.final_fen)
                self.assertEqual(report.diagnostics[0].code, expected_code)
                self.assertTrue(report.has_errors)
                self.assertTrue(
                    all(move.status is MoveLinkStatus.UNVERIFIED for move in report.moves)
                )
                self.assertEqual([move.san for move in game.line.moves], original_sans)

    def test_black_to_move_fen_and_special_move_boundaries_link_canonically(self):
        black_start = one(
            '[SetUp "1"]\n'
            '[FEN "rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq e3 0 1"]\n'
            '[Result "*"]\n\n1... c5 *\n'
        )
        black_report = link_game_legality(black_start)
        self.assertTrue(black_report.canonical)
        self.assertEqual(black_report.moves[0].uci, 'c7c5')

        cases = (
            (
                '[Result "*"]\n\n'
                '1. e4 e5 2. Nf3 Nc6 3. Bc4 Nf6 4. O-O *',
                'e1g1',
                'O-O',
            ),
            (
                '[Result "*"]\n\n'
                '1. e4 a6 2. e5 d5 3. exd6 *',
                'e5d6',
                'exd6',
            ),
            (
                '[SetUp "1"]\n'
                '[FEN "7k/P7/8/8/8/8/8/7K w - - 0 1"]\n'
                '[Result "*"]\n\n1. a8=Q+ *',
                'a7a8q',
                'a8=Q+',
            ),
            (
                '[Result "0-1"]\n\n1. f3 e5 2. g4 Qh4# 0-1',
                'd8h4',
                'Qh4#',
            ),
        )
        for source, expected_uci, expected_san in cases:
            with self.subTest(san=expected_san):
                report = link_game_legality(one(source))
                self.assertTrue(report.canonical)
                self.assertEqual(report.moves[-1].uci, expected_uci)
                self.assertEqual(report.moves[-1].canonical_san, expected_san)

    def test_check_suffix_and_forced_terminal_result_are_verified(self):
        missing_check = one(
            '[SetUp "1"]\n'
            '[FEN "7k/P7/8/8/8/8/8/7K w - - 0 1"]\n'
            '[Result "*"]\n\n1. a8=Q *'
        )
        report = link_game_legality(missing_check)
        self.assertEqual(report.moves[0].status, MoveLinkStatus.LEGAL_NONCANONICAL)
        self.assertEqual(report.moves[0].canonical_san, 'a8=Q+')
        self.assertEqual(
            [item.code for item in report.diagnostics],
            [LegalityDiagnosticCode.NONCANONICAL_SAN],
        )

        wrong_result = one('[Result "1-0"]\n\n1. f3 e5 2. g4 Qh4# 1-0')
        result_report = link_game_legality(wrong_result)
        mismatch = [
            item
            for item in result_report.diagnostics
            if item.code is LegalityDiagnosticCode.RESULT_MISMATCH
        ]
        self.assertEqual(len(mismatch), 1)
        self.assertEqual(mismatch[0].location.label, 'root')
        self.assertIn("'0-1'", mismatch[0].message)
        self.assertTrue(result_report.has_errors)

    def test_recovery_evidence_stays_distinct_from_legality_diagnostics(self):
        game = one('[Result "*"]\n\n1. e4$bad *')

        report = link_game_legality(game)

        self.assertTrue(report.all_moves_legal)
        self.assertFalse(report.canonical)
        self.assertEqual(report.diagnostics, ())
        self.assertEqual(len(report.recovery_issue_codes), 1)
        self.assertEqual(report.recovery_issue_codes[0].value, 'invalid_annotation')

    def test_cycles_reuse_and_node_limits_fail_with_stable_contract_codes(self):
        cyclic = PgnGame(line=VariationLine(moves=[MoveNode('e4')], result='*'))
        cyclic.line.moves[0].variations.append(cyclic.line)
        with self.assertRaises(GameTreeLegalityContractError) as cycle:
            link_game_legality(cyclic)
        self.assertEqual(cycle.exception.code, LegalityContractCode.GRAPH_CYCLE)

        shared = VariationLine(moves=[MoveNode('d4')])
        reused = PgnGame(
            line=VariationLine(
                moves=[
                    MoveNode('e4', variations=[shared]),
                    MoveNode('e5', variations=[shared]),
                ],
                result='*',
            )
        )
        with self.assertRaises(GameTreeLegalityContractError) as reuse:
            link_game_legality(reused)
        self.assertEqual(reuse.exception.code, LegalityContractCode.GRAPH_REUSE)

        bounded = one('[Result "*"]\n\n1. e4 e5 *')
        with mock.patch.object(legality, 'MAX_TREE_NODES', 2):
            with self.assertRaises(GameTreeLegalityContractError) as limit:
                link_game_legality(bounded)
        self.assertEqual(limit.exception.code, LegalityContractCode.GRAPH_NODE_LIMIT)


if __name__ == '__main__':
    unittest.main()
