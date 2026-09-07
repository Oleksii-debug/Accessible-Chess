from __future__ import annotations

import unittest

from acs.analysis_service import AnalysisService
from acs.book_board_workflow import BookBoardWorkflow
from acs.book_webview_projection import BookWebViewProjection
from acs.bookdocument import BookDocument, Game, Paragraph, Position
from acs.bookreader import BookReader
from acs.chesscore import Board
from acs.engine_assisted_workflows import EngineAssistedWorkflowService
from acs.engine_ports import RawAnalysisLine
from acs.full_product_presenters import BookReaderPresenter
from acs.version2_windows_book_board_adapter import (
    BookBoardUiEventKind,
    Version2WindowsBookBoardActionDelegate,
)


GAME = '''[Event "D01 Book Board"]
[Result "*"]

1. e4 {main} (1. d4 $1 d5) e5 2. Nf3 *
'''


class _FakeAnalysisEngine:
    def __init__(self, *, failure: Exception | None = None, callback=None) -> None:
        self.failure = failure
        self.callback = callback
        self.calls: list[tuple[str, int, int]] = []

    def analyze(self, fen: str, multipv: int = 5, depth: int = 16):
        self.calls.append((fen, multipv, depth))
        if self.callback is not None:
            self.callback()
        if self.failure is not None:
            raise self.failure
        return (
            RawAnalysisLine(
                depth=depth,
                score_kind="cp",
                score_value=18,
                pv=("e2e4",),
            ),
        )

    def close(self) -> None:
        pass


