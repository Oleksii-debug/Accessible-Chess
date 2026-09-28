import unittest

from acs.move_entry import parse_piece_coordinate_position
from acs.position_editor import PositionValidationError
from acs.position_text import parse_position_text


class PositionTextAuthorityTests(unittest.TestCase):
    def test_legacy_adapter_matches_canonical_position_state(self):
        text = "W: K e1 Q d1 P e4 B: K e8 Q d8 P e5"
        self.assertEqual(
            parse_position_text(text),
            parse_piece_coordinate_position(text).to_fen(),
        )

    def test_turn_is_preserved_by_single_authority(self):
        text = "W: K e1 B: K e8"
        self.assertEqual(
            parse_position_text(text, turn="b"),
            "4k3/8/8/8/8/8/8/4K3 b - - 0 1",
        )

    def test_leading_garbage_is_rejected_instead_of_partially_parsed(self):
        with self.assertRaisesRegex(ValueError, "W: and B:"):
            parse_position_text("garbage W: K e1 B: K e8")

    def test_duplicate_square_is_rejected_consistently(self):
        text = "W: K e1 Q d1 B: K e8 Q d1"
        with self.assertRaisesRegex(ValueError, "more than once"):
            parse_piece_coordinate_position(text)
        with self.assertRaisesRegex(ValueError, "more than once"):
            parse_position_text(text)

    def test_invalid_square_uses_position_representation_validation(self):
        text = "W: K e1 Q z9 B: K e8"
        with self.assertRaises(PositionValidationError):
            parse_piece_coordinate_position(text)
        with self.assertRaises(PositionValidationError):
            parse_position_text(text)

    def test_king_cardinality_is_identical_for_both_entry_points(self):
        text = "W: Q d1 B: K e8"
        with self.assertRaisesRegex(ValueError, "exactly one"):
            parse_piece_coordinate_position(text)
        with self.assertRaisesRegex(ValueError, "exactly one"):
            parse_position_text(text)


if __name__ == "__main__":
    unittest.main()
