from __future__ import annotations

import unittest

from acs.book_html_import import import_html_book
from acs.bookdocument import ListBlock


class Version2HtmlSemanticListTests(unittest.TestCase):
    def _import(self, body: str):
        return import_html_book(
            f"<html><body>{body}</body></html>",
            source_name="lesson.html",
            title="Lesson",
        )

    def test_ordered_html_list_preserves_group_and_start(self) -> None:
        imported = self._import(
            '<ol start="3"><li>Control the center</li><li>Develop the pieces</li></ol>'
        )
        self.assertEqual(len(imported.document.blocks), 1)
        block = imported.document.blocks[0]
        self.assertIsInstance(block, ListBlock)
        assert isinstance(block, ListBlock)
        self.assertEqual(block.items, ["Control the center", "Develop the pieces"])
        self.assertTrue(block.ordered)
        self.assertEqual(block.start, 3)
        self.assertFalse(any("no list block kind" in value for value in imported.warnings))

    def test_unordered_html_list_preserves_grouped_items(self) -> None:
        imported = self._import("<ul><li>Weak dark squares</li><li>Open file</li></ul>")
        self.assertEqual(len(imported.document.blocks), 1)
        block = imported.document.blocks[0]
        self.assertIsInstance(block, ListBlock)
        assert isinstance(block, ListBlock)
        self.assertEqual(block.items, ["Weak dark squares", "Open file"])
        self.assertFalse(block.ordered)
        self.assertIsNone(block.start)

    def test_inline_markup_inside_item_does_not_split_semantic_item(self) -> None:
        imported = self._import("<ul><li>Control <strong>dark squares</strong></li><li>Open file</li></ul>")
        block = imported.document.blocks[0]
        self.assertIsInstance(block, ListBlock)
        assert isinstance(block, ListBlock)
        self.assertEqual(block.items, ["Control dark squares", "Open file"])

    def test_nonpositive_ordered_start_falls_back_to_readable_text_instead_of_wrong_numbering(self) -> None:
        imported = self._import('<ol start="0"><li>Zero</li><li>One</li></ol>')
        self.assertFalse(any(isinstance(block, ListBlock) for block in imported.document.blocks))
        self.assertTrue(imported.document.blocks)
        self.assertTrue(any("canonical List start must be positive" in value for value in imported.warnings))


if __name__ == "__main__":
    unittest.main()
