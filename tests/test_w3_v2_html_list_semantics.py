from __future__ import annotations

import unittest

from acs.book_html_import import import_html_book
from acs.bookdocument import ListBlock


class W3HtmlListSemanticIngestionTests(unittest.TestCase):
    def test_ordered_html_list_becomes_one_canonical_list_block(self) -> None:
        imported = import_html_book(
            '<html><body><ol start="3"><li>Control the center</li><li>Develop the pieces</li></ol></body></html>',
            source_name="lesson.html",
            title="Lesson",
        )

        self.assertEqual(1, len(imported.document.blocks))
        block = imported.document.blocks[0]
        self.assertIsInstance(
            block,
            ListBlock,
            "HTML ordered-list structure was flattened before reaching canonical BookDocument",
        )
        assert isinstance(block, ListBlock)
        self.assertEqual(["Control the center", "Develop the pieces"], block.items)
        self.assertTrue(block.ordered)
        self.assertEqual(3, block.start)
        self.assertFalse(
            any("BookDocument has no list block kind" in warning for warning in imported.warnings),
            "HTML importer still reports the obsolete pre-ListBlock capability boundary",
        )

    def test_unordered_html_list_preserves_grouped_items(self) -> None:
        imported = import_html_book(
            '<html><body><ul><li>Weak dark squares</li><li>Open file</li></ul></body></html>',
            source_name="features.html",
            title="Features",
        )

        self.assertEqual(1, len(imported.document.blocks))
        block = imported.document.blocks[0]
        self.assertIsInstance(block, ListBlock)
        assert isinstance(block, ListBlock)
        self.assertEqual(["Weak dark squares", "Open file"], block.items)
        self.assertFalse(block.ordered)
        self.assertIsNone(block.start)


if __name__ == "__main__":
    unittest.main()
