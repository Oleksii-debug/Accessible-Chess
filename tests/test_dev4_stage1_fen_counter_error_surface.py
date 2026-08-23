from __future__ import annotations

import contextlib
import sys
import unittest

from acs.chesscore import Board
from acs.webapp import AccessibleChessAPI


_COUNTER_ERROR = "FEN: лічильники мають бути невід’ємними десятковими числами"
_RAW_IMPLEMENTATION_FRAGMENTS = (
    "Exceeds the limit",
    "integer string conversion",
    "sys.set_int_max_str_digits",
)


@contextlib.contextmanager
def _bounded_int_string_limit():
    """Make the CPython conversion boundary deterministic for this oracle."""

    previous = sys.get_int_max_str_digits()
    sys.set_int_max_str_digits(640)
    try:
        yield
    finally:
        sys.set_int_max_str_digits(previous)


class Dev4Stage1FenCounterErrorSurfaceTests(unittest.TestCase):
    @staticmethod
    def _fen(*, halfmove: str = "0", fullmove: str = "1") -> str:
        return (
            "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR "
            f"w KQkq - {halfmove} {fullmove}"
        )

    def assert_domain_error(self, message: str) -> None:
        self.assertEqual(message, _COUNTER_ERROR)
        for fragment in _RAW_IMPLEMENTATION_FRAGMENTS:
            self.assertNotIn(fragment, message)

    def test_board_oversized_halfmove_is_normalized_to_fen_domain_error(self) -> None:
        huge = "9" * 700
        with _bounded_int_string_limit():
            with self.assertRaises(ValueError) as raised:
                Board(self._fen(halfmove=huge))
        self.assert_domain_error(str(raised.exception))

    def test_board_oversized_fullmove_is_normalized_to_fen_domain_error(self) -> None:
        huge = "9" * 700
        with _bounded_int_string_limit():
            with self.assertRaises(ValueError) as raised:
                Board(self._fen(fullmove=huge))
        self.assert_domain_error(str(raised.exception))

    def _assert_api_failure_is_concise_and_atomic(self, fen: str) -> None:
        api = AccessibleChessAPI()
        played = api.make_move("e4")
        self.assertTrue(played["ok"])

        before_fen = api.board.fen()
        before_sans = tuple(api.sans)
        before_sides = tuple(api.move_sides)
        before_cursor = api.review_history.cursor_node_id
        before_live = api.live_history_node
        before_history_length = api.get_state()["historyLength"]

        with _bounded_int_string_limit():
            result = api.set_fen(fen)

        self.assertFalse(result["ok"])
        self.assert_domain_error(result["announcement"])
        self.assertEqual(api.board.fen(), before_fen)
        self.assertEqual(tuple(api.sans), before_sans)
        self.assertEqual(tuple(api.move_sides), before_sides)
        self.assertEqual(api.review_history.cursor_node_id, before_cursor)
        self.assertEqual(api.live_history_node, before_live)
        self.assertEqual(api.get_state()["historyLength"], before_history_length)

    def test_api_oversized_halfmove_does_not_republish_cpython_error(self) -> None:
        self._assert_api_failure_is_concise_and_atomic(
            self._fen(halfmove="9" * 700)
        )

    def test_api_oversized_fullmove_does_not_republish_cpython_error(self) -> None:
        self._assert_api_failure_is_concise_and_atomic(
            self._fen(fullmove="9" * 700)
        )


if __name__ == "__main__":
    unittest.main()
