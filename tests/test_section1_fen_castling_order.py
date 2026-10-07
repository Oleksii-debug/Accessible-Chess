from __future__ import annotations

import unittest

from acs.chesscore import Board
from acs.position_editor import PositionState, PositionValidationError, standard_position


_BASE_BOARD = "r3k2r/8/8/8/8/8/8/R3K2R"


def _fen(castling: str) -> str:
    return f"{_BASE_BOARD} w {castling} - 0 1"


class Section1FenCastlingOrderTests(unittest.TestCase):
    def test_standard_fen_castling_subsets_keep_kqkq_relative_order(self) -> None:
        valid = (
            "-",
            "K",
            "Q",
            "KQ",
            "k",
            "q",
            "kq",
            "Kk",
            "Kq",
            "Qk",
            "Qq",
            "KQkq",
        )
        for castling in valid:
            with self.subTest(castling=castling):
                fen = _fen(castling)
                self.assertEqual(Board(fen).fen(), fen)
                self.assertEqual(PositionState.from_fen(fen).to_fen(), fen)

    def test_out_of_order_fen_castling_tokens_fail_on_both_canonical_boundaries(self) -> None:
        for castling in ("QK", "qk", "kK", "qQ", "KkQ", "qK"):
            with self.subTest(castling=castling):
                fen = _fen(castling)
                with self.assertRaisesRegex(ValueError, "порядок KQkq"):
                    Board(fen)
                with self.assertRaisesRegex(
                    PositionValidationError,
                    "canonical KQkq order",
                ):
                    PositionState.from_fen(fen)

    def test_fen_en_passant_square_requires_canonical_lowercase_text(self) -> None:
        canonical = "4k3/8/8/4p3/8/8/8/4K3 w - e6 0 2"
        self.assertEqual(Board(canonical).fen(), canonical)
        state = PositionState.from_fen(canonical)
        self.assertEqual(state.to_fen(), canonical)

        uppercase = canonical.replace(" e6 ", " E6 ")
        with self.assertRaisesRegex(ValueError, "канонічним нижнім регістром"):
            Board(uppercase)
        with self.assertRaisesRegex(
            PositionValidationError,
            "canonical lowercase text",
        ):
            PositionState.from_fen(uppercase)

        with self.assertRaisesRegex(
            PositionValidationError,
            "canonical lowercase text",
        ):
            PositionState(
                state.pieces,
                turn=state.turn,
                castling=state.castling,
                en_passant="E6",
                halfmove=state.halfmove,
                fullmove=state.fullmove,
            )

        normalized = state.with_en_passant(" E6 ")
        self.assertEqual(normalized.en_passant, "e6")
        self.assertEqual(normalized.to_fen(), canonical)

    def test_board_san_castling_matches_canonical_notation_glyph_policy(self) -> None:
        fen = f"{_BASE_BOARD} w KQkq - 0 1"
        canonical = Board(fen)
        self.assertEqual(canonical.parse_move("O-O"), canonical.parse_move("0-0"))
        self.assertEqual(canonical.parse_move("O-O-O"), canonical.parse_move("0-0-0"))

        mixed = ("0-O", "O-0", "0-O-O", "O-0-O", "O-O-0", "0-0-O")
        before = canonical.fen()
        for token in mixed:
            with self.subTest(token=token):
                with self.assertRaisesRegex(
                    ValueError,
                    "не вдалося|нелегальний",
                ):
                    canonical.parse_move(token)
                with self.assertRaisesRegex(
                    ValueError,
                    "не вдалося|нелегальний",
                ):
                    canonical.push_text(token)
                self.assertEqual(canonical.fen(), before)

    def test_rejected_order_is_atomic_for_live_board_history(self) -> None:
        board = Board()
        board.push_text("e4")
        before = (
            board.fen(),
            tuple(board.undo_stack),
            tuple(board.redo_stack),
            board.last_move,
        )

        with self.assertRaisesRegex(ValueError, "порядок KQkq"):
            board.set_fen(_fen("qK"))

        self.assertEqual(
            (
                board.fen(),
                tuple(board.undo_stack),
                tuple(board.redo_stack),
                board.last_move,
            ),
            before,
        )

    def test_positionstate_internal_state_is_canonical_but_editor_input_still_normalizes(self) -> None:
        position = standard_position()
        with self.assertRaisesRegex(
            PositionValidationError,
            "canonical KQkq order",
        ):
            PositionState(
                position.pieces,
                turn=position.turn,
                castling="qK",
                en_passant=position.en_passant,
                halfmove=position.halfmove,
                fullmove=position.fullmove,
            )

        normalized = position.with_castling("qK")
        self.assertEqual(normalized.castling, "Kq")
        self.assertIn(" w Kq - 0 1", normalized.to_fen())


if __name__ == "__main__":
    unittest.main()
