from __future__ import annotations

import unittest
from collections.abc import Mapping

from acs.board_service import (
    BoardCommandService,
    BoardSnapshot,
    ClockSnapshot,
    EngineSnapshot,
    MaterialView,
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

    def test_moveview_subclasses_are_rejected_before_attribute_hooks(self) -> None:
        class HostileMove(MoveView):
            armed = False
            touched = False

            def __getattribute__(self, name):
                if name in {"frm", "to", "san", "is_capture"} and type(self).armed:
                    type(self).touched = True
                    raise AssertionError("hostile MoveView attribute hook must not execute")
                return super().__getattribute__(name)

        hostile = HostileMove(0, 1, "Na2", False)
        HostileMove.armed = True
        pieces = _empty_pieces()

        with self.assertRaisesRegex(TypeError, "legal_moves must be a tuple of MoveView"):
            BoardSnapshot(pieces, "w", legal_moves=(hostile,))
        self.assertFalse(HostileMove.touched)

        with self.assertRaisesRegex(TypeError, "last_move must be MoveView or None"):
            BoardSnapshot(pieces, "w", last_move=hostile)
        self.assertFalse(HostileMove.touched)

        exact = MoveView(0, 1, "Na2", False)
        snapshot = BoardSnapshot(pieces, "w", legal_moves=(exact,), last_move=exact)
        self.assertIs(snapshot.legal_moves[0], exact)
        self.assertIs(snapshot.last_move, exact)

    def test_snapshot_subclasses_are_rejected_before_attribute_hooks(self) -> None:
        class HostileBoard(BoardSnapshot):
            armed = False
            touched = False

            def __getattribute__(self, name):
                if name in {"pieces", "turn", "legal_moves", "attacks", "last_move", "last_captured_piece"} and type(self).armed:
                    type(self).touched = True
                    raise AssertionError("hostile BoardSnapshot attribute hook must not execute")
                return super().__getattribute__(name)

        class HostileEngine(EngineSnapshot):
            armed = False
            touched = False

            def __getattribute__(self, name):
                if name in {"evaluation", "best_move"} and type(self).armed:
                    type(self).touched = True
                    raise AssertionError("hostile EngineSnapshot attribute hook must not execute")
                return super().__getattribute__(name)

        class HostileClock(ClockSnapshot):
            armed = False
            touched = False

            def __getattribute__(self, name):
                if name in {"my_clock", "opponent_clock"} and type(self).armed:
                    type(self).touched = True
                    raise AssertionError("hostile ClockSnapshot attribute hook must not execute")
                return super().__getattribute__(name)

        board = HostileBoard(_empty_pieces(), "w")
        engine = HostileEngine("+0.1", "e4")
        clocks = HostileClock("01:00", "02:00")
        HostileBoard.armed = HostileEngine.armed = HostileClock.armed = True

        with self.assertRaisesRegex(TypeError, "exact BoardSnapshot"):
            BoardCommandService(board)
        self.assertFalse(HostileBoard.touched)

        exact_board = BoardSnapshot(_empty_pieces(), "w")
        with self.assertRaisesRegex(TypeError, "exact EngineSnapshot"):
            BoardCommandService(exact_board, engine=engine)
        self.assertFalse(HostileEngine.touched)

        with self.assertRaisesRegex(TypeError, "exact ClockSnapshot"):
            BoardCommandService(exact_board, clocks=clocks)
        self.assertFalse(HostileClock.touched)

    def test_mapping_roots_reject_active_containers_before_hooks(self) -> None:
        class HostileMapping(Mapping):
            touched = False

            def __iter__(self):
                type(self).touched = True
                raise AssertionError("hostile mapping iterator must not execute")

            def __len__(self):
                type(self).touched = True
                raise AssertionError("hostile mapping length must not execute")

            def __getitem__(self, key):
                type(self).touched = True
                raise AssertionError("hostile mapping item read must not execute")

            def items(self):
                type(self).touched = True
                raise AssertionError("hostile mapping items must not execute")

        hostile = HostileMapping()
        pieces = _empty_pieces()
        exact = {piece: 0 for piece in "PNBRQK"}

        with self.assertRaisesRegex(TypeError, "attacks must be a canonical dict"):
            BoardSnapshot(pieces, "w", attacks=hostile)
        self.assertFalse(HostileMapping.touched)

        with self.assertRaisesRegex(TypeError, "white material must be a canonical dict"):
            MaterialView(hostile, exact, 0, 0)
        self.assertFalse(HostileMapping.touched)

    def test_material_mapping_rejects_active_keys_before_hash_or_equality(self) -> None:
        class HostileText(str):
            armed = False
            touched = False

            def __hash__(self):
                if type(self).armed:
                    type(self).touched = True
                    raise AssertionError("hostile material-key hash must not execute")
                return super().__hash__()

            def __eq__(self, other):
                if type(self).armed:
                    type(self).touched = True
                    raise AssertionError("hostile material-key equality must not execute")
                return super().__eq__(other)

        hostile = HostileText("P")
        active_key_mapping = {hostile: 0, **{piece: 0 for piece in "NBRQK"}}
        exact = {piece: 0 for piece in "PNBRQK"}
        HostileText.armed = True

        with self.assertRaisesRegex(TypeError, "material keys must be canonical"):
            MaterialView(active_key_mapping, exact, 0, 0)
        self.assertFalse(HostileText.touched)

        with self.assertRaisesRegex(ValueError, "contain every canonical piece"):
            MaterialView({piece: 0 for piece in "PNBRQ"}, exact, 0, 0)

        self.assertEqual(MaterialView(exact, exact, 0, 0).balance, 0)

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
