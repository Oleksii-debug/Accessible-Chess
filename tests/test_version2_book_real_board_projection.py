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


class Version2BookRealBoardProjectionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.database = AcsDatabase(self.root / "library.acsdb")
        self.addCleanup(self.database.close)
        self.analysis = AnalysisService(lambda: None)
        self.addCleanup(self.analysis.close)
        self.projected: list[str] = []

        def position_sink(fen: str):
            self.projected.append(fen)
            return {"ok": True}

        self.app = Version2Application(
            self.database,
            progress_store=BookProgressStore(self.root / "book-progress.json"),
            engine_assistance=EngineAssistedWorkflowService(self.analysis),
            board_dispatch=lambda *_args, **_kwargs: {"ok": True},
            position_sink=position_sink,
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

    def test_opening_book_game_projects_exact_canonical_position(self) -> None:
        self._open_game()
        self.projected.clear()

        result = self.app.browser_command("books", "book.open_position")

        self.assertEqual(result["kind"], "delegated")
        self.assertTrue(self.app.book_workflow.active)
        canonical = self.app.book_delegate.board_snapshot().fen()
        self.assertEqual(canonical, Board.START)
        self.assertEqual(self.projected, [canonical])
        self.assertEqual(self.app.shell.current_route.route_id, "board")

    def test_book_board_navigation_reprojects_each_canonical_position(self) -> None:
        self._open_game()
        self.app.browser_command("books", "book.open_position")
        self.projected.clear()

        self.app.router.dispatch("book.board_next_move")

        canonical = self.app.book_delegate.board_snapshot().fen()
        expected = Board()
        expected.push_text("e4")
        self.assertEqual(canonical, expected.fen())
        self.assertEqual(self.projected, [canonical])

    def test_projection_failure_returns_to_book_instead_of_leaving_split_board_state(self) -> None:
        self._open_game()
        origin = self.app.reader.location()
        self.app._position_sink = lambda _fen: {"ok": False}

        result = self.app.browser_command("books", "book.open_position")

        self.assertEqual(result["kind"], "delegated")
        self.assertFalse(self.app.book_workflow.active)
        self.assertEqual(self.app.reader.location(), origin)
        self.assertEqual(self.app.shell.current_route.route_id, "books")
        events = self.app.drain_events()
        self.assertTrue(any(event.get("kind") == "error" for event in events))

    def test_navigation_projection_failure_closes_review_and_preserves_return_point(self) -> None:
        self._open_game()
        origin = self.app.reader.location()
        self.app.browser_command("books", "book.open_position")
        self.app._position_sink = lambda _fen: {"ok": False}

        result = self.app.browser_command("review", "book.board_next_move")

        self.assertEqual(result["kind"], "error")
        self.assertFalse(self.app.book_workflow.active)
        self.assertEqual(self.app.reader.location(), origin)
        self.assertEqual(self.app.shell.current_route.route_id, "books")


if __name__ == "__main__":
    unittest.main()
