import unittest

from acs.move_entry import parse_piece_coordinate_position
from acs.position_editor import PositionValidationError
from acs.position_text import parse_position_text
from acs.webapp import AccessibleChessAPI


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
        with self.assertRaisesRegex(ValueError, "Потрібні секції W: і B:"):
            parse_position_text("garbage W: K e1 B: K e8")

    def test_duplicate_square_is_rejected_by_both_entry_points(self):
        text = "W: K e1 Q d1 B: K e8 Q d1"
        with self.assertRaisesRegex(ValueError, "more than once"):
            parse_piece_coordinate_position(text)
        with self.assertRaisesRegex(ValueError, "Поле d1 вказане двічі"):
            parse_position_text(text)

    def test_invalid_square_uses_canonical_representation_validation(self):
        text = "W: K e1 Q z9 B: K e8"
        with self.assertRaises(PositionValidationError):
            parse_piece_coordinate_position(text)
        with self.assertRaisesRegex(ValueError, "Неправильне поле: 'z9'"):
            parse_position_text(text)

    def test_king_cardinality_is_rejected_by_both_entry_points(self):
        text = "W: Q d1 B: K e8"
        with self.assertRaisesRegex(ValueError, "exactly one"):
            parse_piece_coordinate_position(text)
        with self.assertRaisesRegex(ValueError, "Потрібно рівно по одному королю"):
            parse_position_text(text)

    def test_legacy_unknown_piece_diagnostic_remains_localized(self):
        with self.assertRaisesRegex(ValueError, "Невідома фігура: X"):
            parse_position_text("W: K e1 X d1 B: K e8")

    def test_stage1_user_flow_rejects_partial_parse_without_mutating_board(self):
        api = AccessibleChessAPI(lang="uk")
        before = api.board.fen()
        result = api.set_position_text("junk W: K e1 B: K e8", "w")
        self.assertFalse(result["ok"])
        self.assertEqual(api.board.fen(), before)
        self.assertEqual(result["announcement"], "Потрібні секції W: і B:")

    def test_stage1_user_flow_accepts_canonical_position(self):
        api = AccessibleChessAPI(lang="uk")
        result = api.set_position_text("W: K e1 Q d1 B: K e8", "b")
        self.assertTrue(result["ok"])
        self.assertEqual(
            api.board.fen(),
            "4k3/8/8/8/8/8/8/3QK3 b - - 0 1",
        )


if __name__ == "__main__":
    unittest.main()
