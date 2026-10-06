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
    _Builder,
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

    def test_warning_budget_includes_suppression_marker_without_losing_non_overflow_warnings(self) -> None:
        with patch("acs.book_text_import.MAX_TEXT_WARNINGS", 3):
            exact = _Builder(BookTextFormat.MARKDOWN)
            for index in range(3):
                exact.warning(f"warning {index}")
            self.assertEqual(
                exact.warnings,
                ["warning 0", "warning 1", "warning 2"],
            )

            overflow = _Builder(BookTextFormat.MARKDOWN)
            for index in range(5):
                overflow.warning(f"warning {index}")
            self.assertEqual(
                overflow.warnings,
                [
                    "warning 0",
                    "warning 1",
                    "additional text import warnings were suppressed",
                ],
            )

    def test_windows_1251_txt_and_markdown_are_decoded_losslessly_without_ai(self) -> None:
        txt_source = (
            "Шахові етюди\n\n"
            "Розділ про короля і пішака. Аналіз позиції словами.\n"
        ).encode("cp1251")
        txt = import_text_book(
            txt_source,
            source_name="legacy-studies.txt",
            source_format="txt",
        )
        self.assertTrue(
            any("Windows-1251" in warning and "losslessly" in warning for warning in txt.warnings)
        )
        self.assertTrue(
            any(
                isinstance(block, Paragraph) and "Шахові етюди" in block.text
                for block in txt.document.blocks
            )
        )

        markdown_source = f"""# Шахова книга

Пояснення варіанта і позиції.

```fen
{Board.START}
Початкова позиція
```
""".encode("cp1251")
        markdown = import_text_book(
            markdown_source,
            source_name="legacy-book.md",
            source_format="markdown",
        )
        self.assertEqual(markdown.positions, 1)
        self.assertEqual(markdown.document.title, "Шахова книга")
        self.assertTrue(any("Windows-1251" in warning for warning in markdown.warnings))

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

    def test_markdown_escaped_and_literal_image_syntax_stays_readable(self) -> None:
        cases = (
            (r"Before \![Board](board.png) after.", "escaped"),
            ("Before `![Board](board.png)` after.", "inline-code"),
            ("Before `![Board](board.png) after.", "unclosed-code"),
        )
        for source, label in cases:
            with self.subTest(label=label):
                result = import_text_book(
                    source,
                    source_name=f"{label}.md",
                    source_format="markdown",
                )
                image_notes = [
                    block
                    for block in result.document.blocks
                    if isinstance(block, Note) and block.note_type == "image"
                ]
                paragraphs = [
                    block.text
                    for block in result.document.blocks
                    if isinstance(block, Paragraph)
                ]
                self.assertEqual(image_notes, [])
                self.assertEqual(paragraphs, [source])

    def test_removed_false_image_snapshot_target_fails_closed_without_retargeting(self) -> None:
        legacy_digest = sha256(("Image\0" + "Board").encode("utf-8")).hexdigest()[:20]
        legacy_image_target = f"block:markdown-{legacy_digest}-1"
        snapshot = {
            "schema_version": BOOK_READER_SNAPSHOT_SCHEMA_VERSION,
            "current_target": legacy_image_target,
            "return_points": {},
            "fallback_digests": {},
        }

        for source, label in (
            (r"Before \![Board](board.png) after.", "escaped"),
            ("Before `![Board](board.png)` after.", "inline-code"),
        ):
            with self.subTest(label=label):
                result = import_text_book(
                    source,
                    source_name=f"legacy-false-image-{label}.md",
                    source_format="markdown",
                )
                self.assertFalse(
                    any(
                        isinstance(block, Note) and block.note_type == "image"
                        for block in result.document.blocks
                    )
                )
                with self.assertRaises(LookupError):
                    BookReader.restore_snapshot(result.document, snapshot)

    def test_markdown_inline_code_does_not_hide_real_image_after_code_span(self) -> None:
        source = "Before `![Literal](literal.png)` then ![Real](real.png) after."
        result = import_text_book(
            source,
            source_name="mixed-literal-image.md",
            source_format="markdown",
        )

        semantic = []
        for block in result.document.blocks:
            if isinstance(block, Note) and block.note_type == "image":
                semantic.append(("image", block.text))
            elif isinstance(block, Paragraph):
                semantic.append(("paragraph", block.text))
        self.assertEqual(
            semantic,
            [
                ("paragraph", "Before `![Literal](literal.png)` then"),
                ("image", "Real"),
                ("paragraph", "after."),
            ],
        )

    def test_markdown_code_span_backslash_does_not_swallow_closing_delimiter(self) -> None:
        source = r"Before `code\` then ![Real](real.png) after."
        result = import_text_book(
            source,
            source_name="code-backslash-close.md",
            source_format="markdown",
        )
        image_notes = [
            block.text
            for block in result.document.blocks
            if isinstance(block, Note) and block.note_type == "image"
        ]
        self.assertEqual(image_notes, ["Real"])

    def test_markdown_even_backslash_parity_keeps_unescaped_image_semantics(self) -> None:
        source = r"Prefix \\![Board](board.png) suffix."
        result = import_text_book(
            source,
            source_name="backslash-parity.md",
            source_format="markdown",
        )
        image_notes = [
            block.text
            for block in result.document.blocks
            if isinstance(block, Note) and block.note_type == "image"
        ]
        self.assertEqual(image_notes, ["Board"])

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

    def test_recoverable_explicit_pgn_surfaces_loss_warning(self) -> None:
        source = "```pgn\n[Event \"Recovered\"]\n[Result \"*\"]\n\n1. e4\n```\n"
        result = import_text_book(
            source,
            source_name="recovered-pgn.md",
            source_format="markdown",
        )
        self.assertEqual(result.pgn_games, 1)
        games = [block for block in result.document.blocks if isinstance(block, Game)]
        self.assertEqual(len(games), 1)
        self.assertTrue(
            any("required canonical recovery" in warning for warning in result.warnings)
        )
        resolved = resolve_book_game(games[0])
        self.assertTrue(resolved.warnings)

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

    def test_markdown_list_inline_image_keeps_list_semantics_and_alt_text(self) -> None:
        result = import_text_book(
            "- Before ![Board](images/board.png) after\n- Plain item\n",
            source_name="list-image.md",
            source_format="markdown",
        )
        lists = [
            block for block in result.document.blocks
            if isinstance(block, ListBlock)
        ]
        self.assertEqual(len(lists), 1)
        self.assertEqual(lists[0].items, ["Before Board after", "Plain item"])
        self.assertFalse(
            any(
                isinstance(block, Note) and block.note_type == "image"
                for block in result.document.blocks
            )
        )
        self.assertTrue(
            any(
                "image inside a list item" in warning
                and "accessible list-item text" in warning
                for warning in result.warnings
            )
        )

    def test_markdown_invalid_raw_destination_space_stays_literal(self) -> None:
        source = "Before ![Board](foo bar) after\n"
        result = import_text_book(
            source,
            source_name="invalid-space-image-destination.md",
            source_format="markdown",
        )
        paragraphs = [
            block.text
            for block in result.document.blocks
            if isinstance(block, Paragraph)
        ]
        self.assertEqual(paragraphs, [source.strip()])
        self.assertFalse(
            any(
                isinstance(block, Note) and block.note_type == "image"
                for block in result.document.blocks
            )
        )

    def test_markdown_quoted_image_title_may_contain_closing_parenthesis(self) -> None:
        result = import_text_book(
            'Before ![Board](asset.png "study ) title") after\n',
            source_name="quoted-title-image.md",
            source_format="markdown",
        )
        paragraphs = [
            block.text
            for block in result.document.blocks
            if isinstance(block, Paragraph)
        ]
        notes = [
            block.text
            for block in result.document.blocks
            if isinstance(block, Note) and block.note_type == "image"
        ]
        self.assertEqual(paragraphs, ["Before", "after"])
        self.assertEqual(notes, ["Board"])
        self.assertNotIn("title", " ".join(paragraphs))

    def test_markdown_angle_destination_may_contain_space_and_parenthesis(self) -> None:
        result = import_text_book(
            "Before ![Board](<assets/study ) board.png>) after\n",
            source_name="angle-image-destination.md",
            source_format="markdown",
        )
        paragraphs = [
            block.text
            for block in result.document.blocks
            if isinstance(block, Paragraph)
        ]
        notes = [
            block.text
            for block in result.document.blocks
            if isinstance(block, Note) and block.note_type == "image"
        ]
        self.assertEqual(paragraphs, ["Before", "after"])
        self.assertEqual(notes, ["Board"])

    def test_markdown_empty_image_destination_keeps_accessible_alt_text(self) -> None:
        result = import_text_book(
            "Before ![Board]() after\n",
            source_name="empty-image-destination.md",
            source_format="markdown",
        )
        paragraphs = [
            block.text
            for block in result.document.blocks
            if isinstance(block, Paragraph)
        ]
        notes = [
            block.text
            for block in result.document.blocks
            if isinstance(block, Note) and block.note_type == "image"
        ]
        self.assertEqual(paragraphs, ["Before", "after"])
        self.assertEqual(notes, ["Board"])

    def test_markdown_empty_image_destination_in_list_keeps_list_semantics(self) -> None:
        result = import_text_book(
            "- Before ![Board]() after\n- Plain\n",
            source_name="empty-image-list-destination.md",
            source_format="markdown",
        )
        lists = [
            block
            for block in result.document.blocks
            if isinstance(block, ListBlock)
        ]
        self.assertEqual(len(lists), 1)
        self.assertEqual(lists[0].items, ["Before Board after", "Plain"])
        self.assertTrue(
            any("image inside a list item" in warning for warning in result.warnings)
        )

    def test_markdown_decorative_empty_image_destination_does_not_leak_markup(self) -> None:
        result = import_text_book(
            "Before ![]() after\n",
            source_name="empty-decorative-image-destination.md",
            source_format="markdown",
        )
        paragraphs = [
            block.text
            for block in result.document.blocks
            if isinstance(block, Paragraph)
        ]
        self.assertEqual(paragraphs, ["Before", "after"])
        self.assertFalse(
            any(
                isinstance(block, Note) and block.note_type == "image"
                for block in result.document.blocks
            )
        )

    def test_markdown_inline_image_balanced_destination_does_not_leak_url_text(self) -> None:
        result = import_text_book(
            "Before ![Board](images/(study)/board.png) after\n",
            source_name="balanced-image.md",
            source_format="markdown",
        )
        paragraphs = [
            block.text for block in result.document.blocks
            if isinstance(block, Paragraph)
        ]
        notes = [
            block for block in result.document.blocks
            if isinstance(block, Note) and block.note_type == "image"
        ]
        self.assertEqual(paragraphs, ["Before", "after"])
        self.assertEqual([block.text for block in notes], ["Board"])
        self.assertFalse(
            any(
                "images/" in block.text
                for block in result.document.blocks
                if hasattr(block, "text")
            )
        )

    def test_markdown_list_image_balanced_destination_keeps_only_alt_text(self) -> None:
        result = import_text_book(
            "- Before ![Board](images/(study)/board.png) after\n"
            "- ![Escaped](images/board\\).png) tail\n",
            source_name="balanced-list-image.md",
            source_format="markdown",
        )
        lists = [
            block for block in result.document.blocks
            if isinstance(block, ListBlock)
        ]
        self.assertEqual(len(lists), 1)
        self.assertEqual(
            lists[0].items,
            ["Before Board after", "Escaped tail"],
        )
        self.assertTrue(
            any("image inside a list item" in warning for warning in result.warnings)
        )

    def test_markdown_balanced_image_destination_does_not_change_reading_identity(self) -> None:
        first = import_text_book(
            "Before ![Board](images/(study-a)/board.png) after\n",
            source_name="identity-a.md",
            source_format="markdown",
        )
        second = import_text_book(
            "Before ![Board](other/(study-b)/board.png) after\n",
            source_name="identity-b.md",
            source_format="markdown",
        )
        first_blocks = [
            block for block in first.document.blocks
            if isinstance(block, (Paragraph, Note))
        ]
        second_blocks = [
            block for block in second.document.blocks
            if isinstance(block, (Paragraph, Note))
        ]
        self.assertEqual(
            [(type(block).__name__, block.text, block.block_id) for block in first_blocks],
            [(type(block).__name__, block.text, block.block_id) for block in second_blocks],
        )

    def test_markdown_escaped_closing_bracket_in_image_alt_stays_accessible(self) -> None:
        result = import_text_book(
            "Before ![Board \\] study](assets/(round)/board.png) after\n",
            source_name="escaped-alt.md",
            source_format="markdown",
        )
        paragraphs = [
            block.text for block in result.document.blocks
            if isinstance(block, Paragraph)
        ]
        notes = [
            block.text for block in result.document.blocks
            if isinstance(block, Note) and block.note_type == "image"
        ]
        self.assertEqual(paragraphs, ["Before", "after"])
        self.assertEqual(notes, ["Board ] study"])
        self.assertNotIn("assets/", " ".join(paragraphs + notes))

    def test_markdown_list_escaped_bracket_alt_preserves_list_semantics(self) -> None:
        result = import_text_book(
            "- Study ![File \\] rank](assets/board.png) now\n",
            source_name="escaped-alt-list.md",
            source_format="markdown",
        )
        lists = [
            block for block in result.document.blocks
            if isinstance(block, ListBlock)
        ]
        self.assertEqual(len(lists), 1)
        self.assertEqual(lists[0].items, ["Study File ] rank now"])

    def test_markdown_unclosed_balanced_image_destination_stays_literal(self) -> None:
        source = "Before ![Board](images/(study)/board.png after\n"
        result = import_text_book(
            source,
            source_name="unclosed-image.md",
            source_format="markdown",
        )
        paragraphs = [
            block.text for block in result.document.blocks
            if isinstance(block, Paragraph)
        ]
        self.assertEqual(paragraphs, [source.strip()])
        self.assertFalse(
            any(
                isinstance(block, Note) and block.note_type == "image"
                for block in result.document.blocks
            )
        )

    def test_markdown_ordered_list_inline_images_keep_one_canonical_list(self) -> None:
        result = import_text_book(
            "3. ![First board](one.png) opening\n"
            "9. middle ![Second board](two.png)\n"
            "1. final\n",
            source_name="ordered-list-images.md",
            source_format="markdown",
        )
        lists = [
            block for block in result.document.blocks
            if isinstance(block, ListBlock)
        ]
        self.assertEqual(len(lists), 1)
        self.assertTrue(lists[0].ordered)
        self.assertEqual(lists[0].start, 3)
        self.assertEqual(
            lists[0].items,
            ["First board opening", "middle Second board", "final"],
        )

    def test_markdown_list_literal_image_syntax_stays_literal(self) -> None:
        result = import_text_book(
            "- \\![escaped](asset.png) stays literal\n"
            "- `![code](asset.png)` stays code text\n",
            source_name="literal-list-images.md",
            source_format="markdown",
        )
        lists = [
            block for block in result.document.blocks
            if isinstance(block, ListBlock)
        ]
        self.assertEqual(len(lists), 1)
        self.assertEqual(
            lists[0].items,
            [
                "\\![escaped](asset.png) stays literal",
                "`![code](asset.png)` stays code text",
            ],
        )
        self.assertFalse(
            any("image inside a list item" in warning for warning in result.warnings)
        )

    def test_markdown_ordered_list_uses_first_marker_as_canonical_start(self) -> None:
        result = import_text_book(
            "3. Third item\n9. Fourth item\n0. Fifth item\n",
            source_name="authored-numbering.md",
            source_format="markdown",
        )
        lists = [
            block for block in result.document.blocks
            if isinstance(block, ListBlock)
        ]
        self.assertEqual(len(lists), 1)
        self.assertTrue(lists[0].ordered)
        self.assertEqual(lists[0].start, 3)
        self.assertEqual(
            lists[0].items,
            ["Third item", "Fourth item", "Fifth item"],
        )

    def test_markdown_ordered_list_parenthesis_delimiter_preserves_one_list(self) -> None:
        result = import_text_book(
            "7) Seven\n1) Eight\n99) Nine\n",
            source_name="parenthesized-numbering.md",
            source_format="markdown",
        )
        lists = [
            block for block in result.document.blocks
            if isinstance(block, ListBlock)
        ]
        self.assertEqual(len(lists), 1)
        self.assertEqual(lists[0].start, 7)
        self.assertEqual(lists[0].items, ["Seven", "Eight", "Nine"])

    def test_markdown_ordered_delimiter_change_starts_new_semantic_list(self) -> None:
        result = import_text_book(
            "1. First\n9. Second\n3) Third\n8) Fourth\n",
            source_name="ordered-delimiter-boundary.md",
            source_format="markdown",
        )
        lists = [
            block for block in result.document.blocks
            if isinstance(block, ListBlock)
        ]
        self.assertEqual(
            [(block.start, block.items) for block in lists],
            [
                (1, ["First", "Second"]),
                (3, ["Third", "Fourth"]),
            ],
        )

    def test_markdown_unordered_marker_change_starts_new_semantic_list(self) -> None:
        result = import_text_book(
            "- Dash one\n- Dash two\n+ Plus one\n+ Plus two\n* Star one\n",
            source_name="unordered-marker-boundary.md",
            source_format="markdown",
        )
        lists = [
            block for block in result.document.blocks
            if isinstance(block, ListBlock)
        ]
        self.assertEqual(
            [block.items for block in lists],
            [
                ["Dash one", "Dash two"],
                ["Plus one", "Plus two"],
                ["Star one"],
            ],
        )
        self.assertTrue(all(not block.ordered for block in lists))

    def test_markdown_nonpositive_first_ordered_marker_remains_readable_fallback(self) -> None:
        result = import_text_book(
            "0. Cannot be canonical start\n1. Valid list start\n",
            source_name="nonpositive-first-marker.md",
            source_format="markdown",
        )
        paragraphs = [
            block.text for block in result.document.blocks
            if isinstance(block, Paragraph)
        ]
        lists = [
            block for block in result.document.blocks
            if isinstance(block, ListBlock)
        ]
        self.assertEqual(paragraphs, ["0. Cannot be canonical start"])
        self.assertEqual(len(lists), 1)
        self.assertEqual(lists[0].start, 1)
        self.assertEqual(lists[0].items, ["Valid list start"])
        self.assertTrue(
            any("non-positive start" in warning for warning in result.warnings)
        )

    def test_markdown_nonpositive_ordered_fallback_keeps_image_alt_only(self) -> None:
        result = import_text_book(
            "0. Before ![Board](secret/position.png) after\n"
            "1. Valid list item\n",
            source_name="nonpositive-image-list.md",
            source_format="markdown",
        )
        paragraphs = [
            block.text for block in result.document.blocks
            if isinstance(block, Paragraph)
        ]
        lists = [
            block for block in result.document.blocks
            if isinstance(block, ListBlock)
        ]
        self.assertEqual(paragraphs, ["0. Before Board after"])
        self.assertNotIn("secret/position.png", " ".join(paragraphs))
        self.assertEqual(len(lists), 1)
        self.assertEqual(lists[0].start, 1)
        self.assertEqual(lists[0].items, ["Valid list item"])
        self.assertTrue(
            any(
                "unrepresentable list item" in warning
                for warning in result.warnings
            )
        )
    def test_markdown_ordered_list_reimport_keeps_stable_semantic_target(self) -> None:
        source = "4. Alpha\n40. Beta\n2. Gamma\n"
        first = import_text_book(
            source,
            source_name="ordered-progress.md",
            source_format="markdown",
        )
        second = import_text_book(
            source,
            source_name="ordered-progress.md",
            source_format="markdown",
        )
        first_list = next(
            block for block in first.document.blocks
            if isinstance(block, ListBlock)
        )
        second_list = next(
            block for block in second.document.blocks
            if isinstance(block, ListBlock)
        )
        self.assertEqual(first_list.block_id, second_list.block_id)
        self.assertEqual(first_list.start, 4)
        self.assertEqual(first_list.items, ["Alpha", "Beta", "Gamma"])

    def test_markdown_ordered_list_progress_restores_after_reimport(self) -> None:
        source = "4. Alpha\n40. Beta\n2. Gamma\n"
        first = import_text_book(
            source,
            source_name="ordered-progress-restore.md",
            source_format="markdown",
        )
        first_index = next(
            index
            for index, block in enumerate(first.document.blocks)
            if isinstance(block, ListBlock)
        )
        first_reader = BookReader(first.document)
        first_reader.go_to(first_index)
        snapshot = first_reader.snapshot()

        second = import_text_book(
            source,
            source_name="ordered-progress-restore.md",
            source_format="markdown",
        )
        restored = BookReader.restore_snapshot(second.document, snapshot)
        location = restored.location()
        restored_block = second.document.blocks[location.index]

        self.assertIsInstance(restored_block, ListBlock)
        self.assertEqual(location.block_id, restored_block.block_id)
        self.assertEqual(restored_block.start, 4)
        self.assertEqual(restored_block.items, ["Alpha", "Beta", "Gamma"])

    def test_markdown_lists_keep_semantics_with_up_to_three_leading_spaces(self) -> None:
        cases = (
            (" - First item\n - Second item\n", False, None, ["First item", "Second item"]),
            ("  3. Third item\n  4. Fourth item\n", True, 3, ["Third item", "Fourth item"]),
            ("   * Alpha\n   * Beta\n", False, None, ["Alpha", "Beta"]),
        )
        for source, ordered, start, items in cases:
            with self.subTest(source=source):
                result = import_text_book(
                    source,
                    source_name="shallow-indent-list.md",
                    source_format="markdown",
                )
                lists = [
                    block
                    for block in result.document.blocks
                    if isinstance(block, ListBlock)
                ]
                self.assertEqual(len(lists), 1)
                self.assertEqual(lists[0].items, items)
                self.assertEqual(lists[0].ordered, ordered)
                self.assertEqual(lists[0].start, start)
                self.assertFalse(
                    any("list indentation" in warning for warning in result.warnings)
                )

    def test_markdown_shallow_indent_preserves_nested_item_as_readable_text(self) -> None:
        result = import_text_book(
            "- Parent\n  - Child 1. e4 e5\n  - Child two\n- Sibling\n",
            source_name="nested-shallow-list.md",
            source_format="markdown",
        )
        lists = [
            block
            for block in result.document.blocks
            if isinstance(block, ListBlock)
        ]
        paragraphs = [
            block
            for block in result.document.blocks
            if isinstance(block, Paragraph)
        ]
        self.assertEqual(
            [(block.items, block.ordered, block.start) for block in lists],
            [(["Parent"], False, None), (["Sibling"], False, None)],
        )
        self.assertEqual(
            [block.text for block in paragraphs],
            ["- Child 1. e4 e5", "- Child two"],
        )
        self.assertTrue(
            any(
                "indentation or nesting" in warning
                and "readable text" in warning
                for warning in result.warnings
            )
        )
        self.assertEqual(result.pgn_games, 0)
        self.assertEqual(result.positions, 0)

    def test_markdown_tab_or_four_space_list_indent_stays_readable_fallback(self) -> None:
        for prefix in ("    ", "\t"):
            with self.subTest(prefix=repr(prefix)):
                source = f"{prefix}- First item\n{prefix}- Second item\n"
                result = import_text_book(
                    source,
                    source_name="unsupported-indent-list.md",
                    source_format="markdown",
                )
                self.assertFalse(
                    any(isinstance(block, ListBlock) for block in result.document.blocks)
                )
                paragraphs = [
                    block.text
                    for block in result.document.blocks
                    if isinstance(block, Paragraph)
                ]
                self.assertEqual(paragraphs, ["- First item", "- Second item"])
                self.assertTrue(
                    any("list indentation" in warning for warning in result.warnings)
                )

    def test_markdown_nested_list_image_fallback_keeps_alt_not_destination(self) -> None:
        result = import_text_book(
            "- Parent\n"
            "  - Child ![Board position](private/board.png) after\n"
            "- Sibling\n",
            source_name="nested-image-list.md",
            source_format="markdown",
        )
        lists = [
            block for block in result.document.blocks
            if isinstance(block, ListBlock)
        ]
        paragraphs = [
            block.text for block in result.document.blocks
            if isinstance(block, Paragraph)
        ]
        self.assertEqual(
            [(block.items, block.ordered, block.start) for block in lists],
            [(["Parent"], False, None), (["Sibling"], False, None)],
        )
        self.assertEqual(paragraphs, ["- Child Board position after"])
        self.assertNotIn("private/board.png", " ".join(paragraphs))
        self.assertTrue(
            any(
                "unrepresentable list item" in warning
                and "accessible text" in warning
                for warning in result.warnings
            )
        )

    def test_markdown_deep_indented_list_image_fallback_keeps_marker_and_alt(self) -> None:
        for prefix in ("    ", "\t"):
            with self.subTest(prefix=repr(prefix)):
                result = import_text_book(
                    f"{prefix}4) Before ![Tactic](assets/tactic.svg) after\n",
                    source_name="deep-image-list.md",
                    source_format="markdown",
                )
                self.assertFalse(
                    any(isinstance(block, ListBlock) for block in result.document.blocks)
                )
                paragraphs = [
                    block.text
                    for block in result.document.blocks
                    if isinstance(block, Paragraph)
                ]
                self.assertEqual(paragraphs, ["4) Before Tactic after"])
                self.assertNotIn("assets/tactic.svg", " ".join(paragraphs))
                self.assertTrue(
                    any("list indentation" in warning for warning in result.warnings)
                )
                self.assertTrue(
                    any(
                        "unrepresentable list item" in warning
                        for warning in result.warnings
                    )
                )

    def test_markdown_decorative_image_in_list_does_not_leak_destination(self) -> None:
        result = import_text_book(
            "- Before ![](private/decorative.png) after\n",
            source_name="decorative-list-image.md",
            source_format="markdown",
        )
        lists = [
            block for block in result.document.blocks
            if isinstance(block, ListBlock)
        ]
        self.assertEqual(len(lists), 1)
        self.assertEqual(lists[0].items, ["Before after"])
        self.assertNotIn("private/decorative.png", lists[0].items[0])
        self.assertTrue(
            any(
                "image inside a list item" in warning
                for warning in result.warnings
            )
        )

    def test_markdown_decorative_image_in_prose_does_not_leak_destination(self) -> None:
        result = import_text_book(
            "Before ![](private/decorative.png) after\n",
            source_name="decorative-prose-image.md",
            source_format="markdown",
        )
        paragraphs = [
            block.text for block in result.document.blocks
            if isinstance(block, Paragraph)
        ]
        self.assertEqual(paragraphs, ["Before", "after"])
        self.assertNotIn("private/decorative.png", " ".join(paragraphs))
        self.assertFalse(
            any(
                isinstance(block, Note) and block.note_type == "image"
                for block in result.document.blocks
            )
        )
    def test_markdown_list_fallback_does_not_invent_images_from_literals(self) -> None:
        result = import_text_book(
            "    - \\![escaped](asset.png) and `![code](asset.png)`\n",
            source_name="deep-literal-image-list.md",
            source_format="markdown",
        )
        paragraphs = [
            block.text for block in result.document.blocks
            if isinstance(block, Paragraph)
        ]
        self.assertEqual(
            paragraphs,
            ["- \\![escaped](asset.png) and `![code](asset.png)`"],
        )
        self.assertFalse(
            any(
                "unrepresentable list item" in warning
                for warning in result.warnings
            )
        )
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
        self.assertIn("Windows-1251", BOOK_TEXT_CAPABILITIES["TXT"]["encoding"])
        self.assertIn("Windows-1251", BOOK_TEXT_CAPABILITIES["Markdown"]["encoding"])


if __name__ == "__main__":
    unittest.main()
