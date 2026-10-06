from __future__ import annotations

from io import BytesIO
import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch
import zipfile

from acs.book_epub_import import import_epub_book
from acs.book_game_content import resolve_book_game
from acs.book_html_import import (
    MAX_HTML_SOURCE_BYTES,
    BookHtmlImportError,
    BookHtmlImportErrorCode,
    SUPPORTED_HTML_BOOK_CAPABILITY,
    import_html_book,
    _SemanticHtmlParser,
)
from acs.book_progress_store import BookProgressStore
from acs.bookdocument import Diagram, Game, Heading, Note, Paragraph, Position
from acs.bookreader import BookReader
from acs.chesscore import Board
from acs.gametree import serialize_game


PGN = '''[Event "Accessible book demo"]
[Site "Kyiv"]
[Date "2026.08.31"]
[Round "1"]
[White "Білі"]
[Black "Black"]
[Result "*"]

1. e4 e5 2. Nf3 Nc6 $1 {Developing the knight.} (2... Nf6 3. Nxe5) *'''


def _html(*, fen: str | None = None, pgn: str = PGN) -> str:
    diagram = (
        f'<img id="diagram-1" src="images/board.png" alt="Позиція після дебюту" data-acs-fen="{fen}">'
        if fen is not None
        else '<img id="diagram-1" src="images/board.png" alt="Chessboard illustration">'
    )
    return f'''<!doctype html>
<html lang="uk">
<head>
  <title>Шахова книга — Chess Book</title>
  <meta name="author" content="Автор Émile">
</head>
<body>
  <h1 id="intro">Вступ — Úvod</h1>
  <p>Білі починають. Čierny відповідає. Español: posición.</p>
  <ul><li>Пункт один</li><li>Пункт два</li></ul>
  <table><tr><td>e4</td><td>e5</td></tr></table>
  {diagram}
  <h2 id="games">Анотовані партії</h2>
  <pre>{{PGN 01}}
{pgn}</pre>
</body>
</html>'''


