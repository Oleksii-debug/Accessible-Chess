import unittest

from acs.move_entry import parse_move_entry, parse_piece_coordinate_position
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

    def test_stage1_english_user_flow_reports_english_position_error(self):
        api = AccessibleChessAPI(lang="en")
        before = api.board.fen()
        result = api.set_position_text("junk W: K e1 B: K e8", "w")
        self.assertFalse(result["ok"])
        self.assertEqual(api.board.fen(), before)
        self.assertEqual(
            result["announcement"],
            "position text must contain W: and B: sections",
        )

    def test_non_text_payload_cannot_coerce_into_a_valid_position(self):
        class CoerciblePosition:
            def __str__(self):
                return "W: K e1 B: K e8"

        payload = CoerciblePosition()
        with self.assertRaisesRegex(ValueError, "position text must be text"):
            parse_piece_coordinate_position(payload)  # type: ignore[arg-type]
        with self.assertRaisesRegex(ValueError, "Текст позиції має бути текстовим значенням"):
            parse_position_text(payload)  # type: ignore[arg-type]

        api = AccessibleChessAPI(lang="uk")
        before = api.board.fen()
        result = api.set_position_text(payload, "w")  # type: ignore[arg-type]
        self.assertFalse(result["ok"])
        self.assertEqual(api.board.fen(), before)
        self.assertEqual(
            result["announcement"],
            "Текст позиції має бути текстовим значенням",
        )

    def test_move_entry_rejects_non_text_without_invoking_string_conversion(self):
        class CoercibleEntry:
            def __init__(self):
                self.string_calls = 0

            def __str__(self):
                self.string_calls += 1
                return "W: K e1 B: K e8"

        payload = CoercibleEntry()
        with self.assertRaisesRegex(ValueError, "move entry text must be text"):
            parse_move_entry(payload)  # type: ignore[arg-type]
        self.assertEqual(payload.string_calls, 0)

    def test_stage1_falsey_non_text_payloads_are_not_coerced_to_empty_text(self):
        api = AccessibleChessAPI(lang="uk")
        before = api.board.fen()
        for payload in (None, 0, False, []):
            with self.subTest(payload=payload):
                result = api.set_position_text(payload, "w")  # type: ignore[arg-type]
                self.assertFalse(result["ok"])
                self.assertEqual(api.board.fen(), before)
                self.assertEqual(
                    result["announcement"],
                    "Текст позиції має бути текстовим значенням",
                )

    def test_invalid_turn_payloads_fail_closed_without_board_mutation(self):
        text = "W: K e1 B: K e8"
        for turn in ("x", 0, False, []):
            with self.subTest(turn=turn):
                with self.assertRaisesRegex(ValueError, "turn must be 'w' or 'b'"):
                    parse_piece_coordinate_position(text, turn=turn)  # type: ignore[arg-type]

        api = AccessibleChessAPI(lang="uk")
        before = api.board.fen()
        for turn in ("x", 0, False, []):
            with self.subTest(stage1_turn=turn):
                result = api.set_position_text(text, turn)  # type: ignore[arg-type]
                self.assertFalse(result["ok"])
                self.assertEqual(api.board.fen(), before)
                self.assertEqual(result["announcement"], "Хід має бути 'w' або 'b'")

    def test_none_turn_preserves_stage1_current_side_default(self):
        api = AccessibleChessAPI(lang="uk")
        api.set_turn("b")
        result = api.set_position_text("W: K e1 B: K e8", None)
        self.assertTrue(result["ok"])
        self.assertEqual(api.board.turn, "b")

    def test_legacy_direct_adapter_defaults_to_ukrainian_errors(self):
        with self.assertRaisesRegex(ValueError, "Потрібні секції W: і B:"):
            parse_position_text("broken position")

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
