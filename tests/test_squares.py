import unittest

from acs.board_service import parse_square as board_parse_square
from acs.chesscore import parse_sq, sq_name
from acs.position_editor import PositionValidationError, empty_position
from acs.squares import iter_square_names, normalize_square, parse_square, square_name


class CanonicalSquareTests(unittest.TestCase):
    def test_all_64_squares_round_trip_in_stable_board_order(self):
        names = tuple(iter_square_names())
        self.assertEqual(len(names), 64)
        self.assertEqual(names[:8], ("a1", "b1", "c1", "d1", "e1", "f1", "g1", "h1"))
        self.assertEqual(names[-8:], ("a8", "b8", "c8", "d8", "e8", "f8", "g8", "h8"))
        for index, name in enumerate(names):
            with self.subTest(index=index, name=name):
                self.assertEqual(parse_square(name), index)
                self.assertEqual(square_name(index), name)

    def test_text_is_trimmed_lowercased_and_normalized(self):
        self.assertEqual(parse_square(" E4 "), 28)
        self.assertEqual(normalize_square(" H8 "), "h8")
        self.assertEqual(normalize_square(0), "a1")

    def test_invalid_text_indices_and_boolean_values_fail_closed(self):
        class LooksLikeSquare:
            def __str__(self):
                return "e4"

        for value in (
            "",
            "e",
            "e9",
            "i1",
            -1,
            64,
            True,
            False,
            b"e4",
            LooksLikeSquare(),
        ):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    parse_square(value)
        with self.assertRaises(ValueError):
            square_name(64)

    def test_existing_core_and_board_apis_delegate_to_same_identity(self):
        for name in ("a1", "e4", "h8"):
            with self.subTest(name=name):
                index = parse_square(name)
                self.assertEqual(board_parse_square(name), index)
                self.assertEqual(parse_sq(name), index)
                self.assertEqual(sq_name(index), name)

    def test_position_editor_preserves_its_public_error_type(self):
        position = empty_position()
        with self.assertRaises(PositionValidationError):
            position.piece_at("z9")


if __name__ == "__main__":
    unittest.main()
