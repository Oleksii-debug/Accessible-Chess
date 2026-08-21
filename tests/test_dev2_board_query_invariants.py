import unittest

from acs.board_service import BoardCommandService, BoardSnapshot
from acs.squares import parse_square


class Dev2BoardQueryInvariantTests(unittest.TestCase):
    def _service(self, turn: str) -> BoardCommandService:
        pieces = [None] * 64
        pieces[parse_square("c3")] = "N"
        pieces[parse_square("d5")] = "p"
        target = parse_square("e4")
        return BoardCommandService(
            BoardSnapshot(
                tuple(pieces),
                turn,
                attacks={target: (parse_square("c3"), parse_square("d5"))},
            )
        )

    def test_empty_square_attackers_and_defenders_are_side_relative(self):
        white_to_move = self._service("w")
        self.assertEqual(
            {item.square for item in white_to_move.all_controllers("e4")},
            {"c3", "d5"},
        )
        self.assertEqual(
            {item.square for item in white_to_move.attackers("e4")}, {"d5"}
        )
        self.assertEqual(
            {item.square for item in white_to_move.defenders("e4")}, {"c3"}
        )

        black_to_move = self._service("b")
        self.assertEqual(
            {item.square for item in black_to_move.attackers("e4")}, {"c3"}
        )
        self.assertEqual(
            {item.square for item in black_to_move.defenders("e4")}, {"d5"}
        )


if __name__ == "__main__":
    unittest.main()
