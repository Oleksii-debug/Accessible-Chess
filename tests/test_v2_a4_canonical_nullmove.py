from __future__ import annotations

import unittest

from acs.chessbase_decoder import _decode_game
from acs.chesscore import Board
from acs.gametree import parse_games, serialize_game
from acs.gametree_legality import GameTreeLegalityCode, validate_game_legality


class V2A4CanonicalNullMoveTests(unittest.TestCase):
    def test_canonical_null_move_transition_and_history(self) -> None:
        board = Board()
        before = board.fen()
        self.assertEqual(board.push_text("--"), "--")
        self.assertEqual(
            board.fen(),
            "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR b KQkq - 1 1",
        )
        self.assertEqual(board.undo(), "--")
        self.assertEqual(board.fen(), before)
        self.assertEqual(board.redo(), "--")
        self.assertEqual(
            board.fen(),
            "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR b KQkq - 1 1",
        )

    def test_black_null_move_advances_fullmove_and_clears_ep(self) -> None:
        board = Board()
        board.push_text("e4")
        self.assertIsNotNone(board.ep)
        self.assertEqual(board.push_text("--"), "--")
        self.assertIsNone(board.ep)
        self.assertEqual(board.turn, "w")
        self.assertEqual(board.fullmove, 2)
        self.assertEqual(board.halfmove, 1)

    def test_chessbase_null_move_is_replayable_by_canonical_legality(self) -> None:
        raw = {
            "index": 0,
            "status": "decoded",
            "start_fen": Board.START,
            "moves": [{"kind": "move", "from": 0, "to": 0, "promote": 6, "comments": []}],
        }
        game, warning = _decode_game(raw, 0, [0])
        self.assertIsNone(warning)
        self.assertIsNotNone(game)
        assert game is not None
        self.assertEqual(game.line.moves[0].san, "--")
        report = validate_game_legality(game)
        self.assertTrue(report.complete)
        self.assertFalse(any(issue.code == GameTreeLegalityCode.ILLEGAL_MOVE for issue in report.issues))

        reopened = parse_games(serialize_game(game))
        self.assertEqual(len(reopened), 1)
        reopened_report = validate_game_legality(reopened[0])
        self.assertTrue(reopened_report.complete)
        self.assertFalse(any(issue.code == GameTreeLegalityCode.ILLEGAL_MOVE for issue in reopened_report.issues))


if __name__ == "__main__":
    unittest.main()
