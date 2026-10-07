import unittest

from acs.chesscore import Board


class Dev2FenAtomicityTests(unittest.TestCase):
    def test_constructor_defaults_only_for_none_and_rejects_falsey_non_fen_values(self):
        self.assertEqual(Board().fen(), Board.START)
        for value in (False, 0, "", [], {}, ()):  # no falsey fallback to START
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    Board(value)

    def test_abbreviated_fen_compatibility_is_four_field_only(self):
        four = Board("7k/8/8/8/8/8/8/K7 w - -")
        self.assertEqual(four.fen(), "7k/8/8/8/8/8/8/K7 w - - 0 1")

        with self.assertRaisesRegex(ValueError, "4 або 6 полів"):
            Board("7k/8/8/8/8/8/8/K7 b - - 17")

        six = Board("7k/8/8/8/8/8/8/K7 w - - 17 23")
        self.assertEqual(six.fen(), "7k/8/8/8/8/8/8/K7 w - - 17 23")

    def test_en_passant_target_requires_real_double_push_provenance(self):
        white_to_move = Board("7k/8/8/4p3/8/8/8/K7 w - e6 0 2")
        self.assertEqual(white_to_move.fen(), "7k/8/8/4p3/8/8/8/K7 w - e6 0 2")

        black_to_move = Board("7k/8/8/8/4P3/8/8/K7 b - e3 0 1")
        self.assertEqual(black_to_move.fen(), "7k/8/8/8/4P3/8/8/K7 b - e3 0 1")

        invalid = (
            # No pawn on the landing square of the alleged previous double push.
            "7k/8/8/8/8/8/8/K7 w - e6 0 2",
            "7k/8/8/8/8/8/8/K7 b - e3 0 1",
            # The alleged origin square is still occupied, so no double push occurred.
            "7k/4p3/8/4p3/8/8/8/K7 w - e6 0 2",
            "7k/8/8/8/4P3/8/4P3/K7 b - e3 0 1",
            # The en-passant target itself must be empty.
            "7k/8/4N3/4p3/8/8/8/K7 w - e6 0 2",
            "7k/8/8/8/4P3/4n3/8/K7 b - e3 0 1",
            # An adjacent capturing pawn cannot make a ghost en-passant target valid.
            "7k/8/8/3P4/8/8/8/K7 w - e6 0 2",
            "7k/8/8/8/3p4/8/8/K7 b - e3 0 1",
        )
        for fen in invalid:
            with self.subTest(fen=fen):
                with self.assertRaises(ValueError):
                    Board(fen)

    def test_inactive_side_cannot_remain_in_check_but_side_to_move_may_be_checked(self):
        valid_checked_side_to_move = (
            "4k3/8/8/8/8/8/4r3/4K3 w - - 0 1",
            "4k3/8/8/8/8/8/4R3/4K3 b - - 0 1",
        )
        for fen in valid_checked_side_to_move:
            with self.subTest(valid=fen):
                self.assertEqual(Board(fen).fen(), fen)

        board = Board()
        board.push_text("e4")
        before = (
            board.fen(),
            tuple(board.undo_stack),
            tuple(board.redo_stack),
            board.last_move,
        )
        impossible = (
            "4k3/8/8/8/8/8/4R3/4K3 w - - 0 1",
            "4k3/4r3/8/8/8/8/8/4K3 b - - 0 1",
        )
        for fen in impossible:
            with self.subTest(impossible=fen):
                with self.assertRaisesRegex(ValueError, "залишається під шахом"):
                    board.set_fen(fen)
                self.assertEqual(
                    (
                        board.fen(),
                        tuple(board.undo_stack),
                        tuple(board.redo_stack),
                        board.last_move,
                    ),
                    before,
                )

    def test_null_move_preserves_reloadable_legality_and_refuses_to_pass_check(self):
        normal = Board()
        self.assertEqual(normal.push_text("--"), "--")
        after_null = normal.fen()
        self.assertEqual(Board(after_null).fen(), after_null)
        self.assertEqual(normal.undo(), "--")
        self.assertEqual(normal.redo(), "--")
        self.assertEqual(normal.fen(), after_null)

        checked = Board("4k3/8/8/8/8/8/4r3/4K3 w - - 0 1")
        before = (
            checked.fen(),
            tuple(checked.undo_stack),
            tuple(checked.redo_stack),
            checked.last_move,
        )
        with self.assertRaisesRegex(ValueError, "Нульовий хід"):
            checked.push_text("--")
        self.assertEqual(
            (
                checked.fen(),
                tuple(checked.undo_stack),
                tuple(checked.redo_stack),
                checked.last_move,
            ),
            before,
        )

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
            "7k/8/8/8/8/8/8/K7 w -",
            "7k/8/8/8/8/8/8/K7 b - - 17",
            "7k/8/8/8/8/8/8/K7 w - - 0 1 extra",
            "7k/8/8/8/8/8/8/K7 w - - +0 1",
            "7k/8/8/8/8/8/8/K7 w - - 0 +1",
            "7k/8/8/8/8/8/8/K7 w - - ٠ 1",
            "7k/8/8/8/8/8/8/K7 w - - 0 ١",
            "7k/8/8/8/8/8/8/K7 w - e6 0 2",
            "7k/8/8/8/8/8/8/K7 b - e3 0 1",
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
