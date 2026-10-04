from __future__ import annotations

from io import BytesIO
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from acs.book_epub_import import import_epub_book
from acs.book_html_import import (
    BookHtmlImportError,
    BookHtmlImportErrorCode,
    import_html_book,
)
from acs.book_progress_store import BookProgressStore
from acs.bookdocument import BookDocument, Diagram, Game, Note, Paragraph, Position
from acs.bookreader import BookReader
from acs.chesscore import Board


_PGN = '''[Event "Source order"]
[Site "Test"]
[Date "2026.10.04"]
[Round "1"]
[White "White"]
[Black "Black"]
[Result "*"]

1. e4 e5 *'''


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


    def test_saved_progress_restores_to_legacy_identity_fragment_after_inline_image_import_change(self) -> None:
        baseline = import_html_book(
            '<html><body><p id="lesson">BeforeAfter</p><p>Next</p></body></html>',
            source_name="progress-baseline.html",
        )
        baseline_reader = BookReader(baseline.document)
        baseline_location = baseline_reader.go_to(0)

        changed = import_html_book(
            '<html><body><p id="lesson">Before<img src="board.png" alt="Board">After</p><p>Next</p></body></html>',
            source_name="progress-inline.html",
            available_assets={"board.png"},
        )

        with tempfile.TemporaryDirectory() as directory:
            store = BookProgressStore(Path(directory) / "progress.json")
            store.save("inline-image-progress-contract", baseline_reader)
            restored = store.restore("inline-image-progress-contract", changed.document)

        location = restored.location()
        block = restored.block_snapshot(location.index)
        self.assertEqual(location.block_id, baseline_location.block_id)
        self.assertEqual(location.source_anchor, "lesson")
        self.assertIsInstance(block, Paragraph)
        self.assertEqual(block.text, "Before")


    def test_inline_order_workflow_watches_books_persistence_and_chess_authority_dependencies(self) -> None:
        workflow = (
            Path(__file__).resolve().parents[1]
            / ".github"
            / "workflows"
            / "book-html-inline-image-order.yml"
        ).read_text(encoding="utf-8")

        self.assertGreaterEqual(workflow.count("- 'acs/book*.py'"), 2)
        self.assertGreaterEqual(workflow.count("- 'acs/chesscore.py'"), 2)
        self.assertGreaterEqual(workflow.count("- 'acs/pgn_roundtrip.py'"), 2)
        self.assertIn("tests.test_book_html_inline_image_order", workflow)
        self.assertIn("tests.test_v2_book_html_import", workflow)
        self.assertIn("from .chesscore import Board", workflow)
        self.assertIn("from .pgn_roundtrip import PgnRoundTripError, parse_pgn_text", workflow)


    def test_explicit_position_before_inline_image_preserves_text_position_image_text_order(self) -> None:
        result = import_html_book(
            f'<html><body><p>Before'
            f'<span data-acs-fen="{Board.START}"></span>'
            f'<img src="illustration.png" alt="Illustration">After</p></body></html>',
            source_name="position-before-image.html",
            available_assets={"illustration.png"},
        )

        projected = []
        for block in result.document.blocks:
            if isinstance(block, Paragraph):
                projected.append(("Paragraph", block.text))
            elif isinstance(block, Position) and not isinstance(block, Diagram):
                projected.append(("Position", Board(block.fen).fen()))
            elif isinstance(block, Note) and block.note_type == "image":
                projected.append(("ImageNote", block.text))

        self.assertEqual(
            projected,
            [
                ("Paragraph", "Before"),
                ("Position", Board.START),
                ("ImageNote", "Illustration"),
                ("Paragraph", "After"),
            ],
        )


    def test_explicit_pgn_game_keeps_crlf_source_order_and_reader_navigation(self) -> None:
        source = (
            "<html><body><h1>Before</h1><pre>{PGN 1}\r\n"
            + _PGN.replace("\n", "\r\n")
            + "</pre><p>After</p></body></html>"
        )
        result = import_html_book(source, source_name="pgn-source-order.html")

        self.assertEqual(
            [block.kind for block in result.document.blocks],
            ["Heading", "Game", "Paragraph"],
        )
        reader = BookReader(result.document)
        reader.go_to(0)
        game_location = reader.next_game()
        self.assertEqual(game_location.index, 1)
        self.assertIsInstance(reader.block_snapshot(game_location.index), Game)
        after = reader.next_block()
        self.assertEqual(after.index, 2)
        after_block = reader.block_snapshot(after.index)
        self.assertIsInstance(after_block, Paragraph)
        self.assertEqual(after_block.text, "After")

    def test_duplicate_explicit_pgns_keep_distinct_ids_and_interleaved_source_order(self) -> None:
        source = (
            "<html><body><p>Before</p>"
            "<pre>{PGN 1}\n" + _PGN + "</pre>"
            "<p>Middle</p>"
            "<pre>{PGN 2}\n" + _PGN + "</pre>"
            "<p>After</p></body></html>"
        )
        result = import_html_book(source, source_name="duplicate-pgn-source-order.html")

        self.assertEqual(
            [block.kind for block in result.document.blocks],
            ["Paragraph", "Game", "Paragraph", "Game", "Paragraph"],
        )
        games = [block for block in result.document.blocks if isinstance(block, Game)]
        self.assertEqual(len(games), 2)
        self.assertNotEqual(games[0].block_id, games[1].block_id)
        self.assertEqual(
            [game.source_anchor for game in games],
            ["pgn:1", "pgn:2"],
        )
        self.assertTrue(games[0].block_id.endswith("-1"))
        self.assertTrue(games[1].block_id.endswith("-2"))


    def test_invalid_explicit_pgn_drops_internal_slot_and_preserves_following_readable_text(self) -> None:
        source = """<html><body><pre>{PGN 1}
[Event "Broken"]
[White "White"]
[Black "Black"]
[Result "*"]

1. e4 e5 2. ThisIsNotAMove *</pre><p>Readable after broken game.</p></body></html>"""
        result = import_html_book(source, source_name="invalid-pgn-slot.html")

        self.assertEqual(result.pgn_games, 0)
        self.assertFalse(any(isinstance(block, Game) for block in result.document.blocks))
        self.assertEqual(
            [block.text for block in result.document.blocks if isinstance(block, Paragraph)],
            ["Readable after broken game."],
        )
        self.assertTrue(
            any(
                "could not be represented canonically" in warning
                or "did not resolve to exactly one canonical game" in warning
                for warning in result.warnings
            )
        )

    def test_unmarked_pgn_remains_readable_prose_and_never_creates_source_slot(self) -> None:
        source = (
            "<html><body><pre>" + _PGN + "</pre><p>After prose.</p></body></html>"
        )
        result = import_html_book(source, source_name="unmarked-pgn-slot.html")

        self.assertEqual(result.pgn_games, 0)
        self.assertFalse(any(isinstance(block, Game) for block in result.document.blocks))
        paragraphs = [
            block.text for block in result.document.blocks if isinstance(block, Paragraph)
        ]
        self.assertTrue(any('[Event "Source order"]' in text for text in paragraphs))
        self.assertEqual(paragraphs[-1], "After prose.")


    def test_nested_block_between_inline_images_preserves_each_source_boundary(self) -> None:
        result = import_html_book(
            '<html><body><p id="outer">A<img src="one.png" alt="One">B'
            '<blockquote id="inner">C</blockquote>D'
            '<img src="two.png" alt="Two">E</p></body></html>',
            source_name="nested-between-images.html",
            available_assets={"one.png", "two.png"},
        )

        self.assertEqual(
            _semantic_signature(result.document.blocks),
            [
                ("Paragraph", "A"),
                ("ImageNote", "One"),
                ("Paragraph", "B"),
                ("Paragraph", "C"),
                ("Paragraph", "C D"),
                ("ImageNote", "Two"),
                ("Paragraph", "E"),
            ],
        )
        inner = next(
            block
            for block in result.document.blocks
            if isinstance(block, Paragraph) and block.source_anchor == "inner"
        )
        self.assertEqual(inner.text, "C")

    def test_nested_only_paragraph_keeps_legacy_projection_without_forced_split(self) -> None:
        result = import_html_book(
            '<html><body><p id="outer">Before'
            '<blockquote id="inner">Inner</blockquote>After</p></body></html>',
            source_name="nested-only-compat.html",
        )

        self.assertEqual(
            _semantic_signature(result.document.blocks),
            [
                ("Paragraph", "Inner"),
                ("Paragraph", "Before Inner After"),
            ],
        )
        outer = next(
            block
            for block in result.document.blocks
            if isinstance(block, Paragraph) and block.source_anchor == "outer"
        )
        self.assertEqual(outer.text, "Before Inner After")

    def test_unclosed_nested_capture_keeps_prefix_before_recovered_semantic_subtree(self) -> None:
        result = import_html_book(
            '<html><body><p id="outer">A<img src="one.png" alt="One">B'
            '<blockquote id="inner">C<img src="two.png" alt="Two">D',
            source_name="unclosed-nested-inline.html",
            available_assets={"one.png", "two.png"},
        )

        signature = _semantic_signature(result.document.blocks)
        self.assertEqual(
            signature[:6],
            [
                ("Paragraph", "A"),
                ("ImageNote", "One"),
                ("Paragraph", "B"),
                ("Paragraph", "C"),
                ("ImageNote", "Two"),
                ("Paragraph", "D"),
            ],
        )
        self.assertTrue(
            any("unclosed blockquote element" in warning for warning in result.warnings)
        )
        self.assertTrue(
            any("unclosed p element" in warning for warning in result.warnings)
        )


    def test_progress_survives_migration_from_legacy_end_appended_game_order(self) -> None:
        source = (
            "<html><body><h1>Chapter</h1><pre>{PGN 1}\n"
            + _PGN
            + "</pre><p id=\"after\">After game.</p></body></html>"
        )
        current = import_html_book(source, source_name="pgn-progress-migration.html")
        self.assertEqual(
            [block.kind for block in current.document.blocks],
            ["Heading", "Game", "Paragraph"],
        )

        heading, game, after = current.document.blocks
        legacy = BookDocument(
            title=current.document.title,
            language=current.document.language,
            author=current.document.author,
            source_name=current.document.source_name,
            blocks=[heading, after, game],
            warnings=list(current.document.warnings),
        )

        with tempfile.TemporaryDirectory() as directory:
            store = BookProgressStore(Path(directory) / "progress.json")

            legacy_reader = BookReader(legacy)
            legacy_reader.go_to(1)
            store.save(current.book_key + ":after", legacy_reader)
            restored_after = store.restore(
                current.book_key + ":after",
                current.document,
            )
            self.assertEqual(restored_after.location().index, 2)
            self.assertEqual(restored_after.location().block_id, after.block_id)

            legacy_reader.go_to(2)
            store.save(current.book_key + ":game", legacy_reader)
            restored_game = store.restore(
                current.book_key + ":game",
                current.document,
            )
            self.assertEqual(restored_game.location().index, 1)
            self.assertEqual(restored_game.location().block_id, game.block_id)

    def test_invalid_first_marked_game_does_not_renumber_later_valid_game_identity(self) -> None:
        source = (
            "<html><body><pre>{PGN 1}\n"
            "[Event \"Broken\"]\n[White \"A\"]\n[Black \"B\"]\n[Result \"*\"]\n\n"
            "1. ThisIsNotAMove *\n"
            "{PGN 2}\n"
            + _PGN
            + "</pre><p>After.</p></body></html>"
        )
        result = import_html_book(source, source_name="mixed-pgn-validity.html")

        games = [block for block in result.document.blocks if isinstance(block, Game)]
        self.assertEqual(len(games), 1)
        self.assertEqual(result.pgn_games, 1)
        self.assertEqual(games[0].source_anchor, "pgn:2")
        self.assertEqual(
            [block.kind for block in result.document.blocks],
            ["Game", "Paragraph"],
        )
        self.assertEqual(
            next(block.text for block in result.document.blocks if isinstance(block, Paragraph)),
            "After.",
        )


if __name__ == "__main__":
    unittest.main()
