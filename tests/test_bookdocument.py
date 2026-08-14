import unittest

from acs.bookdocument import (
    BookDocument,
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
