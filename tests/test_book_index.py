import unittest

from acs.book_index import AmbiguousBookTargetError, BookEntryKind, BookIndex, BookTarget
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
    def test_constructor_rejects_non_book_document(self):
        for value in (None, {}, [], "book"):
            with self.subTest(value=value):
                with self.assertRaisesRegex(TypeError, "BookDocument"):
                    BookIndex(value)  # type: ignore[arg-type]

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
        self.assertEqual(index.entries[0].heading_level, 1)
        self.assertEqual(index.entries[2].heading_level, 2)
        self.assertIsNone(index.entries[3].heading_level)

    def test_contents_and_kind_filters_are_semantic_not_ui_specific(self):
        index = BookIndex(self.make_document())
        self.assertEqual([entry.label for entry in index.contents()], ["Chapter One", "Calculation"])
        self.assertEqual([entry.label for entry in index.contents(max_heading_level=1)], ["Chapter One"])
        self.assertEqual([entry.label for entry in index.of_kind(BookEntryKind.GAME)], ["Model game"])
        self.assertEqual([entry.label for entry in index.of_kind(BookEntryKind.EXERCISE)], ["Find the winning move"])
        with self.assertRaisesRegex(TypeError, "Book entry kind"):
            index.of_kind("game")  # type: ignore[arg-type]

    def test_contents_uses_immutable_heading_snapshot_after_document_edit(self):
        document = self.make_document()
        index = BookIndex(document)

        heading = document.blocks[2]
        self.assertIsInstance(heading, Heading)
        heading.level = 1
        heading.text = "Edited after indexing"

        self.assertEqual(index.entries[2].heading_level, 2)
        self.assertEqual(index.entries[2].label, "Calculation")
        self.assertEqual([entry.label for entry in index.contents(max_heading_level=1)], ["Chapter One"])
        self.assertEqual([entry.label for entry in index.contents(max_heading_level=2)], ["Chapter One", "Calculation"])

        document.blocks.reverse()
        self.assertEqual([entry.target.index for entry in index.entries], list(range(8)))
        self.assertEqual([entry.label for entry in index.contents()], ["Chapter One", "Calculation"])

    def test_index_construction_revalidates_mutated_document_blocks(self):
        document = self.make_document()
        heading = document.blocks[0]
        self.assertIsInstance(heading, Heading)
        heading.level = True
        with self.assertRaises(BookDocumentError):
            BookIndex(document)

    def test_index_construction_uses_one_validated_detached_snapshot(self):
        class MutatingAfterExportBookDocument(BookDocument):
            def as_dict(self):
                payload = super().as_dict()
                heading = self.blocks[0]
                self.assert_heading(heading)
                heading.level = 6
                heading.text = "Mutated after export"
                self.blocks.reverse()
                return payload

            @staticmethod
            def assert_heading(block):
                if not isinstance(block, Heading):
                    raise AssertionError("fixture must begin with a Heading")

        source = self.make_document()
        document = MutatingAfterExportBookDocument(
            title=source.title,
            language=source.language,
            author=source.author,
            source_name=source.source_name,
            source_uri=source.source_uri,
            source_rights=source.source_rights,
            warnings=list(source.warnings),
            blocks=list(source.blocks),
        )

        index = BookIndex(document)

        self.assertEqual(index.entries[0].label, "Chapter One")
        self.assertEqual(index.entries[0].heading_level, 1)
        self.assertEqual(index.entries[0].target.key, "block:h1")
        self.assertEqual(index.entries[-1].label, "Return to the critical position")
        self.assertEqual([entry.label for entry in index.contents()], ["Chapter One", "Calculation"])
        self.assertEqual(document.blocks[0].source_anchor, "note-a")

    def test_stable_target_prefers_block_id_then_source_anchor(self):
        index = BookIndex(self.make_document())
        self.assertEqual(index.entries[0].target.key, "block:h1")
        self.assertEqual(index.entries[1].target.key, "source:p-1")
        self.assertEqual(index.resolve("block:pos-1").target.index, 3)
        self.assertEqual(index.resolve(index.entries[6].target).label, "Main branch")
        for invalid in (None, 3, True):
            with self.subTest(invalid=invalid):
                with self.assertRaisesRegex(TypeError, "Book target"):
                    index.resolve(invalid)  # type: ignore[arg-type]

    def test_resolve_bounds_raw_target_before_dictionary_hashing(self):
        index = BookIndex(self.make_document())
        oversized = "x" * 4097

        with self.assertRaisesRegex(ValueError, "exceeds 4096"):
            index.resolve(oversized)
        with self.assertRaisesRegex(ValueError, "exceeds 4096"):
            index.resolve(BookTarget(oversized, 0, None, None))

        class HashForbiddenString(str):
            def __hash__(self):
                raise AssertionError("string subclass must be rejected before hashing")

        with self.assertRaisesRegex(TypeError, "Book target"):
            index.resolve(HashForbiddenString("block:h1"))
        with self.assertRaisesRegex(TypeError, "target key"):
            index.resolve(BookTarget(HashForbiddenString("block:h1"), 0, None, None))

        with self.assertRaises(LookupError):
            index.resolve("x" * 4096)

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
        invalid_kind_filters = (
            {BookEntryKind.GAME.value},
            {BookEntryKind.GAME, "exercise"},
            [BookEntryKind.GAME],
            frozenset({BookEntryKind.GAME}),
        )
        for kinds in invalid_kind_filters:
            with self.subTest(kinds=kinds):
                with self.assertRaisesRegex(TypeError, "Search kinds"):
                    index.find("model", kinds=kinds)  # type: ignore[arg-type]

    def test_find_bounds_raw_query_before_normalization(self):
        index = BookIndex(self.make_document())

        with self.assertRaisesRegex(ValueError, "exceeds 4096"):
            index.find(" " * 4097)
        self.assertEqual(index.find("x" * 4096), ())

    def test_find_rejects_non_text_query_deterministically(self):
        index = BookIndex(self.make_document())
        for value in (None, 7, True, b"model"):
            with self.subTest(value=value):
                with self.assertRaisesRegex(TypeError, "must be a string"):
                    index.find(value)  # type: ignore[arg-type]

    def test_invalid_contents_depth_is_rejected(self):
        index = BookIndex(self.make_document())
        with self.assertRaises(ValueError):
            index.contents(max_heading_level=0)
        with self.assertRaises(ValueError):
            index.contents(max_heading_level=7)
        for value in (True, 1.0, "1"):
            with self.subTest(value=value):
                with self.assertRaisesRegex(TypeError, "must be an integer"):
                    index.contents(max_heading_level=value)  # type: ignore[arg-type]


if __name__ == "__main__":
    unittest.main()
