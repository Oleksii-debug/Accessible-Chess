import unittest

from acs.bookdocument import (
    BookDocument,
    BookDocumentError,
    Diagram,
    Game,
    Heading,
    Paragraph,
    VariationTree,
)
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

    def test_reader_owns_a_detached_snapshot(self):
        document = self.make_book()
        reader = BookReader(document)
        reader.go_to(3)
        reader.save_return_point("diagram")

        document.blocks.clear()
        self.assertEqual(reader.location().block_id, "diagram")
        self.assertEqual(reader.next_game().block_id, "game")

        exposed = reader.document
        exposed.blocks.clear()
        self.assertEqual(reader.restore_return_point("diagram").block_id, "diagram")
        self.assertEqual(len(reader.document.blocks), 7)

    def test_navigation_rejects_boolean_and_string_index_without_cursor_change(self):
        reader = BookReader(self.make_book())
        before = reader.location()

        for invalid in (True, False, "1", 1.0, None):
            with self.subTest(index=invalid):
                with self.assertRaises(TypeError):
                    reader.go_to(invalid)
                self.assertEqual(reader.location(), before)

    def test_return_point_names_are_exact_text_and_normalized(self):
        reader = BookReader(self.make_book())
        reader.go_to(3)
        reader.save_return_point("  analysis  ")
        reader.go_to(6)
        self.assertEqual(reader.restore_return_point("analysis").block_id, "diagram")

        for invalid in (None, True, 7, "", "   "):
            with self.subTest(name=invalid):
                with self.assertRaises(ValueError):
                    reader.save_return_point(invalid)
                with self.assertRaises(ValueError):
                    reader.restore_return_point(invalid)

    def test_constructor_requires_semantic_document(self):
        with self.assertRaises(BookDocumentError):
            BookReader(object())

    def test_location_captures_exact_book_chapter_block_and_text_offset(self):
        reader = BookReader(self.make_book())
        reader.go_to(1)
        location = reader.set_reading_offset(3)

        self.assertTrue(location.book_id)
        self.assertEqual(len(location.snapshot_id), 64)
        self.assertEqual(location.chapter_index, 0)
        self.assertEqual(location.chapter_block_id, "part-1")
        self.assertEqual(location.chapter_source_anchor, "p1")
        self.assertEqual(location.reading_offset, 3)

        reader.save_return_point("paragraph")
        reader.go_to(6)
        self.assertEqual(reader.restore_return_point("paragraph"), location)

    def test_durable_location_roundtrip_is_strict_and_atomic(self):
        reader = BookReader(self.make_book())
        reader.go_to(1, reading_offset=2)
        payload = reader.location().as_dict()
        reader.go_to(6)
        self.assertEqual(reader.restore_location(payload).reading_offset, 2)

        before = reader.location()
        tampered = (
            dict(payload, book_id="other"),
            dict(payload, snapshot_id="0" * 64),
            dict(payload, kind="Game"),
            dict(payload, chapter_index=99),
            dict(payload, reading_offset=999),
            dict(payload, schema_version=True),
        )
        for invalid in tampered:
            with self.subTest(payload=invalid):
                with self.assertRaises((ValueError, LookupError, IndexError)):
                    reader.restore_location(invalid)
                self.assertEqual(reader.location(), before)

    def test_embedded_chess_exploration_returns_to_exact_source_context(self):
        reader = BookReader(self.make_book())
        reader.go_to(1, reading_offset=4)
        origin = reader.location()

        context = reader.open_chess_block(3)
        self.assertEqual(context.origin, origin)
        self.assertEqual(context.block.block_id, "diagram")
        self.assertEqual(context.position_fen, WHITE_FEN)
        self.assertEqual(reader.location(), origin)

        reader.go_to(6)
        restored = reader.return_to_text()
        self.assertEqual(restored, origin)
        self.assertIsNone(reader.embedded_context)

    def test_only_self_contained_chess_blocks_can_open(self):
        reader = BookReader(self.make_book())
        before = reader.location()
        with self.assertRaisesRegex(LookupError, "no self-contained"):
            reader.open_chess_block(1)
        self.assertEqual(reader.location(), before)

        context = reader.open_chess_block(4)
        self.assertEqual(context.position_fen, "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1")


if __name__ == "__main__":
    unittest.main()
