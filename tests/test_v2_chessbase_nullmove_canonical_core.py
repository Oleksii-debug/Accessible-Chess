from __future__ import annotations

import unittest

from acs.chessbase_decoder import _decode_game
from acs.chesscore import Board
from acs.gametree import parse_games, serialize_game
from acs.gametree_legality import GameTreeLegalityCode, validate_game_legality


class V2ChessBaseNullMoveCanonicalCoreTests(unittest.TestCase):
    @staticmethod
    def _raw_null_game() -> dict[str, object]:
        return {
            "index": 0,
            "status": "decoded",
            "start_fen": Board.START,
            "moves": [
                {
                    "kind": "move",
                    "from": 0,
                    "to": 0,
                    "promote": 6,
                    "comments": [],
                }
            ],
        }

    def test_canonical_board_null_move_has_bounded_fen_semantics_and_history(self) -> None:
        board = Board("rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq e3 0 1")
        original = board.fen()

        self.assertEqual(board.push_text("--"), "--")
        self.assertEqual(
            board.fen(),
            "rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR w KQkq - 1 2",
        )
        self.assertIsNone(board.last_move)

        self.assertEqual(board.undo(), "--")
        self.assertEqual(board.fen(), original)
        self.assertEqual(board.redo(), "--")
        self.assertEqual(
            board.fen(),
            "rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR w KQkq - 1 2",
        )

    def test_chessbase_null_move_replays_through_canonical_legality(self) -> None:
        game, warning = _decode_game(self._raw_null_game(), 0, [0])
        self.assertIsNotNone(game)
        self.assertIsNone(warning)
        assert game is not None
        self.assertEqual(game.line.moves[0].san, "--")

        report = validate_game_legality(game)
        self.assertTrue(report.complete)
        self.assertFalse(
            any(issue.code == GameTreeLegalityCode.ILLEGAL_MOVE for issue in report.issues)
        )
        self.assertEqual(report.moves[0].san_canonical, "--")

    def test_chessbase_null_move_stays_canonical_after_pgn_export_reopen(self) -> None:
        game, warning = _decode_game(self._raw_null_game(), 0, [0])
        self.assertIsNotNone(game)
        self.assertIsNone(warning)
        assert game is not None

        reopened = parse_games(serialize_game(game))
        self.assertEqual(len(reopened), 1)
        self.assertEqual(reopened[0].line.moves[0].san, "--")
        report = validate_game_legality(reopened[0])
        self.assertTrue(report.complete)
        self.assertFalse(
            any(issue.code == GameTreeLegalityCode.ILLEGAL_MOVE for issue in report.issues)
        )


if __name__ == "__main__":
    unittest.main()
