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

    def make_extended_document(self) -> BookDocument:
        base = self.make_document()
        return BookDocument(
            title="Semantic availability equivalence",
            blocks=[
                *base.blocks,
                Heading(text="Appendix", level=2, block_id="heading-2"),
                Exercise(
                    fen=Board.START,
                    prompt="Find the semantic move",
                    answer_text="e4",
                    block_id="exercise-1",
                ),
                Paragraph(text="Exercise context", block_id="paragraph-3"),
                VariationTree(
                    root_fen=Board.START,
                    pgn="1. e4 *",
                    block_id="variation-1",
                ),
                ListBlock(
                    items=["First semantic item", "Second semantic item"],
                    ordered=False,
                    block_id="list-1",
                ),
                Position(
                    fen=Board.START,
                    caption="Appendix position",
                    block_id="position-3",
                ),
                Game(
                    pgn='[Result "*"]\n\n1. c4 *',
                    title="Game three",
                    block_id="game-3",
                ),
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
        document = self.make_extended_document()
        position_types = (Position, Diagram, Exercise, VariationTree)
        commands = (
            ("previous", "previous_block", -1, lambda block: True),
            ("next", "next_block", 1, lambda block: True),
            ("previous_heading", "previous_heading", -1, lambda block: isinstance(block, Heading)),
            ("next_heading", "next_heading", 1, lambda block: isinstance(block, Heading)),
            (
                "previous_position",
                "previous_position",
                -1,
                lambda block: isinstance(block, position_types),
            ),
            (
                "next_position",
                "next_position",
                1,
                lambda block: isinstance(block, position_types),
            ),
            ("previous_game", "previous_game", -1, lambda block: isinstance(block, Game)),
            ("next_game", "next_game", 1, lambda block: isinstance(block, Game)),
        )

        for index in range(len(document.blocks)):
            for availability_key, method_name, direction, matches in commands:
                with self.subTest(
                    index=index,
                    availability_key=availability_key,
                ):
                    candidate = index + direction
                    expected_index = None
                    while 0 <= candidate < len(document.blocks):
                        if matches(document.blocks[candidate]):
                            expected_index = candidate
                            break
                        candidate += direction

                    reader = BookReader(document)
                    reader.go_to(index)
                    before = reader.location()
                    availability = reader.navigation_availability()
                    self.assertEqual(before, reader.location())
                    self.assertEqual(
                        expected_index is not None,
                        availability[availability_key],
                        msg=(
                            f"{availability_key} availability disagrees with nearest "
                            f"semantic target from cursor {index}"
                        ),
                    )

                    command = getattr(reader, method_name)
                    if expected_index is not None:
                        reached = command()
                        self.assertEqual(
                            expected_index,
                            reached.index,
                            msg=(
                                f"{method_name} skipped the nearest semantic target "
                                f"from cursor {index}"
                            ),
                        )
                        self.assertEqual(reached, reader.location())
                    else:
                        with self.assertRaises(LookupError):
                            command()
                        self.assertEqual(before, reader.location())

    def test_navigation_availability_scans_each_direction_exactly_once(self) -> None:
        document = self.make_document()
        reader = BookReader(document)
        reader.go_to(3)

        # BookReader navigates its detached indexed revision, not the mutable
        # source BookDocument. Instrument the exact collection the scan reads;
        # wrapping document.blocks here would be a false-green counter.
        counted = CountingBlocks(reader._indexed_document.blocks)
        reader._indexed_document.blocks = counted
        counted.reads = 0

        availability = reader.navigation_availability()

        self.assertTrue(availability["previous_heading"])
        self.assertTrue(availability["previous_position"])
        self.assertFalse(availability["previous_game"])
        self.assertFalse(availability["next_heading"])
        self.assertTrue(availability["next_position"])
        self.assertTrue(availability["next_game"])
        # Cursor 3 has three blocks on each side. Because each side is missing
        # one semantic class, both scans must reach the boundary: exactly six
        # indexed block reads, not zero and not repeated per semantic class.
        self.assertEqual(counted.reads, 6)

    def test_navigation_availability_stops_after_all_semantic_classes_are_found(self) -> None:
        document = BookDocument(
            title="Bounded semantic scan",
            blocks=[
                Paragraph(text="far previous", block_id="far-previous"),
                Game(pgn='[Result "*"]\n\n1. e4 *', title="Previous game", block_id="previous-game"),
                Position(fen=Board.START, block_id="previous-position"),
                Heading(text="Previous heading", level=2, block_id="previous-heading"),
                Paragraph(text="cursor", block_id="cursor"),
                Heading(text="Next heading", level=2, block_id="next-heading"),
                Exercise(
                    fen=Board.START,
                    prompt="Next position-like block",
                    answer_text="e4",
                    block_id="next-position",
                ),
                Game(pgn='[Result "*"]\n\n1. d4 *', title="Next game", block_id="next-game"),
                Paragraph(text="far next", block_id="far-next"),
            ],
        )
        reader = BookReader(document)
        reader.go_to(4)
        counted = CountingBlocks(reader._indexed_document.blocks)
        reader._indexed_document.blocks = counted
        counted.reads = 0

        availability = reader.navigation_availability()

        self.assertTrue(all(availability.values()))
        self.assertEqual(counted.reads, 6)

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

    def test_projection_fails_closed_on_excessive_list_item_count(self) -> None:
        document = BookDocument(
            title="Bounded list nodes",
            blocks=[
                ListBlock(
                    items=["One", "Two"],
                    ordered=False,
                    block_id="bounded-list",
                )
            ],
        )
        projection = BookWebViewProjection(
            BookReaderPresenter(BookReader(document), language=UILanguage.EN),
            lambda *_: None,
            language=UILanguage.EN,
        )

        with patch("acs.book_webview_projection._MAX_BOOK_LIST_ITEMS", 1):
            with self.assertRaisesRegex(ValueError, "item-count budget"):
                projection.snapshot()

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

    def test_projection_action_enabled_state_matches_reader_at_every_cursor(self) -> None:
        document = self.make_extended_document()
        command_to_availability = {
            "book.previous": "previous",
            "book.next": "next",
            "book.previous_heading": "previous_heading",
            "book.next_heading": "next_heading",
            "book.previous_position": "previous_position",
            "book.next_position": "next_position",
            "book.previous_game": "previous_game",
            "book.next_game": "next_game",
        }

        for index in range(len(document.blocks)):
            with self.subTest(index=index):
                reader = BookReader(document)
                reader.go_to(index)
                presenter = BookReaderPresenter(reader, language=UILanguage.EN)
                projection = BookWebViewProjection(
                    presenter,
                    lambda *_: None,
                    language=UILanguage.EN,
                )
                expected = reader.navigation_availability()
                snapshot = projection.snapshot()
                self.assertEqual(index, snapshot["block"]["index"])

                actions = {
                    action["command"]: action["enabled"]
                    for action in snapshot["actions"]
                    if action["command"] in command_to_availability
                }
                self.assertEqual(set(command_to_availability), set(actions))
                self.assertEqual(
                    {
                        command: expected[availability_key]
                        for command, availability_key in command_to_availability.items()
                    },
                    actions,
                )

    def test_bridge_dispatch_matches_nearest_semantic_target_at_every_cursor(self) -> None:
        document = self.make_extended_document()
        position_types = (Position, Diagram, Exercise, VariationTree)
        commands = (
            ("book.previous", -1, lambda block: True),
            ("book.next", 1, lambda block: True),
            ("book.previous_heading", -1, lambda block: isinstance(block, Heading)),
            ("book.next_heading", 1, lambda block: isinstance(block, Heading)),
            (
                "book.previous_position",
                -1,
                lambda block: isinstance(block, position_types),
            ),
            (
                "book.next_position",
                1,
                lambda block: isinstance(block, position_types),
            ),
            ("book.previous_game", -1, lambda block: isinstance(block, Game)),
            ("book.next_game", 1, lambda block: isinstance(block, Game)),
        )

        for index in range(len(document.blocks)):
            for command, direction, matches in commands:
                with self.subTest(index=index, command=command):
                    candidate = index + direction
                    expected_index = None
                    while 0 <= candidate < len(document.blocks):
                        if matches(document.blocks[candidate]):
                            expected_index = candidate
                            break
                        candidate += direction

                    reader = BookReader(document)
                    reader.go_to(index)
                    presenter = BookReaderPresenter(reader, language=UILanguage.EN)
                    bridge = BookWebViewBridge(
                        BookWebViewProjection(
                            presenter,
                            lambda *_: self.fail(
                                "semantic navigation must not dispatch chess mutation"
                            ),
                            language=UILanguage.EN,
                        )
                    )

                    result = bridge.dispatch(command, {})
                    if expected_index is None:
                        self.assertEqual(result.kind, "error")
                        self.assertEqual(reader.index, index)
                    else:
                        self.assertEqual(result.kind, "render")
                        self.assertEqual(
                            result.payload["snapshot"]["block"]["index"],
                            expected_index,
                        )
                        self.assertEqual(
                            result.payload["focus_target"],
                            f"book-block-{expected_index}",
                        )
                        self.assertEqual(reader.index, expected_index)

    def test_open_position_action_matches_position_like_semantics_at_every_cursor(self) -> None:
        document = self.make_extended_document()
        position_types = (Position, Diagram, Exercise, VariationTree)

        for index, block in enumerate(document.blocks):
            with self.subTest(index=index, block_type=type(block).__name__):
                reader = BookReader(document)
                reader.go_to(index)
                dispatched: list[tuple[str, dict[str, object]]] = []

                def dispatch(command: str, payload) -> object:
                    dispatched.append((command, dict(payload)))
                    return object()

                projection = BookWebViewProjection(
                    BookReaderPresenter(reader, language=UILanguage.EN),
                    dispatch,
                    language=UILanguage.EN,
                )
                bridge = BookWebViewBridge(projection)
                actions = {
                    action["command"]: action["enabled"]
                    for action in projection.snapshot()["actions"]
                }
                expected = isinstance(block, position_types)
                self.assertEqual(actions["book.open_position"], expected)

                result = bridge.dispatch("book.open_position", {})
                if expected:
                    self.assertEqual(result.kind, "delegated")
                    self.assertEqual(len(dispatched), 1)
                    command, payload = dispatched[0]
                    self.assertEqual(command, "book.open_position")
                    self.assertEqual(payload["book_index"], index)
                    self.assertEqual(payload["fen"], Board.START)
                    self.assertEqual(reader.index, index)
                else:
                    self.assertEqual(result.kind, "error")
                    self.assertEqual(dispatched, [])
                    self.assertEqual(reader.index, index)

    def test_open_game_action_matches_game_semantics_at_every_cursor(self) -> None:
        document = self.make_extended_document()

        for index, block in enumerate(document.blocks):
            with self.subTest(index=index, block_type=type(block).__name__):
                reader = BookReader(document)
                reader.go_to(index)
                dispatched: list[tuple[str, dict[str, object]]] = []

                def dispatch(command: str, payload) -> object:
                    dispatched.append((command, dict(payload)))
                    return object()

                projection = BookWebViewProjection(
                    BookReaderPresenter(reader, language=UILanguage.EN),
                    dispatch,
                    language=UILanguage.EN,
                )
                bridge = BookWebViewBridge(projection)
                actions = {
                    action["command"]: action["enabled"]
                    for action in projection.snapshot()["actions"]
                }
                expected = isinstance(block, Game)
                self.assertEqual(actions["book.open_game"], expected)

                result = bridge.dispatch("book.open_game", {})
                if expected:
                    self.assertEqual(result.kind, "delegated")
                    self.assertEqual(
                        result.payload,
                        {
                            "action": "book.open_game",
                            "announcement": "Game opened on the board.",
                        },
                    )
                    self.assertEqual(dispatched, [("book.open_game", {})])
                    self.assertEqual(reader.index, index)
                    reader.go_to(0)
                    returned = bridge.dispatch("book.return_from_board", {})
                    self.assertEqual(returned.kind, "render")
                    self.assertEqual(
                        returned.payload["snapshot"]["block"]["index"],
                        index,
                    )
                    self.assertEqual(
                        returned.payload["focus_target"],
                        f"book-block-{index}",
                    )
                    self.assertEqual(reader.index, index)
                else:
                    self.assertEqual(result.kind, "error")
                    self.assertEqual(dispatched, [])
                    self.assertEqual(reader.index, index)

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


    def test_failed_position_handoff_does_not_publish_phantom_return_point(self) -> None:
        reader = BookReader(self.make_extended_document())
        reader.go_to(1)
        presenter = BookReaderPresenter(reader, language=UILanguage.EN)

        def fail_dispatch(_command: str, _payload) -> object:
            raise RuntimeError("synthetic position handoff failure")

        with self.assertRaisesRegex(RuntimeError, "position handoff failure"):
            presenter.open_current_position(fail_dispatch)

        reader.go_to(0)
        with self.assertRaisesRegex(LookupError, "Unknown return point"):
            presenter.return_from_board()
        self.assertEqual(reader.index, 0)

    def test_failed_position_handoff_restores_previous_return_target(self) -> None:
        reader = BookReader(self.make_extended_document())
        presenter = BookReaderPresenter(reader, language=UILanguage.EN)
        reader.go_to(1)
        presenter.open_current_position(lambda *_: object())
        reader.go_to(4)

        def fail_dispatch(_command: str, _payload) -> object:
            raise RuntimeError("synthetic position handoff failure")

        with self.assertRaisesRegex(RuntimeError, "position handoff failure"):
            presenter.open_current_position(fail_dispatch)

        reader.go_to(0)
        restored = presenter.return_from_board()
        self.assertEqual(restored.index, 1)
        self.assertEqual(reader.index, 1)

    def test_failed_game_handoff_restores_previous_return_target(self) -> None:
        reader = BookReader(self.make_extended_document())
        presenter = BookReaderPresenter(reader, language=UILanguage.EN)
        reader.go_to(3)
        presenter.open_current_game(lambda *_: object())
        reader.go_to(6)

        def fail_dispatch(_command: str, _payload) -> object:
            raise RuntimeError("synthetic game handoff failure")

        with self.assertRaisesRegex(RuntimeError, "game handoff failure"):
            presenter.open_current_game(fail_dispatch)

        reader.go_to(0)
        restored = presenter.return_from_board()
        self.assertEqual(restored.index, 3)
        self.assertEqual(reader.index, 3)


if __name__ == "__main__":
    unittest.main()
