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

    def test_open_route_partial_commit_failure_restores_books_before_projection(self):
        origin = self._open_game_book()
        self.projected_positions.clear()
        real_open_route = self.app.shell.open_route

        def fail_after_board_commit(route_id, *, current_focus_id=""):
            focus = real_open_route(route_id, current_focus_id=current_focus_id)
            if route_id == "board":
                raise RuntimeError("synthetic failure after Board route commit")
            return focus

        with patch.object(
            self.app.shell,
            "open_route",
            side_effect=fail_after_board_commit,
        ):
            result = self.app.browser_command("books", "book.open_game")

        self.assertEqual("error", result["kind"])
        self.assertEqual([], self.projected_positions)
        self.assertFalse(self.app.book_workflow.active)
        self.assertEqual("books", self.app.shell.current_route.route_id)
        self.assertEqual(origin, self.app.reader.location())

    def test_open_focus_precommit_failure_rolls_back_before_release_projection(self):
        origin = self._open_game_book()
        self.projected_positions.clear()
        real_record_focus = self.app.shell.record_focus

        def fail_board_launch_focus(element_id):
            if element_id == "board-launcher":
                raise RuntimeError("synthetic Board focus ownership rejection")
            return real_record_focus(element_id)

        with patch.object(
            self.app.shell,
            "record_focus",
            side_effect=fail_board_launch_focus,
        ):
            result = self.app.browser_command("books", "book.open_game")

        self.assertEqual("error", result["kind"])
        self.assertEqual([], self.projected_positions)
        self.assertFalse(self.app.book_workflow.active)
        self.assertEqual("books", self.app.shell.current_route.route_id)
        self.assertEqual(origin, self.app.reader.location())

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

    def test_visible_books_browser_return_remains_usable(self):
        origin = self._open_board()
        routed = self.app.browser_command("shell", "screen.books")
        self.assertEqual("route", routed["kind"])
        self.assertEqual("books", self.app.shell.current_route.route_id)
        self.assertTrue(self.app.book_workflow.active)

        returned = self.app.browser_command("books", "book.return_from_board")

        self.assertEqual("render", returned["kind"])
        self.assertFalse(self.app.book_workflow.active)
        self.assertEqual("books", self.app.shell.current_route.route_id)
        self.assertEqual(origin, self.app.reader.location())

    def test_visible_books_native_return_remains_usable(self):
        origin = self._open_board()
        self.app.browser_command("shell", "screen.books")
        focus = f"book-block-{self.app.reader.index}"

        returned = self.app.adapter.activate_action(
            "book.return",
            current_focus_id=focus,
        )

        self.assertEqual("delegated", returned.kind)
        self.assertFalse(self.app.book_workflow.active)
        self.assertEqual("books", self.app.shell.current_route.route_id)
        self.assertEqual(origin, self.app.reader.location())

    def test_visible_books_exact_return_failure_preserves_books_route(self):
        origin = self._open_board()
        self.app.browser_command("shell", "screen.books")
        books_focus = self.app.shell.restore_focus_target()

        with patch.object(
            self.app.book_workflow,
            "return_to_book",
            side_effect=RuntimeError("synthetic exact-return failure from Books"),
        ):
            result = self.app.browser_command("books", "book.return_from_board")

        self.assertEqual("error", result["kind"])
        self.assertTrue(self.app.book_workflow.active)
        self.assertEqual("books", self.app.shell.current_route.route_id)
        self.assertEqual(books_focus, self.app.shell.restore_focus_target())
        self.assertEqual(origin, self.app.reader.location())

    def test_visible_books_focus_precommit_failure_preserves_books_route(self):
        origin = self._open_board()
        self.app.browser_command("shell", "screen.books")
        books_focus = self.app.shell.restore_focus_target()
        return_calls = 0
        real_return = self.app.book_workflow.return_to_book

        def observe_return():
            nonlocal return_calls
            return_calls += 1
            return real_return()

        with (
            patch.object(
                self.app.book_workflow,
                "return_to_book",
                side_effect=observe_return,
            ),
            patch.object(
                self.app,
                "_repair_book_block_focus_after_rebind",
                side_effect=RuntimeError("synthetic Books focus failure"),
            ),
        ):
            result = self.app.browser_command("books", "book.return_from_board")

        self.assertEqual("error", result["kind"])
        self.assertEqual(0, return_calls)
        self.assertTrue(self.app.book_workflow.active)
        self.assertEqual("books", self.app.shell.current_route.route_id)
        self.assertEqual(books_focus, self.app.shell.restore_focus_target())
        self.assertEqual(origin, self.app.reader.location())

    def test_stale_review_return_rejected_even_when_books_visible(self):
        origin = self._open_board()
        self.app.browser_command("shell", "screen.books")

        result = self.app.browser_command("review", "book.return")

        self.assertEqual("error", result["kind"])
        self.assertTrue(self.app.book_workflow.active)
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

    def test_return_route_rejection_happens_before_exact_return_mutation(self):
        origin = self._open_board()
        real_open_route = self.app.shell.open_route
        return_calls = 0
        real_return = self.app.book_workflow.return_to_book

        def observe_return():
            nonlocal return_calls
            return_calls += 1
            return real_return()

        def fail_books_route(route_id, *, current_focus_id=""):
            if route_id == "books":
                raise RuntimeError("synthetic Books route ownership rejection")
            return real_open_route(route_id, current_focus_id=current_focus_id)

        with (
            patch.object(
                self.app.book_workflow,
                "return_to_book",
                side_effect=observe_return,
            ),
            patch.object(
                self.app.shell,
                "open_route",
                side_effect=fail_books_route,
            ),
        ):
            result = self.app.browser_command("books", "book.return_from_board")

        self.assertEqual("error", result["kind"])
        self.assertEqual(0, return_calls)
        self.assertTrue(self.app.book_workflow.active)
        self.assertEqual("board", self.app.shell.current_route.route_id)
        self.assertEqual(origin, self.app.reader.location())

    def test_return_route_partial_commit_failure_restores_board_before_domain_return(self):
        origin = self._open_board()
        board_focus = self.app.shell.restore_focus_target()
        real_open_route = self.app.shell.open_route
        return_calls = 0
        real_return = self.app.book_workflow.return_to_book

        def observe_return():
            nonlocal return_calls
            return_calls += 1
            return real_return()

        def fail_after_books_commit(route_id, *, current_focus_id=""):
            focus = real_open_route(route_id, current_focus_id=current_focus_id)
            if route_id == "books":
                raise RuntimeError("synthetic failure after Books route commit")
            return focus

        with (
            patch.object(
                self.app.book_workflow,
                "return_to_book",
                side_effect=observe_return,
            ),
            patch.object(
                self.app.shell,
                "open_route",
                side_effect=fail_after_books_commit,
            ),
        ):
            result = self.app.browser_command("books", "book.return_from_board")

        self.assertEqual("error", result["kind"])
        self.assertEqual(0, return_calls)
        self.assertTrue(self.app.book_workflow.active)
        self.assertEqual("board", self.app.shell.current_route.route_id)
        self.assertEqual(board_focus, self.app.shell.restore_focus_target())
        self.assertEqual(origin, self.app.reader.location())

    def test_exact_return_failure_rolls_precommitted_route_back_to_board(self):
        origin = self._open_board()
        board_focus = self.app.shell.restore_focus_target()

        with patch.object(
            self.app.book_workflow,
            "return_to_book",
            side_effect=RuntimeError("synthetic exact-return failure"),
        ):
            result = self.app.browser_command("books", "book.return_from_board")

        self.assertEqual("error", result["kind"])
        self.assertTrue(self.app.book_workflow.active)
        self.assertEqual("board", self.app.shell.current_route.route_id)
        self.assertEqual(board_focus, self.app.shell.restore_focus_target())
        self.assertEqual(origin, self.app.reader.location())
        self.assertFalse(
            any(
                event.get("kind") == "route"
                and event.get("payload", {}).get("route_id") == "books"
                for event in self.app.drain_events()
            ),
            "failed exact Return must not publish a Books route refresh",
        )

    def test_return_focus_precommit_failure_rolls_route_back_before_domain_return(self):
        origin = self._open_board()
        board_focus = self.app.shell.restore_focus_target()
        return_calls = 0
        real_return = self.app.book_workflow.return_to_book

        def observe_return():
            nonlocal return_calls
            return_calls += 1
            return real_return()

        with (
            patch.object(
                self.app.book_workflow,
                "return_to_book",
                side_effect=observe_return,
            ),
            patch.object(
                self.app,
                "_repair_book_block_focus_after_rebind",
                side_effect=RuntimeError("synthetic Books focus precommit failure"),
            ),
        ):
            result = self.app.browser_command("books", "book.return_from_board")

        self.assertEqual("error", result["kind"])
        self.assertEqual(0, return_calls)
        self.assertTrue(self.app.book_workflow.active)
        self.assertEqual("board", self.app.shell.current_route.route_id)
        self.assertEqual(board_focus, self.app.shell.restore_focus_target())
        self.assertEqual(origin, self.app.reader.location())

    def test_return_succeeds_even_if_adapter_observer_fails(self):
        origin = self._open_board()
        self.app.drain_events()

        def fail_observer(_event):
            raise RuntimeError("synthetic non-authoritative observer failure")

        self.app.book_delegate._event_sink = fail_observer
        result = self.app.browser_command("books", "book.return_from_board")

        self.assertEqual("render", result["kind"])
        self.assertFalse(self.app.book_workflow.active)
        self.assertEqual("books", self.app.shell.current_route.route_id)
        self.assertEqual(origin, self.app.reader.location())
        self.assertEqual(
            [
                event
                for event in self.app.drain_events()
                if event.get("kind") == "route"
            ],
            [{"kind": "route", "payload": {"route_id": "books"}}],
        )


if __name__ == "__main__":
    unittest.main()
