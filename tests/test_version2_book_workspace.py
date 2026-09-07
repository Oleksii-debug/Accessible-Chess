from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from acs.analysis_service import AnalysisService
from acs.book_board_workflow import BookBoardWorkflow
from acs.book_progress_store import BookProgressStore
from acs.bookdocument import BookDocument, Game, ListBlock, Paragraph, Position
from acs.bookreader import BookReader
from acs.chesscore import Board
from acs.engine_assisted_workflows import EngineAssistedWorkflowService
from acs.version2_book_workspace import build_version2_book_webview
from acs.version2_profile import build_version2_router, build_version2_shell
from acs.version2_windows_book_board_adapter import Version2WindowsBookBoardActionDelegate


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
        self.assertEqual(bridge.dispatch("book.open_position").kind, "delegated")
        self.assertTrue(workflow.active)
        workflow.dispatch("book_board.next_move")
        self.assertNotEqual(workflow.board_snapshot().fen(), Board.START)
        reader.go_to(2)
        returned = bridge.dispatch("book.return_from_board")
        self.assertEqual(returned.kind, "render")
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
        self.assertEqual(block["list"], {"ordered": True, "start": 4, "items": ("Центр", "Розвиток", "<script>bad()</script>")})
        self.assertIn("4. Центр", block["text"])
        action = next(a for a in bridge.projection.snapshot()["actions"] if a["command"] == "book.next")
        self.assertFalse(action["enabled"])


if __name__ == "__main__":
    unittest.main()
