from __future__ import annotations

import unittest

from acs.chessbase_decoder import _decode_game
from acs.chesscore import Board
from acs.gametree import parse_games, serialize_game
from acs.gametree_legality import GameTreeLegalityCode, validate_game_legality


class V2AuditBChessBaseNullMoveOneCoreTests(unittest.TestCase):
    @staticmethod
    def _decoded_null_game():
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
        assert game is not None
        assert warning is None
        return game

    def test_chessbase_null_move_must_be_accepted_by_canonical_legality(self) -> None:
        game = self._decoded_null_game()
        self.assertEqual(game.line.moves[0].san, "--")

        report = validate_game_legality(game)
        illegal = [issue for issue in report.issues if issue.code == GameTreeLegalityCode.ILLEGAL_MOVE]

        self.assertTrue(
            report.complete,
            "AB-V2-001: ChessBase emits a GameTree null move that canonical Board/GameTree legality rejects",
        )
        self.assertEqual(
            illegal,
            [],
            "AB-V2-001: adapter-owned null transition is not a canonical chess-core transition",
        )

    def test_chessbase_null_move_must_remain_canonical_after_pgn_reopen(self) -> None:
        game = self._decoded_null_game()
        pgn = serialize_game(game)
        reopened = parse_games(pgn)
        self.assertEqual(len(reopened), 1)
        self.assertEqual(reopened[0].line.moves[0].san, "--")

        report = validate_game_legality(reopened[0])
        self.assertTrue(
            report.complete,
            "AB-V2-001: lexical PGN round-trip preserves '--' but canonical legality still cannot replay it",
        )
        self.assertFalse(
            any(issue.code == GameTreeLegalityCode.ILLEGAL_MOVE for issue in report.issues),
            "AB-V2-001: export/reopen does not repair the non-canonical ChessBase state transition",
        )


if __name__ == "__main__":
    unittest.main()
