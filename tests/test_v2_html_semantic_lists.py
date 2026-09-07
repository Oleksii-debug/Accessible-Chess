from __future__ import annotations

import unittest

from acs.book_html_import import import_html_book
from acs.bookdocument import ListBlock, Paragraph


class Version2HtmlSemanticListTests(unittest.TestCase):
    def _import(self, body: str):
        return import_html_book(
            f"<html><body>{body}</body></html>",
            source_name="lesson.html",
            title="Lesson",
        )

    @staticmethod
    def _paragraph_texts(imported) -> list[str]:
        return [block.text for block in imported.document.blocks if isinstance(block, Paragraph)]

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

    def test_nonpositive_ordered_start_does_not_fabricate_canonical_numbering(self) -> None:
        imported = self._import('<ol start="0"><li>Zero</li><li>One</li></ol>')
        self.assertFalse(any(isinstance(block, ListBlock) for block in imported.document.blocks))
        self.assertEqual(self._paragraph_texts(imported), ["• Zero", "• One"])
        self.assertTrue(any("canonical List start must be positive" in value for value in imported.warnings))

    def test_invalid_ordered_start_preserves_text_without_inventing_numbers(self) -> None:
        imported = self._import('<ol start="not-a-number"><li>First</li><li>Second</li></ol>')
        self.assertFalse(any(isinstance(block, ListBlock) for block in imported.document.blocks))
        self.assertEqual(self._paragraph_texts(imported), ["• First", "• Second"])
        self.assertTrue(any("canonical List start must be positive" in value for value in imported.warnings))

    def test_reversed_ordered_list_falls_back_without_false_ascending_numbers(self) -> None:
        imported = self._import('<ol reversed><li>Third</li><li>Second</li><li>First</li></ol>')
        self.assertFalse(any(isinstance(block, ListBlock) for block in imported.document.blocks))
        self.assertEqual(self._paragraph_texts(imported), ["• Third", "• Second", "• First"])
        self.assertTrue(any("numbering or nesting" in value for value in imported.warnings))

    def test_per_item_value_override_falls_back_without_false_sequence(self) -> None:
        imported = self._import('<ol><li value="5">Five</li><li>Six</li></ol>')
        self.assertFalse(any(isinstance(block, ListBlock) for block in imported.document.blocks))
        self.assertEqual(self._paragraph_texts(imported), ["• Five", "• Six"])
        self.assertTrue(any("numbering or nesting" in value for value in imported.warnings))

    def test_nested_list_never_publishes_false_flat_canonical_list(self) -> None:
        imported = self._import(
            '<ul><li>Parent<ul><li>Child</li></ul></li><li>Peer</li></ul>'
        )
        self.assertFalse(any(isinstance(block, ListBlock) for block in imported.document.blocks))
        paragraph_text = " ".join(self._paragraph_texts(imported))
        self.assertIn("Parent", paragraph_text)
        self.assertIn("Child", paragraph_text)
        self.assertIn("Peer", paragraph_text)
        self.assertTrue(any("Nested HTML list structure" in value for value in imported.warnings))


if __name__ == "__main__":
    unittest.main()
