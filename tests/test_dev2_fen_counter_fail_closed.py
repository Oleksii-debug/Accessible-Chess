import sys
import unittest

from acs.chesscore import Board
from acs.webapp import AccessibleChessAPI


_COUNTER_ERROR = "FEN: лічильники мають бути невід’ємними десятковими числами"
_SAFE_POSITION = "4k3/8/8/8/8/8/8/4K3 w - -"
_FORBIDDEN_RUNTIME_TEXT = (
    "Exceeds the limit",
    "integer string conversion",
    "sys.set_int_max_str_digits",
)


class _TemporaryIntStringLimit:
    def __init__(self, limit=640):
        self.limit = limit
        self.previous = None

    def __enter__(self):
        if not hasattr(sys, "get_int_max_str_digits"):
            raise unittest.SkipTest("Python runtime has no integer-string conversion limit")
        self.previous = sys.get_int_max_str_digits()
        sys.set_int_max_str_digits(self.limit)
        return self

    def __exit__(self, exc_type, exc, tb):
        sys.set_int_max_str_digits(self.previous)
        return False


def _board_state(board):
    return (
        board.fen(),
        tuple(board.undo_stack),
        tuple(board.redo_stack),
        board.last_move,
    )


def _api_state(api):
    return (
        api.board.fen(),
        tuple(api.sans),
        tuple(api.move_sides),
        tuple(api.redo_meta),
        api.selected_source,
        api.start_fen,
        api.live_history_node,
        api.review_history.cursor_node_id,
        tuple(api.review_history.tree_nodes()),
    )


class Dev2FenCounterFailClosedTests(unittest.TestCase):
    def test_board_oversized_halfmove_and_fullmove_fail_with_domain_error_atomically(self):
        board = Board()
        board.push_text("e4")
        before = _board_state(board)
        huge = "9" * 700

        with _TemporaryIntStringLimit():
            for fen in (
                f"{_SAFE_POSITION} {huge} 1",
                f"{_SAFE_POSITION} 0 {huge}",
            ):
                with self.subTest(counter_fen=fen[-32:]):
                    with self.assertRaisesRegex(ValueError, _COUNTER_ERROR):
                        board.set_fen(fen)
                    self.assertEqual(_board_state(board), before)

    def test_accessible_api_never_republishes_cpython_counter_limit_text(self):
        api = AccessibleChessAPI()
        self.assertTrue(api.make_move("e4")["ok"])
        before = _api_state(api)
        huge = "9" * 700

        with _TemporaryIntStringLimit():
            for fen in (
                f"{_SAFE_POSITION} {huge} 1",
                f"{_SAFE_POSITION} 0 {huge}",
            ):
                with self.subTest(counter_fen=fen[-32:]):
                    result = api.set_fen(fen)
                    self.assertFalse(result["ok"])
                    self.assertEqual(result["announcement"], _COUNTER_ERROR)
                    for marker in _FORBIDDEN_RUNTIME_TEXT:
                        self.assertNotIn(marker, result["announcement"])
                    self.assertEqual(_api_state(api), before)

    def test_large_but_convertible_counters_remain_supported_without_small_cap(self):
        near_runtime_limit = "1" * 639
        fen = f"{_SAFE_POSITION} {near_runtime_limit} {near_runtime_limit}"

        with _TemporaryIntStringLimit():
            board = Board(fen)
            self.assertEqual(board.halfmove, int(near_runtime_limit))
            self.assertEqual(board.fullmove, int(near_runtime_limit))
            self.assertEqual(board.fen(), fen)


if __name__ == "__main__":
    unittest.main()
