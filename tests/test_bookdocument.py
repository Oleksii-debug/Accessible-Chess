from pathlib import Path
import unittest

from acs.bookdocument import (
    BookDocument,
    BookDocumentError,
    BookDocumentErrorCode,
    Diagram,
    Exercise,
    Game,
    Heading,
    Note,
    Paragraph,
    Position,
    VariationTree,
)


FEN = "8/8/8/8/8/8/4K3/7k w - - 0 1"


class BookDocumentTests(unittest.TestCase):
    def test_semantic_book_preserves_reading_order(self):
        book = BookDocument("Accessible test book", language="uk", author="Author")
        book.extend([
            Heading(text="Розділ 1", level=1, block_id="h1"),
            Paragraph(text="Авторський вступ."),
            Position(fen=FEN, caption="Позиція 1"),
            Game(pgn="[Result \"*\"]\n\n*", title="Приклад"),
            Note(text="Зверніть увагу на короля."),
        ])
        self.assertEqual([block.kind for block in book.blocks], [
            "Heading", "Paragraph", "Position", "Game", "Note"
        ])
        self.assertEqual(book.headings()[0].text, "Розділ 1")
        self.assertEqual(book.as_dict()["blocks"][2]["fen"], FEN)

    def test_semantic_dict_round_trip_preserves_block_types_and_source_anchors(self):
        original = BookDocument(
            "Round trip",
            language="uk",
            author="Author",
            source_name="source.docx",
            warnings=["source warning"],
            blocks=[
                Heading(text="Розділ", level=1, block_id="h1", source_anchor="p12"),
                Diagram(fen=FEN, caption="Diagram", alt_text="White king e2; black king h1", source_anchor="p13"),
                VariationTree(root_fen=FEN, pgn="1. Kf3 (1. Kd3) *", title="Line", source_anchor="p14"),
                Exercise(fen=FEN, prompt="Find a move", answer_text="Kf3", difficulty="beginner", source_anchor="p15"),
            ],
        )
        restored = BookDocument.from_dict(original.as_dict())
        self.assertEqual(restored.as_dict(), original.as_dict())
        self.assertIsInstance(restored.blocks[0], Heading)
        self.assertIsInstance(restored.blocks[1], Diagram)
        self.assertIsInstance(restored.blocks[2], VariationTree)
        self.assertIsInstance(restored.blocks[3], Exercise)
        self.assertEqual(restored.blocks[1].source_anchor, "p13")

    def test_unknown_semantic_data_is_rejected_not_silently_dropped(self):
        with self.assertRaisesRegex(ValueError, "Unsupported BookDocument fields"):
            BookDocument.from_dict({"title": "Book", "mystery": 1})
        with self.assertRaisesRegex(ValueError, "Unsupported BookDocument block kind"):
            BookDocument.from_dict({"title": "Book", "blocks": [{"kind": "Video", "url": "x"}]})
        with self.assertRaisesRegex(ValueError, "Unsupported fields for Paragraph"):
            BookDocument.from_dict({"title": "Book", "blocks": [{"kind": "Paragraph", "text": "ok", "lost": "no"}]})

    def test_constructor_revalidates_mutated_initial_semantic_blocks(self):
        cases = []

        paragraph = Paragraph(text="Initially valid")
        paragraph.text = ""
        cases.append(paragraph)

        heading = Heading(text="Initially valid", level=2)
        heading.level = 7
        cases.append(heading)

        game = Game(pgn='[Result "*"]\n\n*')
        game.pgn = None  # type: ignore[assignment]
        cases.append(game)

        for block in cases:
            with self.subTest(kind=block.kind):
                with self.assertRaises(BookDocumentError) as caught:
                    BookDocument("Book", blocks=[block])
                self.assertEqual(
                    caught.exception.code,
                    BookDocumentErrorCode.INVALID_FIELD,
                )

    def test_constructor_preserves_valid_initial_block_objects(self):
        paragraph = Paragraph(text="Readable text", block_id="p1")
        book = BookDocument("Book", blocks=[paragraph])

        self.assertIs(book.blocks[0], paragraph)
        self.assertEqual(book.as_dict()["blocks"][0]["text"], "Readable text")

    def test_structure_validation_rejects_mutated_live_block_fields_stably(self):
        heading = Heading(text="Heading", level=1, block_id="h1")
        book = BookDocument("Book", blocks=[heading])

        heading.block_id = []  # type: ignore[assignment]
        with self.assertRaises(BookDocumentError) as identity:
            book.validate_structure()
        self.assertEqual(identity.exception.code, BookDocumentErrorCode.INVALID_FIELD)

        heading.block_id = "h1"
        heading.level = "2"  # type: ignore[assignment]
        with self.assertRaises(BookDocumentError) as level:
            book.validate_structure()
        self.assertEqual(level.exception.code, BookDocumentErrorCode.INVALID_FIELD)

    def test_structure_validation_contains_mutated_document_containers(self):
        bad_warnings = BookDocument("Book")
        bad_warnings.warnings = "not-a-list"  # type: ignore[assignment]
        with self.assertRaises(BookDocumentError) as warnings_error:
            bad_warnings.validate_structure()
        self.assertEqual(
            warnings_error.exception.code,
            BookDocumentErrorCode.INVALID_FIELD,
        )

        bad_blocks = BookDocument("Book")
        bad_blocks.blocks = [object()]  # type: ignore[list-item]
        with self.assertRaises(BookDocumentError) as blocks_error:
            bad_blocks.validate_structure()
        self.assertEqual(
            blocks_error.exception.code,
            BookDocumentErrorCode.INVALID_FIELD,
        )

    def test_bookdocument_gate_late_binds_live_product_for_push_and_pr(self):
        workflow = (
            Path(__file__).resolve().parents[1]
            / ".github"
            / "workflows"
            / "bookdocument-constructor-semantic-integrity.yml"
        ).read_text(encoding="utf-8")

        self.assertIn(
            "PRODUCT_REF: work/full-product-teacher-education-reachability-20260911",
            workflow,
        )
        self.assertNotIn("CURRENT_PRODUCT_BASE:", workflow)
        self.assertIn(
            '"refs/heads/$base_ref:refs/remotes/origin/$base_ref"',
            workflow,
        )
        self.assertIn(
            'upstream="$(git rev-parse "refs/remotes/origin/$base_ref")"',
            workflow,
        )
        self.assertIn(
            'git merge-base --is-ancestor "$event_base" "$upstream"',
            workflow,
        )
        self.assertIn(
            'test "$(git merge-base "$upstream" HEAD)" = "$upstream"',
            workflow,
        )

    def test_diagram_requires_accessibility_warning_when_alt_missing(self):
        book = BookDocument("Book")
        book.append(Diagram(fen=FEN, caption="Diagram"))
        warnings = book.validate_structure()
        self.assertTrue(any("no alt_text" in warning for warning in warnings))

    def test_heading_jump_and_duplicate_ids_are_reported_not_silently_lost(self):
        book = BookDocument("Book")
        book.extend([
            Heading(text="One", level=1, block_id="same"),
            Heading(text="Too deep", level=3, block_id="same"),
        ])
        warnings = book.validate_structure()
        self.assertTrue(any("heading level jumps" in warning for warning in warnings))
        self.assertTrue(any("duplicate block_id" in warning for warning in warnings))

    def test_exercise_carries_prompt_and_solution(self):
        exercise = Exercise(
            fen=FEN,
            prompt="Знайдіть найкращий хід.",
            solution_pgn="1. Kf3 *",
            difficulty="beginner",
        )
        book = BookDocument("Exercises", blocks=[exercise])
        self.assertEqual(book.exercises()[0].difficulty, "beginner")

    def test_variation_tree_keeps_root_position_and_pgn(self):
        tree = VariationTree(root_fen=FEN, pgn="1. Kf3 (1. Kd3) *")
        self.assertEqual(tree.root_fen, FEN)
        self.assertIn("(1. Kd3)", tree.pgn)

    def test_invalid_semantic_blocks_fail_explicitly(self):
        with self.assertRaises(ValueError):
            Heading(text="", level=1)
        with self.assertRaises(ValueError):
            Heading(text="Bad", level=7)
        with self.assertRaises(ValueError):
            Position(fen="bad fen")
        with self.assertRaises(ValueError):
            Exercise(fen=FEN, prompt="Solve", solution_pgn=None, answer_text=None)


if __name__ == "__main__":
    unittest.main()
