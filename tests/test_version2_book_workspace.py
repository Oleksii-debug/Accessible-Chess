from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from acs.acsdb import AcsDatabase
from acs.analysis_service import AnalysisService
from acs.book_board_workflow import BookBoardWorkflow
from acs.book_progress_store import BookProgressStore
from acs.bookdocument import BookDocument, Game, ListBlock, Paragraph, Position, VariationTree
from acs.bookreader import BookReader
from acs.chesscore import Board
from acs.engine_assisted_workflows import EngineAssistedWorkflowService
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

    def test_game_and_variation_blocks_project_readable_semantic_move_trees(self):
        cases = (
            Game(
                pgn='[Event "Accessible Cup"]\n[Site "/home/private/venue.txt"]\n[Date "2026.10.03"]\n[Round "3"]\n[White "Alpha"]\n[Black "Beta"]\n[Result "*"]\n\n{Intro C:\\private\\root.txt} 1. {Before main} e4 {After C:\\private\\secret.txt} (1. d4 $1 d5 * {Nested C:\\private\\branch.txt}) e5 * {Outro C:\\private\\tail.txt}',
                title="Annotated game",
                block_id="game",
            ),
            VariationTree(
                root_fen=Board.START,
                pgn='[White "Gamma"]\n[Black "Delta"]\n[Result "*"]\n\n{Intro variation} 1. {Before variation main} e4 {After variation main} (1. d4 $1 d5 * {Nested variation}) e5 * {Outro variation}',
                title="Variation study",
                block_id="variation",
            ),
        )
        for semantic in cases:
            with self.subTest(kind=type(semantic).__name__):
                reader, workflow, bridge, _ = self.compose(
                    BookDocument(title="Книга", blocks=[semantic])
                )
                progress_before = reader.snapshot()
                snapshot = bridge.projection.snapshot()
                tree = snapshot["block"].get("semantic_tree")

                self.assertIsInstance(tree, dict)
                self.assertEqual(tree["result"], "*")
                self.assertIn(" — ", tree["players"])
                self.assertNotIn("?", tree["players"])
                if isinstance(semantic, Game):
                    details = {
                        item["label"]: item["value"]
                        for item in tree["details"]
                    }
                    self.assertEqual(details["Подія"], "Accessible Cup")
                    self.assertEqual(details["Дата"], "2026.10.03")
                    self.assertEqual(details["Тур"], "3")
                    self.assertNotIn("private", json.dumps(tree["details"]).casefold())
                else:
                    self.assertEqual(tree["details"], ())
                self.assertEqual(len(tree["intro_comments"]), 1)
                self.assertIn("Intro", tree["intro_comments"][0])
                self.assertEqual(len(tree["outro_comments"]), 1)
                self.assertIn("Outro", tree["outro_comments"][0])
                self.assertGreaterEqual(len(tree["items"]), 5)
                self.assertEqual(tree["items"][0]["kind"], "move")
                self.assertEqual(tree["items"][0]["depth"], 0)
                self.assertIsNone(tree["items"][0]["parent_index"])
                self.assertIn("e4", tree["items"][0]["label"])
                expected_before = (
                    "Before main"
                    if isinstance(semantic, Game)
                    else "Before variation main"
                )
                self.assertEqual((expected_before,), tree["items"][0]["comments_before"])
                self.assertEqual(1, len(tree["items"][0]["comments_after"]))
                self.assertIn("After", tree["items"][0]["comments_after"][0])
                self.assertEqual((), tree["items"][0]["comments"])
                self.assertEqual(tree["items"][1]["kind"], "variation")
                self.assertEqual(tree["items"][1]["depth"], 1)
                self.assertEqual(tree["items"][1]["parent_index"], 0)
                self.assertEqual(len(tree["items"][1]["trailing_comments"]), 1)
                self.assertIn("Nested", tree["items"][1]["trailing_comments"][0])
                self.assertEqual(tree["items"][2]["depth"], 2)
                self.assertEqual(tree["items"][2]["parent_index"], 1)
                self.assertIn("d4", tree["items"][2]["label"])
                self.assertIn("$1", tree["items"][2]["label"])
                self.assertEqual(tree["items"][-1]["depth"], 0)
                self.assertIsNone(tree["items"][-1]["parent_index"])
                for item in tree["items"]:
                    if item["kind"] == "move":
                        self.assertEqual(item["depth"] % 2, 0)
                    else:
                        self.assertEqual(item["depth"] % 2, 1)
                serialized = json.dumps(tree, ensure_ascii=False)
                self.assertNotIn("[Result", serialized)
                self.assertNotIn("private", serialized.casefold())
                self.assertNotIn("C:\\", serialized)
                self.assertFalse(workflow.active)
                self.assertEqual(workflow.revision, 0)
                self.assertEqual(reader.snapshot(), progress_before)

    def test_recovered_game_warning_and_last_canonical_metadata_are_readable(self):
        reader, workflow, bridge, _ = self.compose(
            BookDocument(
                title="Recovered source",
                blocks=[
                    Game(
                        pgn=(
                            '[Event "First"]\n'
                            '[Event "Second"]\n'
                            '[Result "*"]\n\n'
                            '1. e4 e5 *'
                        ),
                        title="Recovered game",
                        block_id="recovered-game",
                    )
                ],
            )
        )
        progress_before = reader.snapshot()

        tree = bridge.projection.snapshot()["block"]["semantic_tree"]

        self.assertIn(
            {"label": "Подія", "value": "Second"},
            tree["details"],
        )
        self.assertNotIn(
            {"label": "Подія", "value": "First"},
            tree["details"],
        )
        self.assertTrue(
            any("duplicate tag Event" in warning for warning in tree["warnings"])
        )
        self.assertFalse(workflow.active)
        self.assertEqual(workflow.revision, 0)
        self.assertEqual(reader.snapshot(), progress_before)

    def test_language_switch_rebuilds_semantic_labels_without_moving_reader(self):
        reader, workflow, bridge, _ = self.compose(
            BookDocument(
                title="Bilingual study",
                blocks=[
                    Game(
                        pgn=(
                            '[Event "Accessible Cup"]\n'
                            '[Result "*"]\n\n'
                            '1. e4 (1. d4 d5) e5 *'
                        ),
                        title="Study",
                        block_id="study",
                    )
                ],
            )
        )
        before = reader.snapshot()

        ua = bridge.projection.snapshot()["block"]["semantic_tree"]
        event = bridge.dispatch("book.language", {"language": "en"})
        en = event.payload["snapshot"]["block"]["semantic_tree"]

        self.assertEqual(ua["details_label"], "Відомості про партію")
        self.assertEqual(en["details_label"], "Game details")
        self.assertIn({"label": "Event", "value": "Accessible Cup"}, en["details"])
        self.assertTrue(
            any(
                item["kind"] == "variation" and item["label"] == "Variation 1"
                for item in en["items"]
            )
        )
        self.assertEqual(event.payload["snapshot"]["document"]["lang"], "en")
        self.assertEqual(reader.snapshot(), before)
        self.assertFalse(workflow.active)
        self.assertEqual(workflow.revision, 0)

    def test_excessive_semantic_item_count_fails_closed_but_keeps_board_available(self):
        reader, workflow, bridge, _ = self.compose(
            BookDocument(
                title="Structurally large game",
                blocks=[
                    Game(
                        pgn='[Result "*"]\n\n1. e4 e5 *',
                        title="Bounded game",
                        block_id="bounded-game",
                    )
                ],
            )
        )
        progress_before = reader.snapshot()

        with patch(
            "acs.version2_book_workspace._MAX_BOOK_SEMANTIC_ITEMS",
            1,
        ):
            snapshot = bridge.projection.snapshot()

        self.assertNotIn("semantic_tree", snapshot["block"])
        self.assertIn("шахівниц", snapshot["block"]["warning"].casefold())
        open_action = next(
            action
            for action in snapshot["actions"]
            if action["command"] == "book.open_position"
        )
        self.assertTrue(open_action["enabled"])
        self.assertFalse(workflow.active)
        self.assertEqual(reader.snapshot(), progress_before)

    def test_oversized_semantic_reading_fails_closed_but_keeps_board_available(self):
        reader, workflow, bridge, _ = self.compose(
            BookDocument(
                title="Large annotated game",
                blocks=[
                    Game(
                        pgn='[Result "*"]\\n\\n1. e4 {Long semantic comment} e5 *',
                        title="Large game",
                        block_id="large-game",
                    )
                ],
            )
        )
        progress_before = reader.snapshot()

        with patch(
            "acs.version2_book_workspace._MAX_BOOK_BLOCK_VISIBLE_CHARS",
            8,
        ):
            snapshot = bridge.projection.snapshot()

        self.assertNotIn("semantic_tree", snapshot["block"])
        self.assertIn("шахівниц", snapshot["block"]["warning"].casefold())
        open_action = next(
            action
            for action in snapshot["actions"]
            if action["command"] == "book.open_position"
        )
        self.assertTrue(open_action["enabled"])
        self.assertFalse(workflow.active)
        self.assertEqual(workflow.revision, 0)
        self.assertEqual(reader.snapshot(), progress_before)

    def test_invalid_game_semantics_fail_closed_without_breaking_book_snapshot(self):
        reader, workflow, bridge, _ = self.compose(
            BookDocument(
                title="Broken study",
                blocks=[
                    Game(
                        pgn='[Result "*"]\n\n1. e5 *',
                        title="Invalid line",
                        block_id="invalid-game",
                    )
                ],
            )
        )
        progress_before = reader.snapshot()

        snapshot = bridge.projection.snapshot()

        self.assertNotIn("semantic_tree", snapshot["block"])
        self.assertIn("недоступ", snapshot["block"]["warning"].casefold())
        open_action = next(
            action
            for action in snapshot["actions"]
            if action["command"] == "book.open_position"
        )
        self.assertFalse(open_action["enabled"])
        self.assertFalse(workflow.active)
        self.assertEqual(workflow.revision, 0)
        self.assertEqual(reader.snapshot(), progress_before)

    def test_game_open_move_and_exact_return_use_one_canonical_workflow(self):
        document = BookDocument(title="Книга", blocks=[
            Paragraph(text="Пояснення", block_id="before"),
            Game(pgn='[Result "*"]\n\n1. e4 {Коментар} (1. d4) e5 *', block_id="game"),
            Paragraph(text="Після", block_id="after"),
        ])
        reader, workflow, bridge, events = self.compose(document)
        origin = reader.go_to(1)
        action = next(a for a in bridge.projection.snapshot()["actions"] if a["command"] == "book.open_position")
        self.assertTrue(action["enabled"], "Game must be reachable even without a literal FEN")
        opened = bridge.dispatch("book.open_position")
        self.assertEqual(opened.kind, "delegated")
        self.assertEqual(opened.payload["announcement"], "Позицію відкрито на дошці.")
        self.assertTrue(workflow.active)
        workflow.dispatch("book_board.next_move")
        self.assertNotEqual(workflow.board_snapshot().fen(), Board.START)
        reader.go_to(2)
        returned = bridge.dispatch("book.return_from_board")
        self.assertEqual(returned.kind, "render")
        self.assertEqual(returned.payload["announcement"], "Повернуто до місця читання.")
        self.assertEqual(reader.location(), origin)
        self.assertFalse(workflow.active)
        self.assertEqual(returned.payload["focus_target"], "book-block-1")
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
