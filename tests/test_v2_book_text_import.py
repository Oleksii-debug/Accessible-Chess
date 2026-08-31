from __future__ import annotations

import tempfile
from pathlib import Path
import unittest

from acs.book_game_content import resolve_book_game
from acs.book_progress_store import BookProgressStore
from acs.book_text_import import (
    BOOK_TEXT_CAPABILITIES,
    MAX_TEXT_SOURCE_BYTES,
    BookTextFormat,
    BookTextImportError,
    BookTextImportErrorCode,
    import_text_book,
)
from acs.bookdocument import Diagram, Game, Heading, Note, Paragraph, Position
from acs.bookreader import BookReader
from acs.chesscore import Board
from acs.gametree import serialize_game


PGN = '''[Event "Text book demo"]
[Site "Uzhhorod"]
[Date "2026.08.31"]
[Round "1"]
[White "Білі"]
[Black "Black"]
[Result "*"]

1. e4 e5 2. Nf3 Nc6 $1 {Developing.} (2... Nf6 3. Nxe5) *'''


class BookTextImportTests(unittest.TestCase):
    def test_txt_preserves_unicode_paragraphs_without_guessing_chess(self) -> None:
        source = '''Шахова стратегія — Úvod\nрядок продовження.\n\nASCII board: #K ^K 8/8/8/8/8/8/8/8\n1. e4 e5 2. Nf3 Nc6\n\nОстанній абзац — posición.'''
        result = import_text_book(
            source,
            source_name="strategy.txt",
            source_format="txt",
            title="Шахова стратегія",
            author="Автор",
            language="uk",
        )
        self.assertEqual(result.source_format, BookTextFormat.TXT)
        self.assertEqual(result.document.title, "Шахова стратегія")
        self.assertEqual(result.document.author, "Автор")
        self.assertEqual(result.document.language, "uk")
        self.assertEqual(result.pgn_games, 0)
        self.assertEqual(result.positions, 0)
        self.assertEqual(len(result.document.blocks), 3)
        self.assertTrue(all(isinstance(block, Paragraph) for block in result.document.blocks))
        self.assertIn("8/8/8/8/8/8/8/8", result.document.blocks[1].text)
        self.assertFalse(any(isinstance(block, (Game, Position, Diagram)) for block in result.document.blocks))
        self.assertTrue(result.book_key.startswith("txt-sha256:"))

    def test_markdown_structure_and_explicit_chess_blocks_use_canonical_services(self) -> None:
        source = f'''# Accessible Chess Book

Intro українською — česky.

## Position

```fen
{Board.START}
Initial position
```

## Game

```pgn
{PGN}
```

![Board illustration](images/board.png)

```python
print("not chess")
```
'''
        result = import_text_book(source, source_name="book.md", source_format="markdown")
        self.assertEqual(result.document.title, "Accessible Chess Book")
        self.assertEqual(result.pgn_games, 1)
        self.assertEqual(result.positions, 1)
        headings = [block for block in result.document.blocks if isinstance(block, Heading)]
        self.assertEqual([block.level for block in headings], [1, 2, 2])
        position = next(block for block in result.document.blocks if isinstance(block, Position))
        self.assertEqual(Board(position.fen).fen(), Board.START)
        self.assertEqual(position.caption, "Initial position")
        game = next(block for block in result.document.blocks if isinstance(block, Game))
        canonical = serialize_game(resolve_book_game(game).game)
        self.assertIn("$1", canonical)
        self.assertIn("{Developing.}", canonical)
        self.assertIn("(", canonical)
        self.assertIn("Білі", canonical)
        notes = [block for block in result.document.blocks if isinstance(block, Note)]
        self.assertTrue(any(block.note_type == "image" and block.text == "Board illustration" for block in notes))
        self.assertTrue(any(block.note_type == "code:python" and "not chess" in block.text for block in notes))
        self.assertFalse(any(isinstance(block, Diagram) for block in result.document.blocks))

    def test_explicit_diagram_fen_requires_canonical_board_and_preserves_alt(self) -> None:
        source = f'''# Diagram

```diagram-fen
{Board.START}
Starting board
```
'''
        result = import_text_book(source, source_name="diagram.md", source_format="md")
        diagram = next(block for block in result.document.blocks if isinstance(block, Diagram))
        self.assertEqual(Board(diagram.fen).fen(), Board.START)
        self.assertEqual(diagram.alt_text, "Starting board")

    def test_invalid_explicit_chess_fails_closed_without_raw_payload_in_message(self) -> None:
        bad_fen = "8/8/8/8/8/8/8/8 w - - 0 1"
        with self.assertRaises(BookTextImportError) as fen_error:
            import_text_book(
                f"```fen\n{bad_fen}\n```",
                source_name="bad.md",
                source_format="markdown",
            )
        self.assertEqual(fen_error.exception.code, BookTextImportErrorCode.MALFORMED_CHESS_CONTENT)
        self.assertNotIn(bad_fen, str(fen_error.exception))

        with self.assertRaises(BookTextImportError) as pgn_error:
            import_text_book(
                "```pgn\n[Event \"Broken\"]\n\n1. e4 e5 2. Qz9 *\n```",
                source_name="bad-pgn.md",
                source_format="markdown",
            )
        self.assertEqual(pgn_error.exception.code, BookTextImportErrorCode.MALFORMED_CHESS_CONTENT)
        self.assertNotIn("Qz9", str(pgn_error.exception))

    def test_unclosed_fence_and_resource_or_encoding_errors_fail_closed(self) -> None:
        with self.assertRaises(BookTextImportError) as fence_error:
            import_text_book("# Title\n\n```pgn\n1. e4 *", source_name="open.md", source_format="md")
        self.assertEqual(fence_error.exception.code, BookTextImportErrorCode.MALFORMED_MARKDOWN)

        with self.assertRaises(BookTextImportError) as encoding_error:
            import_text_book(b"\xff\xfe\xfd", source_name="bad.txt", source_format="txt")
        self.assertEqual(encoding_error.exception.code, BookTextImportErrorCode.UNSUPPORTED_ENCODING)

        with self.assertRaises(BookTextImportError) as size_error:
            import_text_book(b"x" * (MAX_TEXT_SOURCE_BYTES + 1), source_name="huge.txt", source_format="txt")
        self.assertEqual(size_error.exception.code, BookTextImportErrorCode.RESOURCE_LIMIT)

        with self.assertRaises(BookTextImportError) as format_error:
            import_text_book("text", source_name="book.rtf", source_format="rtf")
        self.assertEqual(format_error.exception.code, BookTextImportErrorCode.UNSUPPORTED_FORMAT)

    def test_markdown_lists_quotes_are_readable_but_structure_loss_is_explicit(self) -> None:
        source = '''# Notes

- First item
- Second item

> Quoted advice
'''
        result = import_text_book(source, source_name="notes.md", source_format="markdown")
        paragraphs = [block.text for block in result.document.blocks if isinstance(block, Paragraph)]
        self.assertIn("• First item", paragraphs)
        self.assertIn("• Second item", paragraphs)
        self.assertIn("Quoted advice", paragraphs)
        self.assertTrue(any("list structure" in warning for warning in result.warnings))
        self.assertTrue(any("block quote" in warning for warning in result.warnings))

    def test_markdown_game_navigation_exact_return_and_progress_reopen(self) -> None:
        source = f'''# Book

Reading origin.

```pgn
{PGN}
```

After game.
'''
        result = import_text_book(source, source_name="journey.md", source_format="markdown")
        reader = BookReader(result.document)
        origin_index = next(
            index for index, block in enumerate(result.document.blocks)
            if isinstance(block, Paragraph) and block.text == "Reading origin."
        )
        origin = reader.go_to(origin_index)
        reader.save_return_point("before-game")
        game_location = reader.next_game()
        game = result.document.blocks[game_location.index]
        resolved = resolve_book_game(game)
        start_fen = (
            resolved.game.tags.get("FEN")
            if resolved.game.tags.get("SetUp") == "1" and resolved.game.tags.get("FEN")
            else Board.START
        )
        self.assertEqual(Board(start_fen).fen(), Board.START)
        self.assertEqual(reader.restore_return_point("before-game"), origin)

        with tempfile.TemporaryDirectory() as directory:
            store = BookProgressStore(Path(directory) / "progress.json")
            store.save(result.book_key, reader)
            fresh = import_text_book(source, source_name="journey.md", source_format="markdown")
            reopened = store.restore(result.book_key, fresh.document)
            self.assertEqual(reopened.location(), origin)
            self.assertEqual(reopened.next_game().block_id, game_location.block_id)

    def test_capability_matrix_matches_real_acceptance_boundary(self) -> None:
        self.assertEqual(BOOK_TEXT_CAPABILITIES["TXT"]["status"], "SUPPORTED")
        self.assertEqual(BOOK_TEXT_CAPABILITIES["Markdown"]["status"], "PARTIAL")
        nonclaims = set(BOOK_TEXT_CAPABILITIES["does_not_claim"])
        self.assertTrue({"HTML/XHTML", "DOCX", "EPUB", "PDF/OCR"}.issubset(nonclaims))
        self.assertIn("ASCII-diagram recognition", nonclaims)


if __name__ == "__main__":
    unittest.main()
