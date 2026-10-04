from __future__ import annotations

import unittest

from acs.chesscore import Board, Move


class _MoveSpoof:
    frm = 12
    to = 28
    promotion = None
    en_passant = False
    castle = False

    def __eq__(self, other):
        return True


class _MoveSubclass(Move):
    pass


class D02CanonicalMoveScalarFailClosedTests(unittest.TestCase):
    def _snapshot(self, board: Board):
        return (
            board.fen(),
            tuple(board.undo_stack),
            tuple(board.redo_stack),
            board.last_move,
        )

    def test_move_square_identity_rejects_bool_coercion_and_out_of_range_values(self) -> None:
        bad_from = (True, False, -1, 64, 1.0, "1", None, (), [])
        for value in bad_from:
            with self.subTest(frm=value):
                with self.assertRaises(ValueError):
                    Move(value, 18)

        bad_to = (True, False, -1, 64, 18.0, "18", None, (), {})
        for value in bad_to:
            with self.subTest(to=value):
                with self.assertRaises(ValueError):
                    Move(1, value)

        self.assertEqual(Move(1, 18), Move(1, 18))
        self.assertNotEqual(Move(1, 18), Move(2, 18))

    def test_move_metadata_rejects_scalar_coercion_but_keeps_canonical_values(self) -> None:
        for promotion in (True, False, 1, "q", "QQ", "", [], {}):
            with self.subTest(promotion=promotion):
                with self.assertRaises(ValueError):
                    Move(8, 0, promotion=promotion)
        for flag in (0, 1, "true", None, [], {}):
            with self.subTest(en_passant=flag):
                with self.assertRaises(ValueError):
                    Move(28, 21, en_passant=flag)
            with self.subTest(castle=flag):
                with self.assertRaises(ValueError):
                    Move(4, 6, castle=flag)

        for promotion in (None, "Q", "R", "B", "N"):
            self.assertEqual(Move(8, 0, promotion=promotion).promotion, promotion)
        self.assertTrue(Move(28, 21, en_passant=True).en_passant)
        self.assertTrue(Move(4, 6, castle=True).castle)

    def test_spoof_or_subclass_cannot_alias_a_legal_move_or_mutate_board(self) -> None:
        board = Board()
        legal = board.parse_move("e4")
        self.assertIs(type(legal), Move)
        before = self._snapshot(board)

        for spoof in (_MoveSpoof(), _MoveSubclass(12, 28)):
            with self.subTest(spoof=type(spoof).__name__):
                with self.assertRaisesRegex(ValueError, "canonical Move"):
                    board.san(spoof)
                self.assertEqual(self._snapshot(board), before)
                with self.assertRaisesRegex(ValueError, "canonical Move"):
                    board.push(spoof)
                self.assertEqual(self._snapshot(board), before)

    def test_board_query_scalars_fail_closed_without_state_or_history_mutation(self) -> None:
        board = Board()
        board.push_text("e4")
        board.undo()
        before = self._snapshot(board)

        calls = (
            lambda: board.king_square(False),
            lambda: board.king_square("x"),
            lambda: board.attacked(True, "w"),
            lambda: board.attacked(0, False),
            lambda: board.in_check(""),
            lambda: list(board.pseudo_moves(False)),
            lambda: board.square_description(-1),
            lambda: board.square_description(True),
            lambda: board.pieces_description(False),
            lambda: board.attacks_from(64),
            lambda: board.attacks_from(True),
            lambda: board.attackers_of(-1),
        )
        for call in calls:
            with self.subTest(call=call):
                with self.assertRaises(ValueError):
                    call()
                self.assertEqual(self._snapshot(board), before)

    def test_valid_move_castling_en_passant_and_promotion_paths_remain_canonical(self) -> None:
        board = Board()
        self.assertEqual(board.push_text("e4"), "e4")
        self.assertEqual(board.last_move, Move(12, 28))
        self.assertEqual(board.undo(), "e4")
        self.assertEqual(board.redo(), "e4")

        castle = Board("4k2r/8/8/8/8/8/8/4K2R w Kk - 0 1")
        move = castle.parse_move("O-O")
        self.assertEqual(move, Move(4, 6, castle=True))
        self.assertEqual(castle.push(move), "O-O")

        ep = Board("4k3/8/8/3pP3/8/8/8/4K3 w - d6 0 2")
        move = ep.parse_move("exd6")
        self.assertEqual(move, Move(36, 43, en_passant=True))
        self.assertEqual(ep.push(move), "exd6")

        promotion = Board("4k3/P7/8/8/8/8/8/4K3 w - - 0 1")
        move = promotion.parse_move("a8=Q+")
        self.assertEqual(move, Move(48, 56, promotion="Q"))
        self.assertEqual(promotion.push(move), "a8=Q+")

    def test_oversized_fen_counters_use_stable_domain_error_and_are_atomic(self) -> None:
        board = Board()
        board.push_text("e4")
        board.push_text("e5")
        board.undo()
        before = self._snapshot(board)
        parts = board.fen().split()
        huge = "9" * 10000

        for index in (4, 5):
            mutated = list(parts)
            mutated[index] = huge
            with self.subTest(counter=index):
                with self.assertRaisesRegex(
                    ValueError,
                    "FEN: лічильники мають бути невід’ємними десятковими числами",
                ):
                    board.set_fen(" ".join(mutated))
                self.assertEqual(self._snapshot(board), before)


if __name__ == "__main__":
    unittest.main()
