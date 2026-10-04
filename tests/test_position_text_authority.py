import unittest
from unittest.mock import patch

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

    def test_coordinate_text_token_budget_fails_closed_without_board_mutation(self):
        squares = [
            f"{file_name}{rank}"
            for rank in range(1, 9)
            for file_name in "abcdefgh"
        ]
        # Sixty-four complete piece/square pairs consume the representation
        # maximum (128 tokens). One extra token must stop lexical materialization
        # before duplicate-square, king-cardinality, or Board validation.
        white = " ".join(f"P {square}" for square in squares) + " Q"
        text = f"W: {white} B: K e8"

        with self.assertRaisesRegex(
            ValueError,
            "^position text contains too many piece-square tokens$",
        ):
            parse_piece_coordinate_position(text)
        with self.assertRaisesRegex(
            ValueError,
            "^Текст позиції містить забагато описів фігур$",
        ):
            parse_position_text(text)

        api = AccessibleChessAPI(lang="uk")
        before = api.board.fen()
        result = api.set_position_text(text, "w")
        self.assertFalse(result["ok"])
        self.assertEqual(api.board.fen(), before)
        self.assertEqual(
            result["announcement"],
            "Текст позиції містить забагато описів фігур",
        )

    def test_position_text_character_bound_is_exact_and_failure_atomic(self):
        canonical = "W: K e1 B: K e8"
        at_limit = canonical + (" " * (4096 - len(canonical)))
        self.assertEqual(
            parse_piece_coordinate_position(at_limit).to_fen(),
            "4k3/8/8/8/8/8/8/4K3 w - - 0 1",
        )

        too_long = at_limit + " "
        with self.assertRaisesRegex(ValueError, "^position text is too long$"):
            parse_piece_coordinate_position(too_long)
        with self.assertRaisesRegex(ValueError, "^Текст позиції занадто довгий$"):
            parse_position_text(too_long)
        with self.assertRaisesRegex(ValueError, "^position text is too long$"):
            parse_position_text(too_long, language="en")

        api = AccessibleChessAPI(lang="uk")
        before = api.board.fen()
        result = api.set_position_text(too_long, "w")
        self.assertFalse(result["ok"])
        self.assertEqual(api.board.fen(), before)
        self.assertEqual(result["announcement"], "Текст позиції занадто довгий")

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

    def test_stage1_history_rebuild_failure_preserves_live_game_atomically(self):
        api = AccessibleChessAPI(lang="uk")
        move = api.make_move("e4")
        self.assertTrue(move["ok"])

        before_fen = api.board.fen()
        before_start_fen = api.start_fen
        before_sans = list(api.sans)
        before_move_sides = list(api.move_sides)
        before_redo_meta = list(api.redo_meta)
        before_selected_source = api.selected_source
        before_history = api.review_history
        before_adapter = api.review_adapter
        before_live_node = api.live_history_node

        with patch(
            "acs.webapp.ReviewHistory",
            side_effect=RuntimeError("history rebuild failed"),
        ):
            result = api.set_position_text("W: K e1 B: K e8", "b")

        self.assertFalse(result["ok"])
        self.assertEqual(result["announcement"], "history rebuild failed")
        self.assertEqual(api.board.fen(), before_fen)
        self.assertEqual(api.start_fen, before_start_fen)
        self.assertEqual(api.sans, before_sans)
        self.assertEqual(api.move_sides, before_move_sides)
        self.assertEqual(api.redo_meta, before_redo_meta)
        self.assertEqual(api.selected_source, before_selected_source)
        self.assertIs(api.review_history, before_history)
        self.assertIs(api.review_adapter, before_adapter)
        self.assertEqual(api.live_history_node, before_live_node)

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

    def test_string_subclass_is_rejected_before_length_hooks(self):
        class HostilePositionText(str):
            def __new__(cls):
                value = super().__new__(cls, "W: K e1 B: K e8")
                value.length_calls = 0
                return value

            def __len__(self):
                self.length_calls += 1
                raise AssertionError("hostile string length hook must not run")

        payload = HostilePositionText()
        with self.assertRaisesRegex(ValueError, "^position text must be text$"):
            parse_piece_coordinate_position(payload)
        self.assertEqual(payload.length_calls, 0)

        with self.assertRaisesRegex(ValueError, "^Текст позиції має бути текстовим значенням$"):
            parse_position_text(payload)
        self.assertEqual(payload.length_calls, 0)

        api = AccessibleChessAPI(lang="uk")
        before = api.board.fen()
        result = api.set_position_text(payload, "w")
        self.assertFalse(result["ok"])
        self.assertEqual(api.board.fen(), before)
        self.assertEqual(
            result["announcement"],
            "Текст позиції має бути текстовим значенням",
        )
        self.assertEqual(payload.length_calls, 0)

    def test_move_entry_rejects_oversized_text_before_routing(self):
        canonical = "W: K e1 B: K e8"
        at_limit = canonical + (" " * (4096 - len(canonical)))
        intent = parse_move_entry(at_limit)
        self.assertEqual(intent.position.to_fen(), "4k3/8/8/8/8/8/8/4K3 w - - 0 1")

        with self.assertRaisesRegex(ValueError, "^move entry text is too long$"):
            parse_move_entry(at_limit + " ")

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
