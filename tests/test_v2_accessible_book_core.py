from __future__ import annotations

import unittest

from acs.bookdocument import (
    BookDocument,
    BookDocumentError,
    Diagram,
    Exercise,
    Game,
    Heading,
    ListBlock,
    Paragraph,
    Position,
    VariationTree,
)
from acs.bookreader import BookReader
from acs.chesscore import Board


LEGAL_FEN = "8/8/8/8/8/8/4K3/7k w - - 0 1"
INVALID_CANONICAL_FEN = "8/8/8/8/8/8/8/8 w - - 0 1"
PUBLIC_DOMAIN_SOURCE = "Project Gutenberg eBook #16377 — The Blue Book of Chess"
PUBLIC_DOMAIN_URI = "https://www.gutenberg.org/ebooks/16377"
PUBLIC_DOMAIN_RIGHTS = "Project Gutenberg metadata: public domain in the USA"


class V2AccessibleBookCoreTests(unittest.TestCase):
    def test_all_book_position_blocks_delegate_to_canonical_board_validation(self) -> None:
        factories = (
            lambda: Position(fen=INVALID_CANONICAL_FEN),
            lambda: Diagram(fen=INVALID_CANONICAL_FEN, alt_text="Empty board"),
            lambda: VariationTree(root_fen=INVALID_CANONICAL_FEN, pgn="*"),
            lambda: Exercise(fen=INVALID_CANONICAL_FEN, prompt="Move", answer_text="Ke2"),
        )
        for factory in factories:
            with self.subTest(factory=factory):
                with self.assertRaises(BookDocumentError):
                    factory()

        # Positive control: the exact same shared Board contract accepts the legal position.
        self.assertEqual(Board(LEGAL_FEN).fen(), LEGAL_FEN)

    def test_book_extend_is_atomic_when_mutated_position_fails_revalidation(self) -> None:
        document = BookDocument("Atomic book", blocks=[Paragraph(text="Existing content")])
        poisoned = Position(fen=LEGAL_FEN, caption="Will be invalidated")
        poisoned.fen = INVALID_CANONICAL_FEN

        before = document.as_dict()
        with self.assertRaises(BookDocumentError):
            document.extend(
                [
                    Heading(text="New section", level=1, block_id="new-section"),
                    poisoned,
                ]
            )
        self.assertEqual(document.as_dict(), before)
        self.assertEqual(len(document.blocks), 1)

    def test_legacy_v1_without_enriched_provenance_keeps_exact_wire_shape(self) -> None:
        legacy = {
            "schema_version": 1,
            "title": "Legacy book",
            "language": "en",
            "author": "Author",
            "source_name": "legacy-source",
            "warnings": [],
            "blocks": [{"kind": "Paragraph", "text": "Existing semantic text"}],
        }
        restored = BookDocument.from_dict(legacy)
        self.assertEqual(restored.as_dict(), legacy)
        self.assertIsNone(restored.source_uri)
        self.assertIsNone(restored.source_rights)

    def test_semantic_sections_lists_provenance_and_navigation_are_deterministic(self) -> None:
        document = BookDocument(
            "The Blue Book of Chess",
            language="en",
            author="Howard Staunton",
            source_name=PUBLIC_DOMAIN_SOURCE,
            source_uri=PUBLIC_DOMAIN_URI,
            source_rights=PUBLIC_DOMAIN_RIGHTS,
            blocks=[
                Heading(text="Part I", level=1, block_id="part-1", source_anchor="part-i"),
                Heading(text="First principles", level=2, block_id="chapter-1", source_anchor="chapter-i"),
                Paragraph(
                    text="A semantic reading fixture derived from a lawful public-domain chess source.",
                    source_anchor="chapter-i-intro",
                ),
                ListBlock(
                    items=["Board and men", "Notation", "Fundamental rules"],
                    ordered=True,
                    start=1,
                    block_id="contents-list",
                    source_anchor="contents",
                ),
                Diagram(
                    fen=LEGAL_FEN,
                    caption="King ending",
                    alt_text="White king e2; black king h1.",
                    block_id="diagram-1",
                    source_anchor="diagram-1",
                ),
                Game(
                    pgn='[Event "Example"]\n[Result "*"]\n\n1. e4 e5 *',
                    title="Embedded example game",
                    block_id="game-1",
                    source_anchor="game-1",
                ),
                VariationTree(
                    root_fen=LEGAL_FEN,
                    pgn='[SetUp "1"]\n[FEN "8/8/8/8/8/8/4K3/7k w - - 0 1"]\n[Result "*"]\n\n1. Kf3 (1. Kd3) *',
                    title="King alternatives",
                    block_id="variation-1",
                    source_anchor="variation-1",
                ),
            ],
        )

        round_trip = BookDocument.from_dict(document.as_dict())
        self.assertEqual(round_trip.as_dict(), document.as_dict())
        self.assertEqual(round_trip.source_name, PUBLIC_DOMAIN_SOURCE)
        self.assertEqual(round_trip.source_uri, PUBLIC_DOMAIN_URI)
        self.assertEqual(round_trip.source_rights, PUBLIC_DOMAIN_RIGHTS)
        self.assertEqual(round_trip.lists()[0].items, ["Board and men", "Notation", "Fundamental rules"])
        self.assertTrue(round_trip.lists()[0].ordered)

        reader = BookReader(round_trip)
        self.assertEqual(reader.location().heading_path, ("Part I",))
        self.assertEqual(reader.next_heading().heading_path, ("Part I", "First principles"))
        self.assertEqual(reader.next_block().kind, "Paragraph")
        list_location = reader.next_block()
        self.assertEqual(list_location.kind, "List")
        self.assertEqual(list_location.heading_path, ("Part I", "First principles"))

        reader.save_return_point("list")
        self.assertEqual(reader.next_position().kind, "Diagram")
        self.assertEqual(reader.next_game().kind, "Game")
        self.assertEqual(reader.restore_return_point("list").index, list_location.index)

        snapshot = reader.snapshot()
        restored = BookReader.restore_snapshot(round_trip, snapshot)
        self.assertEqual(restored.location(), reader.location())

    def test_list_semantics_fail_closed_instead_of_flattening_invalid_content(self) -> None:
        invalid_cases = (
            lambda: ListBlock(items=[]),
            lambda: ListBlock(items=["ok", ""]),
            lambda: ListBlock(items=["ok"], ordered=1),
            lambda: ListBlock(items=["ok"], ordered=False, start=1),
            lambda: ListBlock(items=["ok"], ordered=True, start=0),
        )
        for factory in invalid_cases:
            with self.subTest(factory=factory):
                with self.assertRaises(BookDocumentError):
                    factory()


if __name__ == "__main__":
    unittest.main()
