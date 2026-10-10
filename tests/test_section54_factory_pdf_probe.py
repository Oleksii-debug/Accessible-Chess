"""Section 54.1 text-PDF probe: byte identity, page anchors, and failure gates."""

from io import BytesIO
import unittest

from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

from acs.format_factory_pdf_probe import (
    FactoryPdfProbeError, probe_factory_text_pdf,
    MAX_PDF_SOURCE_BYTES,
)


def _pdf(pages: int = 2, *, encrypted: bool = False) -> bytes:
    writer = PdfWriter()
    for _ in range(pages):
        writer.add_blank_page(width=612, height=792)
    if encrypted:
        writer.encrypt("restricted")
    stream = BytesIO()
    writer.write(stream)
    return stream.getvalue()


def _text_pdf() -> bytes:
    writer = PdfWriter()
    page = writer.add_blank_page(width=612, height=792)
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
    contents = DecodedStreamObject()
    contents.set_data(b"BT /F1 14 Tf 72 700 Td (Verified text page) Tj ET")
    page[NameObject("/Contents")] = writer._add_object(contents)
    stream = BytesIO()
    writer.write(stream)
    return stream.getvalue()


class PdfProbeTests(unittest.TestCase):
    def test_real_pdf_text_is_extracted_but_never_proven(self):
        source = _text_pdf()
        receipt = probe_factory_text_pdf(source, source_name="text.pdf")
        self.assertEqual(receipt.page_count, 1)
        self.assertIn("Verified text page", receipt.pages[0].text)
        self.assertEqual(receipt.pages[0].review_status, "REVIEW_REQUIRED")
        self.assertFalse(receipt.public_release_approved)
        self.assertIn("DIAGRAMS_AND_CHESS_NOTATION_NOT_VERIFIED", receipt.warnings)

    def test_blank_pages_explicit_review_not_silently_missing(self):
        src = _pdf(2)
        r = probe_factory_text_pdf(src, source_name="Книга.pdf")
        self.assertEqual(r.page_count, 2)
        self.assertEqual([p.anchor for p in r.pages],
                         ["pdf:file-page:1", "pdf:file-page:2"])
        self.assertTrue(all(p.review_status == "REVIEW_REQUIRED" for p in r.pages))
        self.assertEqual(r.review_status, "REVIEW_REQUIRED")
        self.assertFalse(r.public_release_approved)
        self.assertIn("FILE_PAGE_2_NO_EXTRACTABLE_TEXT", r.warnings)
        self.assertEqual(len(r.original_source_sha256), 64)
        self.assertEqual(r.original_byte_count, len(src))

    def test_pdf_extension_spoof_is_denied(self):
        with self.assertRaisesRegex(FactoryPdfProbeError, "matching PDF"):
            probe_factory_text_pdf(b"This is not a PDF", source_name="book.pdf")

    def test_mismatched_extension_denied(self):
        with self.assertRaisesRegex(FactoryPdfProbeError, "matching PDF"):
            probe_factory_text_pdf(_pdf(), source_name="book.txt")

    def test_encrypted_pdf_denied_no_bypass(self):
        with self.assertRaisesRegex(FactoryPdfProbeError, "Encrypted PDF"):
            probe_factory_text_pdf(_pdf(encrypted=True), source_name="book.pdf")

    def test_page_limit_denied(self):
        with self.assertRaisesRegex(FactoryPdfProbeError, "page count"):
            probe_factory_text_pdf(_pdf(129), source_name="book.pdf")

    def test_input_size_denied(self):
        with self.assertRaisesRegex(FactoryPdfProbeError, "size"):
            probe_factory_text_pdf(b"%PDF-1.7" + b"x" * MAX_PDF_SOURCE_BYTES,
                                   source_name="book.pdf")

    def test_invalid_limit_denied(self):
        with self.assertRaisesRegex(FactoryPdfProbeError, "time limit"):
            probe_factory_text_pdf(_pdf(), source_name="book.pdf", timeout_seconds=0)

    def test_bad_pdf_denied_without_private_bytes(self):
        private = b"%PDF-1.5 SECRET-PRIVATE-PAGE"
        with self.assertRaises(FactoryPdfProbeError) as outcome:
            probe_factory_text_pdf(private, source_name="book.pdf")
        self.assertNotIn("SECRET-PRIVATE-PAGE", str(outcome.exception))


if __name__ == "__main__":
    unittest.main()
