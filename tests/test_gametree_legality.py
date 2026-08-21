import unittest

from acs.gametree import MoveNode, PgnGame, VariationLine, serialize_game
from acs.gametree_legality import GameTreeLegalityCode, validate_game_legality
from acs.gametree_navigation import MoveAddress, VariationStep


class GameTreeLegalityTests(unittest.TestCase):
    def test_mainline_and_rav_use_canonical_branch_positions_without_mutation(self):
        alternative = VariationLine(moves=[MoveNode("c5", move_number="1...")])
        game = PgnGame(
            tags={"Event": "Legality", "Result": "*"},
            line=VariationLine(
                moves=[
                    MoveNode("e4", move_number="1."),
                    MoveNode("e5", variations=[alternative]),
                    MoveNode("Nf3", move_number="2."),
                ],
                result="*",
            ),
        )
        before = serialize_game(game)

        report = validate_game_legality(game)

        self.assertTrue(report.complete, report.issues)
        self.assertEqual([], [x for x in report.issues if x.code == GameTreeLegalityCode.ILLEGAL_MOVE])
        self.assertEqual(4, report.legal_move_count)
        addresses = {move.address for move in report.moves}
        self.assertIn(MoveAddress((), 0), addresses)
        self.assertIn(MoveAddress((), 1), addresses)
        self.assertIn(MoveAddress((), 2), addresses)
        self.assertIn(MoveAddress((VariationStep(1, 0),), 0), addresses)
        self.assertEqual(before, serialize_game(game))

    def test_illegal_move_stops_only_that_line_and_preserves_source(self):
        alternative = VariationLine(moves=[MoveNode("c5", move_number="1...")])
        game = PgnGame(
            tags={"Result": "*"},
            line=VariationLine(
                moves=[
                    MoveNode("e4", move_number="1."),
                    MoveNode("e5", variations=[alternative]),
                    MoveNode("e4", move_number="2."),
                    MoveNode("Nf3"),
                ],
                result="*",
            ),
        )
        before = serialize_game(game)

        report = validate_game_legality(game)

        illegal = [x for x in report.issues if x.code == GameTreeLegalityCode.ILLEGAL_MOVE]
        self.assertEqual(1, len(illegal))
        self.assertEqual(MoveAddress((), 2), illegal[0].address)
        self.assertFalse(report.complete)
        self.assertIn(MoveAddress((VariationStep(1, 0),), 0), {m.address for m in report.moves})
        self.assertNotIn(MoveAddress((), 3), {m.address for m in report.moves})
        self.assertEqual(before, serialize_game(game))

    def test_setup_fen_is_explicit_and_invalid_start_fails_closed(self):
        game = PgnGame(
            tags={"SetUp": "1", "FEN": "not a fen", "Result": "*"},
            line=VariationLine(moves=[MoveNode("e4")], result="*"),
        )

        report = validate_game_legality(game)

        self.assertFalse(report.complete)
        self.assertIsNone(report.start_fen)
        self.assertEqual(0, report.legal_move_count)
        self.assertEqual(GameTreeLegalityCode.INVALID_START_POSITION, report.issues[0].code)

    def test_fen_without_setup_is_preserved_but_not_silently_applied(self):
        game = PgnGame(
            tags={
                "FEN": "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR b KQkq - 0 1",
                "Result": "*",
            },
            line=VariationLine(moves=[MoveNode("e4", move_number="1.")], result="*"),
        )

        report = validate_game_legality(game)

        self.assertTrue(report.complete)
        self.assertEqual(1, report.legal_move_count)
        self.assertEqual(GameTreeLegalityCode.FEN_WITHOUT_SETUP, report.issues[0].code)

    def test_move_number_mismatch_is_loss_aware_not_destructive(self):
        game = PgnGame(
            tags={"Result": "*"},
            line=VariationLine(moves=[MoveNode("e4", move_number="9.")], result="*"),
        )

        report = validate_game_legality(game)

        mismatch = [x for x in report.issues if x.code == GameTreeLegalityCode.MOVE_NUMBER_MISMATCH]
        self.assertTrue(report.complete)
        self.assertEqual(1, report.legal_move_count)
        self.assertEqual(1, len(mismatch))
        self.assertEqual(MoveAddress((), 0), mismatch[0].address)

    def test_reused_variation_object_is_rejected_without_recursion(self):
        child = VariationLine(moves=[MoveNode("c5", move_number="1...")])
        game = PgnGame(
            tags={"Result": "*"},
            line=VariationLine(
                moves=[
                    MoveNode("e4", move_number="1."),
                    MoveNode("e5", variations=[child, child]),
                ],
                result="*",
            ),
        )

        report = validate_game_legality(game)

        self.assertFalse(report.complete)
        self.assertIn(GameTreeLegalityCode.GRAPH_REUSE, {x.code for x in report.issues})


if __name__ == "__main__":
    unittest.main()
