from __future__ import annotations

import unittest

from acs.input_limits import MAX_FEN_CHARS
from acs.position_editor import PositionState, PositionValidationError, standard_position


class Section1PositionStateSerializationBoundaryTests(unittest.TestCase):
    def test_low_level_metadata_corruption_fails_closed_before_publication(self) -> None:
        cases = (
            ("turn", "x", "turn must be 'w' or 'b'"),
            ("castling", "qK", "canonical KQkq order"),
        )
        for field, value, message in cases:
            with self.subTest(field=field):
                state = standard_position()
                object.__setattr__(state, field, value)
                with self.assertRaisesRegex(PositionValidationError, message):
                    state.to_fen()

        ep = PositionState.from_fen(
            "4k3/8/8/3pP3/8/8/8/4K3 w - d6 0 2"
        )
        object.__setattr__(ep, "en_passant", "D6")
        with self.assertRaisesRegex(
            PositionValidationError,
            "canonical lowercase text",
        ):
            ep.to_fen()

    def test_low_level_piece_corruption_fails_closed_before_publication(self) -> None:
        state = standard_position()
        pieces = list(state.pieces)
        pieces[0] = "Z"
        object.__setattr__(state, "pieces", tuple(pieces))
        with self.assertRaisesRegex(
            PositionValidationError,
            "invalid piece symbol",
        ):
            state.to_fen()

        state = standard_position()
        object.__setattr__(state, "pieces", list(state.pieces))
        with self.assertRaisesRegex(
            PositionValidationError,
            "immutable tuple",
        ):
            state.to_fen()

    def test_low_level_active_text_is_rejected_before_custom_hooks(self) -> None:
        class HostileText(str):
            comparisons = 0
            lengths = 0

            def __eq__(self, _other):
                type(self).comparisons += 1
                raise AssertionError("hostile equality hook must not execute")

            def __hash__(self):
                raise AssertionError("hostile hash hook must not execute")

            def __len__(self):
                type(self).lengths += 1
                raise AssertionError("hostile length hook must not execute")

        state = standard_position()
        object.__setattr__(state, "turn", HostileText("w"))
        with self.assertRaisesRegex(PositionValidationError, "turn must be"):
            state.to_fen()
        self.assertEqual(HostileText.comparisons, 0)
        self.assertEqual(HostileText.lengths, 0)

    def test_low_level_whole_fen_budget_is_revalidated(self) -> None:
        state = standard_position()
        object.__setattr__(state, "halfmove", 10 ** (MAX_FEN_CHARS - 20))
        with self.assertRaisesRegex(PositionValidationError, "FEN is too long"):
            state.to_fen()

    def test_normal_round_trip_is_unchanged(self) -> None:
        state = PositionState.from_fen(
            "4k3/8/8/3pP3/8/8/8/4K3 w - d6 17 42"
        )
        rendered = state.to_fen()
        self.assertEqual(
            rendered,
            "4k3/8/8/3pP3/8/8/8/4K3 w - d6 17 42",
        )
        self.assertEqual(PositionState.from_fen(rendered), state)


if __name__ == "__main__":
    unittest.main()
