"""PDF text projection must reuse the canonical BookDocument and not infer chess."""

from io import BytesIO
import unittest

from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

from acs.format_factory_pdf_probe import FactoryPdfProbeError
from acs.format_factory_pdf_projection import (
    FactoryPdfTextProjection, project_factory_text_pdf_private,
)


def _pdf_pages(*texts: str | None) -> bytes:
    writer = PdfWriter()
    for text in texts:
        page = writer.add_blank_page(width=612, height=792)
        if text is None:
            continue
        font = DictionaryObject({
            NameObject("/Type"): NameObject("/Font"),
            NameObject("/Subtype"): NameObject("/Type1"),
            NameObject("/BaseFont"): NameObject("/Helvetica"),
        })
        page[NameObject("/Resources")] = DictionaryObject({
            NameObject("/Font"): DictionaryObject({
                NameObject("/F1"): writer._add_object(font),
            }),
        })
        stream = DecodedStreamObject()
        stream.set_data(
            b"BT /F1 14 Tf 72 700 Td (" + text.encode("ascii") + b") Tj ET"
        )
        page[NameObject("/Contents")] = writer._add_object(stream)
    buffer = BytesIO()
    writer.write(buffer)
    return buffer.getvalue()


class PdfTextProjectionTests(unittest.TestCase):
    def test_real_two_page_text_uses_existing_bookdocument(self):
        source = _pdf_pages("First chapter text.", "Next chapter text.")
        result = project_factory_text_pdf_private(
            source, source_name="book.pdf", title="Owner supplied title",
        )
        self.assertEqual(result.probe.page_count, 2)
        self.assertEqual(result.page_start_lines, (1, 3))
        self.assertTrue(result.document.blocks)
        self.assertTrue(all(b.kind == "Paragraph" for b in result.document.blocks))
        self.assertEqual(result.review_status, "REVIEW_REQUIRED")
        self.assertFalse(result.public_release_approved)
        self.assertNotEqual(result.probe.original_source_sha256,
                            result.projected_text_sha256)
        self.assertIn("PDF_TEXT_ONLY_PRIVATE_PREVIEW_REVIEW_REQUIRED",
                      result.document.warnings)

    def test_san_looking_prose_cannot_become_chess_truth(self):
        source = _pdf_pages("1. e4 e5 2. Nf3 Nc6")
        result = project_factory_text_pdf_private(
            source, source_name="game.pdf",
        )
        self.assertTrue(result.document.blocks)
        self.assertFalse(any(b.kind in ("Game", "Position", "Diagram")
                             for b in result.document.blocks))
        self.assertFalse(result.public_release_approved)

    def test_missing_page_blocks_whole_book_projection(self):
        source = _pdf_pages("First page.", None)
        with self.assertRaisesRegex(FactoryPdfProbeError, "requiring OCR"):
            project_factory_text_pdf_private(source, source_name="scanned.pdf")

    def test_corrupt_pdf_fails_closed(self):
        with self.assertRaises(FactoryPdfProbeError):
            project_factory_text_pdf_private(
                b"%PDF-1.7 no actual objects", source_name="bad.pdf",
            )

    def test_caller_cannot_override_release_status(self):
        with self.assertRaises(TypeError):
            FactoryPdfTextProjection(None, None, "0" * 64, (), (),
                                     public_release_approved=True)


if __name__ == "__main__":
    unittest.main()
