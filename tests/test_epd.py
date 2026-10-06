from __future__ import annotations

from pathlib import Path
import unittest
from unittest.mock import patch

from acs.epd import (
    EpdOperation,
    EpdParseError,
    EpdRecord,
    MAX_EPD_CHARS,
    MAX_EPD_OPERATIONS,
    looks_like_epd,
    parse_epd,
    serialize_epd,
)
from acs.move_entry import MoveEntryKind, parse_move_entry
from acs.position_editor import PositionState
from acs.position_text import parse_position_text
from acs.webapp import AccessibleChessAPI


START_BOARD = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR"
START_EPD = f"{START_BOARD} w KQkq -"
START_FEN = f"{START_BOARD} w KQkq - 0 1"


class EpdFormatTests(unittest.TestCase):
    def test_four_field_epd_uses_canonical_position_authority(self):
        record = parse_epd(START_EPD)
        self.assertEqual(record.position.to_fen(), START_FEN)
        self.assertEqual(record.operations, ())
        self.assertTrue(looks_like_epd(START_EPD))

    def test_hmvc_fmvn_and_unknown_operations_are_preserved(self):
        text = START_EPD + ' hmvc 7; id "opening; sample"; bm e4 d4; fmvn 12;'
        record = parse_epd(text)

        self.assertEqual(record.position.halfmove, 7)
        self.assertEqual(record.position.fullmove, 12)
        self.assertEqual(
            record.operations,
            (
                EpdOperation("hmvc", "7"),
                EpdOperation("id", '"opening; sample"'),
                EpdOperation("bm", "e4 d4"),
                EpdOperation("fmvn", "12"),
            ),
        )
        self.assertEqual(serialize_epd(record), text)
        self.assertEqual(parse_epd(record.to_epd()), record)

    def test_serializer_adds_counter_operations_when_state_requires_them(self):
        position = PositionState.from_fen(f"{START_BOARD} b KQkq - 9 21")
        record = EpdRecord(
            position=position,
            operations=(EpdOperation("id", '"counter position"'),),
        )
        self.assertEqual(
            serialize_epd(record),
            f'{START_BOARD} b KQkq - id "counter position"; hmvc 9; fmvn 21;',
        )

    def test_operation_must_be_semicolon_terminated(self):
        with self.assertRaisesRegex(
            EpdParseError,
            "each EPD operation must end with a semicolon",
        ):
            parse_epd(START_EPD + ' id "missing terminator"')

    def test_quoted_operand_must_close(self):
        with self.assertRaisesRegex(EpdParseError, "unterminated quoted operand"):
            parse_epd(START_EPD + ' id "broken;')

    def test_invalid_and_duplicate_counter_operations_fail_closed(self):
        with self.assertRaisesRegex(EpdParseError, "duplicate EPD hmvc"):
            parse_epd(START_EPD + " hmvc 1; hmvc 2;")
        with self.assertRaisesRegex(EpdParseError, "non-negative ASCII integer"):
            parse_epd(START_EPD + " hmvc ١;")
        with self.assertRaisesRegex(EpdParseError, "fmvn must be at least 1"):
            parse_epd(START_EPD + " fmvn 0;")
        signed = parse_epd(START_EPD + " hmvc +7; fmvn +12;")
        self.assertEqual(signed.position.halfmove, 7)
        self.assertEqual(signed.position.fullmove, 12)
        with self.assertRaisesRegex(EpdParseError, "non-negative ASCII integer"):
            parse_epd(START_EPD + " hmvc -1;")

    def test_operation_budget_is_bounded(self):
        operations = " ".join("noop;" for _ in range(MAX_EPD_OPERATIONS + 1))
        with self.assertRaisesRegex(EpdParseError, "too many operations"):
            parse_epd(START_EPD + " " + operations)

    def test_record_counter_operations_must_match_canonical_position(self):
        position = PositionState.from_fen(f"{START_BOARD} w KQkq - 7 12")
        with self.assertRaisesRegex(EpdParseError, "hmvc operation does not match"):
            EpdRecord(
                position=position,
                operations=(EpdOperation("hmvc", "8"),),
            )
        with self.assertRaisesRegex(EpdParseError, "fmvn operation does not match"):
            EpdRecord(
                position=position,
                operations=(EpdOperation("fmvn", "13"),),
            )
        with self.assertRaisesRegex(EpdParseError, "non-negative ASCII integer"):
            EpdRecord(
                position=position,
                operations=(EpdOperation("hmvc", "not-a-number"),),
            )
        with self.assertRaisesRegex(EpdParseError, "fmvn must be at least 1"):
            EpdRecord(
                position=position,
                operations=(EpdOperation("fmvn", "0"),),
            )

        canonical = EpdRecord(
            position=position,
            operations=(
                EpdOperation("hmvc", "7"),
                EpdOperation("fmvn", "12"),
            ),
        )
        self.assertEqual(parse_epd(canonical.to_epd()), canonical)

    def test_quoted_escape_sequences_round_trip_without_semicolon_confusion(self):
        text = START_EPD + r' id "quote: \"; slash: \\";'
        record = parse_epd(text)
        self.assertEqual(record.operations, (EpdOperation("id", r'"quote: \"; slash: \\"'),))
        self.assertEqual(record.to_epd(), text)
        self.assertEqual(parse_epd(record.to_epd()), record)

        with self.assertRaisesRegex(EpdParseError, "invalid escape"):
            parse_epd(START_EPD + r' id "bad \n escape";')

    def test_record_constructor_rejects_duplicate_opcodes(self):
        position = PositionState.from_fen(START_FEN)
        with self.assertRaisesRegex(EpdParseError, "^duplicate EPD id operation$"):
            EpdRecord(
                position=position,
                operations=(
                    EpdOperation("id", '"first"'),
                    EpdOperation("id", '"second"'),
                ),
            )

    def test_direct_operand_representation_is_bounded_and_round_trip_safe(self):
        for operand, message in (
            ("", "operand text must not be empty"),
            (" value", "leading or trailing spaces"),
            ("value ", "leading or trailing spaces"),
            ("x" * (MAX_EPD_CHARS + 1), "operand is too long"),
        ):
            with self.subTest(operand_length=len(operand), message=message):
                with self.assertRaisesRegex(EpdParseError, message):
                    EpdOperation("Xtest", operand)

        empty_string = EpdOperation("Xtest", '""')
        record = EpdRecord(
            position=PositionState.from_fen(START_FEN),
            operations=(empty_string,),
        )
        self.assertEqual(parse_epd(record.to_epd()), record)

    def test_serializer_enforces_total_epd_line_budget(self):
        record = EpdRecord(
            position=PositionState.from_fen(START_FEN),
            operations=tuple(
                EpdOperation(f"X{index}", '"' + ("x" * 255) + '"')
                for index in range(16)
            ),
        )
        with self.assertRaisesRegex(EpdParseError, "^serialized EPD is too long$"):
            serialize_epd(record)

    def test_epd_character_budget_is_exact(self):
        canonical = START_EPD + " noop;"
        at_limit = canonical + (" " * (MAX_EPD_CHARS - len(canonical)))
        self.assertEqual(parse_epd(at_limit).position.to_fen(), START_FEN)
        self.assertTrue(looks_like_epd(at_limit))

        too_long = at_limit + " "
        with self.assertRaisesRegex(EpdParseError, "^EPD is too long$"):
            parse_epd(too_long)
        self.assertFalse(looks_like_epd(too_long))

    def test_opcode_grammar_uniqueness_and_private_namespace(self):
        with self.assertRaisesRegex(EpdParseError, "duplicate EPD noop"):
            parse_epd(START_EPD + " noop; noop value;")
        with self.assertRaisesRegex(EpdParseError, "invalid EPD opcode"):
            parse_epd(START_EPD + " a value;")
        with self.assertRaisesRegex(EpdParseError, "invalid EPD opcode"):
            parse_epd(START_EPD + " abcdefghijklmnop value;")

        private = parse_epd(START_EPD + " Xcase value;")
        self.assertEqual(private.operations, (EpdOperation("Xcase", "value"),))

    def test_epd_is_printable_ascii_and_string_payload_is_bounded(self):
        with self.assertRaisesRegex(EpdParseError, "printable ASCII"):
            parse_epd(START_EPD + ' id "позиція";')
        with self.assertRaisesRegex(EpdParseError, "exceeds 255 bytes"):
            parse_epd(START_EPD + ' id "' + ("x" * 256) + '";')
        valid = parse_epd(START_EPD + ' id "' + ("x" * 255) + '";')
        self.assertEqual(len(valid.operations), 1)

    def test_invalid_board_is_delegated_to_canonical_fen_representation(self):
        malformed = "9/8/8/8/8/8/8/4K2k w - -"
        self.assertTrue(looks_like_epd(malformed))
        with self.assertRaisesRegex(EpdParseError, "invalid EPD position fields"):
            parse_epd(malformed)

    def test_non_exact_text_is_rejected_before_subclass_hooks(self):
        class HostileEpd(str):
            length_calls = 0

            def __len__(self):
                type(self).length_calls += 1
                raise AssertionError("hostile text hook must not run")

        hostile = HostileEpd(START_EPD)
        with self.assertRaisesRegex(EpdParseError, "^EPD must be text$"):
            parse_epd(hostile)
        self.assertFalse(looks_like_epd(hostile))
        self.assertEqual(HostileEpd.length_calls, 0)

    def test_position_editor_exposes_epd_format_guidance_to_screen_readers(self):
        html = (
            Path(__file__).resolve().parents[1] / "web" / "index.html"
        ).read_text(encoding="utf-8")
        self.assertIn(
            '<textarea id="position-input" spellcheck="false" aria-describedby="position-format-hint"></textarea>',
            html,
        )
        self.assertIn(
            'id="position-format-hint">Підтримується формат W:/B: або EPD. Для FEN використовуйте поле FEN вище.</div>',
            html,
        )
        self.assertIn(
            "Supports W:/B: or EPD. Use the FEN field above for FEN.",
            html,
        )

    def test_position_text_adapter_makes_epd_reachable_in_accessible_flow(self):
        epd = START_EPD + ' hmvc 3; fmvn 8; id "lesson 1";'
        self.assertEqual(
            parse_position_text(epd, language="en"),
            f"{START_BOARD} w KQkq - 3 8",
        )

        api = AccessibleChessAPI(lang="uk")
        result = api.set_position_text(epd)
        self.assertTrue(result["ok"])
        self.assertEqual(api.board.fen(), f"{START_BOARD} w KQkq - 3 8")

    def test_malformed_epd_is_localized_and_does_not_mutate_live_board(self):
        malformed = START_EPD + " hmvc invalid;"
        with self.assertRaisesRegex(ValueError, "^Некоректний EPD\\.$"):
            parse_position_text(malformed, language="uk")
        with self.assertRaisesRegex(ValueError, "^Invalid EPD\\.$"):
            parse_position_text(malformed, language="en")

        api = AccessibleChessAPI(lang="uk")
        before = api.board.fen()
        result = api.set_position_text(malformed)
        self.assertFalse(result["ok"])
        self.assertEqual(result["announcement"], "Некоректний EPD.")
        self.assertEqual(api.board.fen(), before)

    def test_malformed_numeric_epd_tail_is_not_misrouted_as_a_move(self):
        malformed = START_EPD + " 12"
        self.assertTrue(looks_like_epd(malformed))

        with self.assertRaisesRegex(ValueError, "^Invalid EPD\\.$"):
            parse_position_text(malformed, language="en")

        api = AccessibleChessAPI(lang="en")
        before = api.board.fen()
        result = api.make_move(malformed)
        self.assertFalse(result["ok"])
        self.assertEqual(result["announcement"], "Invalid EPD.")
        self.assertTrue(result["announceMoveErrors"])
        self.assertEqual(api.board.fen(), before)

    def test_ordinary_six_field_fen_is_never_classified_as_epd(self):
        for fen in (
            START_FEN,
            f"{START_BOARD} b KQkq - 999 123456",
        ):
            with self.subTest(fen=fen):
                self.assertFalse(looks_like_epd(fen))

    def test_epd_move_input_history_recovery_failure_is_atomic(self):
        api = AccessibleChessAPI(lang="uk")
        self.assertTrue(api.make_move("e4")["ok"])
        before_fen = api.board.fen()
        before_start_fen = api.start_fen
        before_sans = list(api.sans)
        before_sides = list(api.move_sides)
        before_history = api.review_history
        before_adapter = api.review_adapter
        before_live_node = api.live_history_node

        epd = START_EPD + ' hmvc 2; fmvn 3; id "atomic";'
        with patch(
            "acs.webapp.ReviewHistory",
            side_effect=RuntimeError("private history failure"),
        ):
            result = api.make_move(epd)

        self.assertFalse(result["ok"])
        self.assertEqual(
            result["announcement"],
            "Не вдалося підготувати історію нової позиції.",
        )
        self.assertTrue(result["announceMoveErrors"])
        self.assertNotIn("private history failure", result["announcement"])
        self.assertEqual(api.board.fen(), before_fen)
        self.assertEqual(api.start_fen, before_start_fen)
        self.assertEqual(api.sans, before_sans)
        self.assertEqual(api.move_sides, before_sides)
        self.assertIs(api.review_history, before_history)
        self.assertIs(api.review_adapter, before_adapter)
        self.assertEqual(api.live_history_node, before_live_node)

    def test_actual_web_move_input_accepts_epd_and_replaces_live_root(self):
        api = AccessibleChessAPI(lang="uk")
        self.assertTrue(api.make_move("e4")["ok"])
        epd = START_EPD + ' hmvc 6; fmvn 9; id "move input";'

        result = api.make_move(epd)

        self.assertTrue(result["ok"])
        self.assertEqual(api.board.fen(), f"{START_BOARD} w KQkq - 6 9")
        self.assertEqual(api.start_fen, f"{START_BOARD} w KQkq - 6 9")
        self.assertEqual(api.sans, [])
        self.assertEqual(api.move_sides, [])
        self.assertEqual(len(api.review_history.tree_nodes()), 1)

    def test_actual_web_move_input_announces_malformed_epd_without_mutation(self):
        api = AccessibleChessAPI(lang="uk")
        before = api.board.fen()

        result = api.make_move(START_EPD + " hmvc invalid;")

        self.assertFalse(result["ok"])
        self.assertEqual(result["announcement"], "Некоректний EPD.")
        self.assertTrue(result["announceMoveErrors"])
        self.assertEqual(api.board.fen(), before)

        api_en = AccessibleChessAPI(lang="en")
        before_en = api_en.board.fen()
        result_en = api_en.make_move(START_EPD + " fmvn 0;")
        self.assertFalse(result_en["ok"])
        self.assertEqual(result_en["announcement"], "Invalid EPD.")
        self.assertTrue(result_en["announceMoveErrors"])
        self.assertEqual(api_en.board.fen(), before_en)

    def test_actual_web_move_input_still_leaves_six_field_fen_to_move_parser(self):
        api = AccessibleChessAPI(lang="en")
        before = api.board.fen()

        result = api.make_move(START_FEN)

        self.assertFalse(result["ok"])
        self.assertEqual(api.board.fen(), before)
        self.assertNotEqual(result["announcement"], "Position loaded from text editor.")
        self.assertNotIn("announceMoveErrors", result)

    def test_move_entry_routes_epd_without_reclassifying_six_field_fen(self):
        epd_intent = parse_move_entry(START_EPD + " hmvc 4; fmvn 5;")
        self.assertEqual(epd_intent.kind, MoveEntryKind.POSITION)
        self.assertIsNotNone(epd_intent.position)
        self.assertEqual(
            epd_intent.position.to_fen(),
            f"{START_BOARD} w KQkq - 4 5",
        )

        fen_intent = parse_move_entry(START_FEN)
        self.assertEqual(fen_intent.kind, MoveEntryKind.CHESS_MOVE)
        self.assertEqual(fen_intent.move_text, START_FEN)


if __name__ == "__main__":
    unittest.main()
