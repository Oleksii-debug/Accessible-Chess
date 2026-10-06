from __future__ import annotations

import unittest

from acs.epd import (
    EpdOperation,
    EpdParseError,
    EpdRecord,
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
        with self.assertRaisesRegex(EpdParseError, "unsigned ASCII decimal"):
            parse_epd(START_EPD + " hmvc ١;")
        with self.assertRaisesRegex(EpdParseError, "fmvn must be at least 1"):
            parse_epd(START_EPD + " fmvn 0;")

    def test_operation_budget_is_bounded(self):
        operations = " ".join("noop;" for _ in range(MAX_EPD_OPERATIONS + 1))
        with self.assertRaisesRegex(EpdParseError, "too many operations"):
            parse_epd(START_EPD + " " + operations)

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
