import unittest

from acs.board_service import (
    BoardCommandService, BoardSnapshot, ClockSnapshot, EngineSnapshot,
    MaterialView, MoveView, SquareView, parse_square, piece_color,
)


def empty():
    return [None] * 64


class BoardCommandServiceTests(unittest.TestCase):
    def sample(self):
        pieces = empty()
        for sq, piece in {
            "e4": "P", "d5": "p", "f5": "p", "c3": "N", "g1": "N",
            "e2": "Q", "e7": "q", "a1": "R", "h8": "r"
        }.items():
            pieces[parse_square(sq)] = piece
        legal = (
            MoveView(parse_square("e4"), parse_square("e5"), "e5"),
            MoveView(parse_square("e4"), parse_square("d5"), "exd5", True),
            MoveView(parse_square("e4"), parse_square("f5"), "exf5", True),
        )
        attacks = {
            parse_square("e4"): (parse_square("d5"), parse_square("c3"), parse_square("f5")),
        }
        return BoardCommandService(
            BoardSnapshot(tuple(pieces), "w", legal, attacks,
                          last_move=MoveView(parse_square("e7"), parse_square("e5"), "e5"),
                          last_captured_piece="p"),
            engine=EngineSnapshot("+0.42", "Nf3"),
            clocks=ClockSnapshot("05:12", "04:58"),
        )

    def test_current_square_and_context(self):
        service = self.sample()
        self.assertEqual(service.current("e4").piece, "P")
        self.assertEqual(service.last_move().san, "e5")
        self.assertEqual(service.last_captured(), "p")
        self.assertEqual(service.evaluation(), "+0.42")
        self.assertEqual(service.best_move(), "Nf3")
        self.assertEqual(service.my_clock(), "05:12")
        self.assertEqual(service.opponent_clock(), "04:58")

    def test_legal_moves_and_captures_are_filtered_by_source(self):
        service = self.sample()
        self.assertEqual([m.san for m in service.legal_moves("e4")], ["e5", "exd5", "exf5"])
        self.assertEqual([m.san for m in service.captures("e4")], ["exd5", "exf5"])
        self.assertEqual(service.legal_moves("a1"), ())

    def test_attackers_and_defenders_follow_occupant_color(self):
        service = self.sample()
        self.assertEqual({x.square for x in service.attackers("e4")}, {"d5", "f5"})
        self.assertEqual({x.square for x in service.defenders("e4")}, {"c3"})

    def test_surroundings_are_exact_and_do_not_wrap_edges(self):
        service = self.sample()
        self.assertEqual(len(service.surroundings("e4")), 8)
        self.assertEqual({x.square for x in service.surroundings("a1")}, {"a2", "b1", "b2"})

    def test_material_counts_and_balance(self):
        material = self.sample().material()
        self.assertEqual(material.white["N"], 2)
        self.assertEqual(material.black["P"], 2)
        self.assertEqual(material.white_points, 21)
        self.assertEqual(material.black_points, 16)
        self.assertEqual(material.balance, 5)

    def test_piece_cycle_wraps_in_both_directions(self):
        service = self.sample()
        self.assertEqual(service.cycle_piece("N", "c3", direction=1).square, "g1")
        self.assertEqual(service.cycle_piece("N", "g1", direction=1).square, "c3")
        self.assertEqual(service.cycle_piece("N", "c3", direction=-1).square, "g1")
        self.assertIsNone(service.cycle_piece("B", "e4", direction=1))

    def test_rank_and_file_queries_are_stable_board_order(self):
        service = self.sample()
        self.assertEqual([x.square for x in service.rank(1)], ["a1","b1","c1","d1","e1","f1","g1","h1"])
        self.assertEqual([x.square for x in service.file("e")], ["e1","e2","e3","e4","e5","e6","e7","e8"])

    def test_invalid_inputs_fail_without_mutating_snapshot(self):
        service = self.sample()
        snapshot = service.board
        with self.assertRaises(ValueError):
            service.current("z9")
        with self.assertRaises(ValueError):
            service.cycle_piece("N", "e4", direction=0)
        with self.assertRaises(ValueError):
            service.rank(9)
        self.assertIs(service.board, snapshot)

    def test_move_view_rejects_coerced_or_impossible_shapes(self):
        self.assertEqual(MoveView(0, 1, "a2", False).frm, 0)
        invalid = (
            (True, 1, None, False),
            (0, 64, None, False),
            (1, 1, None, False),
            (0, 1, True, False),
            (0, 1, "", False),
            (0, 1, "a2\n", False),
            (0, 1, "a2", 1),
        )
        for values in invalid:
            with self.subTest(move=values):
                with self.assertRaises((TypeError, ValueError)):
                    MoveView(*values)

    def test_board_snapshot_validates_and_detaches_all_collections(self):
        pieces = tuple(empty())
        attacks = {0: (1, 8)}
        snapshot = BoardSnapshot(
            pieces,
            "w",
            (MoveView(0, 1),),
            attacks,
        )
        attacks.clear()
        self.assertEqual(snapshot.attacks[0], (1, 8))
        with self.assertRaises(TypeError):
            snapshot.attacks[0] = (2,)

        invalid = (
            lambda: BoardSnapshot(list(pieces), "w"),
            lambda: BoardSnapshot(("X",) + pieces[1:], "w"),
            lambda: BoardSnapshot(pieces, True),
            lambda: BoardSnapshot(pieces, "w", [MoveView(0, 1)]),
            lambda: BoardSnapshot(pieces, "w", (object(),)),
            lambda: BoardSnapshot(pieces, "w", attacks={True: ()}),
            lambda: BoardSnapshot(pieces, "w", attacks={0: [1]}),
            lambda: BoardSnapshot(pieces, "w", attacks={0: (0,)}),
            lambda: BoardSnapshot(pieces, "w", attacks={0: (1, 1)}),
            lambda: BoardSnapshot(pieces, "w", last_move=object()),
            lambda: BoardSnapshot(pieces, "w", last_captured_piece="X"),
        )
        for operation in invalid:
            with self.subTest(operation=operation):
                with self.assertRaises((TypeError, ValueError)):
                    operation()

    def test_projection_dtos_are_exact_detached_and_internally_consistent(self):
        for operation in (
            lambda: EngineSnapshot(evaluation=True),
            lambda: EngineSnapshot(best_move=""),
            lambda: ClockSnapshot(my_clock="05:00\n"),
            lambda: SquareView("A1", None),
            lambda: SquareView("a1", "X"),
            lambda: piece_color(True),
        ):
            with self.subTest(operation=operation):
                with self.assertRaises((TypeError, ValueError)):
                    operation()

        white = {piece: 0 for piece in "PNBRQK"}
        black = {piece: 0 for piece in "PNBRQK"}
        white["Q"] = 1
        material = MaterialView(white, black, 9, 0)
        white["Q"] = 0
        self.assertEqual(material.white["Q"], 1)
        with self.assertRaises(TypeError):
            material.white["Q"] = 0
        with self.assertRaises(ValueError):
            MaterialView({piece: 0 for piece in "PNBRQK"}, black, 1, 0)
        invalid_counts = {piece: 0 for piece in "PNBRQK"}
        invalid_counts["P"] = True
        with self.assertRaises(TypeError):
            MaterialView(invalid_counts, black, 1, 0)

    def test_service_composition_requires_snapshots_and_preserves_falsey_values(self):
        board = BoardSnapshot(tuple(empty()), "w")
        with self.assertRaisesRegex(TypeError, "BoardSnapshot"):
            BoardCommandService(object())
        with self.assertRaisesRegex(TypeError, "EngineSnapshot"):
            BoardCommandService(board, engine=object())
        with self.assertRaisesRegex(TypeError, "ClockSnapshot"):
            BoardCommandService(board, clocks=object())

        class FalseyEngine(EngineSnapshot):
            def __bool__(self):
                return False

        class FalseyClocks(ClockSnapshot):
            def __bool__(self):
                return False

        engine = FalseyEngine("+0.1", "e4")
        clocks = FalseyClocks("01:00", "02:00")
        service = BoardCommandService(board, engine=engine, clocks=clocks)
        self.assertIs(service.engine, engine)
        self.assertIs(service.clocks, clocks)

    def test_query_scalars_reject_object_string_and_boolean_coercion(self):
        service = self.sample()

        class LooksValid:
            def __str__(self):
                return "N"

        for operation in (
            lambda: service.current(LooksValid()),
            lambda: service.cycle_piece(LooksValid(), "e4"),
            lambda: service.cycle_piece("N", "e4", direction=True),
            lambda: service.cycle_piece("N", "e4", color=True),
            lambda: service.cycle_piece("N", "e4", color=""),
            lambda: service.rank(True),
            lambda: service.rank("1"),
            lambda: service.file(1),
            lambda: service.file(LooksValid()),
        ):
            with self.subTest(operation=operation):
                with self.assertRaises((TypeError, ValueError)):
                    operation()


if __name__ == "__main__":
    unittest.main()
