from pathlib import Path
import unittest

from acs.book_index import AmbiguousBookTargetError, BookEntryKind, BookIndex, BookTarget
from acs.bookdocument import (
    BookDocument,
    BookDocumentError,
    Exercise,
    Game,
    Heading,
    ListBlock,
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

    def test_public_document_is_detached_from_source_and_from_prior_callers(self):
        source = self.make_document()
        index = BookIndex(source)

        first = index.document
        self.assertIsNot(first, source)
        self.assertEqual(first.as_dict(), source.as_dict())
        self.assertEqual(first.blocks[2].text, index.entries[2].label)

        # Mutating either the authoring source or a previously returned copy
        # must not make the public document disagree with immutable entries.
        source.blocks.reverse()
        source.blocks[0].source_anchor = "mutated-source"
        first.blocks.reverse()
        first.blocks[0].source_anchor = "mutated-returned-copy"

        second = index.document
        self.assertIsNot(second, first)
        self.assertEqual(second.blocks[0].block_id, "h1")
        self.assertEqual(second.blocks[2].block_id, "h2")
        self.assertEqual(second.blocks[2].text, "Calculation")
        self.assertEqual(second.blocks[2].text, index.entries[2].label)
        self.assertEqual(index.resolve("block:h2").target.index, 2)

    def test_index_construction_revalidates_mutated_document_blocks(self):
        document = self.make_document()
        heading = document.blocks[0]
        self.assertIsInstance(heading, Heading)
        heading.level = True
        with self.assertRaises(BookDocumentError):
            BookIndex(document)

    def test_index_construction_rejects_document_subclass_before_export_hook(self):
        class MutatingAfterExportBookDocument(BookDocument):
            export_touched = False

            def as_dict(self):
                type(self).export_touched = True
                raise AssertionError("BookDocument subclass export must not execute")

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

        with self.assertRaisesRegex(TypeError, "BookDocument"):
            BookIndex(document)

        self.assertFalse(MutatingAfterExportBookDocument.export_touched)

    def test_index_bounds_generated_semantic_target_keys_before_materialization(self):
        block_limit = "b" * (4096 - len("block:"))
        source_limit = "s" * (4096 - len("source:"))

        at_limit = BookIndex(
            BookDocument(
                title="Target bounds",
                blocks=[
                    Paragraph(text="Block", block_id=block_limit),
                    Paragraph(text="Source", source_anchor=source_limit),
                ],
            )
        )
        self.assertEqual(len(at_limit.entries[0].target.key), 4096)
        self.assertEqual(len(at_limit.entries[1].target.key), 4096)

        with self.assertRaisesRegex(ValueError, "exceeds 4096"):
            BookIndex(
                BookDocument(
                    title="Oversized block target",
                    blocks=[Paragraph(text="Block", block_id=block_limit + "x")],
                )
            )
        with self.assertRaisesRegex(ValueError, "exceeds 4096"):
            BookIndex(
                BookDocument(
                    title="Oversized source target",
                    blocks=[Paragraph(text="Source", source_anchor=source_limit + "x")],
                )
            )

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

    def test_resolve_rejects_book_target_subclass_before_attribute_hooks(self):
        index = BookIndex(self.make_document())

        class HostileTarget(BookTarget):
            armed = False
            touched = False

            def __getattribute__(self, name):
                if type(self).armed and name in {"key", "index", "block_id", "source_anchor"}:
                    type(self).touched = True
                    raise AssertionError("BookTarget subclass fields must not be read")
                return super().__getattribute__(name)

        hostile = HostileTarget("block:h1", 0, "h1", None)
        HostileTarget.armed = True

        with self.assertRaisesRegex(TypeError, "Book target"):
            index.resolve(hostile)

        self.assertFalse(HostileTarget.touched)
        self.assertEqual(index.resolve(BookTarget("block:h1", 0, None, None)).target.index, 0)

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

    def test_find_reuses_canonical_nfkc_casefold_search_semantics(self):
        document = BookDocument(
            title="Unicode search",
            blocks=[
                Heading(text="Café strategy", level=1, block_id="accent"),
                Paragraph(text="ＦＩＡＮＣＨＥＴＴＯ plan", block_id="compatibility"),
            ],
        )
        index = BookIndex(document)

        decomposed = index.find("Cafe\u0301")
        self.assertEqual([entry.target.key for entry in decomposed], ["block:accent"])

        compatibility = index.find("fianchetto")
        self.assertEqual(
            [entry.target.key for entry in compatibility],
            ["block:compatibility"],
        )

    def test_find_reuses_canonical_query_whitespace_and_length_policy(self):
        document = BookDocument(
            title="Query policy",
            blocks=[
                Heading(text="Open file strategy", level=1, block_id="spacing"),
            ],
        )
        index = BookIndex(document)

        spaced = index.find("  Open   file   strategy  ")
        self.assertEqual(
            [entry.target.key for entry in spaced],
            ["block:spacing"],
        )

        with self.assertRaisesRegex(ValueError, "maximum search term length"):
            index.find("x" * 257)

    def test_find_normalizes_candidate_whitespace_with_shared_policy(self):
        document = BookDocument(
            title="Candidate whitespace",
            blocks=[
                Heading(
                    text="Open   file\tstrategy",
                    level=1,
                    block_id="candidate-spacing",
                ),
            ],
        )
        index = BookIndex(document)

        matches = index.find("Open file strategy")
        self.assertEqual(
            [entry.target.key for entry in matches],
            ["block:candidate-spacing"],
        )
        self.assertEqual(matches[0].label, "Open   file\tstrategy")


    def test_find_covers_all_list_items_without_duplicate_targets_or_mutable_aliases(self):
        document = BookDocument(
            title="Search every item",
            blocks=[
                Heading(text="Chapter", level=1, block_id="heading"),
                ListBlock(
                    items=[
                        "Opening choices",
                        "Second  knight\tstrategy ...Nf6",
                        "Café pawn structures ...Nf6",
                    ],
                    ordered=True,
                    block_id="main-list",
                ),
                ListBlock(
                    items=["Counterplay", "Black replies ...Nf6"],
                    ordered=False,
                    source_anchor="reply-list",
                ),
                Paragraph(text="Independent commentary", block_id="prose"),
            ],
        )
        index = BookIndex(document)

        # Multiple matching items yield ONE navigable entry per ListBlock.
        found = index.find("Nf6", kinds={BookEntryKind.LIST})
        self.assertEqual(
            [entry.target.key for entry in found],
            ["block:main-list", "source:reply-list"],
        )
        self.assertEqual([entry.target.index for entry in found], [1, 2])
        self.assertEqual([entry.label for entry in found], ["Opening choices", "Counterplay"])
        self.assertIs(index.resolve(found[0].target), found[0])
        self.assertEqual(index.find("Nf6", kinds={BookEntryKind.PARAGRAPH}), ())

        # Non-label items reuse the SAME Unicode/whitespace search authority.
        spaced = index.find("second knight strategy")
        self.assertEqual([entry.target.key for entry in spaced], ["block:main-list"])
        accent = index.find("Cafe\u0301 pawn")
        self.assertEqual([entry.target.key for entry in accent], ["block:main-list"])
        self.assertEqual(index.find("Opening choices")[0].label, "Opening choices")

        # Search and labels are detached from later authoring mutations.
        source_list = document.blocks[1]
        self.assertIsInstance(source_list, ListBlock)
        source_list.items[1] = "Changed after indexing"
        source_list.items.append("New appended item")
        document.blocks.reverse()
        self.assertEqual(
            [entry.target.key for entry in index.find("Nf6")],
            ["block:main-list", "source:reply-list"],
        )
        self.assertEqual(index.find("Changed after indexing"), ())
        self.assertEqual(index.find("New appended item"), ())
        self.assertEqual(index.entries[1].label, "Opening choices")

    def test_find_bounds_raw_query_before_normalization(self):
        index = BookIndex(self.make_document())

        # The 4096 raw-input fence runs before Unicode/whitespace normalization.
        with self.assertRaisesRegex(ValueError, "exceeds 4096"):
            index.find(" " * 4097)
        # The shared semantic search policy remains the tighter user-term limit.
        with self.assertRaisesRegex(ValueError, "maximum search term length"):
            index.find("x" * 257)
        self.assertEqual(index.find("x" * 256), ())

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

    def test_snapshot_gate_late_binds_live_stacked_parent(self) -> None:
        workflow = (
            Path(__file__).resolve().parents[1]
            / ".github"
            / "workflows"
            / "v2-book-index-snapshot-integrity.yml"
        ).read_text(encoding="utf-8")

        self.assertIn('base_ref="${{ github.base_ref }}"', workflow)
        self.assertIn("event_base='${{ github.event.pull_request.base.sha }}'", workflow)
        self.assertIn(
            '"refs/heads/$base_ref:refs/remotes/origin/$base_ref"',
            workflow,
        )
        self.assertIn(
            'live_base="$(git rev-parse "refs/remotes/origin/$base_ref")"',
            workflow,
        )
        self.assertIn(
            'git merge-base --is-ancestor "$event_base" "$live_base"',
            workflow,
        )
        self.assertIn(
            'git merge-base --is-ancestor "$live_base" HEAD',
            workflow,
        )
        self.assertNotIn('product_ref="work/full-product-teacher-education-reachability-20260911"', workflow)


if __name__ == "__main__":
    unittest.main()
