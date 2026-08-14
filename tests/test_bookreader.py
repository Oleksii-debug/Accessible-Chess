import unittest

from acs.bookdocument import BookDocument, Diagram, Game, Heading, Paragraph, VariationTree
from acs.bookreader import BookReader


WHITE_FEN = "8/8/8/8/8/8/4K3/7k w - - 0 1"
BLACK_FEN = "8/8/8/8/8/8/4K3/7k b - - 0 1"


class BookReaderTests(unittest.TestCase):
    def make_book(self):
        return BookDocument("Reader", blocks=[
            Heading(text="Part I", level=1, block_id="part-1", source_anchor="p1"),
            Paragraph(text="Intro"),
            Heading(text="Chapter", level=2, block_id="chapter", source_anchor="p2"),
            Diagram(fen=WHITE_FEN, alt_text="Kings", block_id="diagram", source_anchor="p3"),
            Game(pgn='[Result "*"]\n\n*', title="Example", block_id="game"),
            VariationTree(root_fen=BLACK_FEN, pgn="1... Kh2 *", block_id="variation"),
            Heading(text="Part II", level=1, block_id="part-2"),
        ])

    def test_location_exposes_source_heading_path_position_and_side(self):
        reader = BookReader(self.make_book())
        reader.go_to(3)
        loc = reader.location()
        self.assertEqual(loc.block_id, "diagram")
        self.assertEqual(loc.source_anchor, "p3")
        self.assertEqual(loc.heading_path, ("Part I", "Chapter"))
        self.assertEqual(loc.position_fen, WHITE_FEN)
        self.assertEqual(loc.side_to_move, "white")

    def test_semantic_navigation_preserves_linear_reading_order(self):
        reader = BookReader(self.make_book())
        self.assertEqual(reader.next_heading().block_id, "chapter")
        self.assertEqual(reader.next_position().block_id, "diagram")
        self.assertEqual(reader.next_game().block_id, "game")
        self.assertEqual(reader.next_position().block_id, "variation")
        self.assertEqual(reader.location().side_to_move, "black")
        self.assertEqual(reader.next_heading().block_id, "part-2")

    def test_return_points_restore_exact_semantic_location(self):
        reader = BookReader(self.make_book())
        reader.go_to(3)
        reader.save_return_point("analysis")
        reader.go_to(6)
        restored = reader.restore_return_point("analysis")
        self.assertEqual(restored.index, 3)
        self.assertEqual(restored.block_id, "diagram")
        self.assertEqual(restored.heading_path, ("Part I", "Chapter"))

    def test_boundaries_and_invalid_return_points_fail_explicitly(self):
        reader = BookReader(self.make_book())
        with self.assertRaisesRegex(LookupError, "Beginning"):
            reader.previous_block()
        reader.go_to(6)
        with self.assertRaisesRegex(LookupError, "End"):
            reader.next_block()
        with self.assertRaisesRegex(LookupError, "Unknown return point"):
            reader.restore_return_point("missing")
        with self.assertRaises(IndexError):
            reader.go_to(99)

    def test_empty_book_is_explicit_not_silent(self):
        reader = BookReader(BookDocument("Empty"))
        with self.assertRaisesRegex(LookupError, "no readable blocks"):
            reader.location()


if __name__ == "__main__":
    unittest.main()
