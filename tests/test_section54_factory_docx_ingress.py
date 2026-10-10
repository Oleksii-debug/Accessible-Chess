from __future__ import annotations

from io import BytesIO
import unittest
from zipfile import ZipFile, ZIP_DEFLATED

from acs.format_factory_intake import FactoryIntakeError, import_factory_book, inspect_factory_source

W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
CT = "http://schemas.openxmlformats.org/package/2006/content-types"
MAIN = "application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"

def word_docx(body: str, *, mime: str = MAIN, extra: dict[str, bytes] | None = None) -> bytes:
    content_types = (
        f'<Types xmlns="{CT}"><Override PartName="/word/document.xml" '
        f'ContentType="{mime}"/></Types>'
    ).encode()
    doc = f'<w:document xmlns:w="{W}"><w:body>{body}</w:body></w:document>'.encode()
    stream = BytesIO()
    with ZipFile(stream, "w", compression=ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", content_types)
        archive.writestr("word/document.xml", doc)
        for name, raw in (extra or {}).items():
            archive.writestr(name, raw)
    return stream.getvalue()


class Section54DocxIngressTests(unittest.TestCase):
    def test_plain_docx_uses_canonical_book_html_bridge(self) -> None:
        body = (
            '<w:p><w:pPr><w:pStyle w:val="Heading1"/></w:pPr>'
            '<w:r><w:t>Opening theory</w:t></w:r></w:p>'
            '<w:p><w:r><w:t>1. e4 is prose, not a guessed game.</w:t></w:r></w:p>'
        )
        data = word_docx(body)
        receipt = inspect_factory_source(data, source_name="lesson.docx")
        self.assertEqual(receipt.detected_format, "docx")
        self.assertEqual(receipt.import_status, "PARTIAL")
        imported = import_factory_book(data, source_name="lesson.docx")
        self.assertEqual(imported.source.sha256, receipt.sha256)
        self.assertEqual(imported.importer, "acs.format_factory_docx_import")
        self.assertEqual([block.kind for block in imported.document.blocks], ["Heading", "Paragraph"])
        self.assertFalse(any(block.kind == "Game" for block in imported.document.blocks))
        self.assertTrue(any("not independently proven" in warning for warning in imported.warnings))

    def test_docx_with_structural_or_external_parts_refused(self) -> None:
        simple = '<w:p><w:r><w:t>Readable prose.</w:t></w:r></w:p>'
        hostile = [
            (simple + "<w:tbl/>", {}),
            ('<w:p><w:r><w:drawing/></w:r></w:p>', {}),
            ('<w:p><w:pPr><w:numPr/></w:pPr><w:r><w:t>List</w:t></w:r></w:p>', {}),
            (simple, {"word/media/diagram.png": b"PNG"}),
            (simple, {"word/_rels/document.xml.rels": (
                b'<Relationships><Relationship TargetMode="External" '
                b'Target="https://example.invalid/private"/></Relationships>'
            )}),
        ]
        for body, extra in hostile:
            with self.subTest(body=body[:35], extras=tuple(extra)):
                data = word_docx(body, extra=extra)
                with self.assertRaises(FactoryIntakeError):
                    import_factory_book(data, source_name="lesson.docx")

    def test_wrong_content_type_and_malformed_xml_refused(self) -> None:
        p = '<w:p><w:r><w:t>Text.</w:t></w:r></w:p>'
        cases = [
            word_docx(p, mime="application/x-unknown"),
            word_docx("<w:p><w:r><w:t>unclosed"),
            word_docx('<w:p><w:r><w:rPr><w:b/></w:rPr><w:t>Bold</w:t></w:r></w:p>'),
            word_docx(p, extra={"word/footnotes.xml": b"<notes/>"}),
        ]
        for data in cases:
            with self.subTest(length=len(data)):
                with self.assertRaises(FactoryIntakeError):
                    import_factory_book(data, source_name="lesson.docx")


if __name__ == "__main__":
    unittest.main()
