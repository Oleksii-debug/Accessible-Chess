from __future__ import annotations

import unittest

from acs.input_limits import MAX_FEN_CHARS
from acs.position_editor import PositionState, PositionValidationError, standard_position


class Section1PositionStateCounterBoundaryTests(unittest.TestCase):
    def test_direct_huge_counters_fail_before_decimal_rendering(self) -> None:
        state = standard_position()
        huge = 10 ** (MAX_FEN_CHARS + 1)

        with self.assertRaisesRegex(PositionValidationError, "halfmove clock is too large"):
            state.with_counters(huge, 1)
        with self.assertRaisesRegex(PositionValidationError, "fullmove number is too large"):
            state.with_counters(0, huge)

    def test_whole_canonical_fen_budget_applies_to_direct_state(self) -> None:
        state = standard_position()
        # This value is below the per-counter numeric fence and is safe for
        # Python 3.12 decimal conversion, but the complete canonical FEN would
        # exceed the shared MAX_FEN_CHARS boundary.
        budget_exhausting = 10 ** (MAX_FEN_CHARS - 1)

        with self.assertRaisesRegex(PositionValidationError, "FEN is too long"):
            state.with_counters(budget_exhausting, 1)

    def test_to_fen_contains_low_level_counter_corruption(self) -> None:
        state = standard_position()
        object.__setattr__(state, "halfmove", 10 ** (MAX_FEN_CHARS + 1))

        with self.assertRaisesRegex(PositionValidationError, "halfmove clock is too large"):
            state.to_fen()

    def test_normal_counter_round_trip_is_unchanged(self) -> None:
        state = standard_position().with_counters(123, 456)
        rendered = state.to_fen()

        self.assertLessEqual(len(rendered), MAX_FEN_CHARS)
        self.assertTrue(rendered.endswith(" 123 456"))
        self.assertEqual(PositionState.from_fen(rendered), state)


if __name__ == "__main__":
    unittest.main()
