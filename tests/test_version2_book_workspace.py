from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from acs.acsdb import AcsDatabase
from acs.analysis_service import AnalysisService
from acs.book_board_workflow import (
    BookBoardWorkflow,
    BookBoardWorkflowCode,
    BookBoardWorkflowError,
)
from acs.book_progress_store import BookProgressStore
from acs.bookdocument import BookDocument, Game, ListBlock, Paragraph, Position, VariationTree
from acs.bookreader import BookReader
from acs.chesscore import Board
from acs.engine_assisted_workflows import EngineAssistedWorkflowService
from acs.full_product_presenters import PgnGameView, PgnTreeItem, PgnTreePresenter
from acs.version2_book_workspace import build_version2_book_webview
from acs.version2_profile import build_version2_router, build_version2_shell
from acs.version2_starter_content_application import Version2StarterContentApplication
from acs.version2_windows_book_board_adapter import (
    BookBoardUiEvent,
    BookBoardUiEventKind,
    Version2WindowsBookBoardActionDelegate,
)


class Version2BookWorkspaceTests(unittest.TestCase):
    def compose(self, document):
        reader = BookReader(document)
        analysis = AnalysisService(lambda: None)
        self.addCleanup(analysis.close)
        workflow = BookBoardWorkflow(reader, EngineAssistedWorkflowService(analysis))
        events = []
        delegate = Version2WindowsBookBoardActionDelegate(
            workflow, event_sink=events.append,
            next_delegate=lambda *_: self.fail("unexpected action"),
        )
        router = build_version2_router(build_version2_shell(), delegate)
        bridge = build_version2_book_webview(reader, workflow, router.dispatch)
        return reader, workflow, bridge, events

    def test_game_and_variation_blocks_project_bounded_readable_semantic_moves(self):
        cases = (
            Game(
                pgn=(
                    '[White "Alpha"]\n'
                    '[Black "Beta"]\n'
                    '[Result "*"]\n\n'
                    '{Intro} 1. {Before main} e4 {After C:\\private\\secret.txt} '
                    '(1. d4 d5 * {Variation tail}) e5 * {Outro}'
                ),
                title="Annotated game",
                block_id="game",
            ),
            VariationTree(
                root_fen=Board.START,
                pgn=(
                    '[White "Gamma"]\n'
                    '[Black "Delta"]\n'
                    '[Result "*"]\n\n'
                    '1. e4 (1. d4 d5 *) e5 *'
                ),
                title="Variation study",
                block_id="variation",
            ),
        )
        for semantic in cases:
            with self.subTest(kind=type(semantic).__name__):
                reader, workflow, bridge, _ = self.compose(
                    BookDocument(title="Semantic book", blocks=[semantic])
                )
                before = reader.snapshot()

                snapshot = bridge.projection.snapshot()
                tree = snapshot["semantic_tree"]

                self.assertIsInstance(tree, dict)
                self.assertIn(tree["kind"], {"game", "variation"})
                self.assertEqual(tree["result"], "*")
                self.assertIn(" — ", tree["players"])
                self.assertGreaterEqual(len(tree["items"]), 3)
                self.assertEqual(tree["items"][0]["kind"], "move")
                self.assertEqual(tree["items"][0]["depth"], 0)
                self.assertIsNone(tree["items"][0]["parent_index"])
                self.assertIn("e4", tree["items"][0]["label"])
                variation = next(item for item in tree["items"] if item["kind"] == "variation")
                self.assertEqual(variation["depth"], 1)
                self.assertEqual(variation["parent_index"], 0)
                nested = next(
                    item
                    for item in tree["items"]
                    if item["kind"] == "move" and "d4" in item["label"]
                )
                self.assertEqual(nested["parent_index"], tree["items"].index(variation))
                serialized = json.dumps(tree, ensure_ascii=False)
                self.assertNotIn("[White", serialized)
                self.assertNotIn("private", serialized.casefold())
                self.assertNotIn("C:\\", serialized)
                self.assertNotIn(Board.START, serialized)
                self.assertFalse(workflow.active)
                self.assertEqual(workflow.revision, 0)
                self.assertEqual(reader.snapshot(), before)

    def test_semantic_reading_relocalizes_without_moving_reader_progress(self):
        reader, workflow, bridge, _ = self.compose(
            BookDocument(
                title="Language semantic reading",
                blocks=[
                    Game(
                        pgn='[White "Alpha"]\n[Black "Beta"]\n[Result "*"]\n\n1. e4 (1. d4) e5 *',
                        title="Game",
                    )
                ],
            )
        )
        progress_before = reader.snapshot()

        ua = bridge.projection.snapshot()["semantic_tree"]
        switched = bridge.dispatch("book.language", {"language": "en"})
        en = switched.payload["snapshot"]["semantic_tree"]

        self.assertEqual(switched.kind, "render")
        self.assertEqual(ua["kind"], en["kind"])
        self.assertEqual(ua["players"], en["players"])
        self.assertEqual(ua["result"], en["result"])
        self.assertNotEqual(ua["label"], en["label"])
        self.assertEqual(en["label"], "Moves and variations")
        self.assertTrue(any(item["kind"] == "variation" for item in en["items"]))
        self.assertFalse(workflow.active)
        self.assertEqual(workflow.revision, 0)
        self.assertEqual(reader.snapshot(), progress_before)

    def test_semantic_projection_failure_falls_back_without_leaking_error_details(self):
        reader, workflow, bridge, _ = self.compose(
            BookDocument(
                title="Fallback",
                blocks=[Game(pgn='[Result "*"]\n\n1. e4 *', title="Readable title")],
            )
        )
        progress_before = reader.snapshot()

        with patch.object(
            workflow,
            "semantic_game_snapshot",
            side_effect=ValueError(r"SECRET C:\\private\\source.pgn"),
        ):
            snapshot = bridge.projection.snapshot()

        self.assertIsNone(snapshot["semantic_tree"])
        self.assertEqual(snapshot["block"]["text"], "Readable title")
        self.assertIn("шахівниця", snapshot["block"]["warning"])
        self.assertNotIn("SECRET", repr(snapshot))
        self.assertNotIn("private", repr(snapshot).casefold())
        actions = {item["command"]: item["enabled"] for item in snapshot["actions"]}
        self.assertTrue(actions["book.open_game"])
        self.assertFalse(workflow.active)
        self.assertEqual(workflow.revision, 0)
        self.assertEqual(reader.snapshot(), progress_before)

    def test_semantic_tree_rejects_stale_parent_from_an_inactive_branch(self):
        reader, workflow, bridge, _ = self.compose(
            BookDocument(
                title="Malformed semantic ancestry",
                blocks=[Game(pgn='[Result "*"]\n\n1. e4 *', title="Readable game")],
            )
        )
        before = reader.snapshot()
        items = (
            PgnTreeItem("m0", "move", 0, "1 e4", None),
            PgnTreeItem("v0", "variation", 1, "Variation 1", "m0", result="*"),
            PgnTreeItem("vm0", "move", 2, "1 d4", "v0"),
            PgnTreeItem("m1", "move", 0, "1... e5", None),
            PgnTreeItem("stale", "variation", 1, "Variation 2", "m0", result="*"),
        )
        malformed = PgnGameView(0, "Alpha — Beta", "*", (), (), items, "m0")

        with patch.object(PgnTreePresenter, "view", return_value=malformed):
            snapshot = bridge.projection.snapshot()

        self.assertIsNone(snapshot["semantic_tree"])
        self.assertIn("шахівниця", snapshot["block"]["warning"])
        self.assertFalse(workflow.active)
        self.assertEqual(workflow.revision, 0)
        self.assertEqual(reader.snapshot(), before)

    def test_semantic_tree_rejects_move_owned_variation_endings(self):
        reader, workflow, bridge, _ = self.compose(
            BookDocument(
                title="Malformed semantic slots",
                blocks=[Game(pgn='[Result "*"]\n\n1. e4 *', title="Readable game")],
            )
        )
        before = reader.snapshot()
        malformed = PgnGameView(
            0,
            "Alpha — Beta",
            "*",
            (),
            (),
            (
                PgnTreeItem(
                    "m0",
                    "move",
                    0,
                    "1 e4",
                    None,
                    trailing_comments=("not a move tail",),
                    result="*",
                ),
            ),
            "m0",
        )

        with patch.object(PgnTreePresenter, "view", return_value=malformed):
            snapshot = bridge.projection.snapshot()

        self.assertIsNone(snapshot["semantic_tree"])
        self.assertIn("шахівниця", snapshot["block"]["warning"])
        self.assertEqual(reader.snapshot(), before)

    def test_unavailable_semantic_content_disables_the_matching_board_action(self):
        reader, workflow, bridge, _ = self.compose(
            BookDocument(
                title="Unavailable game",
                blocks=[Game(pgn='[Result "*"]\n\n1. e4 *', title="Readable game")],
            )
        )
        error = BookBoardWorkflowError(
            "provider detail must not escape",
            code=BookBoardWorkflowCode.CONTENT_UNAVAILABLE,
        )

        with patch.object(workflow, "semantic_game_snapshot", side_effect=error):
            snapshot = bridge.projection.snapshot()

        actions = {item["command"]: item["enabled"] for item in snapshot["actions"]}
        self.assertIsNone(snapshot["semantic_tree"])
        self.assertFalse(actions["book.open_game"])
        self.assertNotIn("provider detail", repr(snapshot))
        self.assertFalse(workflow.active)
        self.assertEqual(workflow.revision, 0)
        self.assertEqual(reader.index, 0)

    def test_semantic_revision_drift_propagates_instead_of_publishing_stale_fallback(self):
        reader, workflow, bridge, _ = self.compose(
            BookDocument(
                title="Revision drift",
                blocks=[Game(pgn='[Result "*"]\n\n1. e4 *', title="Game")],
            )
        )
        before = reader.snapshot()
        error = BookBoardWorkflowError(
            "reading location changed",
            code=BookBoardWorkflowCode.RETURN_FAILED,
        )

        with patch.object(workflow, "semantic_game_snapshot", side_effect=error):
            with self.assertRaises(BookBoardWorkflowError) as raised:
                bridge.projection.snapshot()

        self.assertIs(raised.exception.code, BookBoardWorkflowCode.RETURN_FAILED)
        self.assertFalse(workflow.active)
        self.assertEqual(workflow.revision, 0)
        self.assertEqual(reader.snapshot(), before)

    def test_game_open_move_and_exact_return_use_one_canonical_workflow(self):
        document = BookDocument(title="Книга", blocks=[
            Paragraph(text="Пояснення", block_id="before"),
            Game(pgn='[Result "*"]\n\n1. e4 {Коментар} (1. d4) e5 *', block_id="game"),
            Paragraph(text="Після", block_id="after"),
        ])
        reader, workflow, bridge, events = self.compose(document)
        origin = reader.go_to(1)
        before_actions = {
            action["command"]: action["enabled"]
            for action in bridge.projection.snapshot()["actions"]
        }
        self.assertFalse(before_actions["book.open_position"])
        self.assertTrue(before_actions["book.open_game"])
        self.assertFalse(before_actions["book.return_from_board"])
        self.assertFalse(bridge.projection.snapshot()["board_active"])

        opened = bridge.dispatch("book.open_game")
        self.assertEqual(opened.kind, "delegated")
        self.assertEqual(opened.payload["announcement"], "Партію відкрито на дошці.")
        self.assertTrue(workflow.active)
        active_snapshot = bridge.projection.snapshot()
        active_actions = {
            action["command"]: action["enabled"]
            for action in active_snapshot["actions"]
        }
        self.assertTrue(active_snapshot["board_active"])
        self.assertFalse(active_actions["book.open_position"])
        self.assertFalse(active_actions["book.open_game"])
        self.assertTrue(active_actions["book.return_from_board"])
        workflow.dispatch("book_board.next_move")
        self.assertNotEqual(workflow.board_snapshot().fen(), Board.START)
        reader.go_to(2)
        returned = bridge.dispatch("book.return_from_board")
        self.assertEqual(returned.kind, "render")
        self.assertEqual(returned.payload["announcement"], "Повернуто до місця читання.")
        self.assertEqual(reader.location(), origin)
        self.assertFalse(workflow.active)
        self.assertEqual(returned.payload["focus_target"], "book-block-1")
        after_snapshot = bridge.projection.snapshot()
        after_actions = {
            action["command"]: action["enabled"]
            for action in after_snapshot["actions"]
        }
        self.assertFalse(after_snapshot["board_active"])
        self.assertTrue(after_actions["book.open_game"])
        self.assertFalse(after_actions["book.return_from_board"])
        self.assertEqual(len(events), 2)
        # A second return must fail, never revive a separate presenter return stack.
        self.assertEqual(bridge.dispatch("book.return_from_board").kind, "error")
        with tempfile.TemporaryDirectory() as folder:
            store = BookProgressStore(Path(folder) / "progress.json")
            store.save("book:example", reader)
            self.assertEqual(store.restore("book:example", document).location(), origin)

    def test_board_open_and_return_announcements_follow_live_language(self):
        for language, opened_text, returned_text in (
            ("uk", "Позицію відкрито на дошці.", "Повернуто до місця читання."),
            ("en", "Position opened on the board.", "Returned to the reading location."),
        ):
            with self.subTest(language=language):
                reader, workflow, bridge, _ = self.compose(
                    BookDocument(title="Study", blocks=[Position(fen=Board.START)])
                )
                language_event = bridge.dispatch("book.language", {"language": language})
                self.assertEqual(language_event.kind, "render")

                opened = bridge.dispatch("book.open_position")
                self.assertEqual(opened.kind, "delegated")
                self.assertEqual(opened.payload["announcement"], opened_text)
                self.assertTrue(workflow.active)

                returned = bridge.dispatch("book.return_from_board")
                self.assertEqual(returned.kind, "render")
                self.assertEqual(returned.payload["announcement"], returned_text)
                self.assertFalse(workflow.active)
                self.assertEqual(reader.index, 0)

    def test_board_success_event_must_match_action_and_live_workflow_state(self):
        _, active_workflow, active_bridge, _ = self.compose(
            BookDocument(title="Study", blocks=[Position(fen=Board.START)])
        )
        active_workflow.open_current()
        active_bridge.projection._dispatch = lambda *_: BookBoardUiEvent(
            BookBoardUiEventKind.BOARD_OPENED,
            "book.return",
            focus_target="board",
            revision=active_workflow.revision,
        )

        wrong_action = active_bridge.dispatch("book.open_position")

        self.assertEqual(wrong_action.kind, "error")
        self.assertNotIn("announcement", wrong_action.payload)
        self.assertTrue(active_workflow.active)

        active_bridge.projection._dispatch = lambda *_: BookBoardUiEvent(
            BookBoardUiEventKind.BOARD_OPENED,
            "book.open_position",
            focus_target="board",
            revision=active_workflow.revision - 1,
        )

        stale_revision = active_bridge.dispatch("book.open_position")

        self.assertEqual(stale_revision.kind, "error")
        self.assertNotIn("announcement", stale_revision.payload)
        self.assertTrue(active_workflow.active)

        _, inactive_workflow, inactive_bridge, _ = self.compose(
            BookDocument(title="Study", blocks=[Position(fen=Board.START)])
        )
        inactive_bridge.projection._dispatch = lambda *_: BookBoardUiEvent(
            BookBoardUiEventKind.BOARD_OPENED,
            "book.open_position",
            focus_target="board",
        )

        impossible_open = inactive_bridge.dispatch("book.open_position")

        self.assertEqual(impossible_open.kind, "error")
        self.assertNotIn("announcement", impossible_open.payload)
        self.assertFalse(inactive_workflow.active)

    def test_return_success_event_requires_workflow_to_be_closed(self):
        _, workflow, bridge, _ = self.compose(
            BookDocument(title="Study", blocks=[Position(fen=Board.START)])
        )
        workflow.open_current()
        bridge.projection._dispatch = lambda *_: BookBoardUiEvent(
            BookBoardUiEventKind.RETURNED_TO_BOOK,
            "book.return",
            focus_target="book-block-0",
            book_index=0,
            revision=workflow.revision,
        )

        result = bridge.dispatch("book.return_from_board")

        self.assertEqual(result.kind, "error")
        self.assertNotIn("announcement", result.payload)
        self.assertTrue(workflow.active)

    def test_failed_content_open_never_announces_success_or_changes_reader(self):
        reader, workflow, bridge, _ = self.compose(BookDocument(title="Broken", blocks=[
            Game(pgn="1. nonsense *", block_id="broken"),
        ]))
        origin = reader.location()
        result = bridge.dispatch("book.open_position")
        self.assertEqual(result.kind, "error")
        self.assertNotIn("announcement", result.payload)
        self.assertFalse(workflow.active)
        self.assertEqual(reader.location(), origin)

        explicit_game = bridge.dispatch("book.open_game")
        self.assertEqual(explicit_game.kind, "error")
        self.assertNotIn("announcement", explicit_game.payload)
        self.assertFalse(workflow.active)
        self.assertEqual(reader.location(), origin)

    def test_browser_cannot_choose_position_or_raw_host_path(self):
        _, workflow, bridge, _ = self.compose(BookDocument(title="Study", blocks=[Position(fen=Board.START)]))
        for payload in ({"fen": Board.START}, {"path": "C:\\private\\book.txt"}, {"book_index": 2}):
            result = bridge.dispatch("book.open_position", payload)
            self.assertEqual(result.kind, "error")
            self.assertNotIn("private", json.dumps(result.payload))
            self.assertFalse(workflow.active)

    def test_ordered_list_items_and_start_remain_semantic(self):
        _, _, bridge, _ = self.compose(BookDocument(title="Lists", blocks=[
            ListBlock(items=["Центр", "Розвиток", "<script>bad()</script>"], ordered=True, start=4),
        ]))
        block = bridge.projection.snapshot()["block"]
        self.assertEqual(block["role"], "list")
        self.assertEqual(
            block["list"],
            {
                "ordered": True,
                "start": 4,
                "items": ("Центр", "Розвиток", "<script>bad()</script>"),
            },
        )
        self.assertEqual(block["text"], "")
        action = next(a for a in bridge.projection.snapshot()["actions"] if a["command"] == "book.next")
        self.assertFalse(action["enabled"])

    def test_v2_projection_fails_closed_if_live_document_changes_after_presenter_read(self):
        document = BookDocument(title="Lists", blocks=[
            ListBlock(items=["Оригінал"], ordered=False, block_id="list"),
        ])
        _, _, bridge, _ = self.compose(document)
        view = bridge.projection._presenter.current()
        document.blocks[0].items[0] = "Підміна"

        with self.assertRaisesRegex(RuntimeError, "changed after BookReader creation"):
            bridge.projection._snapshot_from_block(view)


    def test_starter_material_render_failure_does_not_publish_or_persist_staged_book(self):
        with tempfile.TemporaryDirectory(prefix="accessible-chess-books-render-atomic-") as raw:
            root = Path(raw)
            database = AcsDatabase(root / "library.acsdb")
            analysis = AnalysisService(lambda: None)
            try:
                app = Version2StarterContentApplication(
                    database,
                    progress_store=BookProgressStore(root / "book-progress.json"),
                    engine_assistance=EngineAssistedWorkflowService(analysis),
                    board_dispatch=lambda *_: None,
                    board_position_projector=lambda _fen: {"ok": True},
                )
                try:
                    app.browser_command("shell", "screen.books")
                    catalogue = app.snapshot()["books"]["starter_materials"]
                    booklet = next(
                        item
                        for item in catalogue["items"]
                        if item["material_id"].startswith("starter-booklet-")
                    )
                    staged_key = app._starter_book_key(booklet["material_id"])
                    self.assertFalse(app.progress_store.has(staged_key))

                    before_reader = app.reader
                    before_books = app.books
                    before_workflow = app.book_workflow
                    before_delegate = app.book_delegate
                    before_key = app.book_key
                    before_material = catalogue["current_id"]

                    with patch(
                        "acs.version2_book_workspace.Version2BookWebViewProjection.snapshot",
                        side_effect=RuntimeError("simulated staged render failure"),
                    ):
                        result = app.browser_command(
                            "books",
                            "book.open_starter_material",
                            {"material_id": booklet["material_id"]},
                        )

                    self.assertEqual("error", result["kind"])
                    self.assertIs(before_reader, app.reader)
                    self.assertIs(before_books, app.books)
                    self.assertIs(before_workflow, app.book_workflow)
                    self.assertIs(before_delegate, app.book_delegate)
                    self.assertEqual(before_key, app.book_key)
                    self.assertEqual(before_material, app._starter_current_material_id)
                    self.assertFalse(app.progress_store.has(staged_key))
                    self.assertEqual("books", app.shell.current_route.route_id)
                finally:
                    app.shutdown()
            finally:
                analysis.close()
                database.close()


if __name__ == "__main__":
    unittest.main()