class Version2WindowsBookBoardActionDelegateTests(unittest.TestCase):
    def _make(
        self,
        document: BookDocument,
        *,
        index: int = 0,
        failure: Exception | None = None,
        callback=None,
        event_sink=None,
        focus: str = "book-block-0",
    ):
        reader = BookReader(document)
        if index:
            reader.go_to(index)
        engine = _FakeAnalysisEngine(failure=failure, callback=callback)
        analysis = AnalysisService(lambda: engine)
        self.addCleanup(analysis.close)
        workflow = BookBoardWorkflow(
            reader,
            EngineAssistedWorkflowService(analysis),
        )
        events = []
        forwarded = []

        def next_delegate(action_id, payload):
            forwarded.append((action_id, dict(payload)))
            return ("next", action_id, dict(payload))

        sink = event_sink if event_sink is not None else events.append
        adapter = Version2WindowsBookBoardActionDelegate(
            workflow,
            event_sink=sink,
            next_delegate=next_delegate,
            current_focus_provider=lambda: focus,
        )
        return reader, workflow, engine, adapter, events, forwarded

    def test_existing_book_webview_open_position_reaches_canonical_bookboard(self) -> None:
        document = BookDocument(
            title="Book",
            blocks=[Position(fen=Board.START, caption="Start", block_id="pos-1")],
        )
        reader, workflow, _engine, adapter, events, _forwarded = self._make(document)
        presenter = BookReaderPresenter(reader)
        projection = BookWebViewProjection(presenter, adapter)

        browser_event = projection.open_position()

        self.assertEqual(browser_event.kind, "delegated")
        self.assertTrue(workflow.active)
        self.assertEqual(adapter.board_snapshot().fen(), Board.START)
        self.assertEqual(len(events), 1)
        host_event = events[0]
        self.assertEqual(host_event.kind, BookBoardUiEventKind.BOARD_OPENED)
        self.assertEqual(host_event.action_id, "book.open_position")
        self.assertEqual(host_event.focus_target, "board")
        self.assertEqual(host_event.mode, "position")
        self.assertEqual(host_event.book_index, 0)
        self.assertFalse(hasattr(host_event, "fen"))
        self.assertNotIn("8/8/8", repr(host_event))

    def test_book_game_open_navigation_variation_and_exact_return(self) -> None:
        document = BookDocument(
            title="Book",
            blocks=[
                Paragraph(text="Before", block_id="before"),
                Game(pgn=GAME, block_id="game-1"),
                Paragraph(text="After", block_id="after"),
            ],
        )
        reader, workflow, _engine, adapter, events, _forwarded = self._make(
            document,
            index=1,
            focus="book-block-1",
        )
        origin = reader.location()

        opened = adapter("book.open_game", {})
        self.assertEqual(opened.kind, BookBoardUiEventKind.BOARD_OPENED)
        self.assertEqual(opened.mode, "game")
        self.assertEqual(opened.book_index, 1)
        self.assertEqual(adapter.board_snapshot().fen(), Board.START)

        expected = Board()
        expected.push_text("e4")
        moved = adapter("book.board_next_move", {})
        self.assertEqual(moved.kind, BookBoardUiEventKind.BOARD_UPDATED)
        self.assertEqual(adapter.board_snapshot().fen(), expected.fen())

        branch = adapter("book.board_enter_variation", {"variation_index": 0})
        self.assertEqual(branch.kind, BookBoardUiEventKind.BOARD_UPDATED)
        self.assertEqual(adapter.board_snapshot().fen(), Board.START)
        adapter("book.board_leave_variation", {})
        self.assertEqual(adapter.board_snapshot().fen(), expected.fen())

        returned = adapter("book.return", {})
        self.assertEqual(returned.kind, BookBoardUiEventKind.RETURNED_TO_BOOK)
        self.assertEqual(returned.focus_target, "book-block-1")
        self.assertEqual(returned.book_index, 1)
        self.assertEqual(reader.location(), origin)
        self.assertFalse(workflow.active)
        self.assertEqual(events[-1], returned)

    def test_legacy_open_payload_is_compatibility_metadata_not_ui_chess_state(self) -> None:
        document = BookDocument(
            title="Book",
            blocks=[Position(fen=Board.START, block_id="pos")],
        )
        _reader, workflow, _engine, adapter, _events, _forwarded = self._make(document)

        event = adapter(
            "book.open_position",
            {"fen": "not the canonical chess state; compatibility metadata only", "book_index": 0},
        )

        self.assertEqual(event.kind, BookBoardUiEventKind.BOARD_OPENED)
        self.assertEqual(adapter.board_snapshot().fen(), Board.START)
        self.assertTrue(workflow.active)

    def test_browser_path_or_unknown_field_is_rejected_before_session_publication(self) -> None:
        private_path = r"C:\Users\blind\private\book.html"
        document = BookDocument(
            title="Book",
            blocks=[Position(fen=Board.START, block_id="pos")],
        )
        _reader, workflow, _engine, adapter, events, _forwarded = self._make(
            document,
            focus="book-block-0",
        )

        event = adapter("book.open_position", {"path": private_path})

        self.assertEqual(event.kind, BookBoardUiEventKind.FAILED)
        self.assertEqual(event.error_code, "invalid_action_payload")
        self.assertEqual(event.focus_target, "book-block-0")
        self.assertFalse(workflow.active)
        self.assertNotIn(private_path, repr(event))
        self.assertNotIn("Users", repr(events))

    def test_bool_book_index_and_analysis_coercions_fail_closed(self) -> None:
        document = BookDocument(
            title="Book",
            blocks=[Position(fen=Board.START, block_id="pos")],
        )
        _reader, workflow, _engine, adapter, _events, _forwarded = self._make(document)

        invalid_open = adapter(
            "book.open_position", {"fen": Board.START, "book_index": True}
        )
        self.assertEqual(invalid_open.kind, BookBoardUiEventKind.FAILED)
        self.assertFalse(workflow.active)

        adapter("book.open_position", {})
        invalid_analysis = adapter("book.board_analyze", {"depth": True})
        self.assertEqual(invalid_analysis.kind, BookBoardUiEventKind.FAILED)
        self.assertEqual(invalid_analysis.error_code, "invalid_command")
        self.assertTrue(workflow.active)

    def test_analysis_ready_projects_count_only_not_uci_or_fen(self) -> None:
        document = BookDocument(
            title="Book",
            blocks=[Position(fen=Board.START, block_id="pos")],
        )
        _reader, _workflow, engine, adapter, events, _forwarded = self._make(document)
        adapter("book.open_position", {})

        event = adapter("book.board_analyze", {"multipv": 1, "depth": 9})

        self.assertEqual(event.kind, BookBoardUiEventKind.ANALYSIS_READY)
        self.assertEqual(event.focus_target, "book-board-analysis")
        self.assertEqual(event.analysis_line_count, 1)
        self.assertEqual(len(engine.calls), 1)
        self.assertNotIn("e2e4", repr(event))
        self.assertNotIn(Board.START, repr(event))
        self.assertEqual(events[-1], event)

    def test_provider_failure_is_sanitized_and_keeps_board_session(self) -> None:
        private = RuntimeError(r"C:\private\stockfish.exe provider exploded")
        document = BookDocument(
            title="Book",
            blocks=[Position(fen=Board.START, block_id="pos")],
        )
        _reader, workflow, _engine, adapter, _events, _forwarded = self._make(
            document,
            failure=private,
        )
        adapter("book.open_position", {})

        event = adapter("book.board_analyze", {"multipv": 1, "depth": 8})

        self.assertEqual(event.kind, BookBoardUiEventKind.FAILED)
        self.assertEqual(event.error_code, "analysis_unavailable")
        self.assertEqual(event.focus_target, "board")
        self.assertTrue(workflow.active)
        self.assertNotIn("stockfish", repr(event).lower())
        self.assertNotIn("private", repr(event).lower())
        self.assertNotIn("\\", repr(event))

    def test_stale_analysis_never_announces_old_lines(self) -> None:
        document = BookDocument(
            title="Book",
            blocks=[Game(pgn='''[Result "*"]\n\n1. e4 e5 *\n''', block_id="game")],
        )
        holder = {}

        def move_during_request() -> None:
            holder["workflow"].next_move()

        _reader, workflow, _engine, adapter, _events, _forwarded = self._make(
            document,
            callback=move_during_request,
        )
        holder["workflow"] = workflow
        adapter("book.open_game", {})

        event = adapter("book.board_analyze", {"multipv": 1, "depth": 8})

        self.assertEqual(event.kind, BookBoardUiEventKind.ANALYSIS_STALE)
        self.assertEqual(event.analysis_line_count, 0)
        self.assertEqual(event.focus_target, "board")
        self.assertEqual(workflow.view().cursor.next_move_index, 1)

    def test_second_open_fails_with_stable_code_without_replacing_session(self) -> None:
        document = BookDocument(
            title="Book",
            blocks=[Position(fen=Board.START, block_id="pos")],
        )
        _reader, workflow, _engine, adapter, _events, _forwarded = self._make(document)
        first = adapter("book.open_position", {})
        revision = first.revision

        second = adapter("book.open_position", {})

        self.assertEqual(second.kind, BookBoardUiEventKind.FAILED)
        self.assertEqual(second.error_code, "active_session")
        self.assertEqual(second.focus_target, "board")
        self.assertTrue(workflow.active)
        self.assertEqual(workflow.revision, revision)

    def test_unowned_action_chains_unchanged(self) -> None:
        document = BookDocument(
            title="Book",
            blocks=[Position(fen=Board.START, block_id="pos")],
        )
        _reader, _workflow, _engine, adapter, _events, forwarded = self._make(document)

        value = adapter("library.search", {"query": "e4"})

        self.assertEqual(value, ("next", "library.search", {"query": "e4"}))
        self.assertEqual(forwarded, [("library.search", {"query": "e4"})])

    def test_event_sink_failure_does_not_roll_back_canonical_open(self) -> None:
        def broken_sink(_event) -> None:
            raise RuntimeError(r"C:\private\webview\sink failed")

        document = BookDocument(
            title="Book",
            blocks=[Position(fen=Board.START, block_id="pos")],
        )
        _reader, workflow, _engine, adapter, _events, _forwarded = self._make(
            document,
            event_sink=broken_sink,
        )

        event = adapter("book.open_position", {})

        self.assertEqual(event.kind, BookBoardUiEventKind.BOARD_OPENED)
        self.assertTrue(workflow.active)
        self.assertEqual(adapter.board_snapshot().fen(), Board.START)


if __name__ == "__main__":
    unittest.main()
