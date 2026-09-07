from __future__ import annotations

import unittest

from acs.book_text_import import BookTextFormat, import_text_book
from acs.bookdocument import ListBlock


class Version2MarkdownSemanticListTests(unittest.TestCase):
    def _import(self, text: str):
        return import_text_book(
            text,
            source_name="lesson.md",
            source_format=BookTextFormat.MARKDOWN,
            title="Lesson",
        )

    def test_ordered_list_groups_items_and_preserves_start(self) -> None:
        imported = self._import("3. Control the center\n4. Develop the pieces\n")
        self.assertEqual(len(imported.document.blocks), 1)
        block = imported.document.blocks[0]
        self.assertIsInstance(block, ListBlock)
        assert isinstance(block, ListBlock)
        self.assertEqual(block.items, ["Control the center", "Develop the pieces"])
        self.assertTrue(block.ordered)
        self.assertEqual(block.start, 3)
        self.assertFalse(any("no list block kind" in value for value in imported.warnings))

    def test_unordered_list_groups_adjacent_items(self) -> None:
        imported = self._import("- Weak dark squares\n- Open file\n")
        self.assertEqual(len(imported.document.blocks), 1)
        block = imported.document.blocks[0]
        self.assertIsInstance(block, ListBlock)
        assert isinstance(block, ListBlock)
        self.assertEqual(block.items, ["Weak dark squares", "Open file"])
        self.assertFalse(block.ordered)
        self.assertIsNone(block.start)

    def test_numbering_gap_starts_a_new_semantic_list_instead_of_losing_authored_number(self) -> None:
        imported = self._import("3. First\n4. Second\n7. Seventh\n8. Eighth\n")
        self.assertEqual(len(imported.document.blocks), 2)
        first, second = imported.document.blocks
        self.assertIsInstance(first, ListBlock)
        self.assertIsInstance(second, ListBlock)
        assert isinstance(first, ListBlock) and isinstance(second, ListBlock)
        self.assertEqual((first.start, first.items), (3, ["First", "Second"]))
        self.assertEqual((second.start, second.items), (7, ["Seventh", "Eighth"]))

    def test_ordered_and_unordered_lists_do_not_merge(self) -> None:
        imported = self._import("1. Ordered\n- Unordered\n")
        self.assertEqual(len(imported.document.blocks), 2)
        first, second = imported.document.blocks
        self.assertIsInstance(first, ListBlock)
        self.assertIsInstance(second, ListBlock)
        assert isinstance(first, ListBlock) and isinstance(second, ListBlock)
        self.assertTrue(first.ordered)
        self.assertFalse(second.ordered)


if __name__ == "__main__":
    unittest.main()
