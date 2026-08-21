import unittest

from acs.chesscore import Board


class Dev2FenAtomicityTests(unittest.TestCase):
    def test_constructor_defaults_only_for_none_and_rejects_falsey_non_fen_values(self):
        self.assertEqual(Board().fen(), Board.START)
        for value in (False, 0, "", [], {}, ()):  # no falsey fallback to START
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    Board(value)

    def test_rejected_fen_is_atomic_for_state_history_redo_and_last_move(self):
        board = Board()
        board.push_text("e4")
        board.push_text("e5")
        board.undo()
        before = (
            board.fen(),
            tuple(board.undo_stack),
            tuple(board.redo_stack),
            board.last_move,
        )
        bad_values = (
            False,
            0,
            [],
            "7k/8/8/8/8/8/8/K7 w - -",
            "7k/8/8/8/8/8/8/K7 w - - 0 1 extra",
            "7k/8/8/8/8/8/8/K7 w - - +0 1",
            "7k/8/8/8/8/8/8/K7 w - - 0 +1",
            "7k/8/8/8/8/8/8/K7 w - - ٠ 1",
        )
        for bad in bad_values:
            with self.subTest(bad=bad):
                with self.assertRaises(ValueError):
                    board.set_fen(bad)
                self.assertEqual(
                    (
                        board.fen(),
                        tuple(board.undo_stack),
                        tuple(board.redo_stack),
                        board.last_move,
                    ),
                    before,
                )

    def test_move_text_and_square_scalar_coercion_fail_closed(self):
        board = Board()
        before = board.fen()
        for value in (False, 0, [], {}, object()):
            with self.subTest(value=type(value).__name__):
                with self.assertRaises(ValueError):
                    board.push_text(value)
                self.assertEqual(board.fen(), before)
                self.assertEqual(board.undo_stack, [])
                self.assertEqual(board.redo_stack, [])


if __name__ == "__main__":
    unittest.main()
