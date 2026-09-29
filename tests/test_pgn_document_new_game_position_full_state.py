from __future__ import annotations

import unittest

from acs.chesscore import Board
from acs.pgn_document import PgnDocumentSession
from acs.position_editor import PositionState


_START_PLACEMENT = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR"


class PgnDocumentNewGameFullStateTests(unittest.TestCase):
    def test_only_exact_board_start_elides_setup_and_fen(self) -> None:
        variants = (
            (
                "black-to-move",
                f"{_START_PLACEMENT} b KQkq - 0 1",
            ),
            (
                "reduced-castling-rights",
                f"{_START_PLACEMENT} w KQk - 0 1",
            ),
            (
                "nondefault-clocks",
                f"{_START_PLACEMENT} w KQkq - 7 23",
            ),
            (
                "legal-en-passant-state",
                "rnbqkbnr/1pp1pppp/p7/3pP3/8/8/PPPP1PPP/RNBQKBNR w KQkq d6 0 3",
            ),
        )

        for label, fen in variants:
            with self.subTest(case=label):
                position = PositionState.from_fen(fen)
                canonical_fen = Board(position.to_fen()).fen()
                self.assertNotEqual(canonical_fen, Board.START)

                session = PgnDocumentSession.new_game_from_position(
                    position,
                    {"Event": f"Full state: {label}"},
                )

                game = session.workspace.current_game()
                self.assertEqual(game.tags["SetUp"], "1")
                self.assertEqual(game.tags["FEN"], canonical_fen)
                pgn = session.copy_pgn()
                self.assertIn('[SetUp "1"]', pgn)
                self.assertIn(f'[FEN "{canonical_fen}"]', pgn)


if __name__ == "__main__":
    unittest.main()
