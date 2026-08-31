from __future__ import annotations

import tempfile
from pathlib import Path
import unittest

from acs.book_game_content import resolve_book_game
from acs.book_html_import import (
    MAX_HTML_SOURCE_BYTES,
    BookHtmlImportError,
    BookHtmlImportErrorCode,
    SUPPORTED_HTML_BOOK_CAPABILITY,
    import_html_book,
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
  <pre>{pgn}</pre>
</body>
</html>'''


class BookHtmlImportTests(unittest.TestCase):
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

    def test_capability_profile_does_not_claim_unimplemented_formats(self) -> None:
        self.assertEqual(SUPPORTED_HTML_BOOK_CAPABILITY["format"], "HTML/XHTML")
        non_claims = set(SUPPORTED_HTML_BOOK_CAPABILITY["does_not_claim"])
        self.assertTrue({"TXT", "Markdown", "DOCX", "EPUB", "PDF/OCR"}.issubset(non_claims))


if __name__ == "__main__":
    unittest.main()
