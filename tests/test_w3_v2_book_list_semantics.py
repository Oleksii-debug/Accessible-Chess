from __future__ import annotations

import unittest

from acs.bookdocument import BookDocument, ListBlock
from acs.bookreader import BookReader
from acs.book_webview_projection import BookWebViewProjection
from acs.full_product_presenters import BookReaderPresenter
from acs.full_product_ui_shell import UILanguage


class W3BookListSemanticProjectionTests(unittest.TestCase):
    def _projection(self, block: ListBlock) -> tuple[BookReaderPresenter, BookWebViewProjection]:
        document = BookDocument(
            title="Semantic list evidence",
            language="en",
            blocks=[block],
        )
        presenter = BookReaderPresenter(BookReader(document), language=UILanguage.EN)
        projection = BookWebViewProjection(
            presenter,
            lambda _action_id, _payload: {"ok": True},
            language=UILanguage.EN,
        )
        return presenter, projection

    def test_ordered_list_reaches_accessible_projection_without_content_loss(self) -> None:
        presenter, projection = self._projection(
            ListBlock(
                items=["Control the center", "Develop the pieces"],
                ordered=True,
                start=3,
                block_id="plan",
            )
        )

        view = presenter.current()
        self.assertEqual(
            "list",
            view.role,
            "canonical ListBlock was flattened to a generic group before WebView projection",
        )
        self.assertEqual(
            ("Control the center", "Develop the pieces"),
            tuple(getattr(view, "items", ())),
            "semantic list items disappeared at the BookReaderPresenter boundary",
        )
        self.assertTrue(getattr(view, "ordered", False))
        self.assertEqual(3, getattr(view, "start", None))

        block = projection.snapshot()["block"]
        self.assertEqual("list", block["role"])
        self.assertEqual(
            ("Control the center", "Develop the pieces"),
            tuple(block.get("items", ())),
            "browser snapshot does not carry semantic list items",
        )
        self.assertTrue(block.get("ordered"))
        self.assertEqual(3, block.get("start"))

    def test_unordered_list_keeps_items_and_has_no_order_start(self) -> None:
        presenter, projection = self._projection(
            ListBlock(
                items=["Weak dark squares", "Open file"],
                ordered=False,
                block_id="features",
            )
        )

        view = presenter.current()
        self.assertEqual("list", view.role)
        self.assertEqual(("Weak dark squares", "Open file"), tuple(getattr(view, "items", ())))
        self.assertFalse(getattr(view, "ordered", True))
        self.assertIsNone(getattr(view, "start", None))

        block = projection.snapshot()["block"]
        self.assertEqual("list", block["role"])
        self.assertEqual(("Weak dark squares", "Open file"), tuple(block.get("items", ())))
        self.assertFalse(block.get("ordered"))
        self.assertIsNone(block.get("start"))


if __name__ == "__main__":
    unittest.main()
