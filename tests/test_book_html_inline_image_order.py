from __future__ import annotations

from io import BytesIO
import unittest
from unittest.mock import patch
import zipfile

from acs.book_epub_import import import_epub_book
from acs.book_html_import import (
    BookHtmlImportError,
    BookHtmlImportErrorCode,
    import_html_book,
)
from acs.bookdocument import Diagram, Note, Paragraph, Position
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

    def test_inline_fragments_do_not_shift_following_legacy_paragraph_identity(self) -> None:
        baseline = import_html_book(
            '<html><body><p id="split">AB</p><p id="after">B</p></body></html>',
            source_name="baseline-following-id.html",
        )
        baseline_after = next(
            block
            for block in baseline.document.blocks
            if isinstance(block, Paragraph) and block.source_anchor == "after"
        )

        result = import_html_book(
            '<html><body><p id="split">A<img src="board.png" alt="Board">B</p><p id="after">B</p></body></html>',
            source_name="inline-following-id.html",
            available_assets={"board.png"},
        )
        result_after = next(
            block
            for block in result.document.blocks
            if isinstance(block, Paragraph) and block.source_anchor == "after"
        )

        self.assertEqual(result_after.block_id, baseline_after.block_id)
        self.assertEqual(
            _semantic_signature(result.document.blocks),
            [
                ("Paragraph", "A"),
                ("ImageNote", "Board"),
                ("Paragraph", "B"),
                ("Paragraph", "B"),
            ],
        )

    def test_decorative_image_does_not_fragment_legacy_paragraph(self) -> None:
        baseline = import_html_book(
            '<html><body><p id="lesson">BeforeAfter</p></body></html>',
            source_name="decorative-baseline.html",
        )
        baseline_paragraph = next(
            block for block in baseline.document.blocks if isinstance(block, Paragraph)
        )

        result = import_html_book(
            '<html><body><p id="lesson">Before<img src="decorative.png">After</p></body></html>',
            source_name="decorative-inline.html",
            available_assets={"decorative.png"},
        )
        paragraph = next(block for block in result.document.blocks if isinstance(block, Paragraph))

        self.assertEqual(_semantic_signature(result.document.blocks), [("Paragraph", "BeforeAfter")])
        self.assertEqual(paragraph.block_id, baseline_paragraph.block_id)
        self.assertEqual(paragraph.source_anchor, "lesson")
        self.assertTrue(any("no accessible text" in warning for warning in result.warnings))

    def test_image_at_paragraph_edges_preserves_reading_order(self) -> None:
        first = import_html_book(
            '<html><body><p><img src="board.png" alt="Board">Tail</p></body></html>',
            source_name="image-first.html",
            available_assets={"board.png"},
        )
        last = import_html_book(
            '<html><body><p>Lead<img src="board.png" alt="Board"></p></body></html>',
            source_name="image-last.html",
            available_assets={"board.png"},
        )

        self.assertEqual(
            _semantic_signature(first.document.blocks),
            [("ImageNote", "Board"), ("Paragraph", "Tail")],
        )
        self.assertEqual(
            _semantic_signature(last.document.blocks),
            [("Paragraph", "Lead"), ("ImageNote", "Board")],
        )

    def test_nested_capture_splits_only_nearest_owner_and_preserves_ancestor_identity(self) -> None:
        baseline = import_html_book(
            '<html><body><p id="outer">Outer<blockquote id="inner">InnerLine</blockquote>Tail</p></body></html>',
            source_name="nested-baseline.html",
        )
        baseline_inner = next(
            block
            for block in baseline.document.blocks
            if isinstance(block, Paragraph) and block.source_anchor == "inner"
        )
        baseline_outer = next(
            block
            for block in baseline.document.blocks
            if isinstance(block, Paragraph) and block.source_anchor == "outer"
        )

        result = import_html_book(
            '<html><body><p id="outer">Outer<blockquote id="inner">Inner<img src="board.png" alt="Board">Line</blockquote>Tail</p></body></html>',
            source_name="nested-inline.html",
            available_assets={"board.png"},
        )
        result_inner = next(
            block
            for block in result.document.blocks
            if isinstance(block, Paragraph) and block.source_anchor == "inner"
        )
        result_outer = next(
            block
            for block in result.document.blocks
            if isinstance(block, Paragraph) and block.source_anchor == "outer"
        )

        self.assertEqual(result_inner.block_id, baseline_inner.block_id)
        self.assertEqual(result_outer.block_id, baseline_outer.block_id)
        self.assertEqual(result_outer.text, "Outer InnerLine Tail")
        self.assertEqual(
            _semantic_signature(result.document.blocks),
            [
                ("Paragraph", "Inner"),
                ("ImageNote", "Board"),
                ("Paragraph", "Line"),
                ("Paragraph", "Outer InnerLine Tail"),
            ],
        )

    def test_malformed_unclosed_paragraph_recovers_inline_order(self) -> None:
        result = import_html_book(
            '<html><body><p id="lesson">Before<img src="board.png" alt="Board">After',
            source_name="unclosed-inline.html",
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
        self.assertTrue(any("unclosed p element" in warning for warning in result.warnings))

    def test_inline_fragment_insertion_respects_semantic_block_limit(self) -> None:
        with patch("acs.book_html_import.MAX_HTML_BLOCKS", 2):
            with self.assertRaises(BookHtmlImportError) as raised:
                import_html_book(
                    '<html><body><p>A<img src="board.png" alt="Board">B</p></body></html>',
                    source_name="bounded-inline.html",
                    available_assets={"board.png"},
                )

        self.assertEqual(raised.exception.code, BookHtmlImportErrorCode.RESOURCE_LIMIT)

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


    def test_nested_semantic_after_inline_image_keeps_close_time_order_and_legacy_outer_id(self) -> None:
        baseline = import_html_book(
            '<html><body><p id="outer">Before<blockquote id="inner">Inner</blockquote>After</p></body></html>',
            source_name="nested-after-baseline.html",
        )
        baseline_outer = next(
            block
            for block in baseline.document.blocks
            if isinstance(block, Paragraph) and block.source_anchor == "outer"
        )

        result = import_html_book(
            '<html><body><p id="outer">Before<img src="board.png" alt="Board">'
            '<blockquote id="inner">Inner</blockquote>After</p></body></html>',
            source_name="nested-after-inline.html",
            available_assets={"board.png"},
        )

        self.assertEqual(
            _semantic_signature(result.document.blocks),
            [
                ("Paragraph", "Before"),
                ("ImageNote", "Board"),
                ("Paragraph", "Inner"),
                ("Paragraph", "Inner After"),
            ],
        )
        outer = next(
            block
            for block in result.document.blocks
            if isinstance(block, Paragraph) and block.source_anchor == "outer"
        )
        self.assertEqual(outer.block_id, baseline_outer.block_id)

    def test_explicit_position_after_inline_image_is_not_jumped_by_trailing_text(self) -> None:
        result = import_html_book(
            f'<html><body><p>Before<img src="illustration.png" alt="Illustration">'
            f'<span data-acs-fen="{Board.START}"></span>After</p></body></html>',
            source_name="inline-before-position.html",
            available_assets={"illustration.png"},
        )

        projected = []
        for block in result.document.blocks:
            if isinstance(block, Paragraph):
                projected.append(("Paragraph", block.text))
            elif isinstance(block, Note) and block.note_type == "image":
                projected.append(("ImageNote", block.text))
            elif isinstance(block, Position) and not isinstance(block, Diagram):
                projected.append(("Position", Board(block.fen).fen()))

        self.assertEqual(
            projected,
            [
                ("Paragraph", "Before"),
                ("ImageNote", "Illustration"),
                ("Position", Board.START),
                ("Paragraph", "After"),
            ],
        )


if __name__ == "__main__":
    unittest.main()
