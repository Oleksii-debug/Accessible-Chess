from __future__ import annotations

import unittest

from acs.book_text_import import BookTextFormat, import_text_book
from acs.bookdocument import BookDocument, ListBlock, Paragraph


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

    def test_indented_nested_item_is_readable_with_explicit_structure_loss_warning(self) -> None:
        imported = self._import("- Parent\n  - Child 1. e4 e5\n")
        self.assertEqual(len(imported.document.blocks), 2)
        parent, child = imported.document.blocks
        self.assertIsInstance(parent, ListBlock)
        self.assertIsInstance(child, Paragraph)
        assert isinstance(parent, ListBlock) and isinstance(child, Paragraph)
        self.assertEqual(parent.items, ["Parent"])
        self.assertFalse(parent.ordered)
        self.assertEqual(child.text, "- Child 1. e4 e5")
        self.assertTrue(
            any(
                "indentation or nesting" in warning and "readable text" in warning
                for warning in imported.warnings
            )
        )
        self.assertEqual(imported.pgn_games, 0)
        self.assertEqual(imported.positions, 0)

    def test_nonpositive_ordered_start_falls_back_without_false_list_semantics(self) -> None:
        imported = self._import("0. Not a canonical positive start\n")
        self.assertEqual(len(imported.document.blocks), 1)
        block = imported.document.blocks[0]
        self.assertIsInstance(block, Paragraph)
        assert isinstance(block, Paragraph)
        self.assertEqual(block.text, "0. Not a canonical positive start")
        self.assertTrue(any("non-positive start" in warning for warning in imported.warnings))

    def test_semantic_lists_round_trip_through_canonical_bookdocument(self) -> None:
        imported = self._import(
            "5. Fifth\n6. Sixth\n\n- Weak squares\n* Open file\n"
        )
        payload = imported.document.as_dict()
        restored = BookDocument.from_dict(payload)
        self.assertEqual(restored.as_dict(), payload)
        lists = restored.lists()
        self.assertEqual(len(lists), 2)
        self.assertEqual((lists[0].ordered, lists[0].start, lists[0].items), (True, 5, ["Fifth", "Sixth"]))
        self.assertEqual((lists[1].ordered, lists[1].start, lists[1].items), (False, None, ["Weak squares", "Open file"]))


if __name__ == "__main__":
    unittest.main()
