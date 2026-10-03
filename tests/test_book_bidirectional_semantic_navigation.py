from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import patch

from acs.book_webview_bridge import BookWebViewBridge
from acs.book_webview_projection import BookWebViewProjection
from acs.bookdocument import BookDocument, Diagram, Exercise, Game, Heading, ListBlock, Paragraph, Position, VariationTree
from acs.bookreader import BookReader
from acs.chesscore import Board
from acs.full_product_actions import FULL_PRODUCT_ACTION_IDS
from acs.full_product_presenters import BookReaderPresenter
from acs.full_product_ui_shell import UILanguage
from acs.version2_application import Version2Application


class CountingBlocks(list):
    def __init__(self, values):
        super().__init__(values)
        self.reads = 0

    def __getitem__(self, index):
        if isinstance(index, int):
            self.reads += 1
        return super().__getitem__(index)


class BookBidirectionalSemanticNavigationTests(unittest.TestCase):
    def make_document(self) -> BookDocument:
        return BookDocument(
            title="Semantic navigation",
            blocks=[
                Heading(text="Chapter", level=1, block_id="heading"),
                Position(fen=Board.START, caption="Start", block_id="position-1"),
                Paragraph(text="Between position and game", block_id="paragraph-1"),
                Game(pgn='[Result "*"]\n\n1. e4 *', title="Game one", block_id="game-1"),
                Diagram(
                    fen=Board.START,
                    caption="Diagram",
                    alt_text="Initial chess position",
                    block_id="position-2",
                ),
                Paragraph(text="Between games", block_id="paragraph-2"),
                Game(pgn='[Result "*"]\n\n1. d4 *', title="Game two", block_id="game-2"),
            ],
        )

    def test_reverse_commands_are_registered_and_progress_atomic(self) -> None:
        for command in ("book.previous_position", "book.previous_game"):
            with self.subTest(command=command):
                self.assertIn(command, FULL_PRODUCT_ACTION_IDS)
                self.assertIn(command, Version2Application._BOOK_PROGRESS_COMMANDS)

    def test_reader_navigates_positions_and_games_in_both_directions(self) -> None:
        reader = BookReader(self.make_document())

        self.assertEqual(reader.next_position().block_id, "position-1")
        self.assertEqual(reader.next_position().block_id, "position-2")
        self.assertEqual(reader.previous_position().block_id, "position-1")

        self.assertEqual(reader.next_game().block_id, "game-1")
        self.assertEqual(reader.next_game().block_id, "game-2")
        self.assertEqual(reader.previous_game().block_id, "game-1")

    def test_reverse_position_semantics_include_exercises_and_variation_trees(self) -> None:
        document = BookDocument(
            title="Position-like semantics",
            blocks=[
                Position(fen=Board.START, block_id="position"),
                Exercise(fen=Board.START, prompt="Find a move", answer_text="e4", block_id="exercise"),
                VariationTree(root_fen=Board.START, pgn="1. e4 *", block_id="variation"),
                Diagram(fen=Board.START, alt_text="Board", block_id="diagram"),
            ],
        )
        reader = BookReader(document)

        self.assertEqual(reader.next_position().block_id, "exercise")
        self.assertEqual(reader.next_position().block_id, "variation")
        self.assertEqual(reader.next_position().block_id, "diagram")
        self.assertEqual(reader.previous_position().block_id, "variation")
        self.assertEqual(reader.previous_position().block_id, "exercise")
        self.assertEqual(reader.previous_position().block_id, "position")

    def test_reverse_boundaries_fail_closed_without_moving_cursor(self) -> None:
        reader = BookReader(self.make_document())
        reader.go_to(1)
        before = reader.location()
        with self.assertRaisesRegex(LookupError, "No matching semantic block"):
            reader.previous_position()
        self.assertEqual(reader.location(), before)

        reader.go_to(3)
        before = reader.location()
        with self.assertRaisesRegex(LookupError, "No matching semantic block"):
            reader.previous_game()
        self.assertEqual(reader.location(), before)

    def test_navigation_availability_is_exact_and_non_mutating(self) -> None:
        reader = BookReader(self.make_document())
        start = reader.location()
        availability = reader.navigation_availability()
        self.assertEqual(reader.location(), start)
        self.assertFalse(availability["previous"])
        self.assertFalse(availability["previous_heading"])
        self.assertFalse(availability["previous_position"])
        self.assertFalse(availability["previous_game"])
        self.assertTrue(availability["next"])
        self.assertTrue(availability["next_position"])
        self.assertTrue(availability["next_game"])

        reader.go_to(6)
        end = reader.location()
        availability = reader.navigation_availability()
        self.assertEqual(reader.location(), end)
        self.assertFalse(availability["next"])
        self.assertFalse(availability["next_heading"])
        self.assertFalse(availability["next_position"])
        self.assertFalse(availability["next_game"])
        self.assertTrue(availability["previous_heading"])
        self.assertTrue(availability["previous_position"])
        self.assertTrue(availability["previous_game"])

    def test_navigation_availability_exactly_matches_every_navigation_command(self) -> None:
        base = self.make_document()
        document = BookDocument(
            title="Semantic availability equivalence",
            blocks=[
                *base.blocks,
                Heading(text="Appendix", level=2, block_id="heading-2"),
                Paragraph(text="Appendix context", block_id="paragraph-3"),
                Position(fen=Board.START, caption="Appendix position", block_id="position-3"),
                Game(
                    pgn='[Result "*"]\n\n1. c4 *',
                    title="Game three",
                    block_id="game-3",
                ),
            ],
        )
        commands = (
            ("previous", "previous_block", -1),
            ("next", "next_block", 1),
            ("previous_heading", "previous_heading", -1),
            ("next_heading", "next_heading", 1),
            ("previous_position", "previous_position", -1),
            ("next_position", "next_position", 1),
            ("previous_game", "previous_game", -1),
            ("next_game", "next_game", 1),
        )

        for index in range(len(document.blocks)):
            for availability_key, method_name, direction in commands:
                with self.subTest(
                    index=index,
                    availability_key=availability_key,
                ):
                    reader = BookReader(document)
                    reader.go_to(index)
                    before = reader.location()
                    availability = reader.navigation_availability()
                    self.assertEqual(before, reader.location())

                    command = getattr(reader, method_name)
                    if availability[availability_key]:
                        reached = command()
                        self.assertGreater(
                            (reached.index - index) * direction,
                            0,
                        )
                    else:
                        with self.assertRaises(LookupError):
                            command()
                        self.assertEqual(before, reader.location())

    def test_navigation_availability_scans_each_direction_at_most_once(self) -> None:
        document = self.make_document()
        reader = BookReader(document)
        counted = CountingBlocks(document.blocks)
        document.blocks = counted
        reader.go_to(3)
        counted.reads = 0

        availability = reader.navigation_availability()

        self.assertTrue(availability["previous_heading"])
        self.assertTrue(availability["previous_position"])
        self.assertFalse(availability["previous_game"])
        self.assertFalse(availability["next_heading"])
        self.assertTrue(availability["next_position"])
        self.assertTrue(availability["next_game"])
        self.assertLessEqual(counted.reads, 2 * (len(counted) - 1))

    def test_presenter_never_rereads_live_block_after_location_validation(self) -> None:
        document = self.make_document()
        reader = BookReader(document)
        presenter = BookReaderPresenter(reader, language=UILanguage.EN)
        original_location = reader.location

        def location_then_mutate():
            location = original_location()
            document.blocks[0].text = "Concurrent replacement"
            return location

        reader.location = location_then_mutate
        with self.assertRaisesRegex(RuntimeError, "changed after BookReader creation"):
            presenter.current()
        self.assertEqual(reader.index, 0)

    def test_list_block_preserves_native_list_semantics_in_webview_projection(self) -> None:
        document = BookDocument(
            title="Structured list",
            blocks=[
                ListBlock(
                    items=["Перший пункт", "Другий пункт"],
                    ordered=True,
                    start=3,
                    block_id="steps",
                )
            ],
        )
        presenter = BookReaderPresenter(BookReader(document), language=UILanguage.UA)
        view = presenter.current()
        self.assertEqual(view.role, "list")
        self.assertEqual(view.list_items, ("Перший пункт", "Другий пункт"))
        self.assertTrue(view.list_ordered)
        self.assertEqual(view.list_start, 3)

        projection = BookWebViewProjection(
            presenter,
            lambda *_: self.fail("list rendering must not dispatch domain mutation"),
            language=UILanguage.UA,
        )
        block = projection.snapshot()["block"]
        self.assertEqual(
            block["list"],
            {
                "items": ("Перший пункт", "Другий пункт"),
                "ordered": True,
                "start": 3,
            },
        )
        self.assertEqual(block["role"], "list")
        self.assertEqual(block["text"], "")

    def test_projection_preserves_complete_text_beyond_legacy_preview_cap(self) -> None:
        long_text = "Початок " + ("абвгд" * 1800) + " Кінець"
        document = BookDocument(
            title="Long readable block",
            blocks=[Paragraph(text=long_text, block_id="long")],
        )
        projection = BookWebViewProjection(
            BookReaderPresenter(BookReader(document), language=UILanguage.UA),
            lambda *_: None,
            language=UILanguage.UA,
        )

        block = projection.snapshot()["block"]
        self.assertGreater(len(long_text), 8000)
        self.assertEqual(block["text"], long_text)
        self.assertTrue(block["text"].endswith(" Кінець"))

    def test_projection_fails_closed_before_exceeding_visible_text_budget(self) -> None:
        document = BookDocument(
            title="Bounded rendering",
            blocks=[Paragraph(text="12345678901", block_id="oversize")],
        )
        projection = BookWebViewProjection(
            BookReaderPresenter(BookReader(document), language=UILanguage.EN),
            lambda *_: None,
            language=UILanguage.EN,
        )

        with patch("acs.book_webview_projection._MAX_BOOK_BLOCK_VISIBLE_CHARS", 10):
            with self.assertRaisesRegex(ValueError, "visible-text budget"):
                projection.snapshot()

    def test_projection_disables_unreachable_semantic_actions(self) -> None:
        reader = BookReader(self.make_document())
        presenter = BookReaderPresenter(reader, language=UILanguage.EN)
        projection = BookWebViewProjection(presenter, lambda *_: None, language=UILanguage.EN)

        start_actions = {action["command"]: action["enabled"] for action in projection.snapshot()["actions"]}
        self.assertFalse(start_actions["book.previous_position"])
        self.assertFalse(start_actions["book.previous_game"])
        self.assertTrue(start_actions["book.next_position"])
        self.assertTrue(start_actions["book.next_game"])

        reader.go_to(6)
        end_actions = {action["command"]: action["enabled"] for action in projection.snapshot()["actions"]}
        self.assertTrue(end_actions["book.previous_position"])
        self.assertTrue(end_actions["book.previous_game"])
        self.assertFalse(end_actions["book.next_position"])
        self.assertFalse(end_actions["book.next_game"])

    def test_presenter_and_bridge_keep_reverse_navigation_semantic(self) -> None:
        reader = BookReader(self.make_document())
        presenter = BookReaderPresenter(reader, language=UILanguage.EN)
        projection = BookWebViewProjection(
            presenter,
            lambda *_: self.fail("semantic navigation must not dispatch chess mutation"),
            language=UILanguage.EN,
        )
        bridge = BookWebViewBridge(projection)

        reader.go_to(6)
        previous_game = bridge.dispatch("book.previous_game", {})
        self.assertEqual(previous_game.kind, "render")
        self.assertEqual(previous_game.payload["snapshot"]["block"]["index"], 3)
        self.assertEqual(previous_game.payload["focus_target"], "book-block-3")

        previous_position = bridge.dispatch("book.previous_position", {})
        self.assertEqual(previous_position.kind, "render")
        self.assertEqual(previous_position.payload["snapshot"]["block"]["index"], 1)
        self.assertEqual(previous_position.payload["focus_target"], "book-block-1")

    def test_projection_exposes_localized_reverse_actions(self) -> None:
        reader = BookReader(self.make_document())
        reader.go_to(6)
        presenter = BookReaderPresenter(reader, language=UILanguage.EN)
        projection = BookWebViewProjection(presenter, lambda *_: None, language=UILanguage.EN)

        en_actions = {action["command"]: action["label"] for action in projection.snapshot()["actions"]}
        self.assertEqual(en_actions["book.previous_position"], "Previous position")
        self.assertEqual(en_actions["book.previous_game"], "Previous game")

        ua = projection.set_language(UILanguage.UA).payload["snapshot"]
        ua_actions = {action["command"]: action["label"] for action in ua["actions"]}
        self.assertEqual(ua_actions["book.previous_position"], "Попередня позиція")
        self.assertEqual(ua_actions["book.previous_game"], "Попередня партія")

    def test_language_render_failure_rolls_back_projection_and_presenter(self) -> None:
        document = BookDocument(
            title="Language rollback",
            blocks=[Position(fen=Board.START, block_id="position")],
        )
        presenter = BookReaderPresenter(BookReader(document), language=UILanguage.EN)
        projection = BookWebViewProjection(
            presenter,
            lambda *_: None,
            language=UILanguage.EN,
        )
        bridge = BookWebViewBridge(projection)

        with patch.object(
            presenter,
            "navigation_availability",
            side_effect=RuntimeError("synthetic render failure"),
        ):
            result = bridge.dispatch("book.language", {"language": "ua"})

        self.assertEqual(result.kind, "error")
        self.assertEqual(projection.language, UILanguage.EN)
        snapshot = projection.snapshot()
        self.assertEqual(snapshot["document"]["lang"], "en")
        self.assertEqual(snapshot["heading"], "Chess book reader")
        self.assertEqual(snapshot["block"]["title"], "Position")

    def test_d01_shared_gate_preserves_product_stage1_and_books_successors(self) -> None:
        source = (
            Path(__file__).parents[1]
            / ".github"
            / "workflows"
            / "d01-pgn-workspace-webview.yml"
        ).read_text(encoding="utf-8")

        self.assertIn(
            'if [ "${{ github.event.pull_request.head.ref }}" = "integration/clock-engine-serial-intake-20261002" ]; then',
            source,
        )
        self.assertIn(
            "test \"$stage1_core_actual\" = b579ca0f59ba20f6b69b3a4b7d89589256d54852",
            source,
        )
        self.assertIn(
            "16e78af6219c8c36f0c4026942ef1d02875a370a|c8629e690a10fa8e10a2053fdc85284f635d2beb|2ac3ca8943e6a4a819e4f273992167f9cf0b47ce",
            source,
        )
        self.assertIn(
            "a752bb6b837d0332ad69047912dffeb537c7bd3f|678812ff028522c36b5c76df743dd2e0bac240c0|b279f68e907038acfaa1754f3e7de76ef541793c",
            source,
        )
        self.assertIn(
            "b6be4376cbe0695136210c3b5b850cdf562f85a4|c30874e661e958db15856a250e414520467c095c",
            source,
        )
        self.assertNotIn(
            "acs/full_product_presenters.py=a752bb6b837d0332ad69047912dffeb537c7bd3f",
            source,
        )
        self.assertNotIn(
            "acs/full_product_actions.py=b6be4376cbe0695136210c3b5b850cdf562f85a4",
            source,
        )

    def test_bridge_rejects_payload_injection_for_reverse_commands(self) -> None:
        presenter = BookReaderPresenter(BookReader(self.make_document()), language=UILanguage.EN)
        bridge = BookWebViewBridge(
            BookWebViewProjection(presenter, lambda *_: None, language=UILanguage.EN)
        )
        before = presenter.current()
        for command in ("book.previous_position", "book.previous_game"):
            result = bridge.dispatch(command, {"index": 0})
            self.assertEqual(result.kind, "error")
            self.assertEqual(presenter.current(), before)


if __name__ == "__main__":
    unittest.main()
