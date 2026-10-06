from __future__ import annotations

import unittest
from unittest.mock import patch

from acs.book_webview_bridge import BookWebViewBridge
from acs.book_webview_projection import BookWebViewProjection
from acs.bookdocument import BookDocument, Paragraph
from acs.bookreader import BookReader
from acs.full_product_presenters import BookReaderPresenter
from acs.full_product_ui_shell import UILanguage
from acs.version2_book_workspace import Version2BookWebViewProjection


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

    def test_exact_projection_method_shadows_cannot_replace_bridge_dispatch(self) -> None:
        presenter = BookReaderPresenter(
            BookReader(
                BookDocument(
                    "Passive bridge",
                    blocks=[
                        Paragraph(text="First", block_id="p1"),
                        Paragraph(text="Second", block_id="p2"),
                    ],
                )
            ),
            language=UILanguage.EN,
        )
        projection = BookWebViewProjection(
            presenter,
            lambda command, payload: None,
            language=UILanguage.EN,
        )
        touched: list[str] = []

        def hostile(*_args, **_kwargs):
            touched.append("hostile")
            raise AssertionError("instance-level BookWebViewProjection hook must not execute")

        projection.next = hostile  # type: ignore[method-assign]
        projection.snapshot = hostile  # type: ignore[method-assign]
        projection._snapshot_from_block = hostile  # type: ignore[method-assign]
        projection._render = hostile  # type: ignore[method-assign]
        projection._navigate = hostile  # type: ignore[method-assign]
        projection._result_announcement = hostile  # type: ignore[method-assign]
        projection.generic_error = hostile  # type: ignore[method-assign]

        bridge = BookWebViewBridge(projection)
        moved = bridge.dispatch("book.next")
        failed = bridge.dispatch("book.unsupported")

        self.assertEqual(moved.kind, "render")
        self.assertEqual(moved.payload["snapshot"]["block"]["text"], "Second")
        self.assertEqual(failed.kind, "error")
        self.assertEqual(touched, [])

    def test_bridge_rejects_unowned_projection_subclass_before_hooks(self) -> None:
        class HostileProjection(BookWebViewProjection):
            touched = False

            def next(self):
                type(self).touched = True
                raise AssertionError("unowned projection subclass hook must not execute")

        hostile = HostileProjection.__new__(HostileProjection)

        with self.assertRaisesRegex(
            TypeError,
            "^projection must be a canonical BookWebViewProjection$",
        ):
            BookWebViewBridge(hostile)

        self.assertFalse(HostileProjection.touched)

    def test_version2_projection_class_dispatch_survives_instance_shadow(self) -> None:
        projection = Version2BookWebViewProjection.__new__(
            Version2BookWebViewProjection
        )
        touched: list[str] = []
        class_calls: list[str] = []

        def hostile(*_args, **_kwargs):
            touched.append("hostile")
            raise AssertionError("V2 projection instance shadow must not execute")

        def canonical(_self):
            class_calls.append("next")
            return type("EventHolder", (), {})()

        projection.next = hostile  # type: ignore[method-assign]
        bridge = BookWebViewBridge(projection)

        from acs.book_webview_projection import BookWebViewEvent

        def canonical_event(_self):
            class_calls.append("next")
            return BookWebViewEvent("render", {"source": "v2-class"})

        with patch.object(
            Version2BookWebViewProjection,
            "next",
            new=canonical_event,
        ):
            event = bridge.dispatch("book.next")

        self.assertEqual(event.kind, "render")
        self.assertEqual(event.payload["source"], "v2-class")
        self.assertEqual(class_calls, ["next"])
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
