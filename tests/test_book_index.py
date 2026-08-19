import unittest

from acs.book_index import (
    AmbiguousBookTargetError,
    BookEntryKind,
    BookIndex,
    BookTarget,
)
from acs.bookdocument import (
    BookDocument,
    BookDocumentError,
    Exercise,
    Game,
    Heading,
    Note,
    Paragraph,
    Position,
    VariationTree,
)


START_FEN = "8/8/8/8/8/8/8/K6k w - - 0 1"
BLACK_FEN = "8/8/8/8/8/8/8/K6k b - - 0 1"


class BookIndexTests(unittest.TestCase):
    def make_document(self):
        return BookDocument(
            title="Study",
            blocks=[
                Heading(text="Chapter One", level=1, block_id="h1"),
                Paragraph(text="Plan and explanation", source_anchor="p-1"),
                Heading(text="Calculation", level=2, block_id="h2"),
                Position(fen=BLACK_FEN, caption="Critical position", block_id="pos-1"),
                Game(pgn="1. e4 e5 *", title="Model game", game_id=7, block_id="g7"),
                Exercise(fen=START_FEN, prompt="Find the winning move", answer_text="Ka2", block_id="ex-1"),
                VariationTree(root_fen=START_FEN, pgn="1. Ka2 *", title="Main branch", source_anchor="var-a"),
                Note(text="Return to the critical position", source_anchor="note-a"),
            ],
        )

    def test_index_preserves_linear_order_heading_paths_and_positions(self):
        index = BookIndex(self.make_document())
        self.assertEqual([entry.target.index for entry in index.entries], list(range(8)))
        self.assertEqual(index.entries[3].heading_path, ("Chapter One", "Calculation"))
        self.assertEqual(index.entries[3].position_fen, BLACK_FEN)
        self.assertEqual(index.entries[3].side_to_move, "black")
        self.assertEqual(index.entries[5].side_to_move, "white")

    def test_contents_and_kind_filters_are_semantic_not_ui_specific(self):
        index = BookIndex(self.make_document())
        self.assertEqual([entry.label for entry in index.contents()], ["Chapter One", "Calculation"])
        self.assertEqual([entry.label for entry in index.contents(max_heading_level=1)], ["Chapter One"])
        self.assertEqual([entry.label for entry in index.of_kind(BookEntryKind.GAME)], ["Model game"])
        self.assertEqual([entry.label for entry in index.of_kind(BookEntryKind.EXERCISE)], ["Find the winning move"])

    def test_stable_target_prefers_block_id_then_source_anchor(self):
        index = BookIndex(self.make_document())
        self.assertEqual(index.entries[0].target.key, "block:h1")
        self.assertEqual(index.entries[1].target.key, "source:p-1")
        self.assertEqual(index.resolve("block:pos-1").target.index, 3)
        self.assertEqual(index.resolve(index.entries[6].target).label, "Main branch")

    def test_duplicate_semantic_target_is_rejected_not_silently_resolved(self):
        document = BookDocument(
            title="Ambiguous",
            blocks=[
                Paragraph(text="First", source_anchor="same"),
                Note(text="Second", source_anchor="same"),
            ],
        )
        index = BookIndex(document)
        with self.assertRaises(AmbiguousBookTargetError):
            index.resolve("source:same")

    def test_find_is_case_insensitive_and_preserves_reading_order(self):
        index = BookIndex(self.make_document())
        matches = index.find("position")
        self.assertEqual([entry.target.index for entry in matches], [3, 7])
        games = index.find("MODEL", kinds={BookEntryKind.GAME})
        self.assertEqual([entry.target.index for entry in games], [4])
        with self.assertRaises(ValueError):
            index.find("   ")

    def test_invalid_contents_depth_is_rejected(self):
        index = BookIndex(self.make_document())
        for invalid in (0, 7, True, False, "2", 2.0):
            with self.subTest(value=invalid):
                with self.assertRaises(ValueError):
                    index.contents(max_heading_level=invalid)

    def test_index_owns_a_detached_snapshot(self):
        document = self.make_document()
        index = BookIndex(document)

        document.blocks.clear()
        self.assertEqual(len(index.entries), 8)
        self.assertEqual(
            [entry.label for entry in index.contents()],
            ["Chapter One", "Calculation"],
        )

        exposed = index.document
        exposed.blocks.clear()
        self.assertEqual(len(index.entries), 8)
        self.assertEqual(len(index.document.blocks), 8)

    def test_filter_and_target_inputs_fail_closed_instead_of_returning_false_empty(self):
        index = BookIndex(self.make_document())

        for invalid_kind in ("game", True, None):
            with self.subTest(kind=invalid_kind):
                with self.assertRaises(ValueError):
                    index.of_kind(invalid_kind)
        for invalid_kinds in ({"game"}, [BookEntryKind.GAME], {True}):
            with self.subTest(kinds=invalid_kinds):
                with self.assertRaises(ValueError):
                    index.find("model", kinds=invalid_kinds)
        for invalid_text in (None, True, 7):
            with self.subTest(text=invalid_text):
                with self.assertRaises(ValueError):
                    index.find(invalid_text)
        for invalid_target in (None, True, 7, "", "   "):
            with self.subTest(target=invalid_target):
                with self.assertRaises(ValueError):
                    index.resolve(invalid_target)
        with self.assertRaises(ValueError):
            index.resolve(BookTarget(key="", index=0, block_id=None, source_anchor=None))
        for kwargs in (
            {"key": "block:h1", "index": True, "block_id": "h1", "source_anchor": None},
            {"key": "block:h1", "index": "0", "block_id": "h1", "source_anchor": None},
            {"key": "block:h1", "index": 0, "block_id": True, "source_anchor": None},
        ):
            with self.subTest(target=kwargs):
                with self.assertRaises(ValueError):
                    BookTarget(**kwargs)

    def test_constructor_requires_semantic_document(self):
        with self.assertRaises(BookDocumentError):
            BookIndex(object())


if __name__ == "__main__":
    unittest.main()
