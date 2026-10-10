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
        self.assertEqual(
            [block.source_anchor for block in imported.document.blocks],
            ["docx-p-1", "docx-p-2"],
        )
        self.assertFalse(any(block.kind == "Game" for block in imported.document.blocks))
        self.assertTrue(any("not independently proven" in warning for warning in imported.warnings))

    def test_docx_with_structural_or_external_parts_refused(self) -> None:
        simple = '<w:p><w:r><w:t>Readable prose.</w:t></w:r></w:p>'
        hostile = [
            (simple + "<w:tbl/>", {}),
            ('<w:p><w:r><w:drawing/></w:r></w:p>', {}),
            ('<w:p><w:pPr><w:numPr/></w:pPr><w:r><w:t>List</w:t></w:r></w:p>', {}),
            (simple, {"word/media/diagram.png": b"PNG"}),
            (simple, {"word/activeX/control1.bin": b"unsafe embedded control"}),
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

    def test_docx_preview_is_private_and_requires_loss_consent(self) -> None:
        from hashlib import sha256
        from acs.format_factory_conversion import (
            FactoryConversionError, convert_factory_book_private,
        )
        from acs.format_factory_policy import FactoryJobPolicy, FactorySelection
        data = word_docx('<w:p><w:r><w:t>Simple legal prose.</w:t></w:r></w:p>')
        p = FactoryJobPolicy(
            source_sha256=sha256(data).hexdigest(),
            source_id="verified-simple-docx",
            selection=FactorySelection("all"),
            output_formats=("html",),
            output_language="en",
        )
        with self.assertRaises(FactoryConversionError):
            convert_factory_book_private(
                data, source_name="simple.docx", policy=p, source_language="en",
            )
        result = convert_factory_book_private(
            data, source_name="simple.docx", policy=p,
            source_language="en", allow_semantic_loss=True,
        )
        self.assertEqual(result.import_format, "docx")
        self.assertEqual(result.source_sha256, sha256(data).hexdigest())
        self.assertIn(b"Simple legal prose.", result.outputs[0].output_bytes)
        self.assertTrue(any("not independently proven" in w for w in result.source_warnings))
        self.assertFalse(result.public_release_approved)

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


    def test_utf16_docx_dtd_rejected_in_each_xml_part(self) -> None:
        # DOCTYPE encoded as UTF-16 is invisible to raw b"<!DOCTYPE" checks.
        # An internal entity would be expanded by an unguarded ET.fromstring.
        base = word_docx('<w:p><w:r><w:t>Safe text.</w:t></w:r></w:p>')
        with ZipFile(BytesIO(base), "r") as archive:
            clean_parts = {name: archive.read(name) for name in archive.namelist()}
        xml_cases = {
            "[Content_Types].xml": (
                "Types",
                f'<Types xmlns="{CT}"><Override PartName="/word/document.xml" '
                f'ContentType="{MAIN}"/></Types>',
            ),
            "word/document.xml": (
                "w:document",
                f'<w:document xmlns:w="{W}"><w:body><w:p><w:r>'
                '<w:t>&injected;</w:t></w:r></w:p></w:body></w:document>',
            ),
            "word/_rels/document.xml.rels": (
                "Relationships",
                '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"/>',
            ),
            "docProps/core.xml": (
                "cp:coreProperties",
                '<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" '
                'xmlns:dc="http://purl.org/dc/elements/1.1/"><dc:title>&injected;</dc:title></cp:coreProperties>',
            ),
        }
        for encoding in ("utf-16-le", "utf-16-be"):
            for part, (root, body) in xml_cases.items():
                with self.subTest(encoding=encoding, part=part):
                    xml = (
                        '<?xml version="1.0" encoding="UTF-16"?>'
                        f'<!DOCTYPE {root} [<!ENTITY injected "UNTRUSTED_ENTITY_TEXT">]>'
                        + body
                    )
                    raw = (b"\\xff\\xfe" if encoding == "utf-16-le" else b"\\xfe\\xff") + xml.encode(encoding)
                    parts = dict(clean_parts)
                    parts[part] = raw
                    packed = BytesIO()
                    with ZipFile(packed, "w", compression=ZIP_DEFLATED) as archive:
                        for name, payload in parts.items():
                            archive.writestr(name, payload)
                    with self.assertRaises(FactoryIntakeError) as raised:
                        import_factory_book(packed.getvalue(), source_name="unsafe.docx")
                    self.assertNotIn("UNTRUSTED_ENTITY_TEXT", str(raised.exception))

    def test_utf16_docx_without_doctype_remains_readable(self) -> None:
        for encoding, bom in (("utf-16-le", b"\\xff\\xfe"), ("utf-16-be", b"\\xfe\\xff")):
            with self.subTest(encoding=encoding):
                document = (
                    '<?xml version="1.0" encoding="UTF-16"?>'
                    f'<w:document xmlns:w="{W}"><w:body>'
                    '<w:p><w:r><w:t>Safe UTF-16 chess prose.</w:t></w:r></w:p>'
                    '</w:body></w:document>'
                )
                original = word_docx('<w:p><w:r><w:t>Placeholder.</w:t></w:r></w:p>')
                parts = {}
                with ZipFile(BytesIO(original), "r") as archive:
                    parts = {name: archive.read(name) for name in archive.namelist()}
                parts["word/document.xml"] = bom + document.encode(encoding)
                output = BytesIO()
                with ZipFile(output, "w", compression=ZIP_DEFLATED) as archive:
                    for name, raw in parts.items():
                        archive.writestr(name, raw)
                imported = import_factory_book(output.getvalue(), source_name="safe.docx")
                self.assertEqual(imported.document.blocks[0].text, "Safe UTF-16 chess prose.")


if __name__ == "__main__":
    unittest.main()
