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

    def test_exact_reader_instance_method_shadows_cannot_replace_presenter_authority(self) -> None:
        reader = self._reader()
        touched: list[str] = []

        def hostile(*_args, **_kwargs):
            touched.append("hostile")
            raise AssertionError("instance-level BookReader hook must not execute")

        reader.document_warning_count = hostile  # type: ignore[method-assign]
        reader.document_warnings_snapshot = hostile  # type: ignore[method-assign]
        presenter = BookReaderPresenter(reader, language=UILanguage.EN)

        reader.location = hostile  # type: ignore[method-assign]
        reader.block_snapshot = hostile  # type: ignore[method-assign]
        reader.navigation_availability = hostile  # type: ignore[method-assign]

        view = BookReaderPresenter.current(presenter)
        navigation = BookReaderPresenter.navigation_availability(presenter)

        self.assertEqual(view.kind, "Paragraph")
        self.assertEqual(view.text, "Readable paragraph")
        self.assertIs(navigation["previous"], False)
        self.assertIs(navigation["next"], False)
        self.assertEqual(touched, [])

    def test_exact_presenter_instance_method_shadows_cannot_replace_webview_authority(self) -> None:
        reader = BookReader(
            BookDocument(
                "Passive projection",
                blocks=[
                    Paragraph(text="First", block_id="p1"),
                    Paragraph(text="Second", block_id="p2"),
                ],
            )
        )
        presenter = BookReaderPresenter(reader, language=UILanguage.EN)
        touched: list[str] = []

        def hostile(*_args, **_kwargs):
            touched.append("hostile")
            raise AssertionError("instance-level BookReaderPresenter hook must not execute")

        presenter.set_language = hostile  # type: ignore[method-assign]
        presenter.current = hostile  # type: ignore[method-assign]
        presenter.navigation_availability = hostile  # type: ignore[method-assign]
        presenter.next_block = hostile  # type: ignore[method-assign]
        presenter.bookmark = hostile  # type: ignore[method-assign]

        projection = BookWebViewProjection(
            presenter,
            lambda command, payload: None,
            language=UILanguage.EN,
        )
        initial = projection.snapshot()
        moved = projection.next()
        saved = projection.save_bookmark("after-next")

        self.assertEqual(initial["block"]["text"], "First")
        self.assertEqual(moved.payload["snapshot"]["block"]["text"], "Second")
        self.assertEqual(saved.payload["snapshot"]["block"]["text"], "Second")
        self.assertEqual(projection.bookmark_name, "after-next")
        self.assertEqual(touched, [])

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
