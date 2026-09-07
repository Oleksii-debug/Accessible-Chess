from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from acs.acsdb import AcsDatabase
from acs.analysis_service import AnalysisService
from acs.book_progress_store import BookProgressStore
from acs.chesscore import Board
from acs.engine_assisted_workflows import EngineAssistedWorkflowService
from acs.version2_application import Version2Application


PGN = '''[Event "Book board projection"]
[White "Alpha"]
[Black "Beta"]
[Result "*"]

1. e4 e5 2. Nf3 *
'''


class Version2BookRealBoardProjectionEvidenceTests(unittest.TestCase):
    """Independent release-composition oracle over exact PR #441 behavior.

    BookBoardWorkflow already owns a detached canonical Board. Version 2 is only
    release-correct when opening/navigating that workflow also projects the same
    canonical position into the real Stage1-derived 64-square board runtime.
    Merely switching the shell route to ``board`` is not sufficient evidence.
    """

    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.database = AcsDatabase(self.root / "library.acsdb")
        self.addCleanup(self.database.close)
        self.analysis = AnalysisService(lambda: None)
        self.addCleanup(self.analysis.close)
        self.board_calls: list[tuple[str, dict[str, object]]] = []

        def board_dispatch(action_id: str, payload=None):
            values = {} if payload is None else dict(payload)
            self.board_calls.append((action_id, values))
            return {"ok": True}

        self.app = Version2Application(
            self.database,
            progress_store=BookProgressStore(self.root / "book-progress.json"),
            engine_assistance=EngineAssistedWorkflowService(self.analysis),
            board_dispatch=board_dispatch,
            copy_text=lambda _value: None,
        )
        self.book = self.root / "study.md"
        self.book.write_text(
            "# Study\n\nBefore\n\n```pgn\n" + PGN + "```\n\nAfter\n",
            encoding="utf-8",
        )

    def _open_game(self) -> None:
        self.app.open_book(self.book)
        self.app.browser_command("books", "book.next_game")

    def test_opening_book_game_projects_canonical_position_to_real_board_runtime(self) -> None:
        self._open_game()
        self.board_calls.clear()

        result = self.app.browser_command("books", "book.open_position")

        self.assertEqual(result["kind"], "delegated")
        self.assertTrue(self.app.book_workflow.active)
        self.assertEqual(self.app.book_delegate.board_snapshot().fen(), Board.START)
        self.assertEqual(self.app.shell.current_route.route_id, "board")
        self.assertTrue(
            self.board_calls,
            "Book -> Board switched the shell route but never projected the canonical "
            "BookBoard position through the real release-board runtime seam",
        )

    def test_book_board_navigation_reprojects_each_canonical_position(self) -> None:
        self._open_game()
        self.app.browser_command("books", "book.open_position")
        self.board_calls.clear()
        before = self.app.book_delegate.board_snapshot().fen()

        self.app.router.dispatch("book.board_next_move")

        after = self.app.book_delegate.board_snapshot().fen()
        self.assertNotEqual(after, before)
        expected = Board()
        expected.push_text("e4")
        self.assertEqual(after, expected.fen())
        self.assertTrue(
            self.board_calls,
            "BookBoardWorkflow advanced canonically, but the real release board was not "
            "reprojected after Book review navigation",
        )


if __name__ == "__main__":
    unittest.main()
