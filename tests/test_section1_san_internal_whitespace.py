from __future__ import annotations

import unittest

from acs.chesscore import Board
from acs.move_entry import MoveEntryKind, parse_move_entry
from acs.notation import NotationError, format_accessible_compact_san, format_san


class Section1SanInternalWhitespaceTests(unittest.TestCase):
    @staticmethod
    def _snapshot(board: Board):
        return (
            board.fen(),
            tuple(board.undo_stack),
            tuple(board.redo_stack),
            board.last_move,
        )

    def test_surrounding_whitespace_and_existing_human_conveniences_remain(self) -> None:
        board = Board()
        move = board.parse_move("  Nf3!?  ")
        self.assertEqual(board.san(move), "Nf3")

        self.assertEqual(Board.norm_san(" Nf3 "), "Nf3")
        self.assertEqual(Board.norm_san("Nf3!?"), "Nf3")

    def test_internal_space_cannot_turn_non_san_into_piece_or_pawn_move(self) -> None:
        for token in ("N f3", "N  f3", "e 4", "N f 3"):
            with self.subTest(token=token):
                board = Board()
                before = self._snapshot(board)

                with self.assertRaisesRegex(ValueError, "не вдалося|нелегальний"):
                    board.parse_move(token)
                self.assertEqual(self._snapshot(board), before)

                with self.assertRaisesRegex(ValueError, "не вдалося|нелегальний"):
                    board.push_text(token)
                self.assertEqual(self._snapshot(board), before)

    def test_internal_space_cannot_repair_coordinate_move(self) -> None:
        board = Board()
        before = self._snapshot(board)
        self.assertEqual(board.parse_move("e2e4").frm, 12)

        with self.assertRaisesRegex(ValueError, "не вдалося|нелегальний"):
            board.parse_move("e2 e4")
        self.assertEqual(self._snapshot(board), before)

    def test_internal_space_cannot_repair_castling_spelling(self) -> None:
        fen = "r3k2r/8/8/8/8/8/8/R3K2R w KQkq - 0 1"
        canonical = Board(fen).parse_move("O-O")
        legacy = Board(fen).parse_move("0-0")
        surrounded = Board(fen).parse_move(" 0-0 ")
        self.assertTrue(canonical.castle)
        self.assertEqual(legacy, canonical)
        self.assertEqual(surrounded, canonical)

        for token in ("O - O", "0 - 0", "O- O", "0- 0"):
            with self.subTest(token=token):
                board = Board(fen)
                before = self._snapshot(board)
                with self.assertRaisesRegex(ValueError, "не вдалося|нелегальний"):
                    board.parse_move(token)
                self.assertEqual(self._snapshot(board), before)

    def test_move_entry_preserves_internal_space_for_rules_boundary_to_reject(self) -> None:
        intent = parse_move_entry("N f3")
        self.assertEqual(intent.kind, MoveEntryKind.CHESS_MOVE)
        self.assertEqual(intent.move_text, "N f3")

        board = Board()
        before = self._snapshot(board)
        with self.assertRaises(ValueError):
            board.parse_move(intent.move_text)
        self.assertEqual(self._snapshot(board), before)

    def test_board_ingress_matches_strict_notation_whitespace_grammar(self) -> None:
        for token in ("N f3", "e 4", "N f 3"):
            with self.subTest(token=token):
                with self.assertRaises(NotationError):
                    format_san(token, "san")
                with self.assertRaises(ValueError):
                    Board().parse_move(token)

        # Accessible compact output is presentation text, not a second SAN
        # ingress grammar. It must not be silently reparsed as canonical SAN.
        compact = format_accessible_compact_san("Nf3", "en")
        self.assertEqual(compact, "N f 3")
        with self.assertRaises(ValueError):
            Board().parse_move(compact)


if __name__ == "__main__":
    unittest.main()
