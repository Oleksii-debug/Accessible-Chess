import unittest

from acs.position_editor import (
    PositionState,
    PositionValidationError,
    empty_position,
    standard_position,
)


class PositionEditorTests(unittest.TestCase):
    def test_standard_position_round_trips_exact_fen(self):
        position = standard_position()
        self.assertEqual(
            position.to_fen(),
            "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1",
        )
        self.assertEqual(position.validate_playable(), ())

    def test_empty_position_is_editable_but_not_yet_playable(self):
        position = empty_position()
        self.assertEqual(position.to_fen(), "8/8/8/8/8/8/8/8 w - - 0 1")
        problems = position.validate_playable()
        self.assertIn("white king count must be 1, got 0", problems)
        self.assertIn("black king count must be 1, got 0", problems)

    def test_piece_edits_are_immutable_and_square_addressed(self):
        empty = empty_position()
        with_white_king = empty.with_piece("e1", "K")
        complete = with_white_king.with_piece("e8", "k")
        self.assertIsNone(empty.piece_at("e1"))
        self.assertEqual(with_white_king.piece_at("e1"), "K")
        self.assertEqual(complete.piece_at("e8"), "k")
        self.assertEqual(complete.validate_playable(), ())

    def test_turn_change_clears_stale_en_passant_target(self):
        position = PositionState.from_fen("8/8/8/3pP3/8/8/8/K6k w - d6 0 12")
        changed = position.with_turn("b")
        self.assertEqual(changed.turn, "b")
        self.assertEqual(changed.en_passant, "-")
        self.assertEqual(position.en_passant, "d6")

    def test_castling_rights_are_canonicalized_and_checked_structurally(self):
        position = empty_position().with_piece("e1", "K").with_piece("e8", "k")
        position = position.with_castling("qK")
        self.assertEqual(position.castling, "Kq")
        problems = position.validate_playable()
        self.assertIn("white kingside castling right inconsistent with e1/h1", problems)
        self.assertIn("black queenside castling right inconsistent with e8/a8", problems)

    def test_pawns_on_first_or_eighth_rank_are_reported(self):
        position = (
            empty_position()
            .with_piece("e1", "K")
            .with_piece("e8", "k")
            .with_piece("a1", "P")
            .with_piece("h8", "p")
        )
        problems = position.validate_playable()
        self.assertIn("pawn on invalid first rank at a1", problems)
        self.assertIn("pawn on invalid eighth rank at h8", problems)

    def test_invalid_fen_fields_and_rank_expansion_are_rejected(self):
        invalid = (
            "8/8/8/8/8/8/8/8 w - - 0",
            "8/8/8/8/8/8/8 w - - 0 1",
            "9/8/8/8/8/8/8/8 w - - 0 1",
            "7/8/8/8/8/8/8/8 w - - 0 1",
            "8/8/8/8/8/8/8/X7 w - - 0 1",
        )
        for fen in invalid:
            with self.subTest(fen=fen):
                with self.assertRaises(PositionValidationError):
                    PositionState.from_fen(fen)

    def test_non_string_fen_is_rejected_without_coercion(self):
        invalid = (
            None,
            123,
            b"8/8/8/8/8/8/8/8 w - - 0 1",
            ["8/8/8/8/8/8/8/8 w - - 0 1"],
        )
        for fen in invalid:
            with self.subTest(fen=fen):
                with self.assertRaisesRegex(PositionValidationError, "FEN must be text"):
                    PositionState.from_fen(fen)  # type: ignore[arg-type]

    def test_direct_counter_types_reject_bool_and_float(self):
        pieces = (None,) * 64
        invalid = (
            {"halfmove": True, "fullmove": 1, "message": "halfmove"},
            {"halfmove": 0.0, "fullmove": 1, "message": "halfmove"},
            {"halfmove": 0, "fullmove": False, "message": "fullmove"},
            {"halfmove": 0, "fullmove": 1.0, "message": "fullmove"},
        )
        for case in invalid:
            with self.subTest(case=case):
                with self.assertRaisesRegex(PositionValidationError, case["message"]):
                    PositionState(
                        pieces,
                        halfmove=case["halfmove"],  # type: ignore[arg-type]
                        fullmove=case["fullmove"],  # type: ignore[arg-type]
                    )

    def test_direct_state_rejects_mutable_or_coercible_field_shapes(self):
        pieces = (None,) * 64
        invalid = (
            {"kwargs": {"pieces": [None] * 64}, "message": "immutable tuple"},
            {"kwargs": {"pieces": pieces[:-1] + (1,)}, "message": "piece symbol"},
            {"kwargs": {"pieces": pieces, "turn": 1}, "message": "turn"},
            {"kwargs": {"pieces": pieces, "castling": ()}, "message": "castling rights"},
            {"kwargs": {"pieces": pieces, "en_passant": None}, "message": "en-passant"},
        )
        for case in invalid:
            with self.subTest(case=case):
                with self.assertRaisesRegex(PositionValidationError, case["message"]):
                    PositionState(**case["kwargs"])  # type: ignore[arg-type]

    def test_edit_methods_fail_closed_on_non_text_piece_or_castling_symbols(self):
        position = empty_position()
        for piece in (1, True, ["Q"]):
            with self.subTest(piece=piece):
                with self.assertRaisesRegex(PositionValidationError, "piece symbol"):
                    position.with_piece("a1", piece)  # type: ignore[arg-type]
        for rights in (("K", 1), 3):
            with self.subTest(rights=rights):
                with self.assertRaisesRegex(PositionValidationError, "castling rights"):
                    position.with_castling(rights)  # type: ignore[arg-type]

    def test_en_passant_rank_must_match_side_to_move(self):
        PositionState.from_fen("8/8/8/3pP3/8/8/8/K6k w - d6 0 12")
        PositionState.from_fen("8/8/8/8/3Pp3/8/8/K6k b - d3 0 12")
        with self.assertRaisesRegex(PositionValidationError, "en-passant"):
            PositionState.from_fen("8/8/8/3pP3/8/8/8/K6k b - d6 0 12")

    def test_move_counters_are_validated(self):
        with self.assertRaisesRegex(PositionValidationError, "halfmove"):
            PositionState.from_fen("8/8/8/8/8/8/8/K6k w - - -1 1")
        with self.assertRaisesRegex(PositionValidationError, "fullmove"):
            PositionState.from_fen("8/8/8/8/8/8/8/K6k w - - 0 0")

    def test_clear_preserves_turn_but_resets_position_metadata(self):
        position = PositionState.from_fen("r3k2r/8/8/8/8/8/8/R3K2R b KQkq - 17 22")
        cleared = position.cleared()
        self.assertEqual(cleared.turn, "b")
        self.assertEqual(cleared.castling, "-")
        self.assertEqual(cleared.en_passant, "-")
        self.assertEqual(cleared.halfmove, 0)
        self.assertEqual(cleared.fullmove, 22)
        self.assertEqual(cleared.pieces, (None,) * 64)


if __name__ == "__main__":
    unittest.main()
