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


if __name__ == "__main__":
    unittest.main()
