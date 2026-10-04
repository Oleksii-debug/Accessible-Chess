from __future__ import annotations

import unittest

from acs.book_webview_projection import BookWebViewProjection
from acs.bookdocument import BookDocument, Diagram, Paragraph
from acs.bookreader import BookReader
from acs.full_product_presenters import BookReaderPresenter
from acs.full_product_ui_shell import UILanguage


FEN = "8/8/8/8/8/8/4P3/4K2k w - - 0 1"


class BookDocumentWarningAccessibilityTests(unittest.TestCase):
    def _presenter(
        self,
        warnings: list[str],
        *,
        language: UILanguage = UILanguage.EN,
    ) -> tuple[BookDocument, BookReaderPresenter]:
        document = BookDocument(
            title="Warning retention",
            warnings=warnings,
            blocks=[Paragraph(text="Readable body")],
        )
        return document, BookReaderPresenter(BookReader(document), language=language)

    def test_document_warning_is_retained_as_readable_block_warning(self) -> None:
        _document, presenter = self._presenter(
            ["nested list structure was flattened"]
        )

        block = presenter.current()

        self.assertEqual("paragraph", block.role)
        self.assertIn("Import warnings:", block.warning)
        self.assertIn("nested list structure was flattened", block.warning)

    def test_document_warning_prefix_tracks_presentation_language(self) -> None:
        _document, presenter = self._presenter(["semantic fallback used"])
        self.assertIn("Import warnings:", presenter.current().warning)

        presenter.set_language(UILanguage.UA)

        self.assertIn("Попередження імпорту:", presenter.current().warning)
        self.assertIn("semantic fallback used", presenter.current().warning)

    def test_warning_snapshot_is_stable_for_open_reader_session(self) -> None:
        document, presenter = self._presenter(["original retained warning"])

        document.warnings[:] = ["later authoring mutation"]

        warning = presenter.current().warning
        self.assertIn("original retained warning", warning)
        self.assertNotIn("later authoring mutation", warning)

    def test_presenter_uses_reader_indexed_warning_snapshot(self) -> None:
        document = BookDocument(
            title="Warning snapshot boundary",
            warnings=["warning captured by reader"],
            blocks=[Paragraph(text="Readable body")],
        )
        reader = BookReader(document)
        document.warnings[:] = ["later authoring warning"]

        presenter = BookReaderPresenter(reader, language=UILanguage.EN)

        warning = presenter.current().warning
        self.assertIn("warning captured by reader", warning)
        self.assertNotIn("later authoring warning", warning)

    def test_reader_warning_snapshot_limit_is_bounded_and_counted(self) -> None:
        document = BookDocument(
            title="Warning snapshot limit",
            warnings=[f"warning-{index}" for index in range(1, 6)],
            blocks=[Paragraph(text="Readable body")],
        )
        reader = BookReader(document)

        self.assertEqual(5, reader.document_warning_count())
        self.assertEqual(
            ("warning-1", "warning-2"),
            reader.document_warnings_snapshot(limit=2),
        )
        with self.assertRaises(TypeError):
            reader.document_warnings_snapshot(limit=True)
        with self.assertRaises(ValueError):
            reader.document_warnings_snapshot(limit=-1)

    def test_warning_summary_is_bounded_and_reports_hidden_items(self) -> None:
        warnings = [f"warning-{index}" for index in range(1, 6)]
        warnings[0] = "x" * 400
        _document, presenter = self._presenter(warnings)

        warning = presenter.current().warning

        self.assertIn("x" * 180, warning)
        self.assertNotIn("x" * 181, warning)
        self.assertIn("warning-4", warning)
        self.assertNotIn("warning-5", warning)
        self.assertIn("1 more warnings", warning)
        self.assertLessEqual(len(warning), 1000)

    def test_bounded_warning_with_long_leading_whitespace_remains_visible(self) -> None:
        _document, presenter = self._presenter(
            [(" " * 181) + "meaningful warning after the presentation bound"]
        )

        warning = presenter.current().warning

        self.assertIn("Import warnings:", warning)
        self.assertIn(
            "warning text omitted after excessive leading whitespace",
            warning,
        )
        self.assertNotEqual("", warning)

    def test_projection_redacts_private_paths_from_document_warning(self) -> None:
        document = BookDocument(
            title="Private path warning",
            warnings=[r"failed source C:\Users\Example\private\chapter.xhtml"],
            blocks=[Paragraph(text="Readable body")],
        )
        projection = BookWebViewProjection(
            BookReaderPresenter(BookReader(document), language=UILanguage.EN),
            lambda _action_id, _payload: None,
            language=UILanguage.EN,
        )

        snapshot = projection.snapshot()
        warning = snapshot["block"]["warning"]

        self.assertIn("Import warnings:", warning)
        self.assertIn("[local path hidden]", warning)
        self.assertNotIn("Example", warning)
        self.assertNotIn("chapter.xhtml", warning)

    def test_document_warning_preserves_existing_block_accessibility_warning(self) -> None:
        document = BookDocument(
            title="Diagram warning",
            warnings=["source omitted non-semantic decoration"],
            blocks=[
                Diagram(
                    fen=FEN,
                    caption="Critical position",
                    alt_text=None,
                )
            ],
        )
        presenter = BookReaderPresenter(BookReader(document), language=UILanguage.EN)

        warning = presenter.current().warning

        self.assertIn("No separate diagram description", warning)
        self.assertIn("Import warnings:", warning)
        self.assertIn("source omitted non-semantic decoration", warning)

    def test_document_without_warnings_preserves_existing_empty_warning(self) -> None:
        _document, presenter = self._presenter([])
        self.assertEqual("", presenter.current().warning)


if __name__ == "__main__":
    unittest.main()
