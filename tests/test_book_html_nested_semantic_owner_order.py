from __future__ import annotations

import unittest

from acs.book_html_import import import_html_book
from acs.bookdocument import Note, Paragraph


def _reading_signature(blocks):
    signature = []
    for block in blocks:
        if isinstance(block, Paragraph):
            signature.append(("Paragraph", block.text))
        elif isinstance(block, Note) and block.note_type == "image":
            signature.append(("ImageNote", block.text))
        else:
            signature.append((block.kind, ""))
    return signature


class BookHtmlNestedSemanticOwnerOrderTests(unittest.TestCase):
    def test_rich_nested_capture_inside_list_item_does_not_duplicate_or_reorder_text(self) -> None:
        result = import_html_book(
            '<html><body><ul id="choices"><li id="rich">Before'
            '<blockquote id="quote">Inner<img src="board.png" alt="Board">Tail</blockquote>'
            'After</li></ul></body></html>',
            source_name="nested-rich-list-item.html",
            available_assets={"board.png"},
        )

        self.assertEqual(
            _reading_signature(result.document.blocks),
            [
                ("Paragraph", "• Before"),
                ("Paragraph", "Inner"),
                ("ImageNote", "Board"),
                ("Paragraph", "Tail"),
                ("Paragraph", "After"),
            ],
        )
        self.assertFalse(any(block.kind == "List" for block in result.document.blocks))
        self.assertEqual(
            sum(
                block.text.count("Inner") + block.text.count("Tail")
                for block in result.document.blocks
                if isinstance(block, Paragraph)
            ),
            2,
        )
        self.assertTrue(
            any(
                "inline semantic content cannot be represented" in warning
                for warning in result.warnings
            )
        )

    def test_rich_nested_capture_inside_table_row_keeps_single_source_order_projection(self) -> None:
        result = import_html_book(
            '<html><body><table><tr id="row"><td>Before</td><td>'
            '<blockquote id="quote">Inner<img src="board.png" alt="Board">Tail</blockquote>'
            '</td><td>After</td></tr></table></body></html>',
            source_name="nested-rich-table-row.html",
            available_assets={"board.png"},
        )

        self.assertEqual(
            _reading_signature(result.document.blocks),
            [
                ("Paragraph", "Before"),
                ("Paragraph", "Inner"),
                ("ImageNote", "Board"),
                ("Paragraph", "Tail"),
                ("Paragraph", "After"),
            ],
        )
        self.assertEqual(
            sum(
                block.text.count("Inner") + block.text.count("Tail")
                for block in result.document.blocks
                if isinstance(block, Paragraph)
            ),
            2,
        )
        self.assertTrue(
            any(
                "table structure is preserved as row text" in warning
                for warning in result.warnings
            )
        )

    def test_plain_nested_capture_remains_an_ordering_boundary_when_later_image_splits_list_item(self) -> None:
        result = import_html_book(
            '<html><body><ul><li id="rich">Lead'
            '<blockquote id="quote">Nested</blockquote>Middle'
            '<img src="board.png" alt="Board">Tail</li></ul></body></html>',
            source_name="nested-plain-before-rich-list-item.html",
            available_assets={"board.png"},
        )

        self.assertEqual(
            _reading_signature(result.document.blocks),
            [
                ("Paragraph", "• Lead"),
                ("Paragraph", "Nested"),
                ("Paragraph", "Middle"),
                ("ImageNote", "Board"),
                ("Paragraph", "Tail"),
            ],
        )
        self.assertEqual(
            sum(
                block.text.count("Nested")
                for block in result.document.blocks
                if isinstance(block, Paragraph)
            ),
            1,
        )

    def test_explicit_pgn_nested_inside_list_item_stays_canonical_and_in_source_order(self) -> None:
        pgn = (
            '[Event "Nested"]\n'
            '[Site "Test"]\n'
            '[Date "2026.10.04"]\n'
            '[Round "1"]\n'
            '[White "White"]\n'
            '[Black "Black"]\n'
            '[Result "*"]\n\n'
            '1. e4 e5 *'
        )
        result = import_html_book(
            '<html><body><ul><li id="rich">Before<pre>{PGN 1}\n'
            + pgn
            + '</pre>After</li></ul></body></html>',
            source_name="nested-pgn-list-item.html",
        )

        self.assertEqual(
            _reading_signature(result.document.blocks),
            [
                ("Paragraph", "• Before"),
                ("Game", ""),
                ("Paragraph", "After"),
            ],
        )
        self.assertEqual(result.pgn_games, 1)
        self.assertFalse(any(block.kind == "List" for block in result.document.blocks))


if __name__ == "__main__":
    unittest.main()
