from __future__ import annotations

import inspect
import unittest
from unittest import mock

import acs.chessbase_decoder as decoder
from acs.chessbase_decoder import _decode_game, _decode_move
from acs.chesscore import Board
from acs.gametree import parse_games, serialize_game
from acs.gametree_legality import validate_game_legality


class CbhCanonicalAdapterTests(unittest.TestCase):
    def test_promote_6_delegates_exactly_to_canonical_push_null(self) -> None:
        board = Board()
        token = {"from": 0, "to": 0, "promote": 6}
        with mock.patch.object(Board, "push_null", autospec=True, return_value="--") as push_null:
            self.assertEqual(_decode_move(board, token), "--")
        push_null.assert_called_once_with(board)

    def test_adapter_contains_no_local_null_state_rewrite(self) -> None:
        source = inspect.getsource(decoder)
        self.assertNotIn("def _null_move", source)
        self.assertNotIn('board.set_fen(" ".join(parts))', source)

    def test_unusual_black_start_null_move_roundtrips_through_canonical_legality(self) -> None:
        start_fen = "8/8/8/8/8/8/4K3/7k b - - 7 42"
        raw = {
            "index": 0,
            "status": "decoded",
            "start_fen": start_fen,
            "moves": [{"kind": "move", "from": 0, "to": 0, "promote": 6, "comments": []}],
        }
        game, warning = _decode_game(raw, 0, [0])
        self.assertIsNone(warning)
        self.assertIsNotNone(game)
        assert game is not None
        self.assertEqual(game.tags["SetUp"], "1")
        self.assertEqual(game.tags["FEN"], start_fen)
        self.assertEqual(game.line.moves[0].san, "--")
        self.assertTrue(validate_game_legality(game).complete)
        reopened = parse_games(serialize_game(game))[0]
        self.assertTrue(validate_game_legality(reopened).complete)
        board = Board(start_fen)
        board.push_null()
        self.assertEqual(board.fen(), "8/8/8/8/8/8/4K3/7k w - - 8 43")

    def test_zero_ply_unusual_start_is_preserved(self) -> None:
        start_fen = "8/8/8/8/8/8/4K3/7k w - - 0 17"
        raw = {"index": 0, "status": "decoded", "start_fen": start_fen, "moves": []}
        game, warning = _decode_game(raw, 0, [0])
        self.assertIsNone(warning)
        self.assertIsNotNone(game)
        assert game is not None
        self.assertEqual(game.line.moves, [])
        self.assertEqual(game.tags["FEN"], start_fen)
        reopened = parse_games(serialize_game(game))[0]
        self.assertEqual(reopened.tags["FEN"], start_fen)
        self.assertEqual(reopened.line.moves, [])

    def test_underpromotion_still_uses_canonical_legal_move_path(self) -> None:
        board = Board("7k/P7/8/8/8/8/8/7K w - - 0 1")
        san = _decode_move(board, {"from": 48, "to": 56, "promote": 5})
        self.assertIn("=N", san)
        self.assertEqual(board.board[56], "N")


if __name__ == "__main__":
    unittest.main()
