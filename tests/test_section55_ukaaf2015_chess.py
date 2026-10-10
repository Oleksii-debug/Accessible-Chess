from __future__ import annotations

"""UKAAF 2015 clause 5.1 examples and strict six-dot roundtrip fixtures.

Reference: UKAAF Braille Chess Code and Layout (2015), 5.1, distributed
at braillechess.org.uk/wp-content/uploads/2023/08/Braille-Chess-Notation.htm.
No source-specific licensing for full chess books is claimed.
"""

import unittest
from acs.chesscore import Board
from acs.bookdocument import BookDocument, Position, Paragraph, Diagram
from hashlib import sha256
import json
from acs.chess_braille_factory import BrailleFactoryError
from acs.chess_braille_ukaaf2015 import (
    STANDARD_ID, decode_ukaaf2015_position_cells, encode_ukaaf2015_position,
    encode_ukaaf2015_simple_san, build_ukaaf2015_diagram_catalog,
    encode_ukaaf2015_canonical_mainline_pgn,
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


class TestUKAAF2015SourceLinkedCatalog(unittest.TestCase):
    def test_canonical_positions_and_diagrams_have_reversible_cells(self):
        fen = "4k3/8/8/8/8/8/8/4K3 w - - 0 1"
        book = BookDocument(title="Owned chess guide", blocks=[
            Paragraph(text="Learn the position."),
            Position(fen=fen),
            Diagram(fen=fen, alt_text="Two kings at e1 and e8"),
        ])
        result = build_ukaaf2015_diagram_catalog(book)
        self.assertEqual(result.count, 2)
        self.assertEqual(result.sha256, sha256(result.data).hexdigest())
        body = json.loads(result.data.decode("utf-8"))
        self.assertIs(body["print_ready"], False)
        self.assertIs(body["layout_qualified"], False)
        self.assertEqual(body["diagram_count"], 2)
        self.assertEqual(body["diagrams"][0]["block_index"], 2)
        self.assertEqual(body["diagrams"][1]["block_index"], 3)
        self.assertEqual(
            body["diagrams"][1]["roundtrip_placement"],
            Board(fen).fen().split()[0],
        )
        self.assertEqual(result, build_ukaaf2015_diagram_catalog(book))

    def test_missing_semantic_chess_position_never_invents_a_diagram(self):
        with self.assertRaises(BrailleFactoryError):
            build_ukaaf2015_diagram_catalog(
                BookDocument(title="Text only", blocks=[Paragraph(text="No FEN")])
            )

    def test_warning_bearing_books_do_not_publish_catalog(self):
        with self.assertRaises(BrailleFactoryError):
            build_ukaaf2015_diagram_catalog(BookDocument(
                title="Unproven", blocks=[Position(
                    fen="4k3/8/8/8/8/8/8/4K3 w - - 0 1",
                )], warnings=["Unresolved source ambiguity"],
            ))


class TestUKAAF2015CanonicalPGNBridge(unittest.TestCase):
    def test_short_legal_pgn_moves_are_proven_by_existing_board(self):
        pgn = "1. e4 e5 2. Nf3 Nc6 *"
        result = encode_ukaaf2015_canonical_mainline_pgn(pgn)
        self.assertEqual([move.canonical_san for move in result.moves],
                         ["e4", "e5", "Nf3", "Nc6"])
        self.assertEqual([move.braille_cells for move in result.moves],
                         ["⠑⠲", "⠑⠢", "⠎⠋⠒", "⠎⠉⠖"])
        self.assertEqual(result.start_fen, Board.START)
        self.assertEqual(result.moves[0].before_fen, Board.START)
        self.assertEqual(result.moves[-1].after_fen, result.end_fen)
        self.assertIs(result.layout_qualified, False)
        self.assertIs(result.variation_proof, False)
        self.assertEqual(result.status, "UNVERIFIED_REQUIRES_DECISION")

    def test_illegal_chess_move_is_rejected_by_canonical_board(self):
        with self.assertRaises(BrailleFactoryError):
            encode_ukaaf2015_canonical_mainline_pgn("1. e4 e5 2. e5 *")

    def test_unqualified_variations_and_commentary_are_refused(self):
        examples = (
            "1. e4 (1. d4) e5 *",
            "1. e4 {owned analysis} e5 *",
            "1. e4 $1 e5 *",
            "1. e4 e5 2. Nf3 Nc6 3. Bc4 Bc5 4. O-O *",
        )
        for pgn in examples:
            with self.subTest(pgn=pgn), self.assertRaises(BrailleFactoryError):
                encode_ukaaf2015_canonical_mainline_pgn(pgn)

    def test_explicit_promotion_but_unqualified_braille_code_is_refused(self):
        pgn = (
            '[SetUp "1"]\n[FEN "4k3/P7/8/8/8/8/8/4K3 w - - 0 1"]\n'
            '[Result "*"]\n\n1. a8=Q *'
        )
        with self.assertRaises(BrailleFactoryError):
            encode_ukaaf2015_canonical_mainline_pgn(pgn)

    def test_multiple_games_or_oversized_source_cannot_be_misidentified(self):
        for pgn in ("1. e4 e5 *\n\n1. d4 d5 *", "e" * 100001):
            with self.subTest(example=pgn[:20]), self.assertRaises(BrailleFactoryError):
                encode_ukaaf2015_canonical_mainline_pgn(pgn)

if __name__ == "__main__":
    unittest.main()