class BookHtmlImportTests(unittest.TestCase):
    def test_warning_budget_includes_suppression_marker_without_losing_non_overflow_warnings(self) -> None:
        with patch("acs.book_html_import.MAX_HTML_WARNINGS", 3):
            exact = _SemanticHtmlParser(available_assets=None)
            for index in range(3):
                exact._warning(f"warning {index}")
            self.assertEqual(
                exact.warnings,
                ["warning 0", "warning 1", "warning 2"],
            )

            overflow = _SemanticHtmlParser(available_assets=None)
            for index in range(5):
                overflow._warning(f"warning {index}")
            self.assertEqual(
                overflow.warnings,
                [
                    "warning 0",
                    "warning 1",
                    "additional HTML import warnings were suppressed",
                ],
            )

    def test_multilingual_structure_images_and_canonical_embedded_pgn(self) -> None:
        result = import_html_book(
            _html(),
            source_name="lawful-book.html",
            available_assets={"images/board.png"},
        )

        self.assertEqual(result.document.language, "uk")
        self.assertEqual(result.document.author, "Автор Émile")
        self.assertIn("Шахова книга", result.document.title)
        self.assertEqual(result.pgn_games, 1)
        self.assertEqual(result.missing_assets, ())
        self.assertEqual(result.image_references, ("images/board.png",))
        self.assertTrue(result.book_key.startswith("html-sha256:"))

        headings = [block for block in result.document.blocks if isinstance(block, Heading)]
        paragraphs = [block for block in result.document.blocks if isinstance(block, Paragraph)]
        image_notes = [
            block for block in result.document.blocks
            if isinstance(block, Note) and block.note_type == "image"
        ]
        games = [block for block in result.document.blocks if isinstance(block, Game)]
        self.assertGreaterEqual(len(headings), 2)
        self.assertTrue(any("Čierny" in block.text and "posición" in block.text for block in paragraphs))
        self.assertEqual([block.text for block in image_notes], ["Chessboard illustration"])
        self.assertEqual(len(games), 1)
        self.assertFalse(any(isinstance(block, Diagram) for block in result.document.blocks))

        resolved = resolve_book_game(games[0])
        canonical = serialize_game(resolved.game)
        self.assertIn("$1", canonical)
        self.assertIn("{Developing the knight.}", canonical)
        self.assertIn("(", canonical)
        self.assertIn("Білі", canonical)

    def test_br_preserves_semantic_text_boundaries_for_reading_and_copy(self) -> None:
        result = import_html_book(
            """<html><head><title>Breaks</title></head><body>
<h1>White<br>to move</h1>
<p>First line<br/>Second line</p>
</body></html>""",
            source_name="breaks.html",
        )

        headings = [block.text for block in result.document.blocks if isinstance(block, Heading)]
        paragraphs = [block.text for block in result.document.blocks if isinstance(block, Paragraph)]
        self.assertEqual(headings, ["White to move"])
        self.assertEqual(paragraphs, ["First line Second line"])
        self.assertNotIn("Whiteto", "\n".join(headings))
        self.assertNotIn("lineSecond", "\n".join(paragraphs))

    def test_epub_inherits_br_semantic_text_boundaries(self) -> None:
        buffer = BytesIO()
        container = b'''<?xml version="1.0" encoding="UTF-8"?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
  <rootfiles>
    <rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/>
  </rootfiles>
</container>'''
        opf = b'''<?xml version="1.0" encoding="UTF-8"?>
<package version="3.0" unique-identifier="uid" xmlns="http://www.idpf.org/2007/opf" xmlns:dc="http://purl.org/dc/elements/1.1/">
  <metadata><dc:identifier id="uid">urn:test:br-boundary</dc:identifier><dc:title>Boundary EPUB</dc:title><dc:language>en</dc:language><meta property="dcterms:modified">2026-10-05T00:00:00Z</meta></metadata>
  <manifest><item id="c1" href="Text/chapter.xhtml" media-type="application/xhtml+xml"/><item id="nav" href="nav.xhtml" media-type="application/xhtml+xml" properties="nav"/></manifest>
  <spine><itemref idref="c1"/></spine>
</package>'''
        chapter = b"<html><body><h1>White<br>to move</h1><p>First<br/>Second</p></body></html>"
        with zipfile.ZipFile(buffer, "w") as archive:
            mimetype = zipfile.ZipInfo("mimetype")
            mimetype.compress_type = zipfile.ZIP_STORED
            archive.writestr(mimetype, b"application/epub+zip")
            archive.writestr("META-INF/container.xml", container, compress_type=zipfile.ZIP_DEFLATED)
            archive.writestr("OEBPS/content.opf", opf, compress_type=zipfile.ZIP_DEFLATED)
            archive.writestr("OEBPS/Text/chapter.xhtml", chapter, compress_type=zipfile.ZIP_DEFLATED)
            archive.writestr("OEBPS/nav.xhtml", '<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops"><body><nav epub:type="toc"><ol><li><a href="Text/chapter.xhtml">Chapter</a></li></ol></nav></body></html>', compress_type=zipfile.ZIP_DEFLATED)

        result = import_epub_book(buffer.getvalue(), source_name="breaks.epub")
        headings = [block.text for block in result.document.blocks if isinstance(block, Heading)]
        paragraphs = [block.text for block in result.document.blocks if isinstance(block, Paragraph)]
        self.assertEqual(headings, ["White to move"])
        self.assertEqual(paragraphs, ["First Second"])

    def test_table_cells_do_not_collapse_inside_row_text(self) -> None:
        result = import_html_book(
            "<html><body><table><tr><td>e4</td><td>e5</td></tr></table></body></html>",
            source_name="table-boundaries.html",
        )

        paragraphs = [block.text for block in result.document.blocks if isinstance(block, Paragraph)]
        self.assertEqual(paragraphs, ["e4 e5"])
        self.assertNotIn("e4e5", paragraphs)

    def test_nested_block_close_preserves_resumed_reading_text_boundary(self) -> None:
        result = import_html_book(
            "<html><body><p>Alpha<div>Beta</div>Gamma</p></body></html>",
            source_name="nested-boundaries.html",
        )

        paragraphs = [block.text for block in result.document.blocks if isinstance(block, Paragraph)]
        self.assertEqual(paragraphs, ["Alpha Beta Gamma"])
        self.assertNotIn("BetaGamma", paragraphs[0])

    def test_nested_semantic_capture_preserves_inner_br_in_parent_reading_text(self) -> None:
        result = import_html_book(
            "<html><body><p>Outer<blockquote>Inner<br>Line</blockquote>Tail</p></body></html>",
            source_name="nested-capture-boundaries.html",
        )

        paragraphs = [block.text for block in result.document.blocks if isinstance(block, Paragraph)]
        self.assertIn("Inner Line", paragraphs)
        self.assertIn("Outer Inner Line Tail", paragraphs)
        self.assertNotIn("InnerLine", "\n".join(paragraphs))

    def test_br_preserves_list_item_boundaries(self) -> None:
        result = import_html_book(
            "<html><body><ul><li>White<br>to move</li><li>Black<br/>to move</li></ul></body></html>",
            source_name="list-breaks.html",
        )

        lists = result.document.lists()
        self.assertEqual(len(lists), 1)
        self.assertEqual(lists[0].items, ["White to move", "Black to move"])

    def test_br_delimited_explicit_pgn_is_not_duplicated_as_reading_prose(self) -> None:
        result = import_html_book(
            """<html><body><pre>{PGN 1}<br>
[Event "BR game"]<br>[White "A"]<br>[Black "B"]<br>[Result "*"]<br><br>
1. e4 e5 *</pre></body></html>""",
            source_name="pgn-breaks.html",
        )

        games = [block for block in result.document.blocks if isinstance(block, Game)]
        paragraphs = [block for block in result.document.blocks if isinstance(block, Paragraph)]
        self.assertEqual(result.pgn_games, 1)
        self.assertEqual(len(games), 1)
        self.assertFalse(any('[Event "BR game"]' in block.text for block in paragraphs))

    def test_windows_1251_html_is_decoded_losslessly_without_ai(self) -> None:
        source = """<!doctype html>
<html lang="uk">
<head><meta charset="windows-1251"><title>Шахова книга</title></head>
<body><h1>Етюди</h1><p>Король, ферзь і пішак у навчальній позиції.</p></body>
</html>""".encode("cp1251")

        result = import_html_book(source, source_name="legacy-book.html")

        self.assertEqual(result.document.title, "Шахова книга")
        self.assertTrue(
            any(
                isinstance(block, Heading) and block.text == "Етюди"
                for block in result.document.blocks
            )
        )
        self.assertTrue(
            any("Windows-1251" in warning and "losslessly" in warning for warning in result.warnings)
        )
        self.assertEqual(result.pgn_games, 0)

    def test_unmarked_valid_pgn_is_readable_text_and_never_fabricates_game(self) -> None:
        source = f'''<!doctype html>
<html><head><title>Quoted PGN</title></head><body>
<h1>Example notation</h1>
<p>The following notation is quoted as ordinary book text.</p>
<pre>{PGN}</pre>
</body></html>'''
        result = import_html_book(source, source_name="quoted-pgn.html")

        self.assertEqual(result.pgn_games, 0)
        self.assertFalse(any(isinstance(block, Game) for block in result.document.blocks))
        paragraphs = [block for block in result.document.blocks if isinstance(block, Paragraph)]
        self.assertTrue(any('[Event "Accessible book demo"]' in block.text for block in paragraphs))
        self.assertTrue(any("1. e4 e5" in block.text for block in paragraphs))

    def test_pgn_marker_must_be_standalone_and_immediately_own_an_event_region(self) -> None:
        prose_marker = import_html_book(
            f'''<html><body><p>Reference {{PGN 01}} below.</p><pre>{PGN}</pre></body></html>''',
            source_name="prose-marker.html",
        )
        orphan_marker = import_html_book(
            f'''<html><body><p>{{PGN 01}}</p><p>Commentary first.</p><pre>{PGN}</pre></body></html>''',
            source_name="orphan-marker.html",
        )

        self.assertEqual(prose_marker.pgn_games, 0)
        self.assertEqual(orphan_marker.pgn_games, 0)
        self.assertFalse(any(isinstance(block, Game) for block in prose_marker.document.blocks))
        self.assertFalse(any(isinstance(block, Game) for block in orphan_marker.document.blocks))

    def test_explicit_html_position_uses_canonical_board_and_can_be_a_diagram(self) -> None:
        fen = Board.START
        result = import_html_book(_html(fen=fen), source_name="position-book.xhtml")
        diagrams = [block for block in result.document.blocks if isinstance(block, Diagram)]
        self.assertEqual(len(diagrams), 1)
        self.assertEqual(Board(diagrams[0].fen).fen(), Board.START)
        self.assertEqual(diagrams[0].alt_text, "Позиція після дебюту")
        self.assertFalse(any(isinstance(block, Position) and not isinstance(block, Diagram) for block in result.document.blocks))

    def test_canonical_invalid_explicit_fen_fails_before_document_publication(self) -> None:
        empty_board = "8/8/8/8/8/8/8/8 w - - 0 1"
        with self.assertRaises(BookHtmlImportError) as caught:
            import_html_book(_html(fen=empty_board), source_name="invalid-position.html")
        self.assertEqual(caught.exception.code, BookHtmlImportErrorCode.MALFORMED_CHESS_CONTENT)
        self.assertNotIn(empty_board, str(caught.exception))

    def test_duplicate_explicit_fen_marker_fails_closed_before_document_publication(self) -> None:
        cases = (
            (
                "same-value",
                f'<html><body><div data-acs-fen="{Board.START}" data-acs-fen="{Board.START}"></div></body></html>',
            ),
            (
                "invalid-first-valid-last",
                f'<html><body><div data-acs-fen="not-a-position" DATA-ACS-FEN="{Board.START}"></div></body></html>',
            ),
        )
        for label, source in cases:
            with self.subTest(label=label):
                with self.assertRaises(BookHtmlImportError) as caught:
                    import_html_book(source, source_name="duplicate-position.html")
                self.assertEqual(
                    caught.exception.code,
                    BookHtmlImportErrorCode.MALFORMED_CHESS_CONTENT,
                )
                self.assertNotIn("not-a-position", str(caught.exception))

    def test_duplicate_semantic_attributes_preserve_first_browser_value(self) -> None:
        result = import_html_book(
            '''<html lang="uk" LANG="en"><head>
<meta name="author" content="First Author" CONTENT="Second Author">
</head><body>
<img id="first-image" ID="second-image"
 src="images/first.png" SRC="images/second.png"
 alt="First accessible text" ALT="Second accessible text">
<p>Readable.</p>
</body></html>''',
            source_name="duplicate-semantic-attributes.html",
        )

        self.assertEqual(result.document.language, "uk")
        self.assertEqual(result.document.author, "First Author")
        self.assertEqual(result.image_references, ("images/first.png",))
        image_notes = [
            block
            for block in result.document.blocks
            if isinstance(block, Note) and block.note_type == "image"
        ]
        self.assertEqual(len(image_notes), 1)
        self.assertEqual(image_notes[0].text, "First accessible text")
        self.assertEqual(image_notes[0].source_anchor, "first-image")

    def test_duplicate_aria_hidden_preserves_first_accessibility_value(self) -> None:
        hidden_first = import_html_book(
            '''<html><body>
<div aria-hidden="true" ARIA-HIDDEN="false"><p>Must stay hidden.</p></div>
<p>Visible text.</p>
</body></html>''',
            source_name="duplicate-hidden-first.html",
        )
        visible_first = import_html_book(
            '''<html><body>
<div aria-hidden="false" ARIA-HIDDEN="true"><p>Must stay visible.</p></div>
</body></html>''',
            source_name="duplicate-visible-first.html",
        )

        hidden_text = [
            block.text
            for block in hidden_first.document.blocks
            if isinstance(block, Paragraph)
        ]
        visible_text = [
            block.text
            for block in visible_first.document.blocks
            if isinstance(block, Paragraph)
        ]
        self.assertNotIn("Must stay hidden.", hidden_text)
        self.assertIn("Visible text.", hidden_text)
        self.assertIn("Must stay visible.", visible_text)

    def test_duplicate_marker_inside_suppressed_content_does_not_narrow_html_recovery(self) -> None:
        result = import_html_book(
            '''<html><body>
<template><div data-acs-fen="not-a-position" data-acs-fen="also-not-a-position"></div></template>
<p class="first" class="second">Readable malformed prose remains available.</p>
</body></html>''',
            source_name="suppressed-duplicate-position.html",
        )
        self.assertTrue(
            any(
                isinstance(block, Paragraph)
                and "Readable malformed prose remains available." in block.text
                for block in result.document.blocks
            )
        )
        self.assertFalse(any(isinstance(block, Position) for block in result.document.blocks))

    def test_missing_referenced_asset_is_reported_without_fake_diagram(self) -> None:
        result = import_html_book(
            _html(),
            source_name="missing-asset.html",
            available_assets=(),
        )
        self.assertEqual(result.missing_assets, ("images/board.png",))
        self.assertTrue(any("referenced asset is unavailable" in item for item in result.warnings))
        self.assertFalse(any(isinstance(block, Diagram) for block in result.document.blocks))
        self.assertTrue(any(isinstance(block, Game) for block in result.document.blocks))

    def test_malformed_utf8_and_resource_excess_fail_closed(self) -> None:
        with self.assertRaises(BookHtmlImportError) as bad_encoding:
            import_html_book(b"\xff\xfe\xfd", source_name="bad.html")
        self.assertEqual(bad_encoding.exception.code, BookHtmlImportErrorCode.UNSUPPORTED_ENCODING)

        oversized = b"<p>" + b"x" * MAX_HTML_SOURCE_BYTES + b"</p>"
        with self.assertRaises(BookHtmlImportError) as too_large:
            import_html_book(oversized, source_name="large.html")
        self.assertEqual(too_large.exception.code, BookHtmlImportErrorCode.RESOURCE_LIMIT)

    def test_malformed_markup_recovers_readable_text_with_loss_warning(self) -> None:
        result = import_html_book(
            "<html><head><title>Broken</title></head><body><h1>Heading<p>Paragraph without closes",
            source_name="broken.html",
        )
        self.assertTrue(result.document.blocks)
        self.assertTrue(any("unclosed" in warning for warning in result.warnings))

    def test_unclosed_suppressed_markup_reports_possible_reading_text_loss(self) -> None:
        result = import_html_book(
            "<html><body><p>Visible before.</p><template><p>Suppressed tail.</p><h2>Also suppressed",
            source_name="unclosed-template.html",
        )
        paragraphs = [
            block.text
            for block in result.document.blocks
            if isinstance(block, Paragraph)
        ]
        self.assertTrue(any("Visible before." in text for text in paragraphs))
        self.assertFalse(any("Suppressed tail." in text for text in paragraphs))
        self.assertTrue(
            any(
                "suppressed content unclosed" in warning
                and "may have been omitted" in warning
                for warning in result.warnings
            )
        )

    def test_unmatched_suppressed_close_cannot_publish_explicit_chess_semantics(self) -> None:
        result = import_html_book(
            f'''<html><body><p>Before.</p><template>
</script><div data-acs-fen="{Board.START}">must stay suppressed</div>
</template><p>After.</p></body></html>''',
            source_name="unmatched-suppressed-close.html",
        )
        paragraphs = [
            block.text
            for block in result.document.blocks
            if isinstance(block, Paragraph)
        ]
        self.assertTrue(any("Before." in text for text in paragraphs))
        self.assertTrue(any("After." in text for text in paragraphs))
        self.assertFalse(any(isinstance(block, Position) for block in result.document.blocks))
        self.assertFalse(any(isinstance(block, Diagram) for block in result.document.blocks))
        self.assertTrue(
            any("mismatched suppressed elements" in warning for warning in result.warnings)
        )

    def test_mismatched_suppressed_markup_reports_possible_reading_text_loss(self) -> None:
        result = import_html_book(
            "<html><body><p>Before.</p><template><noscript>Hidden.</template>"
            "<p>Ambiguous middle.</p></noscript></template><p>After.</p></body></html>",
            source_name="mismatched-suppressed.html",
        )
        paragraphs = [
            block.text
            for block in result.document.blocks
            if isinstance(block, Paragraph)
        ]
        self.assertTrue(any("Before." in text for text in paragraphs))
        self.assertFalse(any("Ambiguous middle." in text for text in paragraphs))
        self.assertTrue(any("After." in text for text in paragraphs))
        self.assertTrue(
            any(
                "mismatched suppressed elements" in warning
                and "may have been omitted" in warning
                for warning in result.warnings
            )
        )

    def test_import_navigation_game_board_return_and_progress_reopen(self) -> None:
        source = _html()
        result = import_html_book(source, source_name="journey.html")
        reader = BookReader(result.document)
        paragraph_index = next(
            index for index, block in enumerate(result.document.blocks)
            if isinstance(block, Paragraph) and "Білі починають" in block.text
        )
        origin = reader.go_to(paragraph_index)
        reader.save_return_point("before-game")

        game_location = reader.next_game()
        game_block = result.document.blocks[game_location.index]
        self.assertIsInstance(game_block, Game)
        resolved = resolve_book_game(game_block)
        start_fen = (
            resolved.game.tags.get("FEN")
            if resolved.game.tags.get("SetUp") == "1" and resolved.game.tags.get("FEN")
            else Board.START
        )
        board = Board(start_fen)
        self.assertEqual(len(board.board), 64)
        self.assertEqual(board.fen(), Board.START)

        returned = reader.restore_return_point("before-game")
        self.assertEqual(returned, origin)

        with tempfile.TemporaryDirectory() as directory:
            store = BookProgressStore(Path(directory) / "book-progress.json")
            store.save(result.book_key, reader)
            fresh = import_html_book(source, source_name="journey.html")
            reopened = store.restore(result.book_key, fresh.document)
            self.assertEqual(reopened.location(), origin)
            reopened_game = reopened.next_game()
            self.assertEqual(reopened_game.block_id, game_location.block_id)

    def test_text_boundary_workflow_qualifies_only_against_current_apex_parent(self) -> None:
        workflow = (
            Path(__file__).resolve().parents[1]
            / ".github"
            / "workflows"
            / "book-html-br-text-integrity.yml"
        ).read_text(encoding="utf-8")

        self.assertIn(
            "      - integration/pgn-grammar-structural-integrity-apex-20261004-sol6p3",
            workflow,
        )
        self.assertNotIn(
            "      - work/full-product-teacher-education-reachability-20260911",
            workflow,
        )
        self.assertIn(
            '"refs/heads/${{ github.base_ref }}:refs/remotes/origin/${{ github.base_ref }}"',
            workflow,
        )
        self.assertIn(
            'upstream="$(git rev-parse "refs/remotes/origin/${{ github.base_ref }}")"',
            workflow,
        )

    def test_semantic_marker_workflow_uses_live_current_apex_base(self) -> None:
        workflow = (
            Path(__file__).resolve().parents[1]
            / ".github"
            / "workflows"
            / "book-html-semantic-marker-integrity.yml"
        ).read_text(encoding="utf-8")

        self.assertIn(
            'PR_BASE_REF: ${{ github.event.pull_request.base.ref }}',
            workflow,
        )
        self.assertIn('git fetch --no-tags origin "$base_ref"', workflow)
        self.assertIn(
            'git merge-base --is-ancestor "$event_base" "$live_base"',
            workflow,
        )
        self.assertIn('git merge-base --is-ancestor "$live_base" HEAD', workflow)
        self.assertIn(
            'test "$(git merge-base "$live_base" HEAD)" = "$live_base"',
            workflow,
        )
        self.assertIn('upstream="$live_base"', workflow)
        self.assertIn(
            ".github/workflows/book-html-semantic-marker-integrity.yml|"
            ".github/workflows/book-html-br-text-integrity.yml|"
            "acs/book_html_import.py|tests/test_v2_book_html_import.py",
            workflow,
        )
        self.assertNotIn("w6-v2-package-assembler.yml", workflow)

    def test_capability_profile_does_not_claim_unimplemented_or_implicit_semantics(self) -> None:
        self.assertEqual(SUPPORTED_HTML_BOOK_CAPABILITY["format"], "HTML/XHTML")
        self.assertIn(
            "Game(explicit {PGN N} marker)",
            SUPPORTED_HTML_BOOK_CAPABILITY["semantic_blocks"],
        )
        non_claims = set(SUPPORTED_HTML_BOOK_CAPABILITY["does_not_claim"])
        self.assertTrue({"TXT", "Markdown", "DOCX", "EPUB", "PDF/OCR"}.issubset(non_claims))
        self.assertIn("implicit PGN inference from ordinary text", non_claims)
        self.assertIn("Windows-1251", SUPPORTED_HTML_BOOK_CAPABILITY["encoding"])


    def test_hidden_html_title_marker_cannot_own_unmarked_body_pgn(self) -> None:
        source = f"""<html><head><title>{{PGN 1}}</title>
<meta name="author" content="Автор Émile"></head>
<body><h1>Visible study</h1><pre>{PGN}</pre></body></html>"""
        result = import_html_book(source, source_name="metadata-marker.html")
        self.assertEqual(result.document.title, "{PGN 1}")
        self.assertEqual(result.document.author, "Автор Émile")
        self.assertEqual(result.pgn_games, 0)
        self.assertFalse(any(isinstance(block, Game) for block in result.document.blocks))
        self.assertTrue(
            any(
                isinstance(block, Paragraph) and '[Event "Accessible book demo"]' in block.text
                for block in result.document.blocks
            )
        )

    def test_non_rendered_head_text_cannot_create_pgn_game_or_chess_position(self) -> None:
        source = f"""<html lang="uk"><head>{{PGN 2}}
<img id="hidden-diagram" src="images/hidden.png" alt="Not rendered" data-acs-fen="{Board.START}">
<div data-acs-fen="{Board.START}">Hidden metadata position</div>
<title>Readable book title</title>
</head><body><h1>Visible chapter</h1><pre>{PGN}</pre></body></html>"""
        result = import_html_book(source, source_name="head-chess-markers.html")
        self.assertEqual(result.document.title, "Readable book title")
        self.assertEqual(result.document.language, "uk")
        self.assertEqual(result.pgn_games, 0)
        self.assertEqual(result.image_references, ())
        self.assertFalse(
            any(isinstance(block, (Game, Diagram, Position, Note)) for block in result.document.blocks)
        )
        self.assertTrue(
            any(isinstance(block, Heading) and block.text == "Visible chapter"
                for block in result.document.blocks)
        )

    def test_visible_body_marker_still_publishes_one_canonical_pgn_game(self) -> None:
        source = f"""<html><head><title>{{PGN 9}}</title></head>
<body><h1>Game</h1><pre>{{PGN 1}}
{PGN}</pre></body></html>"""
        result = import_html_book(source, source_name="visible-body-marker.html")
        self.assertEqual(result.document.title, "{PGN 9}")
        self.assertEqual(result.pgn_games, 1)
        self.assertEqual(sum(isinstance(block, Game) for block in result.document.blocks), 1)
        self.assertFalse(
            any(
                isinstance(block, Paragraph) and '[Event "Accessible book demo"]' in block.text
                for block in result.document.blocks
            )
        )

    def test_inline_display_none_cannot_publish_reading_or_chess_semantics(self) -> None:
        source = f"""<html><body>
<h1>Visible before</h1>
<section style=" color: red ; DISPLAY : none ">
  <p>Style-hidden reading text</p>
  <div data-acs-fen="{Board.START}">Hidden position</div>
  <img src="images/hidden.png" alt="Hidden image" data-acs-fen="{Board.START}">
  <pre>{{PGN 1}}
{PGN}</pre>
</section>
<p>Visible after</p>
</body></html>"""
        result = import_html_book(
            source,
            source_name="style-display-none.html",
            available_assets={"images/hidden.png"},
        )

        self.assertEqual(result.pgn_games, 0)
        self.assertEqual(result.image_references, ())
        self.assertFalse(
            any(
                isinstance(block, (Game, Diagram, Position, Note))
                for block in result.document.blocks
            )
        )
        rendered = "\n".join(
            getattr(block, "text", "")
            for block in result.document.blocks
        )
        self.assertIn("Visible before", rendered)
        self.assertIn("Visible after", rendered)
        self.assertNotIn("Style-hidden reading text", rendered)
        self.assertNotIn('[Event "Accessible book demo"]', rendered)

    def test_inline_display_cascade_uses_last_declaration_and_important_precedence(self) -> None:
        visible_sources = (
            f"""<html><body>
<div style="display:none; DISPLAY:block">
  <p>Visible by later declaration</p>
  <div data-acs-fen="{Board.START}">Visible position</div>
</div>
</body></html>""",
            f"""<html><body>
<div style="display: block ! IMPORTANT; display:none">
  <p>Visible by important declaration</p>
  <div data-acs-fen="{Board.START}">Visible position</div>
</div>
</body></html>""",
        )
        for index, source in enumerate(visible_sources):
            with self.subTest(index=index):
                result = import_html_book(
                    source,
                    source_name=f"style-visible-{index}.html",
                )
                self.assertTrue(
                    any(isinstance(block, Paragraph) for block in result.document.blocks)
                )
                positions = [
                    block
                    for block in result.document.blocks
                    if isinstance(block, Position)
                ]
                self.assertEqual(len(positions), 1)
                self.assertEqual(positions[0].fen, Board.START)

        hidden = import_html_book(
            f"""<html><body>
<div style="display:none!important; display:block">
  <div data-acs-fen="{Board.START}">Must remain hidden</div>
</div>
<p>Visible tail</p>
</body></html>""",
            source_name="style-important-hidden.html",
        )
        self.assertFalse(any(isinstance(block, Position) for block in hidden.document.blocks))
        self.assertTrue(
            any(
                isinstance(block, Paragraph) and block.text == "Visible tail"
                for block in hidden.document.blocks
            )
        )

    def test_invalid_display_value_cannot_override_valid_hidden_declaration(self) -> None:
        hidden_sources = (
            f"""<html><body>
<section style="display:none; display:bogus">
  <div data-acs-fen="{Board.START}">Hidden invalid override</div>
</section>
<p>Visible tail one</p>
</body></html>""",
            f"""<html><body>
<section style='display:none; display:"block"'>
  <pre>{{PGN 1}}
{PGN}</pre>
</section>
<p>Visible tail two</p>
</body></html>""",
            f"""<html><body>
<section style="display:none !important; display:bogus !important">
  <img src="images/hidden.png" alt="Hidden invalid important override" data-acs-fen="{Board.START}">
</section>
<p>Visible tail three</p>
</body></html>""",
        )
        for index, source in enumerate(hidden_sources):
            with self.subTest(index=index):
                result = import_html_book(
                    source,
                    source_name=f"style-invalid-display-override-{index}.html",
                    available_assets={"images/hidden.png"},
                )
                self.assertEqual(result.pgn_games, 0)
                self.assertEqual(result.image_references, ())
                self.assertFalse(
                    any(
                        isinstance(block, (Game, Diagram, Position, Note))
                        for block in result.document.blocks
                    )
                )
                rendered = "\n".join(
                    getattr(block, "text", "")
                    for block in result.document.blocks
                )
                self.assertIn(
                    f"Visible tail {('one', 'two', 'three')[index]}",
                    rendered,
                )
                self.assertNotIn("Hidden", rendered)

    def test_known_valid_display_values_can_override_prior_none(self) -> None:
        for index, display_value in enumerate(
            (
                "block",
                "inline",
                "flex",
                "grid",
                "inline-block",
                "block flow-root",
                "inline flex",
                "block flow list-item",
            )
        ):
            with self.subTest(display_value=display_value):
                result = import_html_book(
                    f"""<html><body>
<section style="display:none; display:{display_value}">
  <div data-acs-fen="{Board.START}">Visible valid override</div>
</section>
</body></html>""",
                    source_name=f"style-valid-display-override-{index}.html",
                )
                positions = [
                    block
                    for block in result.document.blocks
                    if isinstance(block, Position)
                ]
                self.assertEqual(len(positions), 1)
                self.assertEqual(positions[0].fen, Board.START)

    def test_inline_display_comments_cannot_smuggle_hidden_semantics(self) -> None:
        hidden_sources = (
            f'''<html><body>
<section style="display/* comment */:none">
  <p>Comment-hidden text</p>
  <div data-acs-fen="{Board.START}">Hidden position</div>
</section>
<p>Visible tail one</p>
</body></html>''',
            f'''<html><body>
<section style="display:/* ; display:block */none">
  <pre>{{PGN 1}}
{PGN}</pre>
</section>
<p>Visible tail two</p>
</body></html>''',
            f'''<html><body>
<section style="display:none/* ; display:block */">
  <img src="images/hidden.png" alt="Hidden image" data-acs-fen="{Board.START}">
</section>
<p>Visible tail three</p>
</body></html>''',
        )
        for index, source in enumerate(hidden_sources):
            with self.subTest(index=index):
                result = import_html_book(
                    source,
                    source_name=f"style-comment-hidden-{index}.html",
                    available_assets={"images/hidden.png"},
                )
                self.assertEqual(result.pgn_games, 0)
                self.assertEqual(result.image_references, ())
                self.assertFalse(
                    any(
                        isinstance(block, (Game, Diagram, Position, Note))
                        for block in result.document.blocks
                    )
                )
                rendered = "\n".join(
                    getattr(block, "text", "")
                    for block in result.document.blocks
                )
                self.assertIn(f"Visible tail {('one', 'two', 'three')[index]}", rendered)
                self.assertNotIn("Comment-hidden text", rendered)

    def test_inline_display_comments_preserve_cascade_and_token_boundaries(self) -> None:
        visible_sources = (
            f'''<html><body>
<section style="display:none/* comment */; display:block">
  <p>Later visible declaration</p>
  <div data-acs-fen="{Board.START}">Visible position</div>
</section>
</body></html>''',
            f'''<html><body>
<section style="display:block !important; /* ; */ display:none">
  <p>Important visible declaration</p>
  <div data-acs-fen="{Board.START}">Visible position</div>
</section>
</body></html>''',
            f'''<html><body>
<section style="dis/* separator */play:none">
  <p>Split property name remains visible</p>
  <div data-acs-fen="{Board.START}">Visible position</div>
</section>
</body></html>''',
            f'''<html><body>
<section style="display:n/* separator */one">
  <p>Split property value remains visible</p>
  <div data-acs-fen="{Board.START}">Visible position</div>
</section>
</body></html>''',
        )
        for index, source in enumerate(visible_sources):
            with self.subTest(index=index):
                result = import_html_book(
                    source,
                    source_name=f"style-comment-visible-{index}.html",
                )
                positions = [
                    block
                    for block in result.document.blocks
                    if isinstance(block, Position)
                ]
                self.assertEqual(len(positions), 1)
                self.assertEqual(positions[0].fen, Board.START)
                self.assertTrue(
                    any(isinstance(block, Paragraph) for block in result.document.blocks)
                )

    def test_comment_markers_inside_css_strings_do_not_consume_later_display_none(self) -> None:
        hidden_sources = (
            f'''<html><body>
<section style='font-family:"/*"; display:none'>
  <div data-acs-fen="{Board.START}">Hidden quoted marker</div>
</section>
<p>Visible tail one</p>
</body></html>''',
            f'''<html><body>
<section style="font-family:'/*'; display:none">
  <div data-acs-fen="{Board.START}">Hidden single-quoted marker</div>
</section>
<p>Visible tail two</p>
</body></html>''',
            f'''<html><body>
<section style='--token:\\/\\*; display:none'>
  <div data-acs-fen="{Board.START}">Hidden escaped marker</div>
</section>
<p>Visible tail three</p>
</body></html>''',
        )
        for index, source in enumerate(hidden_sources):
            with self.subTest(index=index):
                result = import_html_book(
                    source,
                    source_name=f"style-string-comment-marker-{index}.html",
                )
                self.assertFalse(
                    any(isinstance(block, Position) for block in result.document.blocks)
                )
                rendered = "\n".join(
                    getattr(block, "text", "")
                    for block in result.document.blocks
                )
                self.assertIn(
                    f"Visible tail {('one', 'two', 'three')[index]}",
                    rendered,
                )
                self.assertNotIn("Hidden", rendered)

    def test_inline_style_semicolons_inside_strings_or_escapes_are_not_declarations(self) -> None:
        visible_sources = (
            f'''<html><body>
<section style='--label:"x; display:none; y"; display:block'>
  <div data-acs-fen="{Board.START}">Visible quoted semicolon</div>
</section>
</body></html>''',
            f'''<html><body>
<section style='--label:x\\;display:none; display:block'>
  <div data-acs-fen="{Board.START}">Visible escaped semicolon</div>
</section>
</body></html>''',
        )
        for index, source in enumerate(visible_sources):
            with self.subTest(index=index):
                result = import_html_book(
                    source,
                    source_name=f"style-semicolon-data-{index}.html",
                )
                positions = [
                    block for block in result.document.blocks
                    if isinstance(block, Position)
                ]
                self.assertEqual(len(positions), 1)
                self.assertEqual(positions[0].fen, Board.START)

        hidden = import_html_book(
            f'''<html><body>
<section style='--label:"x; display:block; y"; display:none'>
  <div data-acs-fen="{Board.START}">Hidden after quoted semicolon</div>
</section>
<p>Visible tail</p>
</body></html>''',
            source_name="style-real-display-after-quoted-semicolon.html",
        )
        self.assertFalse(
            any(isinstance(block, Position) for block in hidden.document.blocks)
        )
        self.assertTrue(
            any(
                isinstance(block, Paragraph) and block.text == "Visible tail"
                for block in hidden.document.blocks
            )
        )

    def test_inline_display_css_escapes_match_browser_hidden_semantics(self) -> None:
        hidden_sources = (
            f"""<html><body>
<section style="d\\69 splay:none">
  <div data-acs-fen="{Board.START}">Hidden escaped property</div>
</section>
<p>Visible tail property</p>
</body></html>""",
            f"""<html><body>
<section style="display:n\\6f ne">
  <div data-acs-fen="{Board.START}">Hidden escaped value</div>
</section>
<p>Visible tail value</p>
</body></html>""",
            f"""<html><body>
<section style="display:none !\\69 mportant; display:block">
  <div data-acs-fen="{Board.START}">Hidden escaped important</div>
</section>
<p>Visible tail important</p>
</body></html>""",
        )
        for index, source in enumerate(hidden_sources):
            with self.subTest(index=index):
                result = import_html_book(
                    source,
                    source_name=f"style-css-escape-hidden-{index}.html",
                )
                self.assertFalse(
                    any(isinstance(block, Position) for block in result.document.blocks)
                )

        visible = import_html_book(
            f"""<html><body>
<section style="display:block !\\69 mportant; display:none">
  <div data-acs-fen="{Board.START}">Visible escaped important</div>
</section>
</body></html>""",
            source_name="style-css-escape-visible-important.html",
        )
        positions = [
            block for block in visible.document.blocks if isinstance(block, Position)
        ]
        self.assertEqual(len(positions), 1)
        self.assertEqual(positions[0].fen, Board.START)

    def test_css_token_matching_does_not_unicode_fold_visible_content_away(self) -> None:
        visible_sources = (
            f"""<html><body>
<section style="diſplay:none">
  <div data-acs-fen="{Board.START}">Visible long-s property</div>
</section>
</body></html>""",
            f"""<html><body>
<section style="display:noNE ">
  <div data-acs-fen="{Board.START}">Visible NBSP value</div>
</section>
</body></html>""",
            f"""<html><body>
<section style="display :none">
  <div data-acs-fen="{Board.START}">Visible NBSP property</div>
</section>
</body></html>""",
            f"""<html><body>
<section style="display:block !important; display:none !İmportant">
  <div data-acs-fen="{Board.START}">Visible non-ASCII important</div>
</section>
</body></html>""",
        )
        for index, source in enumerate(visible_sources):
            with self.subTest(index=index):
                result = import_html_book(
                    source,
                    source_name=f"style-css-unicode-token-{index}.html",
                )
                positions = [
                    block for block in result.document.blocks
                    if isinstance(block, Position)
                ]
                self.assertEqual(len(positions), 1)
                self.assertEqual(positions[0].fen, Board.START)

        hidden = import_html_book(
            f"""<html><body>
<section style="DISPLAY:NoNe ! IMPORTANT">
  <div data-acs-fen="{Board.START}">ASCII case-insensitive hidden</div>
</section>
<p>Visible tail</p>
</body></html>""",
            source_name="style-css-ascii-case-insensitive.html",
        )
        self.assertFalse(
            any(isinstance(block, Position) for block in hidden.document.blocks)
        )
        self.assertTrue(
            any(
                isinstance(block, Paragraph) and block.text == "Visible tail"
                for block in hidden.document.blocks
            )
        )

    def test_css_comments_after_hex_escapes_cannot_join_display_tokens(self) -> None:
        visible_sources = (
            f"""<html><body>
<section style="d\\69/**/splay:none">
  <div data-acs-fen="{Board.START}">Visible split property escape</div>
</section>
</body></html>""",
            f"""<html><body>
<section style="display:n\\6f/**/ne">
  <div data-acs-fen="{Board.START}">Visible split value escape</div>
</section>
</body></html>""",
            f"""<html><body>
<section style="display:none !\\69/**/mportant; display:block">
  <div data-acs-fen="{Board.START}">Visible split important escape</div>
</section>
</body></html>""",
        )
        for index, source in enumerate(visible_sources):
            with self.subTest(index=index):
                result = import_html_book(
                    source,
                    source_name=f"style-comment-after-hex-escape-{index}.html",
                )
                positions = [
                    block
                    for block in result.document.blocks
                    if isinstance(block, Position)
                ]
                self.assertEqual(len(positions), 1)
                self.assertEqual(positions[0].fen, Board.START)

    def test_invalid_css_identifier_escapes_do_not_invent_display_none(self) -> None:
        visible_sources = (
            f"""<html><body>
<section style="display:n\\
one; display:block">
  <div data-acs-fen="{Board.START}">Visible newline escape</div>
</section>
</body></html>""",
            f"""<html><body>
<section style="display:n\\6f\u00a0ne; display:block">
  <div data-acs-fen="{Board.START}">Visible non-CSS whitespace</div>
</section>
</body></html>""",
        )
        for index, source in enumerate(visible_sources):
            with self.subTest(index=index):
                result = import_html_book(
                    source,
                    source_name=f"style-invalid-css-escape-{index}.html",
                )
                positions = [
                    block for block in result.document.blocks
                    if isinstance(block, Position)
                ]
                self.assertEqual(len(positions), 1)
                self.assertEqual(positions[0].fen, Board.START)

    def test_nested_css_component_semicolons_cannot_forge_display_declarations(self) -> None:
        hidden = import_html_book(
            f"""<html><body>
<section style="--token:url(data:text/plain;x; display:block !important); display:none">
  <div data-acs-fen="{Board.START}">Hidden despite fake nested block</div>
</section>
<p>Visible tail</p>
</body></html>""",
            source_name="style-nested-fake-block.html",
        )
        self.assertFalse(
            any(isinstance(block, Position) for block in hidden.document.blocks)
        )
        self.assertTrue(
            any(
                isinstance(block, Paragraph) and block.text == "Visible tail"
                for block in hidden.document.blocks
            )
        )

        visible = import_html_book(
            f"""<html><body>
<section style="--token:fn(x; display:none !important); display:block">
  <div data-acs-fen="{Board.START}">Visible despite fake nested none</div>
</section>
</body></html>""",
            source_name="style-nested-fake-none.html",
        )
        positions = [
            block for block in visible.document.blocks
            if isinstance(block, Position)
        ]
        self.assertEqual(len(positions), 1)
        self.assertEqual(positions[0].fen, Board.START)

    def test_unterminated_inline_style_comment_consumes_remainder_without_leak(self) -> None:
        hidden = import_html_book(
            f'''<html><body>
<section style="display:none/* unclosed">
  <div data-acs-fen="{Board.START}">Hidden position</div>
</section>
<p>Visible tail</p>
</body></html>''',
            source_name="style-comment-unclosed-hidden.html",
        )
        self.assertFalse(any(isinstance(block, Position) for block in hidden.document.blocks))
        self.assertTrue(
            any(
                isinstance(block, Paragraph) and block.text == "Visible tail"
                for block in hidden.document.blocks
            )
        )

    def test_inline_visibility_can_be_overridden_by_visible_descendant(self) -> None:
        source = f"""<html><body>
<section style="visibility:hidden">
  <p style="visibility:visible">Visible descendant text</p>
  <div style="visibility:visible" data-acs-fen="{Board.START}">Visible position</div>
</section>
</body></html>"""
        result = import_html_book(
            source,
            source_name="style-visibility-descendant-override.html",
        )

        self.assertTrue(
            any(
                isinstance(block, Paragraph)
                and block.text == "Visible descendant text"
                for block in result.document.blocks
            )
        )
        positions = [
            block
            for block in result.document.blocks
            if isinstance(block, Position)
        ]
        self.assertEqual(len(positions), 1)
        self.assertEqual(positions[0].fen, Board.START)

    def test_inline_style_hidden_void_element_does_not_hide_following_content(self) -> None:
        source = f"""<html><body>
<img style="display:none" src="images/hidden.png" alt="Hidden image" data-acs-fen="{Board.START}">
<p>Visible after style-hidden image</p>
</body></html>"""
        result = import_html_book(
            source,
            source_name="style-hidden-void.html",
            available_assets={"images/hidden.png"},
        )

        self.assertEqual(result.image_references, ())
        self.assertFalse(
            any(isinstance(block, (Diagram, Position, Note)) for block in result.document.blocks)
        )
        self.assertTrue(
            any(
                isinstance(block, Paragraph)
                and block.text == "Visible after style-hidden image"
                for block in result.document.blocks
            )
        )

    def test_hidden_subtree_cannot_publish_reading_or_chess_semantics(self) -> None:
        source = f"""<html><body>
<h1>Visible before</h1>
<section hidden>
  <p>Secret reading text</p>
  <div data-acs-fen="{Board.START}">Hidden position</div>
  <img src="images/hidden.png" alt="Hidden image" data-acs-fen="{Board.START}">
  <pre>{{PGN 1}}
{PGN}</pre>
</section>
<p>Visible after</p>
</body></html>"""
        result = import_html_book(
            source,
            source_name="hidden-semantics.html",
            available_assets={"images/hidden.png"},
        )

        self.assertEqual(result.pgn_games, 0)
        self.assertEqual(result.image_references, ())
        self.assertFalse(
            any(
                isinstance(block, (Game, Diagram, Position, Note))
                for block in result.document.blocks
            )
        )
        rendered = "\n".join(
            getattr(block, "text", "")
            for block in result.document.blocks
        )
        self.assertIn("Visible before", rendered)
        self.assertIn("Visible after", rendered)
        self.assertNotIn("Secret reading text", rendered)
        self.assertNotIn('[Event "Accessible book demo"]', rendered)

    def test_hidden_until_found_is_still_non_rendered_at_import_time(self) -> None:
        source = f"""<html><body>
<div hidden="until-found">
  <div data-acs-fen="{Board.START}">Deferred hidden position</div>
  <pre>{{PGN 1}}
{PGN}</pre>
</div>
<h1>Visible chapter</h1>
</body></html>"""
        result = import_html_book(source, source_name="hidden-until-found.html")

        self.assertEqual(result.pgn_games, 0)
        self.assertFalse(
            any(isinstance(block, (Game, Diagram, Position)) for block in result.document.blocks)
        )
        self.assertTrue(
            any(
                isinstance(block, Heading)
                and block.text == "Visible chapter"
                for block in result.document.blocks
            )
        )

    def test_aria_hidden_true_cannot_publish_accessible_or_chess_semantics(self) -> None:
        source = f"""<html><body>
<section aria-hidden="TRUE">
  <p>Screen-reader-hidden text</p>
  <div data-acs-fen="{Board.START}">Hidden position</div>
  <pre>{{PGN 1}}
{PGN}</pre>
</section>
<p>Accessible text</p>
</body></html>"""
        result = import_html_book(source, source_name="aria-hidden.html")

        self.assertEqual(result.pgn_games, 0)
        self.assertFalse(
            any(
                isinstance(block, (Game, Diagram, Position, Note))
                for block in result.document.blocks
            )
        )
        rendered = "\n".join(
            getattr(block, "text", "")
            for block in result.document.blocks
        )
        self.assertIn("Accessible text", rendered)
        self.assertNotIn("Screen-reader-hidden text", rendered)

    def test_aria_hidden_false_remains_semantically_available(self) -> None:
        source = f"""<html><body>
<p aria-hidden="false">Readable text</p>
<div aria-hidden="false" data-acs-fen="{Board.START}">Visible position</div>
</body></html>"""
        result = import_html_book(source, source_name="aria-visible.html")

        self.assertTrue(
            any(
                isinstance(block, Paragraph)
                and block.text == "Readable text"
                for block in result.document.blocks
            )
        )
        positions = [
            block
            for block in result.document.blocks
            if isinstance(block, Position)
        ]
        self.assertEqual(len(positions), 1)
        self.assertEqual(positions[0].fen, Board.START)

    def test_hidden_void_element_does_not_hide_following_visible_content(self) -> None:
        source = f"""<html><body>
<img hidden src="images/hidden.png" alt="Hidden image" data-acs-fen="{Board.START}">
<p>Visible after hidden image</p>
</body></html>"""
        result = import_html_book(
            source,
            source_name="hidden-void.html",
            available_assets={"images/hidden.png"},
        )

        self.assertEqual(result.image_references, ())
        self.assertFalse(
            any(isinstance(block, (Diagram, Position, Note)) for block in result.document.blocks)
        )
        self.assertTrue(
            any(
                isinstance(block, Paragraph)
                and block.text == "Visible after hidden image"
                for block in result.document.blocks
            )
        )

    def test_hidden_self_closing_void_elements_do_not_fake_nesting_mismatches(self) -> None:
        source = """<html><body>
<section hidden>
  <area/><base/><col/><embed/><param/><source/><track/><wbr/>
  <p>Hidden text</p>
</section>
<p>Visible tail</p>
</body></html>"""
        result = import_html_book(source, source_name="hidden-void-startend.html")

        rendered = "\n".join(
            getattr(block, "text", "")
            for block in result.document.blocks
        )
        self.assertIn("Visible tail", rendered)
        self.assertNotIn("Hidden text", rendered)
        self.assertFalse(
            any("mismatched hidden elements" in warning for warning in result.warnings)
        )
        self.assertFalse(
            any("hidden content unclosed" in warning for warning in result.warnings)
        )

    def test_malformed_hidden_nesting_fails_closed_without_resuming_early(self) -> None:
        source = """<html><body>
<p>Visible before</p>
<div hidden><span>Secret text</div>
<p>Must stay omitted after mismatch</p>
</body></html>"""
        result = import_html_book(source, source_name="hidden-mismatch.html")

        rendered = "\n".join(
            getattr(block, "text", "")
            for block in result.document.blocks
        )
        self.assertIn("Visible before", rendered)
        self.assertNotIn("Secret text", rendered)
        self.assertNotIn("Must stay omitted", rendered)
        self.assertTrue(
            any("mismatched hidden elements" in warning for warning in result.warnings)
        )
        self.assertTrue(
            any("hidden content unclosed" in warning for warning in result.warnings)
        )

    def test_explicit_body_closes_omitted_head_and_restores_readable_content(self) -> None:
        result = import_html_book(
            f'''<html><head><title>Recovered Book</title>
<meta name="author" content="Recovered Author">
<body>
<p>Readable body text.</p>
<div data-acs-fen="{Board.START}"></div>
</body></html>''',
            source_name="body-closes-head.html",
        )

        self.assertEqual(result.document.title, "Recovered Book")
        self.assertEqual(result.document.author, "Recovered Author")
        self.assertTrue(
            any(
                isinstance(block, Paragraph)
                and block.text == "Readable body text."
                for block in result.document.blocks
            )
        )
        self.assertTrue(
            any(
                isinstance(block, Position)
                and Board(block.fen).fen() == Board.START
                for block in result.document.blocks
            )
        )
        self.assertTrue(
            any(
                "implicitly closed by body start" in warning
                for warning in result.warnings
            )
        )

    def test_unclosed_head_cannot_recover_hidden_markers_as_readable_games(self) -> None:
        source = f"""<html><head><title>{{PGN 1}}</title><div data-acs-fen="{Board.START}">
<pre>{PGN}</pre>"""
        with self.assertRaises(BookHtmlImportError) as caught:
            import_html_book(source, source_name="unclosed-head.html")
        self.assertEqual(caught.exception.code, BookHtmlImportErrorCode.NO_READABLE_CONTENT)


if __name__ == "__main__":
    unittest.main()
