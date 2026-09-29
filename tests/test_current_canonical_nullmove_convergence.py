from __future__ import annotations

import inspect
from pathlib import Path
import tempfile
import unittest
from unittest import mock

import acs.chessbase_decoder as decoder
from acs.chessbase_decoder import _decode_game, _decode_move
from acs.chesscore import Board
from acs.gametree import parse_games, serialize_game
from acs.gametree_legality import GameTreeLegalityCode, validate_game_legality
from acs.version2_release_ui import Version2ReleaseAccessibleChessAPI


class CurrentCanonicalNullMoveConvergenceTests(unittest.TestCase):
    def test_move_entry_rejects_null_move_without_mutating_gameplay_state(self) -> None:
        for language, expected in (
            ("uk", "Нульовий хід не можна грати вручну."),
            ("en", "A null move cannot be played manually."),
        ):
            with self.subTest(language=language), tempfile.TemporaryDirectory() as temp:
                api = Version2ReleaseAccessibleChessAPI(
                    lang=language,
                    keymap_path=Path(temp) / "keymap.json",
                )
                before_fen = api.board.fen()
                before_sans = tuple(api.sans)
                before_history = api.review_history.node_count

                for move_text in ("--", " --! ", "– –"):
                    with self.subTest(language=language, move_text=move_text):
                        result = api.make_move(move_text)

                        self.assertFalse(result["ok"])
                        self.assertEqual(result["announcement"], expected)
                        self.assertEqual(api.board.fen(), before_fen)
                        self.assertEqual(tuple(api.sans), before_sans)
                        self.assertEqual(
                            api.review_history.node_count,
                            before_history,
                        )

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

    def test_black_null_move_clears_ep_and_advances_fullmove(self) -> None:
        board = Board()
        board.push_text("e4")
        self.assertIsNotNone(board.ep)

        self.assertEqual(board.push_null(), "--")

        self.assertIsNone(board.ep)
        self.assertEqual(board.turn, "w")
        self.assertEqual(board.fullmove, 2)
        self.assertEqual(board.halfmove, 1)

    def test_chessbase_promote_6_delegates_exactly_to_board_push_null(self) -> None:
        board = Board()
        token = {"from": 0, "to": 0, "promote": 6}
        with mock.patch.object(
            Board,
            "push_null",
            autospec=True,
            return_value="--",
        ) as push_null:
            self.assertEqual(_decode_move(board, token), "--")
        push_null.assert_called_once_with(board)

    def test_decoder_contains_no_adapter_local_null_state_rewrite(self) -> None:
        source = inspect.getsource(decoder)
        self.assertNotIn("def _null_move", source)
        self.assertNotIn('board.set_fen(" ".join(parts))', source)

    def test_chessbase_null_move_replays_through_canonical_legality_and_pgn(self) -> None:
        raw = {
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

        game, warning = _decode_game(raw, 0, [0])

        self.assertIsNone(warning)
        self.assertIsNotNone(game)
        assert game is not None
        self.assertEqual(game.line.moves[0].san, "--")
        report = validate_game_legality(game)
        self.assertTrue(report.complete)
        self.assertFalse(
            any(issue.code == GameTreeLegalityCode.ILLEGAL_MOVE for issue in report.issues)
        )

        reopened = parse_games(serialize_game(game))
        self.assertEqual(len(reopened), 1)
        reopened_report = validate_game_legality(reopened[0])
        self.assertTrue(reopened_report.complete)
        self.assertFalse(
            any(
                issue.code == GameTreeLegalityCode.ILLEGAL_MOVE
                for issue in reopened_report.issues
            )
        )

    def test_unusual_black_start_null_move_keeps_setup_fen_and_counters(self) -> None:
        start_fen = "8/8/8/8/8/8/4K3/7k b - - 7 42"
        raw = {
            "index": 0,
            "status": "decoded",
            "start_fen": start_fen,
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

    def test_underpromotion_still_uses_canonical_legal_move_path(self) -> None:
        board = Board("7k/P7/8/8/8/8/8/7K w - - 0 1")

        san = _decode_move(board, {"from": 48, "to": 56, "promote": 5})

        self.assertIn("=N", san)
        self.assertEqual(board.board[56], "N")


if __name__ == "__main__":
    unittest.main()
