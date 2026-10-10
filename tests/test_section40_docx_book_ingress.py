"""Section 40 authentic DOCX -> canonical BookDocument bounded import regression."""
from __future__ import annotations

from io import BytesIO
from pathlib import Path
import tempfile
import unittest
from zipfile import ZipFile

from acs.book_docx_import import import_docx_book
from acs.bookdocument import Game, Heading, Paragraph, Position
from acs.version2_application import Version2Application


_WORD_XML = (
    '<?xml version="1.0" encoding="UTF-8"?>'
    '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
    '<w:body>'
    '<w:p><w:pPr><w:pStyle w:val="Heading1"/></w:pPr>'
    '<w:r><w:t>Advanced Chess Laboratory</w:t></w:r></w:p>'
    '<w:p><w:pPr><w:pStyle w:val="Heading2"/></w:pPr>'
    '<w:r><w:t>S37-01 lesson</w:t></w:r></w:p>'
    '<w:p><w:r><w:t>Find the strongest move.</w:t></w:r></w:p>'
    '<w:p><w:r><w:t>FEN: 8/8/8/8/8/8/8/K6k w - - 0 1</w:t></w:r></w:p>'
    '</w:body></w:document>'
).encode("utf-8")


def _archive(*, document: bytes = _WORD_XML, name: str = "word/document.xml",
             extra: dict[str, bytes] | None = None) -> bytes:
    buf = BytesIO()
    with ZipFile(buf, "w") as z:
        z.writestr("[Content_Types].xml", b"<Types/>")
        z.writestr(name, document)
        for key, value in (extra or {}).items():
            z.writestr(key, value)
    return buf.getvalue()


class Section40DocxBookIngressTests(unittest.TestCase):
    def test_real_word_xml_heading_and_text_go_through_canonical_book(self):
        raw = _archive()
        imported = import_docx_book(raw, source_name="advanced.docx")
        self.assertTrue(imported.book_key.startswith("docx-sha256:"))
        self.assertEqual(len([b for b in imported.document.blocks if isinstance(b, Heading)]), 2)
        self.assertTrue(any("strongest move" in b.text for b in imported.document.blocks if isinstance(b, Paragraph)))
        # A prose FEN label is NEVER silently converted into a new chess position.
        self.assertFalse(any(isinstance(b, Position) for b in imported.document.blocks))
        self.assertEqual([], imported.document.validate_structure())
        with tempfile.TemporaryDirectory(prefix="s40-docx-book-") as temp:
            path = Path(temp) / "advanced.docx"
            path.write_bytes(raw)
            first = Version2Application.prepare_book_open(path)
            second = Version2Application.prepare_book_open(path)
            self.assertEqual(first.book_key, imported.book_key)
            self.assertEqual(first.document.as_dict(), second.document.as_dict())

    def test_plain_word_prose_with_markdown_fences_never_invents_chess_semantics(self):
        """DOCX plaintext must not accidentally become an explicit Markdown FEN/PGN fence."""
        extra = (
            b'<w:p><w:r><w:t>```fen</w:t></w:r></w:p>'
            b'<w:p><w:r><w:t>8/8/8/8/8/8/8/K6k w - - 0 1</w:t></w:r></w:p>'
            b'<w:p><w:r><w:t>```</w:t></w:r></w:p>'
            b'<w:p><w:r><w:t># Plain Word heading-looking prose</w:t></w:r></w:p>'
        )
        raw = _archive(document=_WORD_XML.replace(b'</w:body>', extra + b'</w:body>'))
        imported = import_docx_book(raw, source_name="plain-word.docx")
        self.assertEqual(len([b for b in imported.document.blocks if isinstance(b, Heading)]), 2)
        self.assertEqual(len([b for b in imported.document.blocks if isinstance(b, Position)]), 0)
        self.assertEqual(len([b for b in imported.document.blocks if isinstance(b, Game)]), 0)
        self.assertTrue(any(b.text == "```fen" for b in imported.document.blocks if isinstance(b, Paragraph)))
        self.assertTrue(any(b.text.startswith("# Plain Word") for b in imported.document.blocks if isinstance(b, Paragraph)))
        self.assertEqual(imported.document.validate_structure(), [])

    def test_rejects_traversal_and_unsafe_macro_member(self):
        for extra in ({"../outside.txt": b"ignored"}, {"word/vbaProject.bin": b"macro"}):
            with self.subTest(extra=extra):
                with self.assertRaises(ValueError):
                    import_docx_book(_archive(extra=extra), source_name="unsafe.docx")

    def test_rejects_missing_word_document_and_malformed_xml(self):
        with self.assertRaises(ValueError):
            import_docx_book(_archive(name="word/unrelated.xml"), source_name="empty.docx")
        with self.assertRaises(ValueError):
            import_docx_book(_archive(document=b"<w:bad"), source_name="broken.docx")

    def test_rejects_xml_entity_definitions(self):
        original = _WORD_XML
        injected = b'<!DOCTYPE doc [<!ENTITY external SYSTEM "file:///etc/passwd">]>' + original
        with self.assertRaises(ValueError):
            import_docx_book(_archive(document=injected), source_name="external.docx")

    def test_cancellation_is_a_fail_closed_boundary(self):
        with self.assertRaisesRegex(RuntimeError, "cancelled"):
            import_docx_book(
                _archive(), source_name="cancel.docx",
                control_checkpoint=lambda: (_ for _ in ()).throw(RuntimeError("cancelled")),
            )


if __name__ == "__main__":
    unittest.main()
