import unittest

from acs.gametree import MoveNode, PgnGame, VariationLine, parse_games
from acs.gametree_result_contract import (
    LEGALITY_SNAPSHOT_VERSION,
    GameTreeResultCode,
    GameTreeTerminalKind,
    analyze_result_contract,
    create_legality_snapshot,
    legality_snapshot_from_payload,
    legality_snapshot_to_payload,
)


class GameTreeResultContractTests(unittest.TestCase):
    def test_forced_checkmate_result_matches_source_without_mutation(self):
        game = parse_games(
            '[Event "Mate"]\n[Result "0-1"]\n\n1. f3 e5 2. g4 Qh4# 0-1'
        )[0]
        before = (
            tuple(game.tags.items()),
            tuple(node.san for node in game.line.moves),
            game.line.result,
        )

        result = analyze_result_contract(game)

        self.assertTrue(result.mainline_complete)
        self.assertEqual(GameTreeTerminalKind.CHECKMATE, result.terminal_kind)
        self.assertEqual("0-1", result.forced_result)
        self.assertTrue(result.result_consistent)
        self.assertEqual((), result.issues)
        self.assertEqual(
            before,
            (
                tuple(game.tags.items()),
                tuple(node.san for node in game.line.moves),
                game.line.result,
            ),
        )

    def test_forced_checkmate_result_mismatch_is_explicit(self):
        game = PgnGame(
            tags={"Result": "1-0"},
            line=VariationLine(
                moves=[
                    MoveNode("f3", move_number="1."),
                    MoveNode("e5"),
                    MoveNode("g4", move_number="2."),
                    MoveNode("Qh4#"),
                ],
                result="1-0",
            ),
        )

        result = analyze_result_contract(game)

        self.assertEqual(GameTreeTerminalKind.CHECKMATE, result.terminal_kind)
        self.assertEqual("0-1", result.forced_result)
        self.assertFalse(result.result_consistent)
        self.assertIn(
            GameTreeResultCode.FORCED_RESULT_MISMATCH,
            {issue.code for issue in result.issues},
        )

    def test_setup_fen_stalemate_is_forced_draw(self):
        game = PgnGame(
            tags={
                "SetUp": "1",
                "FEN": "7k/5Q2/6K1/8/8/8/8/8 b - - 0 1",
                "Result": "1/2-1/2",
            },
            line=VariationLine(result="1/2-1/2"),
        )

        result = analyze_result_contract(game)

        self.assertTrue(result.mainline_complete)
        self.assertEqual(GameTreeTerminalKind.STALEMATE, result.terminal_kind)
        self.assertEqual("1/2-1/2", result.forced_result)
        self.assertTrue(result.result_consistent)

    def test_nonterminal_decisive_result_is_not_rejected_as_resignation_is_possible(self):
        game = PgnGame(
            tags={"Result": "1-0"},
            line=VariationLine(
                moves=[MoveNode("e4", move_number="1.")],
                result="1-0",
            ),
        )

        result = analyze_result_contract(game)

        self.assertTrue(result.mainline_complete)
        self.assertEqual(GameTreeTerminalKind.ONGOING, result.terminal_kind)
        self.assertIsNone(result.forced_result)
        self.assertIsNone(result.result_consistent)
        self.assertNotIn(
            GameTreeResultCode.FORCED_RESULT_MISMATCH,
            {issue.code for issue in result.issues},
        )

    def test_illegal_mainline_keeps_terminal_state_unknown(self):
        game = PgnGame(
            tags={"Result": "*"},
            line=VariationLine(
                moves=[
                    MoveNode("e4", move_number="1."),
                    MoveNode("e4"),
                ],
                result="*",
            ),
        )

        result = analyze_result_contract(game)

        self.assertFalse(result.mainline_complete)
        self.assertEqual(GameTreeTerminalKind.UNKNOWN, result.terminal_kind)
        self.assertIsNone(result.forced_result)
        self.assertIsNone(result.result_consistent)
        self.assertIn(
            GameTreeResultCode.MAINLINE_INCOMPLETE,
            {issue.code for issue in result.issues},
        )

    def test_snapshot_round_trip_is_versioned_and_exact(self):
        game = parse_games(
            '[Event "Snapshot"]\n[Result "0-1"]\n\n1. f3 e5 2. g4 Qh4# 0-1'
        )[0]

        snapshot = create_legality_snapshot(game)
        payload = legality_snapshot_to_payload(snapshot)
        restored = legality_snapshot_from_payload(payload)

        self.assertEqual(LEGALITY_SNAPSHOT_VERSION, payload["schema_version"])
        self.assertEqual(snapshot, restored)
        self.assertEqual("0-1", restored.forced_result)
        self.assertEqual(GameTreeTerminalKind.CHECKMATE, restored.terminal_kind)

    def test_snapshot_rejects_bool_version_unknown_fields_and_coercive_counts(self):
        game = PgnGame(tags={"Result": "*"}, line=VariationLine(result="*"))
        payload = legality_snapshot_to_payload(create_legality_snapshot(game))

        bad_version = dict(payload)
        bad_version["schema_version"] = True
        with self.assertRaises(ValueError):
            legality_snapshot_from_payload(bad_version)

        extra = dict(payload)
        extra["future"] = "silent-normalization-forbidden"
        with self.assertRaises(ValueError):
            legality_snapshot_from_payload(extra)

        bad_count = dict(payload)
        bad_count["legal_move_count"] = "0"
        with self.assertRaises(ValueError):
            legality_snapshot_from_payload(bad_count)

    def test_snapshot_rejects_inconsistent_terminal_contract(self):
        game = PgnGame(tags={"Result": "*"}, line=VariationLine(result="*"))
        payload = legality_snapshot_to_payload(create_legality_snapshot(game))

        bad = dict(payload)
        bad["mainline_complete"] = False
        bad["terminal_kind"] = "ongoing"
        with self.assertRaises(ValueError):
            legality_snapshot_from_payload(bad)

        bad = dict(payload)
        bad["forced_result"] = None
        bad["result_consistent"] = True
        with self.assertRaises(ValueError):
            legality_snapshot_from_payload(bad)


if __name__ == "__main__":
    unittest.main()
