from __future__ import annotations

from hashlib import sha256
from io import BytesIO
import unittest
from xml.etree import ElementTree as ET
from zipfile import ZipFile

from acs.bookdocument import BookDocument, Heading, Paragraph, ListBlock, Diagram, Game, Exercise
from acs.format_factory_docx import export_factory_docx_preview
from acs.format_factory_export import FactoryExportError

SOURCE = "c" * 64
DATE = "2026-10-10T00:00:00Z"
FEN = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"


class FactoryDocxPreviewTests(unittest.TestCase):
    def test_valid_word_package_semantic_headings_numbering_and_xml_escaping(self) -> None:
        doc = BookDocument(
            title="Study & tactics", language="en",
            blocks=[
                Heading(text="First <chapter>", level=2),
                Paragraph(text="Content & <tag>"),
                ListBlock(items=["First", "Second"], ordered=True),
            ],
        )
        result = export_factory_docx_preview(doc, source_sha256=SOURCE, modified_utc=DATE)
        self.assertEqual(result.output_sha256, sha256(result.output_bytes).hexdigest())
        self.assertEqual(result.losses, ())
        self.assertFalse(result.public_release_approved)
        with ZipFile(BytesIO(result.output_bytes)) as zf:
            parts = set(zf.namelist())
            self.assertEqual(parts, {
                "[Content_Types].xml", "_rels/.rels", "docProps/core.xml",
                "word/document.xml", "word/_rels/document.xml.rels",
                "word/styles.xml", "word/numbering.xml",
            })
            for filename in parts:
                ET.fromstring(zf.read(filename))
            xml = zf.read("word/document.xml").decode()
            self.assertIn('w:val="Heading2"', xml)
            self.assertIn('w:numId w:val="2"', xml)
            self.assertIn("Content &amp; &lt;tag&gt;", xml)
            self.assertNotIn("<tag>", xml)

    def test_same_edition_bytes_repeat_but_selected_contents_change_identity(self) -> None:
        left = BookDocument(title="Study", blocks=[Paragraph(text="A")])
        right = BookDocument(title="Study", blocks=[Paragraph(text="B")])
        a = export_factory_docx_preview(left, source_sha256=SOURCE, modified_utc=DATE)
        b = export_factory_docx_preview(left, source_sha256=SOURCE, modified_utc=DATE)
        c = export_factory_docx_preview(right, source_sha256=SOURCE, modified_utc=DATE)
        self.assertEqual(a.output_bytes, b.output_bytes)
        with ZipFile(BytesIO(a.output_bytes)) as aa, ZipFile(BytesIO(c.output_bytes)) as cc:
            self.assertNotEqual(aa.read("docProps/core.xml"), cc.read("docProps/core.xml"))

    def test_diagram_graphic_loss_requires_owner_approval(self) -> None:
        doc = BookDocument(title="Board", blocks=[Diagram(fen=FEN, alt_text="Starting chessboard")])
        with self.assertRaises(FactoryExportError):
            export_factory_docx_preview(doc, source_sha256=SOURCE, modified_utc=DATE)
        result = export_factory_docx_preview(
            doc, source_sha256=SOURCE, modified_utc=DATE, allow_semantic_loss=True
        )
        self.assertIn("ORIGINAL_DIAGRAM_GRAPHICS_NOT_REPRODUCED", result.losses)
        with ZipFile(BytesIO(result.output_bytes)) as zf:
            xml = zf.read("word/document.xml").decode()
            self.assertIn(FEN, xml)
            self.assertIn("Starting chessboard", xml)

    def test_ordered_list_custom_start_not_silently_lost(self) -> None:
        doc = BookDocument(title="List", blocks=[ListBlock(items=["Example"], ordered=True, start=7)])
        with self.assertRaises(FactoryExportError):
            export_factory_docx_preview(doc, source_sha256=SOURCE, modified_utc=DATE)
        result = export_factory_docx_preview(
            doc, source_sha256=SOURCE, modified_utc=DATE, allow_semantic_loss=True
        )
        self.assertIn("ORDERED_LIST_START_NOT_PRESERVED", result.losses)

    def test_game_reference_without_pgn_rejected(self) -> None:
        doc = BookDocument(title="Games", blocks=[Game(game_id=2)])
        with self.assertRaises(FactoryExportError):
            export_factory_docx_preview(doc, source_sha256=SOURCE, modified_utc=DATE)

    def test_invalid_xml_character_fails_closed(self) -> None:
        doc = BookDocument(title="Book", blocks=[Paragraph(text="Body" + chr(1))])
        with self.assertRaises(FactoryExportError):
            export_factory_docx_preview(doc, source_sha256=SOURCE, modified_utc=DATE)

    def test_timestamp_and_source_identity_required(self) -> None:
        doc = BookDocument(title="Book", blocks=[])
        with self.assertRaises(FactoryExportError):
            export_factory_docx_preview(doc, source_sha256=SOURCE, modified_utc="")
        with self.assertRaises(FactoryExportError):
            export_factory_docx_preview(doc, source_sha256="bad", modified_utc=DATE)


if __name__ == "__main__":
    unittest.main()
