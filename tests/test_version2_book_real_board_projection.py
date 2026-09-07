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
from acs.version2_release_ui import Version2ReleaseAccessibleChessAPI


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
        self.book = self.root / "study.md"
        self.book.write_text(
            "# Study\n\nBefore\n\n```pgn\n" + PGN + "```\n\nAfter\n",
            encoding="utf-8",
        )

    def _application(self, projector):
        return Version2Application(
            self.database,
            progress_store=BookProgressStore(self.root / "book-progress.json"),
            engine_assistance=EngineAssistedWorkflowService(self.analysis),
            board_dispatch=lambda *_args, **_kwargs: {"ok": True},
            board_position_projector=projector,
            copy_text=lambda _value: None,
        )

    def _open_game(self, app: Version2Application) -> None:
        app.open_book(self.book)
        result = app.browser_command("books", "book.next_game")
        self.assertNotEqual(result["kind"], "error")

    def test_book_game_projects_exact_canonical_position_into_real_release_board(self) -> None:
        api = Version2ReleaseAccessibleChessAPI(keymap_path=self.root / "keymap.json")
        self.addCleanup(api.close_analysis)
        app = Version2Application(
            self.database,
            progress_store=BookProgressStore(self.root / "book-progress.json"),
            engine_assistance=EngineAssistedWorkflowService(self.analysis),
            board_dispatch=api.v2_board_dispatch,
            board_position_projector=api.set_fen,
            copy_text=lambda _value: None,
        )
        api.bind_version2_application(app)
        self._open_game(app)

        opened = app.browser_command("books", "book.open_position")

        self.assertEqual(opened["kind"], "delegated")
        self.assertTrue(app.book_workflow.active)
        self.assertEqual(app.book_delegate.board_snapshot().fen(), Board.START)
        self.assertEqual(api.get_state()["fen"], Board.START)
        self.assertEqual(app.shell.current_route.route_id, "board")

        expected = Board()
        expected.push_text("e4")
        moved = app.browser_command("review", "book.board_next_move")

        self.assertEqual(moved["kind"], "review")
        self.assertEqual(app.book_delegate.board_snapshot().fen(), expected.fen())
        self.assertEqual(api.get_state()["fen"], expected.fen())
        self.assertEqual(app.shell.current_route.route_id, "board")

    def test_book_navigation_reprojects_each_canonical_position(self) -> None:
        calls: list[str] = []

        def projector(fen: str):
            calls.append(fen)
            return {"ok": True}

        app = self._application(projector)
        self._open_game(app)
        self.assertEqual(app.browser_command("books", "book.open_position")["kind"], "delegated")
        self.assertEqual(calls, [Board.START])

        expected = Board()
        expected.push_text("e4")
        self.assertEqual(app.browser_command("review", "book.board_next_move")["kind"], "review")
        self.assertEqual(calls[-1], expected.fen())
        self.assertEqual(app.book_workflow.view().current_fen, expected.fen())

        self.assertEqual(app.browser_command("review", "book.board_previous_move")["kind"], "review")
        self.assertEqual(calls[-1], Board.START)
        self.assertEqual(app.book_workflow.view().current_fen, Board.START)

    def test_open_projection_failure_returns_to_book_without_hidden_session(self) -> None:
        calls: list[str] = []

        def projector(fen: str):
            calls.append(fen)
            return {"ok": False}

        app = self._application(projector)
        self._open_game(app)
        origin = app.reader.location()

        result = app.browser_command("books", "book.open_position")

        self.assertEqual(result["kind"], "error")
        self.assertEqual(calls, [Board.START])
        self.assertFalse(app.book_workflow.active)
        self.assertEqual(app.reader.location(), origin)
        self.assertEqual(app.shell.current_route.route_id, "books")

    def test_navigation_projection_failure_rolls_back_book_cursor_and_board(self) -> None:
        expected = Board()
        expected.push_text("e4")
        calls: list[str] = []

        def projector(fen: str):
            calls.append(fen)
            if fen == expected.fen():
                return {"ok": False}
            return {"ok": True}

        app = self._application(projector)
        self._open_game(app)
        self.assertEqual(app.browser_command("books", "book.open_position")["kind"], "delegated")
        before = app.book_workflow.view()

        result = app.browser_command("review", "book.board_next_move")

        self.assertEqual(result["kind"], "error")
        restored = app.book_workflow.view()
        self.assertEqual(restored.cursor, before.cursor)
        self.assertEqual(restored.current_fen, before.current_fen)
        self.assertTrue(app.book_workflow.active)
        self.assertEqual(app.shell.current_route.route_id, "board")
        self.assertEqual(calls[-2], expected.fen())
        self.assertEqual(calls[-1], before.current_fen)

    def test_missing_projector_fails_closed_and_restores_book(self) -> None:
        app = self._application(None)
        self._open_game(app)
        origin = app.reader.location()

        result = app.browser_command("books", "book.open_position")

        self.assertEqual(result["kind"], "error")
        self.assertFalse(app.book_workflow.active)
        self.assertEqual(app.reader.location(), origin)
        self.assertEqual(app.shell.current_route.route_id, "books")


if __name__ == "__main__":
    unittest.main()
