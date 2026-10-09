from __future__ import annotations

"""Real canonical PGN -> BookDocument route, no mocked chess parser or book model."""

from hashlib import sha256
import unittest

from acs.bookdocument import BookDocument, Game
from acs.format_factory_intake import (
    FactoryIntakeError, import_factory_book, inspect_factory_source,
)
from acs.format_factory_pgn_book import FactoryPgnBookError, import_pgn_as_book
from acs.format_factory_export import export_factory_preview


FIRST = (
    '[Event "Opening lesson"]\n[White "Player A"]\n'
    '[Black "Player B"]\n[Result "*"]\n\n'
    '1. e4 {Read the center} e5 2. Nf3 Nc6 *\n'
)
SECOND = (
    '[Event "Second game"]\n[White "Player C"]\n'
    '[Black "Player D"]\n[Result "*"]\n\n'
    '1. d4 d5 2. c4 e6 *\n'
)


class Section54StrictPgnBookTests(unittest.TestCase):
    def test_one_source_two_games_become_canonical_book_blocks(self):
        source = (FIRST + "\n" + SECOND).encode("utf-8")
        imported = import_factory_book(
            source, source_name="my-collection.pgn", title="My chess study",
        )
        self.assertIsInstance(imported.document, BookDocument)
        self.assertEqual(imported.document.title, "My chess study")
        self.assertEqual(imported.source.sha256, sha256(source).hexdigest())
        self.assertEqual(imported.importer, "acs.format_factory_pgn_book")
        self.assertEqual(len(imported.document.blocks), 2)
        self.assertTrue(all(type(x) is Game for x in imported.document.blocks))
        self.assertIn("Read the center", imported.document.blocks[0].pgn)
        self.assertIn("1. d4 d5", imported.document.blocks[1].pgn)
        self.assertNotEqual(
            imported.document.blocks[0].block_id,
            imported.document.blocks[1].block_id,
        )
        self.assertEqual(imported.document.blocks[0].source_anchor, "pgn:game:1")
        self.assertEqual(imported.document.blocks[1].source_anchor, "pgn:game:2")
        self.assertEqual(imported.document.as_dict()["blocks"][0]["kind"], "Game")
        self.assertTrue(any("legality" in w for w in imported.warnings))

    def test_reading_preview_is_html_escaped_and_remains_private(self):
        source = FIRST.replace("Opening lesson", "<script>alert(1)</script>").encode()
        book = import_factory_book(source, source_name="my.pgn")
        result = export_factory_preview(
            book.document, source_sha256=sha256(source).hexdigest(),
            output_format="html",
        )
        html = result.output_bytes.decode("utf-8")
        self.assertIn("&lt;script&gt;", html)
        self.assertNotIn("<script>", html)
        self.assertIn("Read the center", html)
        self.assertFalse(result.public_release_approved)

    def test_repeat_ingest_is_deterministic_without_duplicate_identity(self):
        raw = (FIRST + "\n" + SECOND).encode("utf-8")
        first = import_pgn_as_book(raw, source_name="collection.pgn")
        second = import_pgn_as_book(raw, source_name="collection.pgn")
        self.assertEqual(first.as_dict(), second.as_dict())
        self.assertEqual(first.as_dict()["blocks"][0]["kind"], "Game")

    def test_invalid_san_fails_entire_collection(self):
        invalid = (
            FIRST + "\n" +
            '[Event "Bad move"]\n[Result "*"]\n\n1. impossible9 *\n'
        ).encode("utf-8")
        with self.assertRaises(FactoryPgnBookError):
            import_factory_book(invalid, source_name="damaged.pgn")

    def test_plain_prose_with_pgn_extension_is_not_a_game(self):
        data = b"1. This is not a chess game. It is a paragraph."
        inspected = inspect_factory_source(data, source_name="fake.pgn")
        self.assertTrue(inspected.extension_mismatch)
        with self.assertRaises(FactoryIntakeError):
            import_factory_book(data, source_name="fake.pgn")

    def test_binary_and_missing_source_fail_closed(self):
        with self.assertRaises(FactoryPgnBookError):
            import_pgn_as_book(b"", source_name="empty.pgn")
        with self.assertRaises(FactoryIntakeError):
            import_factory_book(b"\x00\x01\x02", source_name="bad.pgn")


if __name__ == "__main__":
    unittest.main()
