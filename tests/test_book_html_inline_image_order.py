from __future__ import annotations

from io import BytesIO
from html.parser import HTMLParser
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
from acs.bookdocument import BookDocument, Diagram, Game, Heading, Note, Paragraph, Position
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
        self.assertEqual(result_outer.text, "Outer")
        self.assertEqual(
            _semantic_signature(result.document.blocks),
            [
                ("Paragraph", "Outer"),
                ("Paragraph", "Inner"),
                ("ImageNote", "Board"),
                ("Paragraph", "Line"),
                ("Paragraph", "Tail"),
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
<package version="3.0" unique-identifier="bookid" xmlns="http://www.idpf.org/2007/opf" xmlns:dc="http://purl.org/dc/elements/1.1/">
  <metadata><dc:identifier id="bookid">urn:uuid:inline-image-test</dc:identifier><dc:title>Inline image EPUB</dc:title><dc:language>en</dc:language></metadata>
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
                ("Paragraph", "After"),
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


    def test_explicit_pgn_nested_inside_list_item_stays_canonical_and_in_source_order(self) -> None:
        result = import_html_book(
            "<html><body><ul><li id=\"rich\">Before<pre>{PGN 1}\n"
            + _PGN
            + "</pre>After</li></ul></body></html>",
            source_name="nested-pgn-list-item.html",
        )

        self.assertEqual(result.pgn_games, 1)
        self.assertEqual(
            [block.kind for block in result.document.blocks],
            ["Paragraph", "Game", "Paragraph"],
        )
        paragraphs = [
            block.text for block in result.document.blocks
            if isinstance(block, Paragraph)
        ]
        self.assertEqual(paragraphs, ["• Before", "After"])
        self.assertFalse(any(block.kind == "List" for block in result.document.blocks))

        reader = BookReader(result.document)
        reader.go_to(0)
        game_location = reader.next_game()
        self.assertEqual(game_location.index, 1)
        self.assertIsInstance(reader.block_snapshot(game_location.index), Game)
        after = reader.next_block()
        self.assertEqual(after.index, 2)
        self.assertEqual(reader.block_snapshot(after.index).text, "After")


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


    def test_invalid_explicit_pgn_preserves_source_and_following_readable_text(self) -> None:
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
            ['[Event "Broken"]\n[White "White"]\n[Black "Black"]\n[Result "*"]\n\n1. e4 e5 2. ThisIsNotAMove *',
             "Readable after broken game."],
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
                ("Paragraph", "D"),
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
            ["Paragraph", "Game", "Paragraph"],
        )
        self.assertEqual(
            result.document.blocks[-1].text,
            "After.",
        )


    def test_nested_boundary_split_restores_legacy_outer_progress(self) -> None:
        baseline = import_html_book(
            '<html><body><p id="outer">AB'
            '<blockquote id="inner">C</blockquote>DE</p></body></html>',
            source_name="nested-progress-baseline.html",
        )
        baseline_index = next(
            index
            for index, block in enumerate(baseline.document.blocks)
            if isinstance(block, Paragraph) and block.source_anchor == "outer"
        )
        baseline_reader = BookReader(baseline.document)
        baseline_location = baseline_reader.go_to(baseline_index)

        changed = import_html_book(
            '<html><body><p id="outer">A<img src="one.png" alt="One">B'
            '<blockquote id="inner">C</blockquote>D'
            '<img src="two.png" alt="Two">E</p></body></html>',
            source_name="nested-progress-changed.html",
            available_assets={"one.png", "two.png"},
        )

        with tempfile.TemporaryDirectory() as directory:
            store = BookProgressStore(Path(directory) / "progress.json")
            store.save("nested-boundary-progress", baseline_reader)
            restored = store.restore("nested-boundary-progress", changed.document)

        location = restored.location()
        block = restored.block_snapshot(location.index)
        self.assertEqual(location.block_id, baseline_location.block_id)
        self.assertEqual(location.source_anchor, "outer")
        self.assertIsInstance(block, Paragraph)
        self.assertEqual(block.text, "A")


    def test_malformed_nested_heading_keeps_outer_prefix_before_heading_when_later_image_splits_parent(self) -> None:
        result = import_html_book(
            '<html><body><p id="outer">A<h2 id="inner">H</h2>B'
            '<img src="image.png" alt="Image">C</p></body></html>',
            source_name="malformed-nested-heading-inline.html",
            available_assets={"image.png"},
        )

        projected = []
        for block in result.document.blocks:
            if isinstance(block, Heading):
                projected.append(("Heading", block.text))
            elif isinstance(block, Paragraph):
                projected.append(("Paragraph", block.text))
            elif isinstance(block, Note) and block.note_type == "image":
                projected.append(("ImageNote", block.text))

        self.assertEqual(
            projected,
            [
                ("Paragraph", "A"),
                ("Heading", "H"),
                ("Paragraph", "B"),
                ("ImageNote", "Image"),
                ("Paragraph", "C"),
            ],
        )


    def test_inline_heading_image_preserves_source_order_legacy_identity_and_heading_navigation(self) -> None:
        baseline = import_html_book(
            '<html><body><h2 id="topic">BeforeAfter</h2><h2>Next</h2></body></html>',
            source_name="heading-baseline.html",
        )
        baseline_headings = [
            block for block in baseline.document.blocks if isinstance(block, Heading)
        ]
        self.assertEqual(len(baseline_headings), 2)

        result = import_html_book(
            '<html><body><h2 id="topic">Before<img src="board.png" alt="Board">After</h2>'
            '<h2>Next</h2></body></html>',
            source_name="heading-inline.html",
            available_assets={"board.png"},
        )

        self.assertEqual(
            [
                (
                    block.kind,
                    block.text if isinstance(block, (Heading, Paragraph, Note)) else "",
                )
                for block in result.document.blocks
            ],
            [
                ("Heading", "Before"),
                ("Note", "Board"),
                ("Paragraph", "After"),
                ("Heading", "Next"),
            ],
        )
        first_heading = result.document.blocks[0]
        next_heading = result.document.blocks[3]
        self.assertIsInstance(first_heading, Heading)
        self.assertEqual(first_heading.level, 2)
        self.assertEqual(first_heading.source_anchor, "topic")
        self.assertEqual(first_heading.block_id, baseline_headings[0].block_id)
        self.assertIsInstance(next_heading, Heading)
        self.assertEqual(next_heading.block_id, baseline_headings[1].block_id)

        reader = BookReader(result.document)
        reader.go_to(0)
        location = reader.next_heading()
        self.assertEqual(location.index, 3)
        self.assertEqual(reader.block_snapshot(location.index).text, "Next")

    def test_inline_heading_image_edges_keep_true_source_order(self) -> None:
        image_first = import_html_book(
            '<html><body><h3><img src="board.png" alt="Board">Tail</h3></body></html>',
            source_name="heading-image-first.html",
            available_assets={"board.png"},
        )
        self.assertEqual(
            [
                (block.kind, block.text if isinstance(block, (Heading, Paragraph, Note)) else "")
                for block in image_first.document.blocks
            ],
            [("Note", "Board"), ("Heading", "Tail")],
        )

        image_last = import_html_book(
            '<html><body><h3>Lead<img src="board.png" alt="Board"></h3></body></html>',
            source_name="heading-image-last.html",
            available_assets={"board.png"},
        )
        self.assertEqual(
            [
                (block.kind, block.text if isinstance(block, (Heading, Paragraph, Note)) else "")
                for block in image_last.document.blocks
            ],
            [("Heading", "Lead"), ("Note", "Board")],
        )

    def test_inline_heading_explicit_position_keeps_heading_position_text_order(self) -> None:
        result = import_html_book(
            f'<html><body><h1 id="chapter">Before'
            f'<span data-acs-fen="{Board.START}"></span>After</h1></body></html>',
            source_name="heading-position.html",
        )

        self.assertEqual(
            [block.kind for block in result.document.blocks],
            ["Heading", "Position", "Paragraph"],
        )
        heading, position, trailing = result.document.blocks
        self.assertIsInstance(heading, Heading)
        self.assertEqual(heading.text, "Before")
        self.assertEqual(heading.source_anchor, "chapter")
        self.assertIsInstance(position, Position)
        self.assertEqual(Board(position.fen).fen(), Board.START)
        self.assertIsInstance(trailing, Paragraph)
        self.assertEqual(trailing.text, "After")

    def test_heading_progress_restores_to_legacy_identity_fragment_after_inline_split(self) -> None:
        baseline = import_html_book(
            '<html><body><h2 id="topic">BeforeAfter</h2><p>Body</p></body></html>',
            source_name="heading-progress-baseline.html",
        )
        baseline_reader = BookReader(baseline.document)
        baseline_location = baseline_reader.go_to(0)

        changed = import_html_book(
            '<html><body><h2 id="topic">Before<img src="board.png" alt="Board">After</h2>'
            '<p>Body</p></body></html>',
            source_name="heading-progress-changed.html",
            available_assets={"board.png"},
        )

        with tempfile.TemporaryDirectory() as directory:
            store = BookProgressStore(Path(directory) / "progress.json")
            store.save("inline-heading-progress", baseline_reader)
            restored = store.restore("inline-heading-progress", changed.document)

        location = restored.location()
        block = restored.block_snapshot(location.index)
        self.assertEqual(location.block_id, baseline_location.block_id)
        self.assertEqual(location.source_anchor, "topic")
        self.assertIsInstance(block, Heading)
        self.assertEqual(block.text, "Before")
        self.assertEqual(block.level, 2)

    def test_unclosed_inline_heading_recovers_source_order_without_losing_heading_identity(self) -> None:
        baseline = import_html_book(
            '<html><body><h2 id="topic">AB</h2></body></html>',
            source_name="heading-unclosed-baseline.html",
        )
        baseline_heading = next(
            block for block in baseline.document.blocks if isinstance(block, Heading)
        )

        result = import_html_book(
            '<html><body><h2 id="topic">A<img src="board.png" alt="Board">B',
            source_name="heading-unclosed.html",
            available_assets={"board.png"},
        )

        self.assertEqual(
            [
                (block.kind, block.text if isinstance(block, (Heading, Paragraph, Note)) else "")
                for block in result.document.blocks
            ],
            [("Heading", "A"), ("Note", "Board"), ("Paragraph", "B")],
        )
        recovered_heading = result.document.blocks[0]
        self.assertIsInstance(recovered_heading, Heading)
        self.assertEqual(recovered_heading.block_id, baseline_heading.block_id)
        self.assertTrue(
            any("unclosed h2 element" in warning for warning in result.warnings)
        )


    def test_nested_inline_heading_does_not_duplicate_heading_text_in_outer_split(self) -> None:
        result = import_html_book(
            '<html><body><p id="outer">A'
            '<h2 id="inner">H1<img src="inner.png" alt="Inner">H2</h2>'
            'B<img src="outer.png" alt="Outer">C</p></body></html>',
            source_name="nested-inline-heading.html",
            available_assets={"inner.png", "outer.png"},
        )

        projected = []
        for block in result.document.blocks:
            if isinstance(block, Heading):
                projected.append(("Heading", block.text))
            elif isinstance(block, Paragraph):
                projected.append(("Paragraph", block.text))
            elif isinstance(block, Note) and block.note_type == "image":
                projected.append(("ImageNote", block.text))

        self.assertEqual(
            projected,
            [
                ("Paragraph", "A"),
                ("Heading", "H1"),
                ("ImageNote", "Inner"),
                ("Paragraph", "H2"),
                ("Paragraph", "B"),
                ("ImageNote", "Outer"),
                ("Paragraph", "C"),
            ],
        )
        self.assertEqual(
            sum(
                block.text.count("H1") + block.text.count("H2")
                for block in result.document.blocks
                if isinstance(block, (Heading, Paragraph))
            ),
            2,
        )


    def test_nested_heading_inside_heading_is_structural_boundary_when_outer_inline_semantic_splits(self) -> None:
        result = import_html_book(
            '<html><body><h2 id="outer">A<h3 id="inner">B</h3>C'
            '<img src="board.png" alt="Board">D</h2></body></html>',
            source_name="nested-heading-owner-split.html",
            available_assets={"board.png"},
        )

        projected = []
        for block in result.document.blocks:
            if isinstance(block, Heading):
                projected.append(("Heading", block.text))
            elif isinstance(block, Paragraph):
                projected.append(("Paragraph", block.text))
            elif isinstance(block, Note) and block.note_type == "image":
                projected.append(("ImageNote", block.text))

        self.assertEqual(
            projected,
            [
                ("Heading", "A"),
                ("Heading", "B"),
                ("Paragraph", "C"),
                ("ImageNote", "Board"),
                ("Paragraph", "D"),
            ],
        )
        self.assertEqual(
            sum(
                block.text.count("B")
                for block in result.document.blocks
                if isinstance(block, (Heading, Paragraph))
            ),
            1,
        )

    def test_nested_heading_inside_heading_without_inline_semantic_keeps_legacy_projection(self) -> None:
        result = import_html_book(
            '<html><body><h2 id="outer">A<h3 id="inner">B</h3>C</h2></body></html>',
            source_name="nested-heading-owner-legacy.html",
        )

        self.assertEqual(
            [
                (block.kind, block.text)
                for block in result.document.blocks
                if isinstance(block, (Heading, Paragraph))
            ],
            [
                ("Heading", "B"),
                ("Heading", "A B C"),
            ],
        )

    def test_list_item_inline_image_falls_back_without_reordering_neighbor_items(self) -> None:
        result = import_html_book(
            '<html><body><ul id="choices"><li>First</li>'
            '<li id="rich">Before<img src="board.png" alt="Board">After</li>'
            '<li>Last</li></ul></body></html>',
            source_name="list-inline-image.html",
            available_assets={"board.png"},
        )

        self.assertEqual(
            _semantic_signature(result.document.blocks),
            [
                ("Paragraph", "• First"),
                ("Paragraph", "• Before"),
                ("ImageNote", "Board"),
                ("Paragraph", "After"),
                ("Paragraph", "• Last"),
            ],
        )
        self.assertFalse(any(block.kind == "List" for block in result.document.blocks))
        paragraphs = [
            block for block in result.document.blocks if isinstance(block, Paragraph)
        ]
        self.assertEqual(paragraphs[0].source_anchor, "choices")
        self.assertEqual(paragraphs[1].source_anchor, "rich")
        self.assertIsNone(paragraphs[2].source_anchor)
        self.assertEqual(paragraphs[3].source_anchor, "choices")
        self.assertTrue(
            any(
                "inline semantic content cannot be represented" in warning
                for warning in result.warnings
            )
        )

    def test_image_only_rich_list_item_cannot_jump_before_previous_item(self) -> None:
        result = import_html_book(
            '<html><body><ol id="steps"><li>First</li><li>'
            '<img src="board.png" alt="Board"></li><li>Last</li></ol>'
            '</body></html>',
            source_name="list-image-only-item.html",
            available_assets={"board.png"},
        )

        self.assertEqual(
            _semantic_signature(result.document.blocks),
            [
                ("Paragraph", "• First"),
                ("Paragraph", "•"),
                ("ImageNote", "Board"),
                ("Paragraph", "• Last"),
            ],
        )
        self.assertFalse(any(block.kind == "List" for block in result.document.blocks))
        self.assertTrue(
            any(
                "inline semantic content cannot be represented" in warning
                for warning in result.warnings
            )
        )

    def test_rich_list_fallback_preserves_legacy_list_progress_target(self) -> None:
        baseline = import_html_book(
            '<html><body><ul id="choices"><li>BeforeAfter</li><li>Last</li>'
            '</ul></body></html>',
            source_name="list-progress-baseline.html",
        )
        baseline_index = next(
            index
            for index, block in enumerate(baseline.document.blocks)
            if block.kind == "List"
        )
        baseline_reader = BookReader(baseline.document)
        baseline_location = baseline_reader.go_to(baseline_index)

        changed = import_html_book(
            '<html><body><ul id="choices"><li>Before'
            '<img src="board.png" alt="Board">After</li><li>Last</li>'
            '</ul></body></html>',
            source_name="list-progress-changed.html",
            available_assets={"board.png"},
        )

        first_fallback = changed.document.blocks[0]
        self.assertIsInstance(first_fallback, Paragraph)
        self.assertEqual(first_fallback.text, "• Before")
        self.assertEqual(first_fallback.block_id, baseline_location.block_id)
        self.assertEqual(first_fallback.source_anchor, "choices")

        with tempfile.TemporaryDirectory() as directory:
            store = BookProgressStore(Path(directory) / "progress.json")
            store.save("rich-list-progress", baseline_reader)
            restored = store.restore("rich-list-progress", changed.document)

        restored_location = restored.location()
        restored_block = restored.block_snapshot(restored_location.index)
        self.assertEqual(restored_location.block_id, baseline_location.block_id)
        self.assertEqual(restored_location.source_anchor, "choices")
        self.assertIsInstance(restored_block, Paragraph)
        self.assertEqual(restored_block.text, "• Before")

    def test_rich_list_fallback_does_not_shift_following_paragraph_identity(self) -> None:
        baseline = import_html_book(
            '<html><body><ul><li>BeforeAfter</li><li>Last</li></ul>'
            '<p id="after">• Last</p></body></html>',
            source_name="list-following-id-baseline.html",
        )
        baseline_after = next(
            block
            for block in baseline.document.blocks
            if isinstance(block, Paragraph) and block.source_anchor == "after"
        )

        changed = import_html_book(
            '<html><body><ul><li>Before'
            '<img src="board.png" alt="Board">After</li><li>Last</li></ul>'
            '<p id="after">• Last</p></body></html>',
            source_name="list-following-id-changed.html",
            available_assets={"board.png"},
        )
        changed_after = next(
            block
            for block in changed.document.blocks
            if isinstance(block, Paragraph) and block.source_anchor == "after"
        )

        self.assertEqual(changed_after.block_id, baseline_after.block_id)
        self.assertEqual(changed_after.text, "• Last")

    def test_list_inline_position_uses_canonical_board_and_true_source_order(self) -> None:
        result = import_html_book(
            f'<html><body><ul><li>Before'
            f'<span data-acs-fen="{Board.START}"></span>After</li></ul>'
            f'</body></html>',
            source_name="list-inline-position.html",
        )

        self.assertEqual(
            [block.kind for block in result.document.blocks],
            ["Paragraph", "Position", "Paragraph"],
        )
        leading, position, trailing = result.document.blocks
        self.assertIsInstance(leading, Paragraph)
        self.assertEqual(leading.text, "• Before")
        self.assertIsInstance(position, Position)
        self.assertEqual(Board(position.fen).fen(), Board.START)
        self.assertIsInstance(trailing, Paragraph)
        self.assertEqual(trailing.text, "After")

    def test_head_close_contains_all_nested_unclosed_titles_before_body_text(self) -> None:
        if "title" in getattr(HTMLParser, "RCDATA_CONTENT_ELEMENTS", ()):
            # Qualified newer parser treats all of this as unclosed title text.
            # There is no deterministic readable BODY to invent or recover.
            with self.assertRaises(BookHtmlImportError) as caught:
                import_html_book('<html><head><title>Outer<title>Inner</head><body><p>Body text</p></body></html>', source_name='malformed-nested-title-close.html')
            self.assertEqual(caught.exception.code, BookHtmlImportErrorCode.NO_READABLE_CONTENT)
            return
        result = import_html_book(
            '<html><head><title>Outer<title>Inner</head>'
            '<body><p id="body">Body text</p></body></html>',
            source_name="malformed-nested-title-close.html",
        )

        self.assertEqual(result.document.title, "Inner")
        paragraphs = [
            block for block in result.document.blocks if isinstance(block, Paragraph)
        ]
        self.assertEqual(
            [(block.source_anchor, block.text) for block in paragraphs],
            [("body", "Body text")],
        )
        self.assertGreaterEqual(
            sum("unclosed title element" in warning for warning in result.warnings),
            2,
        )

    def test_head_close_contains_unclosed_title_before_body_text(self) -> None:
        if "title" in getattr(HTMLParser, "RCDATA_CONTENT_ELEMENTS", ()):
            with self.assertRaises(BookHtmlImportError) as caught:
                import_html_book('<html><head><title>Book title</head><body><p>Body text</p></body></html>', source_name='malformed-title-close.html')
            self.assertEqual(caught.exception.code, BookHtmlImportErrorCode.NO_READABLE_CONTENT)
            return
        result = import_html_book(
            '<html><head><title>Book title</head>'
            '<body><p id="body">Body text</p></body></html>',
            source_name="malformed-title-close.html",
        )

        self.assertEqual(result.document.title, "Book title")
        paragraphs = [
            block for block in result.document.blocks if isinstance(block, Paragraph)
        ]
        self.assertEqual(
            [(block.source_anchor, block.text) for block in paragraphs],
            [("body", "Body text")],
        )
        self.assertTrue(
            any("unclosed title element" in warning for warning in result.warnings)
        )

    def test_explicit_ancestor_close_recovers_unclosed_semantic_descendant_before_following_text(self) -> None:
        result = import_html_book(
            '<html><body><p id="outer">A<blockquote id="inner">B</p>'
            '<p id="outside">Outside</p></body></html>',
            source_name="malformed-ancestor-close.html",
        )

        paragraphs = [
            block for block in result.document.blocks if isinstance(block, Paragraph)
        ]
        self.assertEqual(
            [(block.source_anchor, block.text) for block in paragraphs],
            [
                ("inner", "B"),
                ("outer", "A B"),
                ("outside", "Outside"),
            ],
        )
        self.assertTrue(
            any(
                "unclosed blockquote element" in warning
                for warning in result.warnings
            )
        )
        self.assertEqual(
            sum("Outside" in block.text for block in paragraphs),
            1,
        )

    def test_list_close_recovers_unclosed_item_before_following_text(self) -> None:
        result = import_html_book(
            '<html><body><ul id="items"><li id="broken">A</ul>'
            '<p id="outside">Outside</p></body></html>',
            source_name="malformed-list-close.html",
        )

        self.assertEqual(len(result.document.blocks), 2)
        list_block, outside = result.document.blocks
        self.assertEqual(list_block.kind, "List")
        self.assertEqual(list_block.items, ["A"])
        self.assertEqual(list_block.source_anchor, "items")
        self.assertIsInstance(outside, Paragraph)
        self.assertEqual(outside.text, "Outside")
        self.assertEqual(outside.source_anchor, "outside")
        self.assertTrue(
            any("unclosed li element" in warning for warning in result.warnings)
        )
        self.assertFalse(
            any(
                isinstance(block, Paragraph)
                and "Outside" in block.text
                and block.source_anchor == "broken"
                for block in result.document.blocks
            )
        )

    def test_malformed_nested_list_inline_event_does_not_escape_to_outer_owner(self) -> None:
        result = import_html_book(
            '<html><body><p id="outer">A<ul><li>B'
            '<img src="inner.png" alt="Inner">C</li></ul>D'
            '<img src="outer.png" alt="Outer">E</p></body></html>',
            source_name="malformed-nested-list-inline.html",
            available_assets={"inner.png", "outer.png"},
        )

        image_notes = [
            block.text
            for block in result.document.blocks
            if isinstance(block, Note) and block.note_type == "image"
        ]
        self.assertEqual(image_notes, ["Inner", "Outer"])
        self.assertTrue(result.document.blocks)
        self.assertIsInstance(result.document.blocks[0], Paragraph)
        self.assertEqual(result.document.blocks[0].text, "A")
        self.assertFalse(any(block.kind == "List" for block in result.document.blocks))
        self.assertTrue(
            any(
                isinstance(block, Paragraph) and block.text.startswith("• B")
                for block in result.document.blocks
            )
        )
        self.assertIsInstance(result.document.blocks[-1], Paragraph)
        self.assertEqual(result.document.blocks[-1].text, "E")


    def test_inline_heading_diagram_preserves_board_authority_and_source_order(self) -> None:
        result = import_html_book(
            f'<html><body><h2>Before'
            f'<img src="board.png" alt="Start board" data-acs-fen="{Board.START}">'
            f'After</h2></body></html>',
            source_name="heading-diagram.html",
            available_assets={"board.png"},
        )

        self.assertEqual(
            [block.kind for block in result.document.blocks],
            ["Heading", "Diagram", "Paragraph"],
        )
        heading, diagram, trailing = result.document.blocks
        self.assertIsInstance(heading, Heading)
        self.assertEqual(heading.text, "Before")
        self.assertIsInstance(diagram, Diagram)
        self.assertEqual(Board(diagram.fen).fen(), Board.START)
        self.assertEqual(diagram.alt_text, "Start board")
        self.assertIsInstance(trailing, Paragraph)
        self.assertEqual(trailing.text, "After")

    def test_table_row_inline_image_preserves_flattened_text_source_order(self) -> None:
        result = import_html_book(
            '<html><body><table><tr id="row"><td>Before</td><td>'
            '<img src="board.png" alt="Board"></td><td>After</td></tr></table>'
            '</body></html>',
            source_name="table-row-inline-image.html",
            available_assets={"board.png"},
        )

        self.assertEqual(
            [
                (
                    block.kind,
                    block.text if isinstance(block, (Paragraph, Note)) else "",
                )
                for block in result.document.blocks
            ],
            [
                ("Paragraph", "Before"),
                ("Note", "Board"),
                ("Paragraph", "After"),
            ],
        )
        self.assertEqual(result.document.blocks[0].source_anchor, "row")
        self.assertIsNone(result.document.blocks[2].source_anchor)
        self.assertTrue(
            any(
                "table structure is preserved as row text" in warning
                for warning in result.warnings
            )
        )

    def test_non_pgn_pre_inline_image_preserves_prose_source_order(self) -> None:
        result = import_html_book(
            '<html><body><pre id="sample">Before'
            '<img src="board.png" alt="Board">After</pre></body></html>',
            source_name="pre-inline-image.html",
            available_assets={"board.png"},
        )

        self.assertEqual(
            [
                (
                    block.kind,
                    block.text if isinstance(block, (Paragraph, Note)) else "",
                )
                for block in result.document.blocks
            ],
            [
                ("Paragraph", "Before"),
                ("Note", "Board"),
                ("Paragraph", "After"),
            ],
        )
        self.assertEqual(result.document.blocks[0].source_anchor, "sample")
        self.assertIsNone(result.document.blocks[2].source_anchor)

    def test_nested_blockquote_is_not_duplicated_when_outer_paragraph_splits(self) -> None:
        result = import_html_book(
            '<html><body><p id="outer">A'
            '<blockquote id="quote">B</blockquote>C'
            '<img src="board.png" alt="Board">D</p></body></html>',
            source_name="nested-blockquote-paragraph.html",
            available_assets={"board.png"},
        )

        self.assertEqual(
            _semantic_signature(result.document.blocks),
            [
                ("Paragraph", "A"),
                ("Paragraph", "B"),
                ("Paragraph", "C"),
                ("ImageNote", "Board"),
                ("Paragraph", "D"),
            ],
        )
        self.assertEqual(
            sum(
                block.text.count("B")
                for block in result.document.blocks
                if isinstance(block, Paragraph)
            ),
            1,
        )
        self.assertEqual(result.document.blocks[0].source_anchor, "outer")
        self.assertEqual(result.document.blocks[1].source_anchor, "quote")

    def test_nested_blockquote_is_not_duplicated_in_rich_list_fallback(self) -> None:
        result = import_html_book(
            '<html><body><ul id="items"><li id="rich">A'
            '<blockquote id="quote">B</blockquote>C'
            '<img src="board.png" alt="Board">D</li></ul></body></html>',
            source_name="nested-blockquote-list.html",
            available_assets={"board.png"},
        )

        self.assertEqual(
            _semantic_signature(result.document.blocks),
            [
                ("Paragraph", "• A"),
                ("Paragraph", "B"),
                ("Paragraph", "C"),
                ("ImageNote", "Board"),
                ("Paragraph", "D"),
            ],
        )
        self.assertEqual(
            sum(
                block.text.count("B")
                for block in result.document.blocks
                if isinstance(block, Paragraph)
            ),
            1,
        )
        self.assertFalse(any(block.kind == "List" for block in result.document.blocks))
        self.assertEqual(result.document.blocks[0].source_anchor, "items")
        self.assertEqual(result.document.blocks[1].source_anchor, "quote")

    def test_nested_blockquote_is_not_duplicated_when_table_row_splits(self) -> None:
        result = import_html_book(
            '<html><body><table><tr id="row"><td>A'
            '<blockquote id="quote">B</blockquote>C'
            '<img src="board.png" alt="Board">D</td></tr></table></body></html>',
            source_name="nested-blockquote-row.html",
            available_assets={"board.png"},
        )

        self.assertEqual(
            _semantic_signature(result.document.blocks),
            [
                ("Paragraph", "A"),
                ("Paragraph", "B"),
                ("Paragraph", "C"),
                ("ImageNote", "Board"),
                ("Paragraph", "D"),
            ],
        )
        self.assertEqual(
            sum(
                block.text.count("B")
                for block in result.document.blocks
                if isinstance(block, Paragraph)
            ),
            1,
        )
        self.assertEqual(result.document.blocks[0].source_anchor, "row")
        self.assertEqual(result.document.blocks[1].source_anchor, "quote")

    def test_nested_blockquote_is_not_duplicated_when_non_pgn_pre_splits(self) -> None:
        result = import_html_book(
            '<html><body><pre id="sample">A'
            '<blockquote id="quote">B</blockquote>C'
            '<img src="board.png" alt="Board">D</pre></body></html>',
            source_name="nested-blockquote-pre.html",
            available_assets={"board.png"},
        )

        self.assertEqual(
            _semantic_signature(result.document.blocks),
            [
                ("Paragraph", "A"),
                ("Paragraph", "B"),
                ("Paragraph", "C"),
                ("ImageNote", "Board"),
                ("Paragraph", "D"),
            ],
        )
        self.assertEqual(
            sum(
                block.text.count("B")
                for block in result.document.blocks
                if isinstance(block, Paragraph)
            ),
            1,
        )
        self.assertEqual(result.document.blocks[0].source_anchor, "sample")
        self.assertEqual(result.document.blocks[1].source_anchor, "quote")

    def test_nested_semantic_split_preserves_legacy_outer_progress_identity(self) -> None:
        baseline = import_html_book(
            '<html><body><p id="outer">A'
            '<blockquote id="quote">B</blockquote>CD</p></body></html>',
            source_name="nested-progress-baseline.html",
        )
        baseline_outer = next(
            block
            for block in baseline.document.blocks
            if isinstance(block, Paragraph) and block.source_anchor == "outer"
        )

        changed = import_html_book(
            '<html><body><p id="outer">A'
            '<blockquote id="quote">B</blockquote>C'
            '<img src="board.png" alt="Board">D</p></body></html>',
            source_name="nested-progress-changed.html",
            available_assets={"board.png"},
        )
        changed_outer = next(
            block
            for block in changed.document.blocks
            if isinstance(block, Paragraph) and block.source_anchor == "outer"
        )

        self.assertEqual(changed_outer.block_id, baseline_outer.block_id)
        self.assertEqual(changed_outer.text, "A")

    def test_rich_nested_capture_inside_paragraph_propagates_split_to_parent(self) -> None:
        result = import_html_book(
            '<html><body><p id="outer">Before'
            '<blockquote id="quote">Inner<img src="board.png" alt="Board">Tail</blockquote>'
            'After</p></body></html>',
            source_name="nested-rich-paragraph.html",
            available_assets={"board.png"},
        )

        self.assertEqual(
            _semantic_signature(result.document.blocks),
            [
                ("Paragraph", "Before"),
                ("Paragraph", "Inner"),
                ("ImageNote", "Board"),
                ("Paragraph", "Tail"),
                ("Paragraph", "After"),
            ],
        )
        self.assertEqual(
            sum(
                block.text.count("Inner") + block.text.count("Tail")
                for block in result.document.blocks
                if isinstance(block, Paragraph)
            ),
            2,
        )
        self.assertEqual(result.document.blocks[0].source_anchor, "outer")
        self.assertEqual(result.document.blocks[1].source_anchor, "quote")

    def test_rich_nested_capture_inside_list_item_propagates_split_to_parent(self) -> None:
        result = import_html_book(
            '<html><body><ul id="choices"><li id="rich">Before'
            '<blockquote id="quote">Inner<img src="board.png" alt="Board">Tail</blockquote>'
            'After</li></ul></body></html>',
            source_name="nested-rich-list-item.html",
            available_assets={"board.png"},
        )

        self.assertEqual(
            _semantic_signature(result.document.blocks),
            [
                ("Paragraph", "• Before"),
                ("Paragraph", "Inner"),
                ("ImageNote", "Board"),
                ("Paragraph", "Tail"),
                ("Paragraph", "After"),
            ],
        )
        self.assertFalse(any(block.kind == "List" for block in result.document.blocks))
        self.assertEqual(
            sum(
                block.text.count("Inner") + block.text.count("Tail")
                for block in result.document.blocks
                if isinstance(block, Paragraph)
            ),
            2,
        )
        self.assertTrue(
            any(
                "inline semantic content cannot be represented" in warning
                for warning in result.warnings
            )
        )

    def test_rich_nested_capture_inside_table_row_propagates_split_to_parent(self) -> None:
        result = import_html_book(
            '<html><body><table><tr id="row"><td>Before</td><td>'
            '<blockquote id="quote">Inner<img src="board.png" alt="Board">Tail</blockquote>'
            '</td><td>After</td></tr></table></body></html>',
            source_name="nested-rich-table-row.html",
            available_assets={"board.png"},
        )

        self.assertEqual(
            _semantic_signature(result.document.blocks),
            [
                ("Paragraph", "Before"),
                ("Paragraph", "Inner"),
                ("ImageNote", "Board"),
                ("Paragraph", "Tail"),
                ("Paragraph", "After"),
            ],
        )
        self.assertEqual(
            sum(
                block.text.count("Inner") + block.text.count("Tail")
                for block in result.document.blocks
                if isinstance(block, Paragraph)
            ),
            2,
        )
        self.assertTrue(
            any(
                "table structure is preserved as row text" in warning
                for warning in result.warnings
            )
        )

    def test_rich_nested_capture_inside_non_pgn_pre_propagates_split_to_parent(self) -> None:
        result = import_html_book(
            '<html><body><pre id="sample">Before'
            '<blockquote id="quote">Inner<img src="board.png" alt="Board">Tail</blockquote>'
            'After</pre></body></html>',
            source_name="nested-rich-pre.html",
            available_assets={"board.png"},
        )

        self.assertEqual(
            _semantic_signature(result.document.blocks),
            [
                ("Paragraph", "Before"),
                ("Paragraph", "Inner"),
                ("ImageNote", "Board"),
                ("Paragraph", "Tail"),
                ("Paragraph", "After"),
            ],
        )
        self.assertEqual(
            sum(
                block.text.count("Inner") + block.text.count("Tail")
                for block in result.document.blocks
                if isinstance(block, Paragraph)
            ),
            2,
        )

    def test_recursive_rich_nested_capture_propagates_split_through_each_parent(self) -> None:
        result = import_html_book(
            '<html><body><ul><li>Before'
            '<blockquote>Outer<blockquote>Inner'
            '<img src="board.png" alt="Board">Tail</blockquote>OuterTail</blockquote>'
            'After</li></ul></body></html>',
            source_name="recursive-nested-rich-list.html",
            available_assets={"board.png"},
        )

        self.assertEqual(
            _semantic_signature(result.document.blocks),
            [
                ("Paragraph", "• Before"),
                ("Paragraph", "Outer"),
                ("Paragraph", "Inner"),
                ("ImageNote", "Board"),
                ("Paragraph", "Tail"),
                ("Paragraph", "OuterTail"),
                ("Paragraph", "After"),
            ],
        )
        text = " ".join(
            block.text
            for block in result.document.blocks
            if isinstance(block, Paragraph)
        )
        self.assertEqual(text.count("Inner"), 1)
        self.assertEqual(text.count("OuterTail"), 1)

    def test_nested_explicit_position_remains_single_canonical_navigation_target(self) -> None:
        result = import_html_book(
            f'<html><body><ul><li>Before'
            f'<blockquote>Inner<span data-acs-fen="{Board.START}"></span>Tail</blockquote>'
            f'After</li></ul></body></html>',
            source_name="nested-position-list.html",
        )

        self.assertEqual(
            [block.kind for block in result.document.blocks],
            ["Paragraph", "Paragraph", "Position", "Paragraph", "Paragraph"],
        )
        self.assertEqual(result.document.blocks[0].text, "• Before")
        self.assertEqual(result.document.blocks[1].text, "Inner")
        self.assertEqual(result.document.blocks[3].text, "Tail")
        self.assertEqual(result.document.blocks[4].text, "After")
        positions = [
            block for block in result.document.blocks if isinstance(block, Position)
        ]
        self.assertEqual(len(positions), 1)
        self.assertEqual(Board(positions[0].fen).fen(), Board.START)

        reader = BookReader(result.document)
        location = reader.next_position()
        self.assertEqual(location.index, 2)
        self.assertEqual(Board(location.position_fen).fen(), Board.START)

    def test_unclosed_nested_rich_capture_recovers_once_in_source_order(self) -> None:
        result = import_html_book(
            '<html><body><p id="outer">Before'
            '<blockquote id="quote">Inner<img src="board.png" alt="Board">Tail',
            source_name="unclosed-nested-rich.html",
            available_assets={"board.png"},
        )

        self.assertEqual(
            _semantic_signature(result.document.blocks),
            [
                ("Paragraph", "Before"),
                ("Paragraph", "Inner"),
                ("ImageNote", "Board"),
                ("Paragraph", "Tail"),
            ],
        )
        self.assertEqual(
            sum(
                block.text.count("Inner") + block.text.count("Tail")
                for block in result.document.blocks
                if isinstance(block, Paragraph)
            ),
            2,
        )
        self.assertTrue(any("unclosed blockquote" in warning for warning in result.warnings))
        self.assertTrue(any("unclosed p" in warning for warning in result.warnings))

    def test_nested_rich_list_split_restores_legacy_list_progress_identity(self) -> None:
        baseline = import_html_book(
            '<html><body><ul id="choices"><li>Before InnerTail After</li></ul>'
            '</body></html>',
            source_name="nested-rich-list-progress-baseline.html",
        )
        baseline_reader = BookReader(baseline.document)
        baseline_index = next(
            index
            for index, block in enumerate(baseline.document.blocks)
            if block.kind == "List"
        )
        baseline_location = baseline_reader.go_to(baseline_index)

        changed = import_html_book(
            '<html><body><ul id="choices"><li>Before'
            '<blockquote>Inner<img src="board.png" alt="Board">Tail</blockquote>'
            'After</li></ul></body></html>',
            source_name="nested-rich-list-progress-changed.html",
            available_assets={"board.png"},
        )
        first = changed.document.blocks[0]
        self.assertIsInstance(first, Paragraph)
        self.assertEqual(first.text, "• Before")
        self.assertEqual(first.block_id, baseline_location.block_id)
        self.assertEqual(first.source_anchor, "choices")

        with tempfile.TemporaryDirectory() as directory:
            store = BookProgressStore(Path(directory) / "progress.json")
            store.save("nested-rich-list-progress", baseline_reader)
            restored = store.restore(
                "nested-rich-list-progress",
                changed.document,
            )

        restored_location = restored.location()
        restored_block = restored.block_snapshot(restored_location.index)
        self.assertEqual(restored_location.block_id, baseline_location.block_id)
        self.assertEqual(restored_location.source_anchor, "choices")
        self.assertIsInstance(restored_block, Paragraph)
        self.assertEqual(restored_block.text, "• Before")

    def test_decorative_heading_image_does_not_split_heading_text(self) -> None:
        baseline = import_html_book(
            '<html><body><h2 id="topic">BeforeAfter</h2></body></html>',
            source_name="heading-decorative-baseline.html",
        )
        result = import_html_book(
            '<html><body><h2 id="topic">Before<img src="decoration.png">After</h2></body></html>',
            source_name="heading-decorative.html",
            available_assets={"decoration.png"},
        )

        headings = [block for block in result.document.blocks if isinstance(block, Heading)]
        self.assertEqual(len(headings), 1)
        self.assertEqual(headings[0].text, "BeforeAfter")
        self.assertEqual(headings[0].block_id, baseline.document.blocks[0].block_id)
        self.assertEqual(headings[0].source_anchor, "topic")
        self.assertFalse(
            any(
                isinstance(block, Note) and block.note_type == "image"
                for block in result.document.blocks
            )
        )
        self.assertTrue(
            any("no accessible text" in warning for warning in result.warnings)
        )


if __name__ == "__main__":
    unittest.main()
