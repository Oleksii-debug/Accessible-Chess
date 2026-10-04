from __future__ import annotations

import unittest

from acs.board_service import (
    BoardCommandService,
    BoardSnapshot,
    ClockSnapshot,
    EngineSnapshot,
    MoveView,
    SquareView,
    piece_color,
)


def _empty_pieces() -> tuple[None, ...]:
    return (None,) * 64


class BoardServicePassiveBoundaryTests(unittest.TestCase):
    def test_hostile_text_subclasses_are_rejected_before_text_hooks(self) -> None:
        class HostileText(str):
            touched = False

            def strip(self, *args, **kwargs):
                type(self).touched = True
                raise AssertionError("hostile strip hook must not execute")

            def upper(self, *args, **kwargs):
                type(self).touched = True
                raise AssertionError("hostile upper hook must not execute")

            def lower(self, *args, **kwargs):
                type(self).touched = True
                raise AssertionError("hostile lower hook must not execute")

            def isupper(self, *args, **kwargs):
                type(self).touched = True
                raise AssertionError("hostile isupper hook must not execute")

            def __eq__(self, other):
                type(self).touched = True
                raise AssertionError("hostile equality hook must not execute")

            def __hash__(self):
                type(self).touched = True
                raise AssertionError("hostile hash hook must not execute")

        hostile = HostileText("N")
        board = BoardSnapshot(_empty_pieces(), "w")
        service = BoardCommandService(board)

        operations = (
            lambda: piece_color(hostile),
            lambda: MoveView(0, 1, san=hostile),
            lambda: EngineSnapshot(evaluation=hostile),
            lambda: EngineSnapshot(best_move=hostile),
            lambda: ClockSnapshot(my_clock=hostile),
            lambda: ClockSnapshot(opponent_clock=hostile),
            lambda: BoardSnapshot((hostile,) + _empty_pieces()[1:], "w"),
            lambda: BoardSnapshot(_empty_pieces(), hostile),
            lambda: SquareView(hostile, None),
            lambda: service.cycle_piece(hostile, "a1"),
            lambda: service.cycle_piece("N", "a1", color=hostile),
            lambda: service.file(hostile),
        )
        for operation in operations:
            with self.subTest(operation=operation):
                with self.assertRaises((TypeError, ValueError)):
                    operation()
                self.assertFalse(HostileText.touched)

    def test_hostile_tuple_subclasses_are_rejected_before_container_hooks(self) -> None:
        class HostileTuple(tuple):
            touched = False

            def __len__(self):
                type(self).touched = True
                raise AssertionError("hostile tuple length hook must not execute")

            def __iter__(self):
                type(self).touched = True
                raise AssertionError("hostile tuple iterator hook must not execute")

            def __contains__(self, item):
                type(self).touched = True
                raise AssertionError("hostile tuple containment hook must not execute")

        pieces = _empty_pieces()
        with self.assertRaisesRegex(ValueError, "pieces must contain exactly 64"):
            BoardSnapshot(HostileTuple(pieces), "w")
        self.assertFalse(HostileTuple.touched)

        with self.assertRaisesRegex(TypeError, "legal_moves must be a tuple"):
            BoardSnapshot(pieces, "w", legal_moves=HostileTuple((MoveView(0, 1),)))
        self.assertFalse(HostileTuple.touched)

        with self.assertRaisesRegex(TypeError, "attack origins must be tuples"):
            BoardSnapshot(pieces, "w", attacks={0: HostileTuple((1,))})
        self.assertFalse(HostileTuple.touched)

    def test_exact_builtin_values_keep_public_board_command_semantics(self) -> None:
        pieces = list(_empty_pieces())
        pieces[0] = "N"
        board = BoardSnapshot(
            tuple(pieces),
            "w",
            legal_moves=(MoveView(0, 1, "Na2", False),),
            attacks={1: (0,)},
        )
        service = BoardCommandService(
            board,
            engine=EngineSnapshot("+0.20", "Na2"),
            clocks=ClockSnapshot("01:00", "00:59"),
        )

        self.assertEqual(piece_color("N"), "w")
        self.assertEqual(service.current("a1").piece, "N")
        self.assertEqual(service.file("a")[0].square, "a1")
        self.assertEqual(service.cycle_piece("N", "a1", color="w").square, "a1")
        self.assertEqual(service.evaluation(), "+0.20")
        self.assertEqual(service.my_clock(), "01:00")


if __name__ == "__main__":
    unittest.main()
