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
        with self.assertRaisesRegex(
            PositionValidationError,
            "^invalid square: 'z9'$",
        ):
            parse_piece_coordinate_position(text)
        with self.assertRaisesRegex(ValueError, "^Неправильне поле: 'z9'$"):
            parse_position_text(text)
        with self.assertRaisesRegex(ValueError, "^invalid square: 'z9'$"):
            parse_position_text(text, language="en")

        api_uk = AccessibleChessAPI(lang="uk")
        api_en = AccessibleChessAPI(lang="en")
        before_uk = api_uk.board.fen()
        before_en = api_en.board.fen()

        rejected_uk = api_uk.set_position_text(text, "w")
        rejected_en = api_en.set_position_text(text, "w")

        self.assertFalse(rejected_uk["ok"])
        self.assertFalse(rejected_en["ok"])
        self.assertEqual(rejected_uk["announcement"], "Неправильне поле: 'z9'")
        self.assertEqual(rejected_en["announcement"], "invalid square: 'z9'")
        self.assertEqual(api_uk.board.fen(), before_uk)
        self.assertEqual(api_en.board.fen(), before_en)

    def test_long_invalid_square_is_not_echoed_into_accessible_errors(self):
        square = "z" * 64
        text = f"W: K e1 Q {square} B: K e8"

        with self.assertRaisesRegex(PositionValidationError, "^invalid square$"):
            parse_piece_coordinate_position(text)
        with self.assertRaisesRegex(ValueError, "^Неправильне поле$"):
            parse_position_text(text)
        with self.assertRaisesRegex(ValueError, "^invalid square$"):
            parse_position_text(text, language="en")

        for language, expected in (
            ("uk", "Неправильне поле"),
            ("en", "invalid square"),
        ):
            with self.subTest(language=language):
                api = AccessibleChessAPI(lang=language)
                before = api.board.fen()
                result = api.set_position_text(text, "w")
                self.assertFalse(result["ok"])
                self.assertEqual(result["announcement"], expected)
                self.assertNotIn(square, result["announcement"])
                self.assertEqual(api.board.fen(), before)

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
        self.assertEqual(
            result["announcement"],
            "Не вдалося підготувати історію нової позиції.",
        )
        self.assertNotIn("history rebuild failed", result["announcement"])
        self.assertEqual(api.board.fen(), before_fen)
        self.assertEqual(api.start_fen, before_start_fen)
        self.assertEqual(api.sans, before_sans)
        self.assertEqual(api.move_sides, before_move_sides)
        self.assertEqual(api.redo_meta, before_redo_meta)
        self.assertEqual(api.selected_source, before_selected_source)
        self.assertIs(api.review_history, before_history)
        self.assertIs(api.review_adapter, before_adapter)
        self.assertEqual(api.live_history_node, before_live_node)

        api_en = AccessibleChessAPI(lang="en")
        with patch(
            "acs.webapp.ReviewHistory",
            side_effect=RuntimeError("private implementation detail"),
        ):
            english = api_en.set_position_text("W: K e1 B: K e8", "w")
        self.assertFalse(english["ok"])
        self.assertEqual(
            english["announcement"],
            "Could not prepare history for the new position.",
        )
        self.assertNotIn("private implementation detail", english["announcement"])

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

    def test_stage1_move_text_rejects_non_text_before_custom_hooks(self):
        class HostileMoveText(str):
            touched = False

            def strip(self, *_args, **_kwargs):
                type(self).touched = True
                raise AssertionError("hostile move-text hook must not execute")

        api = AccessibleChessAPI(lang="uk")
        before = api.board.fen()

        hostile = HostileMoveText("e4")
        result = api.make_move(hostile)
        self.assertFalse(result["ok"])
        self.assertEqual(
            result["announcement"],
            "Текст ходу має бути текстовим значенням.",
        )
        self.assertEqual(api.board.fen(), before)
        self.assertFalse(HostileMoveText.touched)

        for payload in (None, 0, False, []):
            with self.subTest(payload=payload):
                result = api.make_move(payload)  # type: ignore[arg-type]
                self.assertFalse(result["ok"])
                self.assertEqual(
                    result["announcement"],
                    "Текст ходу має бути текстовим значенням.",
                )
                self.assertEqual(api.board.fen(), before)

        api_en = AccessibleChessAPI(lang="en")
        result = api_en.make_move(HostileMoveText("e4"))
        self.assertFalse(result["ok"])
        self.assertEqual(result["announcement"], "Move text must be a text value.")
        self.assertFalse(HostileMoveText.touched)

    def test_move_entry_rejects_oversized_text_before_routing(self):
        canonical = "W: K e1 B: K e8"
        at_limit = canonical + (" " * (4096 - len(canonical)))
        intent = parse_move_entry(at_limit)
        self.assertEqual(intent.position.to_fen(), "4k3/8/8/8/8/8/8/4K3 w - - 0 1")

        with self.assertRaisesRegex(ValueError, "^move entry text is too long$"):
            parse_move_entry(at_limit + " ")

    def test_stage1_history_target_rejects_non_text_before_custom_hooks(self):
        class HostileHistoryTarget(str):
            touched = False

            def strip(self, *_args, **_kwargs):
                type(self).touched = True
                raise AssertionError("hostile history-target hook must not execute")

        api = AccessibleChessAPI(lang="uk")
        self.assertTrue(api.make_move("e4")["ok"])
        before_fen = api.board.fen()
        before_node = api.review_history.cursor_node_id

        hostile = HostileHistoryTarget("start")
        result = api.go_to_move(hostile)
        self.assertFalse(result["ok"])
        self.assertEqual(result["announcement"], "Такої позиції в історії немає.")
        self.assertFalse(HostileHistoryTarget.touched)
        self.assertEqual(api.board.fen(), before_fen)
        self.assertEqual(api.review_history.cursor_node_id, before_node)

        for payload in (None, False, 0, []):
            with self.subTest(payload=payload):
                result = api.go_to_move(payload)  # type: ignore[arg-type]
                self.assertFalse(result["ok"])
                self.assertEqual(
                    result["announcement"],
                    "Такої позиції в історії немає.",
                )
                self.assertEqual(api.review_history.cursor_node_id, before_node)

    def test_stage1_move_text_character_budget_fails_before_strip_and_board_parse(self):
        at_limit = "e4" + (" " * (4096 - 2))
        api = AccessibleChessAPI(lang="uk")
        accepted = api.make_move(at_limit)
        self.assertTrue(accepted["ok"])

        api = AccessibleChessAPI(lang="uk")
        before = api.board.fen()
        oversized = "e4" + (" " * (4097 - 2))
        rejected = api.make_move(oversized)
        self.assertFalse(rejected["ok"])
        self.assertEqual(rejected["announcement"], "Текст ходу занадто довгий.")
        self.assertEqual(api.board.fen(), before)
        self.assertNotIn(oversized, rejected["announcement"])

        api_en = AccessibleChessAPI(lang="en")
        rejected_en = api_en.make_move(oversized)
        self.assertFalse(rejected_en["ok"])
        self.assertEqual(rejected_en["announcement"], "Move text is too long.")
        self.assertEqual(api_en.board.fen(), before)

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

    def test_stage1_set_turn_rejects_non_exact_text_before_equality_hooks(self):
        class HostileTurn(str):
            comparisons = 0

            def __eq__(self, _other):
                type(self).comparisons += 1
                raise AssertionError("hostile turn equality hook must not execute")

        api = AccessibleChessAPI(lang="uk")
        before_fen = api.board.fen()
        before_history = api.review_history
        before_live_node = api.live_history_node

        hostile = HostileTurn("b")
        result = api.set_turn(hostile)
        self.assertFalse(result["ok"])
        self.assertEqual(result["announcement"], "Неправильний колір.")
        self.assertEqual(HostileTurn.comparisons, 0)
        self.assertEqual(api.board.fen(), before_fen)
        self.assertIs(api.review_history, before_history)
        self.assertEqual(api.live_history_node, before_live_node)

        for color in (None, False, 0, []):
            with self.subTest(color=color):
                result = api.set_turn(color)  # type: ignore[arg-type]
                self.assertFalse(result["ok"])
                self.assertEqual(result["announcement"], "Неправильний колір.")
                self.assertEqual(api.board.fen(), before_fen)

    def test_none_turn_preserves_stage1_current_side_default(self):
        api = AccessibleChessAPI(lang="uk")
        api.set_turn("b")
        result = api.set_position_text("W: K e1 B: K e8", None)
        self.assertTrue(result["ok"])
        self.assertEqual(api.board.turn, "b")

    def test_legacy_direct_adapter_defaults_to_ukrainian_errors(self):
        with self.assertRaisesRegex(ValueError, "Потрібні секції W: і B:"):
            parse_position_text("broken position")

    def test_legacy_adapter_rejects_non_text_language_before_custom_hooks(self):
        class HostileLanguage(str):
            hash_calls = 0

            def __hash__(self):
                type(self).hash_calls += 1
                raise AssertionError("hostile language hash hook must not execute")

        text = "W: K e1 B: K e8"
        hostile = HostileLanguage("uk")
        with self.assertRaisesRegex(ValueError, "^language must be 'uk' or 'en'$"):
            parse_position_text(text, language=hostile)
        self.assertEqual(HostileLanguage.hash_calls, 0)

        for language in (None, False, 0, []):
            with self.subTest(language=language):
                with self.assertRaisesRegex(ValueError, "^language must be 'uk' or 'en'$"):
                    parse_position_text(text, language=language)  # type: ignore[arg-type]

    def test_stage1_successfully_replaces_all_live_history_state(self):
        api = AccessibleChessAPI(lang="uk")
        self.assertTrue(api.make_move("e4")["ok"])
        self.assertTrue(api.undo()["ok"])
        self.assertTrue(api.redo_meta)
        self.assertTrue(api.board.redo_stack)

        result = api.set_position_text("W: K e1 Q d1 B: K e8", "b")
        expected_fen = "4k3/8/8/8/8/8/8/3QK3 b - - 0 1"

        self.assertTrue(result["ok"])
        self.assertEqual(api.board.fen(), expected_fen)
        self.assertEqual(api.start_fen, expected_fen)
        self.assertEqual(api.sans, [])
        self.assertEqual(api.move_sides, [])
        self.assertEqual(api.redo_meta, [])
        self.assertIsNone(api.selected_source)
        self.assertEqual(api.board.undo_stack, [])
        self.assertEqual(api.board.redo_stack, [])
        self.assertIsNone(api.board.last_move)
        self.assertEqual(api.review_history.cursor_node_id, api.live_history_node)
        self.assertEqual(len(api.review_history.tree_nodes()), 1)
        self.assertEqual(api.review_adapter.current().fen, expected_fen)
        self.assertEqual(api.review_adapter.current().ply, 0)

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
