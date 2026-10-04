from __future__ import annotations

from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from acs.acsdb import AcsDatabase
from acs.analysis_service import AnalysisService
from acs.book_progress_store import BookProgressStore
from acs.engine_assisted_workflows import EngineAssistedWorkflowService
from acs.version2_application import Version2Application


_BOOK_PGN = (
    '[Event "Route ownership"]\n'
    '[White "Reader"]\n'
    '[Black "Board"]\n'
    '[Result "*"]\n\n'
    '1. e4 e5 2. Nf3 *\n'
)


class BookBoardRouteOwnershipTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.database = AcsDatabase(self.root / "library.acsdb")
        self.addCleanup(self.database.close)
        self.analysis = AnalysisService(lambda: None)
        self.addCleanup(self.analysis.close)
        self.projected_positions: list[str] = []

        def project_position(fen: str):
            self.projected_positions.append(fen)
            return {"ok": True}

        self.app = Version2Application(
            self.database,
            progress_store=BookProgressStore(self.root / "progress.json"),
            engine_assistance=EngineAssistedWorkflowService(self.analysis),
            board_dispatch=lambda *_args: None,
            board_position_projector=project_position,
        )

    def _open_game_book(self):
        source = self.root / "route-ownership.md"
        source.write_text(
            "# Route ownership\n\n"
            "Reader text.\n\n"
            "```pgn\n"
            + _BOOK_PGN
            + "```\n\n"
            "After game.\n",
            encoding="utf-8",
        )
        self.app.open_book(source)
        moved = self.app.browser_command("books", "book.next_game")
        self.assertEqual("render", moved["kind"])
        origin = self.app.reader.location()
        self.assertEqual("Game", origin.kind)
        return origin

    def _open_board(self):
        origin = self._open_game_book()
        self.projected_positions.clear()
        opened = self.app.browser_command("books", "book.open_game")
        self.assertEqual("delegated", opened["kind"])
        self.assertTrue(self.app.book_workflow.active)
        self.assertEqual("board", self.app.shell.current_route.route_id)
        self.assertEqual(1, len(self.projected_positions))
        return origin

    def test_open_route_failure_rolls_back_before_release_board_projection(self):
        origin = self._open_game_book()
        self.projected_positions.clear()
        self.app.pgn_board_active = True
        real_open_route = self.app.shell.open_route

        def fail_board_route(route_id, *, current_focus_id=""):
            if route_id == "board":
                raise RuntimeError("synthetic route ownership rejection")
            return real_open_route(route_id, current_focus_id=current_focus_id)

        with patch.object(
            self.app.shell,
            "open_route",
            side_effect=fail_board_route,
        ):
            result = self.app.browser_command("books", "book.open_game")

        self.assertEqual("error", result["kind"])
        self.assertEqual([], self.projected_positions)
        self.assertFalse(self.app.book_workflow.active)
        self.assertEqual("books", self.app.shell.current_route.route_id)
        self.assertEqual(origin, self.app.reader.location())
        self.assertTrue(
            self.app.pgn_board_active,
            "failed Book route acquisition must not discard the previous Board owner flag",
        )

    def test_navigation_route_failure_restores_cursor_before_projection(self):
        self._open_board()
        before = self.app.book_delegate.view()
        self.projected_positions.clear()
        real_open_route = self.app.shell.open_route

        def fail_board_route(route_id, *, current_focus_id=""):
            if route_id == "board":
                raise RuntimeError("synthetic Board route refresh rejection")
            return real_open_route(route_id, current_focus_id=current_focus_id)

        with patch.object(
            self.app.shell,
            "open_route",
            side_effect=fail_board_route,
        ):
            result = self.app.browser_command("review", "book.board_next_move")

        self.assertEqual("error", result["kind"])
        self.assertEqual([], self.projected_positions)
        self.assertTrue(self.app.book_workflow.active)
        self.assertEqual("board", self.app.shell.current_route.route_id)
        after = self.app.book_delegate.view()
        self.assertEqual(before.cursor, after.cursor)
        self.assertEqual(before.current_fen, after.current_fen)
        self.assertEqual(before.origin, after.origin)

    def test_hidden_browser_return_cannot_unwind_active_book_board(self):
        origin = self._open_board()
        routed = self.app.browser_command("shell", "screen.library")
        self.assertEqual("route", routed["kind"])
        self.assertEqual("library", self.app.shell.current_route.route_id)

        result = self.app.browser_command("books", "book.return_from_board")

        self.assertEqual("error", result["kind"])
        self.assertTrue(self.app.book_workflow.active)
        self.assertEqual("library", self.app.shell.current_route.route_id)
        self.assertEqual(origin, self.app.reader.location())

        self.assertEqual(
            "route",
            self.app.browser_command("shell", "screen.board")["kind"],
        )
        returned = self.app.browser_command("books", "book.return_from_board")
        self.assertEqual("render", returned["kind"])
        self.assertFalse(self.app.book_workflow.active)
        self.assertEqual("books", self.app.shell.current_route.route_id)
        self.assertEqual(origin, self.app.reader.location())

    def test_hidden_review_return_cannot_unwind_active_book_board(self):
        origin = self._open_board()
        self.app.browser_command("shell", "screen.library")

        result = self.app.browser_command("review", "book.return")

        self.assertEqual("error", result["kind"])
        self.assertTrue(self.app.book_workflow.active)
        self.assertEqual("library", self.app.shell.current_route.route_id)
        self.assertEqual(origin, self.app.reader.location())

    def test_hidden_native_return_fails_before_workflow_mutation(self):
        origin = self._open_board()
        self.app.browser_command("shell", "screen.library")

        result = self.app.adapter.activate_action(
            "book.return",
            current_focus_id="library-search-player",
        )

        self.assertEqual("error", result.kind)
        self.assertTrue(self.app.book_workflow.active)
        self.assertEqual("library", self.app.shell.current_route.route_id)
        self.assertEqual(origin, self.app.reader.location())


if __name__ == "__main__":
    unittest.main()
