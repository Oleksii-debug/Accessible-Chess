from __future__ import annotations

"""UKAAF 2015 clause 5.1 examples and strict six-dot roundtrip fixtures.

Reference: UKAAF Braille Chess Code and Layout (2015), 5.1, distributed
at braillechess.org.uk/wp-content/uploads/2023/08/Braille-Chess-Notation.htm.
No source-specific licensing for full chess books is claimed.
"""

import unittest
from acs.chesscore import Board
from acs.chess_braille_factory import BrailleFactoryError
from acs.chess_braille_ukaaf2015 import (
    STANDARD_ID, decode_ukaaf2015_position_cells, encode_ukaaf2015_position,
    encode_ukaaf2015_simple_san,
)


class TestUKAAF2015ForsythPositions(unittest.TestCase):
    def test_starting_position_matches_published_2015_5_1_reference(self):
        expected = (
            "⠷⠮⠧⠿⠥⠧⠮⠷ ⠯⠯⠯⠯⠯⠯⠯⠯ ⠒⠆ "
            "⠏⠏⠏⠏⠏⠏⠏⠏ ⠗⠎⠇⠟⠅⠇⠎⠗"
        )
        result = encode_ukaaf2015_position(Board.START)
        self.assertEqual(result.position_cells, expected)
        self.assertEqual(result.placement, Board.START.split()[0])
        self.assertEqual(result.standard, STANDARD_ID)
        self.assertIs(result.layout_qualified, False)
        self.assertIs(result.tactile_qualified, False)
        self.assertEqual(result.status, "UNVERIFIED_REQUIRES_DECISION")

    def test_pieces_and_empty_rows_roundtrip_from_canonical_board(self):
        test_fens = (
            "4k3/8/8/8/8/8/8/4K3 w - - 0 1",
            Board.START,
            "r3k2r/8/8/4p3/3P4/8/8/R3K2R w KQkq - 0 1",
        )
        for fen in test_fens:
            with self.subTest(fen=fen):
                result = encode_ukaaf2015_position(fen)
                self.assertEqual(
                    decode_ukaaf2015_position_cells(result.position_cells),
                    Board(fen).fen().split()[0],
                )
                self.assertTrue(all("\u2800" <= c <= "\u283f"
                                    for c in result.position_cells if c != " "))

    def test_both_colors_have_distinct_single_cell_piece_codes(self):
        result = encode_ukaaf2015_position(Board.START).position_cells
        self.assertIn("⠷", result)  # Black rook
        self.assertIn("⠗", result)  # White rook
        self.assertIn("⠯", result)  # Black pawn
        self.assertIn("⠏", result)  # White pawn
        self.assertIn("⠥", result)  # Black king
        self.assertIn("⠅", result)  # White king

    def test_mutated_unknown_eight_dot_and_wrong_count_fail_closed(self):
        original = encode_ukaaf2015_position(Board.START).position_cells
        for mutation in (original + "⠁", original.replace("⠷", "⢷", 1),
                         original.replace("⠒⠆", "⠦", 1),
                         original.replace(" ", "  ", 1)):
            with self.subTest(mutated=mutation):
                with self.assertRaises(BrailleFactoryError):
                    decode_ukaaf2015_position_cells(mutation)

    def test_input_is_canonical_fen_not_unqualified_ascii_diagram(self):
        with self.assertRaises((BrailleFactoryError, ValueError)):
            encode_ukaaf2015_position("unknown positions")
        with self.assertRaises(BrailleFactoryError):
            decode_ukaaf2015_position_cells("⠷⠷")

    def test_deterministic_for_the_same_board(self):
        first = encode_ukaaf2015_position(Board.START)
        second = encode_ukaaf2015_position(Board.START)
        self.assertEqual(first, second)



class TestUKAAF2015AlgebraicSubset(unittest.TestCase):
    def test_exact_published_code_2015_moves(self):
        # Fixed partial examples independently drawn from UKAAF 2015 §§3.2-3.9, 2.2.
        examples = {
            "Rf4": "⠗⠋⠲",
            "d5": "⠙⠢",
            "cxd5": "⠉⠰⠙⠢",
            "f5+": "⠘⠋⠢",
            "Rxf4+": "⠗⠸⠋⠲",
            "Nce5": "⠎⠉⠑⠢",
            "Nb1c3": "⠎⠃⠂⠉⠒",
            "N1c3": "⠎⠂⠉⠒",
            "Re8#": "⠗⠑⠦⠜⠍",
        }
        for san, braille in examples.items():
            with self.subTest(san=san):
                result = encode_ukaaf2015_simple_san(san)
                self.assertEqual(result.cells, braille)
                self.assertFalse(result.move_legality_proven)
                self.assertFalse(result.layout_qualified)
                self.assertEqual(result.status, "UNVERIFIED_REQUIRES_DECISION")

    def test_uncovered_chess_codes_fail_closed(self):
        unsupported = (
            "O-O", "O-O-O", "0-0", "a8=Q", "e8=Q+", "Qd2!",
            "Rxh8??", "Nf3?!", "1.e4", "1...e5", "cxd6 e.p.",
            "cd5", "exd6=Q", "Nac3=Q", "p4", "Bxe5#?", "Kg0",
        )
        for san in unsupported:
            with self.subTest(san=san):
                with self.assertRaises(BrailleFactoryError):
                    encode_ukaaf2015_simple_san(san)

    def test_subset_is_deterministic_and_six_dot_only(self):
        first = encode_ukaaf2015_simple_san("Nxf4+")
        second = encode_ukaaf2015_simple_san("Nxf4+")
        self.assertEqual(first, second)
        self.assertTrue(all("\u2800" <= ch <= "\u283f" for ch in first.cells))

if __name__ == "__main__":
    unittest.main()
