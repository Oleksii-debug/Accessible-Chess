from __future__ import annotations

import unittest

from acs.book_webview_projection import BookWebViewProjection
from acs.bookdocument import BookDocument, Paragraph
from acs.bookreader import BookReader
from acs.full_product_presenters import BookReaderPresenter
from acs.full_product_ui_shell import UILanguage


class BookPresenterPassiveIngressTests(unittest.TestCase):
    @staticmethod
    def _reader() -> BookReader:
        return BookReader(
            BookDocument(
                "Passive presenter",
                blocks=[
                    Paragraph(
                        text="Readable paragraph",
                        block_id="paragraph",
                        source_anchor="chapter:1:p1",
                    )
                ],
            )
        )

    def test_presenter_rejects_reader_subclass_before_warning_hook(self) -> None:
        class HostileBookReader(BookReader):
            touched = False

            def document_warning_count(self) -> int:
                type(self).touched = True
                raise AssertionError("BookReader subclass hook must not execute")

        hostile = HostileBookReader.__new__(HostileBookReader)

        with self.assertRaisesRegex(
            TypeError,
            "^book presenter reader must be BookReader$",
        ):
            BookReaderPresenter(hostile)

        self.assertFalse(HostileBookReader.touched)

    def test_projection_rejects_presenter_subclass_before_language_hook(self) -> None:
        class HostilePresenter(BookReaderPresenter):
            touched = False

            def set_language(self, language: UILanguage) -> None:
                type(self).touched = True
                raise AssertionError("BookReaderPresenter subclass hook must not execute")

        hostile = HostilePresenter.__new__(HostilePresenter)

        with self.assertRaisesRegex(
            TypeError,
            "^presenter must be BookReaderPresenter$",
        ):
            BookWebViewProjection(
                hostile,
                lambda command, payload: None,
                language=UILanguage.EN,
            )

        self.assertFalse(HostilePresenter.touched)

    def test_exact_reader_presenter_projection_chain_still_renders(self) -> None:
        presenter = BookReaderPresenter(
            self._reader(),
            language=UILanguage.EN,
        )
        projection = BookWebViewProjection(
            presenter,
            lambda command, payload: None,
            language=UILanguage.EN,
        )

        snapshot = projection.snapshot()

        self.assertEqual(snapshot["document"]["lang"], "en")
        self.assertEqual(snapshot["block"]["kind"], "Paragraph")
        self.assertEqual(snapshot["block"]["text"], "Readable paragraph")
        self.assertEqual(snapshot["block"]["source_anchor"], "chapter:1:p1")


if __name__ == "__main__":
    unittest.main()
