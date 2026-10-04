from __future__ import annotations

from io import BytesIO
import unittest
import zipfile

from acs.book_epub_import import import_epub_book
from acs.book_html_import import import_html_book
from acs.bookdocument import Diagram, Note, Paragraph
from acs.chesscore import Board


def _semantic_signature(blocks):
    signature = []
    for block in blocks:
        if isinstance(block, Paragraph):
            signature.append(("Paragraph", block.text))
        elif isinstance(block, Diagram):
            signature.append(("Diagram", block.alt_text or ""))
        elif isinstance(block, Note) and block.note_type == "image":
            signature.append(("ImageNote", block.text))
    return signature


class BookHtmlInlineImageOrderTests(unittest.TestCase):
    def test_inline_image_note_keeps_text_image_text_source_order_and_legacy_progress_id(self) -> None:
        baseline = import_html_book(
            '<html><body><p id="lesson">BeforeAfter</p></body></html>',
            source_name="baseline.html",
        )
        expected_progress_target = next(
            block for block in baseline.document.blocks if isinstance(block, Paragraph)
        )

        result = import_html_book(
            '<html><body><p id="lesson">Before<img src="board.png" alt="Board">After</p></body></html>',
            source_name="inline.html",
            available_assets={"board.png"},
        )

        self.assertEqual(
            _semantic_signature(result.document.blocks),
            [
                ("Paragraph", "Before"),
                ("ImageNote", "Board"),
                ("Paragraph", "After"),
            ],
        )
        paragraphs = [block for block in result.document.blocks if isinstance(block, Paragraph)]
        self.assertEqual(paragraphs[0].block_id, expected_progress_target.block_id)
        self.assertEqual(paragraphs[0].source_anchor, "lesson")
        self.assertIsNone(paragraphs[1].source_anchor)
        self.assertEqual(result.image_references, ("board.png",))

    def test_inline_explicit_fen_diagram_uses_same_source_order_without_new_chess_authority(self) -> None:
        result = import_html_book(
            f'<html><body><p>Before<img src="board.png" alt="Start" data-acs-fen="{Board.START}">After</p></body></html>',
            source_name="diagram.html",
            available_assets={"board.png"},
        )

        self.assertEqual(
            _semantic_signature(result.document.blocks),
            [
                ("Paragraph", "Before"),
                ("Diagram", "Start"),
                ("Paragraph", "After"),
            ],
        )
        diagram = next(block for block in result.document.blocks if isinstance(block, Diagram))
        self.assertEqual(Board(diagram.fen).fen(), Board.START)

    def test_multiple_inline_images_preserve_each_source_boundary(self) -> None:
        result = import_html_book(
            '<html><body><p>A<img src="one.png" alt="One">B<img src="two.png" alt="Two">C</p></body></html>',
            source_name="multiple.html",
            available_assets={"one.png", "two.png"},
        )

        self.assertEqual(
            _semantic_signature(result.document.blocks),
            [
                ("Paragraph", "A"),
                ("ImageNote", "One"),
                ("Paragraph", "B"),
                ("ImageNote", "Two"),
                ("Paragraph", "C"),
            ],
        )

    def test_epub_xhtml_inherits_inline_image_source_order(self) -> None:
        buffer = BytesIO()
        container = b'''<?xml version="1.0" encoding="UTF-8"?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
  <rootfiles>
    <rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/>
  </rootfiles>
</container>'''
        opf = b'''<?xml version="1.0" encoding="UTF-8"?>
<package version="3.0" xmlns="http://www.idpf.org/2007/opf" xmlns:dc="http://purl.org/dc/elements/1.1/">
  <metadata><dc:title>Inline image EPUB</dc:title><dc:language>en</dc:language></metadata>
  <manifest>
    <item id="c1" href="Text/chapter.xhtml" media-type="application/xhtml+xml"/>
    <item id="board" href="Images/board.png" media-type="image/png"/>
  </manifest>
  <spine><itemref idref="c1"/></spine>
</package>'''
        chapter = b'<html><body><p>Before<img src="../Images/board.png" alt="Board">After</p></body></html>'
        with zipfile.ZipFile(buffer, "w") as archive:
            mimetype = zipfile.ZipInfo("mimetype")
            mimetype.compress_type = zipfile.ZIP_STORED
            archive.writestr(mimetype, b"application/epub+zip")
            archive.writestr("META-INF/container.xml", container, compress_type=zipfile.ZIP_DEFLATED)
            archive.writestr("OEBPS/content.opf", opf, compress_type=zipfile.ZIP_DEFLATED)
            archive.writestr("OEBPS/Text/chapter.xhtml", chapter, compress_type=zipfile.ZIP_DEFLATED)
            archive.writestr("OEBPS/Images/board.png", b"not-decoded-by-importer", compress_type=zipfile.ZIP_DEFLATED)

        result = import_epub_book(buffer.getvalue(), source_name="inline.epub")

        self.assertEqual(
            _semantic_signature(result.document.blocks),
            [
                ("Paragraph", "Before"),
                ("ImageNote", "Board"),
                ("Paragraph", "After"),
            ],
        )


if __name__ == "__main__":
    unittest.main()
