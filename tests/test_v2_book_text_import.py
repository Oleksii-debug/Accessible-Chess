from __future__ import annotations

from hashlib import sha256
import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch

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
from acs.bookdocument import Diagram, Game, Heading, ListBlock, Note, Paragraph, Position
from acs.bookreader import BOOK_READER_SNAPSHOT_SCHEMA_VERSION, BookReader
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

    def test_markdown_heading_preserves_literal_trailing_hash_text(self) -> None:
        source = """# C#

## Mate in 3#

### Closing marker ###

#### Hash payload ##not-a-close
"""
        result = import_text_book(
            source,
            source_name="heading-hashes.md",
            source_format="markdown",
        )
        headings = [
            block.text
            for block in result.document.blocks
            if isinstance(block, Heading)
        ]
        self.assertEqual(
            headings,
            ["C#", "Mate in 3#", "Closing marker", "Hash payload ##not-a-close"],
        )
        self.assertEqual(result.document.title, "C#")

    def test_markdown_inline_images_preserve_source_reading_order(self) -> None:
        source = """# Images

Before ![Board](board.png) middle ![Arrow](arrow.png) after.
"""
        result = import_text_book(
            source,
            source_name="inline-images.md",
            source_format="markdown",
        )
        semantic = []
        for block in result.document.blocks:
            if isinstance(block, Note) and block.note_type == "image":
                semantic.append(("image", block.text))
            elif isinstance(block, Paragraph):
                semantic.append(("paragraph", block.text))
            elif isinstance(block, Heading):
                semantic.append(("heading", block.text))
            else:
                semantic.append((type(block).__name__, None))
        self.assertEqual(
            semantic,
            [
                ("heading", "Images"),
                ("paragraph", "Before"),
                ("image", "Board"),
                ("paragraph", "middle"),
                ("image", "Arrow"),
                ("paragraph", "after."),
            ],
        )

    def test_markdown_inline_image_order_progress_reopens_same_semantic_block(self) -> None:
        source = """# Images

Before ![Board](board.png) after.
"""
        first = import_text_book(
            source,
            source_name="inline-progress.md",
            source_format="markdown",
        )
        reader = BookReader(first.document)
        target_index = next(
            index
            for index, block in enumerate(first.document.blocks)
            if isinstance(block, Paragraph) and block.text == "after."
        )
        target = reader.go_to(target_index)

        with tempfile.TemporaryDirectory() as directory:
            store = BookProgressStore(Path(directory) / "progress.json")
            store.save(first.book_key, reader)
            reopened = import_text_book(
                source,
                source_name="inline-progress.md",
                source_format="markdown",
            )
            restored = store.restore(first.book_key, reopened.document)

        self.assertEqual(restored.location(), target)
        self.assertEqual(reopened.document.blocks[target_index].text, "after.")

    def test_markdown_repairs_restore_legacy_progress_targets(self) -> None:
        source = """# C#

Before ![Board](board.png) after.
"""
        result = import_text_book(
            source,
            source_name="legacy-targets.md",
            source_format="markdown",
        )

        def legacy_id(kind: str, payload: str) -> str:
            digest = sha256((kind + "\0" + payload).encode("utf-8")).hexdigest()[:20]
            return f"markdown-{digest}-1"

        legacy_heading = legacy_id("Heading", "1\0C")
        legacy_paragraph = legacy_id("Paragraph", "Before  after.")
        snapshot = {
            "schema_version": BOOK_READER_SNAPSHOT_SCHEMA_VERSION,
            "current_target": f"block:{legacy_paragraph}",
            "return_points": {"heading": f"block:{legacy_heading}"},
            "fallback_digests": {},
        }

        restored = BookReader.restore_snapshot(result.document, snapshot)
        current = restored.location()
        self.assertEqual(result.document.blocks[current.index].text, "Before")
        heading = restored.restore_return_point("heading")
        self.assertEqual(result.document.blocks[heading.index].text, "C#")

    def test_markdown_legacy_progress_occurrence_stays_stable_for_duplicate_lines(self) -> None:
        source = """# Images

Before ![Board](board.png) after.

Before ![Board](board.png) after.
"""
        result = import_text_book(
            source,
            source_name="duplicate-legacy-targets.md",
            source_format="markdown",
        )
        legacy_text = "Before  after."
        digest = sha256(("Paragraph\0" + legacy_text).encode("utf-8")).hexdigest()[:20]
        snapshot = {
            "schema_version": BOOK_READER_SNAPSHOT_SCHEMA_VERSION,
            "current_target": f"block:markdown-{digest}-2",
            "return_points": {},
            "fallback_digests": {},
        }

        restored = BookReader.restore_snapshot(result.document, snapshot)
        current = restored.location()
        matching = [
            index
            for index, block in enumerate(result.document.blocks)
            if isinstance(block, Paragraph) and block.text == "Before"
        ]
        self.assertEqual(len(matching), 2)
        self.assertEqual(current.index, matching[1])

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

    def test_markdown_chess_fence_requires_unambiguous_fence_indentation(self) -> None:
        accepted = import_text_book(
            f"   ```fen\n{Board.START}\n   ```",
            source_name="three-space-fence.md",
            source_format="markdown",
        )
        self.assertEqual(accepted.positions, 1)

        for prefix in ("    ", "\t"):
            source = (
                f"{prefix}```fen\n"
                f"{Board.START}\n"
                f"{prefix}```"
            )
            rejected_as_semantics = import_text_book(
                source,
                source_name="indented-code.md",
                source_format="markdown",
            )
            self.assertEqual(rejected_as_semantics.positions, 0)
            self.assertFalse(
                any(
                    isinstance(block, (Position, Diagram, Game))
                    for block in rejected_as_semantics.document.blocks
                )
            )

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

    def test_markdown_inline_image_flood_fails_at_semantic_block_limit(self) -> None:
        source = " ".join("![x](asset.png)" for _ in range(6))
        with patch("acs.book_text_import.MAX_TEXT_BLOCKS", 4):
            with self.assertRaises(BookTextImportError) as error:
                import_text_book(
                    source,
                    source_name="image-flood.md",
                    source_format="markdown",
                )
        self.assertEqual(error.exception.code, BookTextImportErrorCode.RESOURCE_LIMIT)

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

    def test_markdown_lists_are_semantic_while_block_quote_loss_remains_explicit(self) -> None:
        source = '''# Notes

- First item
- Second item

> Quoted advice
'''
        result = import_text_book(source, source_name="notes.md", source_format="markdown")
        lists = [block for block in result.document.blocks if isinstance(block, ListBlock)]
        self.assertEqual(len(lists), 1)
        self.assertEqual(lists[0].items, ["First item", "Second item"])
        self.assertFalse(lists[0].ordered)
        self.assertIsNone(lists[0].start)
        paragraphs = [block.text for block in result.document.blocks if isinstance(block, Paragraph)]
        self.assertIn("Quoted advice", paragraphs)
        self.assertFalse(any("list structure" in warning for warning in result.warnings))
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
