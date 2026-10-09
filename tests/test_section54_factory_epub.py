from __future__ import annotations

from io import BytesIO
from zipfile import ZIP_STORED, ZipFile
from xml.etree import ElementTree as ET
from hashlib import sha256
import unittest

from acs.bookdocument import BookDocument, Heading, Paragraph, Diagram
from acs.format_factory_epub import export_factory_epub3_preview
from acs.format_factory_export import FactoryExportError


SHA = "e" * 64
UTC = "2026-10-09T22:00:00Z"
FEN = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"


class FactoryEpubPreviewTests(unittest.TestCase):
    def test_reproducible_epub3_archive_and_valid_xhtml_nav(self) -> None:
        book = BookDocument(title="Chess: <Strategies>", language="en",
                            blocks=[Heading(text="Opening & middle", level=2),
                                    Paragraph(text="A safe <script>string</script>.")])
        a = export_factory_epub3_preview(book, source_sha256=SHA, modified_utc=UTC)
        b = export_factory_epub3_preview(book, source_sha256=SHA, modified_utc=UTC)
        self.assertEqual(a.output_bytes, b.output_bytes)
        self.assertEqual(a.output_sha256, sha256(a.output_bytes).hexdigest())
        self.assertFalse(a.public_release_approved)
        self.assertEqual(a.losses, ())
        with ZipFile(BytesIO(a.output_bytes)) as zf:
            names = zf.namelist()
            self.assertEqual(names[0], "mimetype")
            self.assertEqual(zf.getinfo("mimetype").compress_type, ZIP_STORED)
            self.assertEqual(zf.read("mimetype"), b"application/epub+zip")
            self.assertEqual(set(names), {
                "mimetype", "META-INF/container.xml", "OEBPS/package.opf",
                "OEBPS/nav.xhtml", "OEBPS/book.xhtml",
            })
            for name in names[1:]:
                ET.fromstring(zf.read(name))
            page = zf.read("OEBPS/book.xhtml").decode()
            nav = zf.read("OEBPS/nav.xhtml").decode()
            self.assertIn("Opening &amp; middle", page)
            self.assertIn("book.xhtml#section-1", nav)
            self.assertIn("&lt;script&gt;", page)
            self.assertNotIn("<script>", page)
            self.assertIn("urn:sha256:", zf.read("OEBPS/package.opf").decode())

    def test_epub_preview_reimports_with_accepted_canonical_spine(self) -> None:
        from acs.book_epub_import import import_epub_book
        book = BookDocument(title="My study", language="en",
                            blocks=[Heading(text="Chapter One", level=1),
                                    Paragraph(text="First canonical paragraph.")])
        result = export_factory_epub3_preview(book, source_sha256=SHA, modified_utc=UTC)
        imported = import_epub_book(result.output_bytes, source_name="private-preview.epub")
        self.assertTrue(imported.document.blocks)
        self.assertTrue(any("First canonical paragraph." in getattr(x, "text", "")
                            for x in imported.document.blocks))

    def test_missing_chapters_get_accessible_fallback_navigation(self) -> None:
        book = BookDocument(title="Simple", language="uk", blocks=[Paragraph(text="Ласкаво просимо.")])
        a = export_factory_epub3_preview(book, source_sha256=SHA, modified_utc=UTC)
        with ZipFile(BytesIO(a.output_bytes)) as zf:
            self.assertIn("book.xhtml#start", zf.read("OEBPS/nav.xhtml").decode())

    def test_diagram_requires_explicit_graphic_loss_approval(self) -> None:
        book = BookDocument(title="Diagram", language="en", blocks=[Diagram(fen=FEN, alt_text="Starting board")])
        with self.assertRaises(FactoryExportError):
            export_factory_epub3_preview(book, source_sha256=SHA, modified_utc=UTC)
        output = export_factory_epub3_preview(book, source_sha256=SHA, modified_utc=UTC, allow_semantic_loss=True)
        self.assertIn("ORIGINAL_DIAGRAM_GRAPHICS_NOT_REPRODUCED", output.losses)
        with ZipFile(BytesIO(output.output_bytes)) as zf:
            self.assertIn(FEN, zf.read("OEBPS/book.xhtml").decode())

    def test_falsified_or_missing_modified_date_rejected(self) -> None:
        book = BookDocument(title="Book", language="en", blocks=[])
        for stamp in ("", "not-a-date", "1979-10-09T22:00:00Z",
                      "2026-02-30T22:00:00Z", "2026-10-09T22:00:00+00:00"):
            with self.subTest(stamp=stamp), self.assertRaises(FactoryExportError):
                export_factory_epub3_preview(book, source_sha256=SHA, modified_utc=stamp)

    def test_unknown_source_language_cannot_claim_epub_accessibility(self) -> None:
        book = BookDocument(title="Book", blocks=[Paragraph(text="Hello.")])
        with self.assertRaises(FactoryExportError):
            export_factory_epub3_preview(book, source_sha256=SHA, modified_utc=UTC)


if __name__ == "__main__":
    unittest.main()
