from __future__ import annotations

import re
import unittest
from unittest.mock import patch

from acs.input_limits import MAX_FEN_CHARS
from acs.webapp import AccessibleChessAPI, parse_sq as canonical_parse_sq


CYRILLIC = re.compile(r"[А-Яа-яІіЇїЄє]")


class Stage1LocalizedValidationCurrentTests(unittest.TestCase):
    def assertEnglishOnly(self, message: str) -> None:
        self.assertIsNone(CYRILLIC.search(message), message)

    def test_english_invalid_move_is_localized_and_atomic(self) -> None:
        api = AccessibleChessAPI(lang="en")
        before = api.get_state()

        result = api.make_move("definitely-not-a-chess-move")

        self.assertFalse(result["ok"])
        self.assertEqual(result["announcement"], api._t("move_invalid"))
        self.assertEnglishOnly(result["announcement"])
        self.assertEqual(api.get_state()["fen"], before["fen"])
        self.assertEqual(api.sans, [])
        self.assertEqual(api.move_sides, [])

    def test_english_invalid_square_never_announces_legacy_ukrainian_core_text(self) -> None:
        api = AccessibleChessAPI(lang="en")
        before_fen = api.board.fen()

        result = api.activate_square("z9")

        self.assertFalse(result["ok"])
        self.assertEqual(result["announcement"], "Invalid square.")
        self.assertEnglishOnly(result["announcement"])
        self.assertEqual(api.board.fen(), before_fen)
        self.assertIsNone(api.selected_source)

    def test_english_fen_type_size_and_structure_have_stable_localized_messages(self) -> None:
        class HostileValue:
            touched = False

            def __str__(self):
                type(self).touched = True
                raise AssertionError("rejected FEN object must not be stringified")

        api = AccessibleChessAPI(lang="en")
        before = api.board.fen()

        wrong_type = api.set_fen(HostileValue())  # type: ignore[arg-type]
        self.assertEqual(wrong_type["announcement"], "FEN must be a text value.")
        self.assertFalse(HostileValue.touched)

        oversized = api.set_fen("x" * (MAX_FEN_CHARS + 1))
        self.assertEqual(oversized["announcement"], "FEN is too long.")

        malformed = api.set_fen("not a fen")
        self.assertEqual(malformed["announcement"], "Invalid FEN.")

        for result in (wrong_type, oversized, malformed):
            self.assertFalse(result["ok"])
            self.assertEnglishOnly(result["announcement"])
        self.assertEqual(api.board.fen(), before)

    def test_english_position_text_keeps_parser_detail_but_hides_ukrainian_board_detail(self) -> None:
        api = AccessibleChessAPI(lang="en")
        before = api.board.fen()

        malformed = api.set_position_text("broken", "w")
        self.assertFalse(malformed["ok"])
        self.assertIn("W: and B:", malformed["announcement"])
        self.assertEnglishOnly(malformed["announcement"])

        # Structurally valid coordinate text reaches Board validation, where
        # adjacent kings are rejected by the legacy Ukrainian chess core.
        illegal_chess_position = api.set_position_text("W: K e1 B: K e2", "w")
        self.assertFalse(illegal_chess_position["ok"])
        self.assertEqual(illegal_chess_position["announcement"], "Invalid position.")
        self.assertEnglishOnly(illegal_chess_position["announcement"])
        self.assertEqual(api.board.fen(), before)

    def test_unexpected_internal_exceptions_do_not_enter_live_region_text(self) -> None:
        api = AccessibleChessAPI(lang="en")

        with patch("acs.webapp.Board.__init__", side_effect=RuntimeError("private FEN implementation detail")):
            fen_result = api.set_fen("8/8/8/8/8/8/8/K6k w - - 0 1")
        self.assertFalse(fen_result["ok"])
        self.assertEqual(fen_result["announcement"], "Invalid FEN.")
        self.assertNotIn("private", fen_result["announcement"])

        with patch("acs.chesscore.Board.push_text", side_effect=RuntimeError("private move implementation detail")):
            move_result = api.make_move("e4")
        self.assertFalse(move_result["ok"])
        self.assertEqual(
            move_result["announcement"],
            "Could not synchronize the board and move history.",
        )
        self.assertNotIn("private", move_result["announcement"])

        parse_calls = 0

        def fail_first_parse(value):
            nonlocal parse_calls
            parse_calls += 1
            if parse_calls == 1:
                raise RuntimeError("private square implementation detail")
            return canonical_parse_sq(value)

        with patch("acs.webapp.parse_sq", side_effect=fail_first_parse):
            square_result = api.activate_square("e2")
        self.assertFalse(square_result["ok"])
        self.assertEqual(square_result["announcement"], "Invalid square.")
        self.assertNotIn("private", square_result["announcement"])

    def test_ukrainian_expected_validation_detail_is_retained(self) -> None:
        api = AccessibleChessAPI(lang="uk")

        square = api.activate_square("z9")
        fen = api.set_fen("not a fen")

        self.assertFalse(square["ok"])
        self.assertEqual(square["announcement"], "Неправильне поле")
        self.assertFalse(fen["ok"])
        self.assertTrue(fen["announcement"].startswith("FEN"))


if __name__ == "__main__":
    unittest.main()
