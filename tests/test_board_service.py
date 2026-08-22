import unittest

from acs.board_service import (
    BoardCommandService, BoardSnapshot, ClockSnapshot, EngineSnapshot, MoveView,
    parse_square,
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


if __name__ == "__main__":
    unittest.main()
