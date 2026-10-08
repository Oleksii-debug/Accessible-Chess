"""Revised Section 38: DOCX semantic ingress through canonical Books, not a new chess core."""
from __future__ import annotations

import io
from pathlib import Path
import tempfile
import unittest
from zipfile import ZipFile, ZIP_DEFLATED

from acs.book_docx_import import (
    MAX_DOCX_SOURCE_BYTES, DocxBookImportError, import_docx_book,
)
from acs.bookreader import BookReader
from acs.version2_application import Version2Application
from acs.version2_windows_native_dialog_ownership import _DIALOG_TEXT


WORD = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
DCTERMS = "http://purl.org/dc/elements/1.1/"
WP = "http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing"


def _docx(*, xml: bytes | None = None, extra: dict[str, bytes] | None = None) -> bytes:
    if xml is None:
        xml = f'''<?xml version="1.0" encoding="utf-8"?>
<w:document xmlns:w="{WORD}" xmlns:wp="{WP}">
  <w:body>
    <w:p><w:pPr><w:pStyle w:val="Heading1"/></w:pPr>
      <w:r><w:t>Strategy</w:t></w:r>
    </w:p>
    <w:p><w:r><w:t>Actual chess prose without inferred moves.</w:t></w:r></w:p>
    <w:p><w:r><w:drawing><wp:inline>
      <wp:docPr id="1" name="Chess diagram" descr="A described chess illustration"/>
    </wp:inline></w:drawing></w:r></w:p>
  </w:body>
</w:document>'''.encode("utf-8")
    core = f'''<cp:coreProperties
        xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties"
        xmlns:dc="{DCTERMS}"><dc:title>Accessible Word Chess Book</dc:title>
        <dc:creator>Example Author</dc:creator></cp:coreProperties>'''.encode("utf-8")
    members = {
        "[Content_Types].xml": b"<Types/>",
        "word/document.xml": xml,
        "docProps/core.xml": core,
        **(extra or {}),
    }
    buffer = io.BytesIO()
    with ZipFile(buffer, "w", compression=ZIP_DEFLATED) as archive:
        for name, payload in members.items():
            archive.writestr(name, payload)
    return buffer.getvalue()


class RealDocxIngressContractTests(unittest.TestCase):
    def test_real_docx_structure_to_canonical_books_and_windows_open(self):
        source = _docx()
        first = import_docx_book(source, source_name="chess.docx")
        self.assertEqual(first.document.title, "Accessible Word Chess Book")
        self.assertEqual(first.document.author, "Example Author")
        self.assertEqual(tuple(b.kind for b in first.document.blocks),
                         ("Heading", "Paragraph", "Note"))
        self.assertEqual(first.document.blocks[0].level, 1)
        self.assertEqual(first.document.blocks[0].text, "Strategy")
        self.assertEqual(first.document.blocks[2].text, "A described chess illustration")
        self.assertTrue(any("no chess position" in warning for warning in first.warnings))
        self.assertFalse(any(block.kind in ("Position", "Diagram", "Game", "VariationTree")
                             for block in first.document.blocks))
        with tempfile.TemporaryDirectory() as temp:
            filename = Path(temp) / "chess.docx"
            filename.write_bytes(source)
            prepared = Version2Application.prepare_book_open(filename)
            self.assertEqual(prepared.book_key, first.book_key)
            self.assertEqual(prepared.document.as_dict(), first.document.as_dict())
            original = BookReader(prepared.document)
            location = original.next_block()
            original.save_return_point("bookmark")
            snap = original.snapshot()
            reopened = Version2Application.prepare_book_open(filename)
            restored = BookReader.restore_snapshot(reopened.document, snap)
            self.assertEqual(restored.location(), location)
            self.assertEqual(restored.next_block().kind, "Note")
            self.assertEqual(restored.restore_return_point("bookmark"), location)

    def test_malformed_xml_package_navigation_and_limits_refused(self):
        for source in (
            b"",
            b"not zip",
            b"X" * (MAX_DOCX_SOURCE_BYTES + 1),
            _docx(xml=b'<w:document xmlns:w="' + WORD.encode() + b'">'),
            _docx(xml=b'<!DOCTYPE x [<!ENTITY e "value">]><document/>'),
            _docx(extra={"../escape.txt": b"bad"}),
            _docx(extra={"word/../../outside.txt": b"bad"}),
        ):
            with self.subTest(length=len(source)):
                with self.assertRaises(DocxBookImportError):
                    import_docx_book(source, source_name="bad.docx")

    def test_cancel_and_empty_source_publish_no_book(self):
        source = _docx()
        calls = 0

        def cancel():
            nonlocal calls
            calls += 1
            if calls == 3:
                raise RuntimeError("owner cancellation")

        with self.assertRaisesRegex(RuntimeError, "owner cancellation"):
            import_docx_book(source, source_name="book.docx",
                             control_checkpoint=cancel)
        self.assertEqual(calls, 3)
        empty = f'<w:document xmlns:w="{WORD}"><w:body/></w:document>'.encode()
        with self.assertRaises(DocxBookImportError):
            import_docx_book(_docx(xml=empty), source_name="empty.docx")

    def test_bilingual_native_file_picker_and_unsupported_pdf_are_explicit(self):
        for language in ("uk", "en"):
            picker = _DIALOG_TEXT[language]["book_filter"]
            self.assertIn("*.docx", picker)
            self.assertNotIn("*.pdf", picker)
        with tempfile.TemporaryDirectory() as temp:
            filename = Path(temp) / "not-supported.pdf"
            filename.write_bytes(b"%PDF-1.7\n")
            with self.assertRaisesRegex(ValueError, "unsupported book source"):
                Version2Application.prepare_book_open(filename)


if __name__ == "__main__":
    unittest.main()
