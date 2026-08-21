import unittest

from acs.board_service import BoardCommandService, BoardSnapshot
from acs.squares import parse_square


class Dev2BoardQueryInvariantTests(unittest.TestCase):
    def _service(self, turn: str, occupant: str | None = None) -> BoardCommandService:
        pieces = [None] * 64
        pieces[parse_square("c3")] = "N"
        pieces[parse_square("d5")] = "p"
        target = parse_square("e4")
        pieces[target] = occupant
        return BoardCommandService(
            BoardSnapshot(
                tuple(pieces),
                turn,
                attacks={target: (parse_square("c3"), parse_square("d5"))},
            )
        )

    def test_empty_square_attackers_preserve_stage1_all_controllers_contract(self):
        for turn in ("w", "b"):
            with self.subTest(turn=turn):
                service = self._service(turn)
                self.assertEqual(
                    {item.square for item in service.all_controllers("e4")},
                    {"c3", "d5"},
                )
                self.assertEqual(
                    {item.square for item in service.attackers("e4")},
                    {"c3", "d5"},
                )

    def test_empty_square_defenders_keep_side_to_move_projection(self):
        white_to_move = self._service("w")
        self.assertEqual(
            {item.square for item in white_to_move.defenders("e4")}, {"c3"}
        )

        black_to_move = self._service("b")
        self.assertEqual(
            {item.square for item in black_to_move.defenders("e4")}, {"d5"}
        )

    def test_occupied_square_attackers_and_defenders_follow_occupant_color(self):
        white_piece = self._service("w", "P")
        self.assertEqual(
            {item.square for item in white_piece.attackers("e4")}, {"d5"}
        )
        self.assertEqual(
            {item.square for item in white_piece.defenders("e4")}, {"c3"}
        )

        black_piece = self._service("w", "p")
        self.assertEqual(
            {item.square for item in black_piece.attackers("e4")}, {"c3"}
        )
        self.assertEqual(
            {item.square for item in black_piece.defenders("e4")}, {"d5"}
        )


if __name__ == "__main__":
    unittest.main()
