from __future__ import annotations

import unittest

from acs.book_text_import import BookTextFormat, import_text_book
from acs.bookdocument import ListBlock


class W3MarkdownListSemanticIngestionTests(unittest.TestCase):
    def test_ordered_markdown_list_preserves_group_and_start(self) -> None:
        imported = import_text_book(
            "3. Control the center\n4. Develop the pieces\n",
            source_name="lesson.md",
            source_format=BookTextFormat.MARKDOWN,
            title="Lesson",
        )

        self.assertEqual(1, len(imported.document.blocks))
        block = imported.document.blocks[0]
        self.assertIsInstance(
            block,
            ListBlock,
            "Markdown ordered-list structure was flattened before canonical BookDocument",
        )
        assert isinstance(block, ListBlock)
        self.assertEqual(["Control the center", "Develop the pieces"], block.items)
        self.assertTrue(block.ordered)
        self.assertEqual(3, block.start)
        self.assertFalse(
            any("BookDocument has no list block kind" in warning for warning in imported.warnings),
            "Markdown importer still reports the obsolete pre-ListBlock capability boundary",
        )

    def test_unordered_markdown_list_preserves_grouped_items(self) -> None:
        imported = import_text_book(
            "- Weak dark squares\n- Open file\n",
            source_name="features.md",
            source_format=BookTextFormat.MARKDOWN,
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
