from __future__ import annotations

import unittest

from acs.book_webview_bridge import BookWebViewBridge
from acs.book_webview_projection import BookWebViewProjection
from acs.bookdocument import BookDocument, Diagram, Game, Heading, Paragraph, Position
from acs.bookreader import BookReader
from acs.chesscore import Board
from acs.full_product_presenters import BookReaderPresenter
from acs.full_product_ui_shell import UILanguage


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

    def test_reader_navigates_positions_and_games_in_both_directions(self) -> None:
        reader = BookReader(self.make_document())

        self.assertEqual(reader.next_position().block_id, "position-1")
        self.assertEqual(reader.next_position().block_id, "position-2")
        self.assertEqual(reader.previous_position().block_id, "position-1")

        self.assertEqual(reader.next_game().block_id, "game-1")
        self.assertEqual(reader.next_game().block_id, "game-2")
        self.assertEqual(reader.previous_game().block_id, "game-1")

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
