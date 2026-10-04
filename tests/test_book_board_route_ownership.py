from __future__ import annotations

from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from acs.acsdb import AcsDatabase
from acs.analysis_service import AnalysisService
from acs.book_progress_store import (
    BookProgressStore,
    BookProgressStoreError,
    BookProgressStoreErrorCode,
)
from acs.bookdocument import BookDocument, Exercise
from acs.bookreader import BookReader
from acs.chesscore import Board
from acs.engine_assisted_workflows import EngineAssistedWorkflowService
from acs.pgn_service import open_pgn
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

    def _load_pgn_workspace(self):
        source = self.root / "route-owner.pgn"
        source.write_text(_BOOK_PGN, encoding="utf-8")
        self.app.set_document(open_pgn(source))
        self.app.shell.open_route("pgn")
        return source

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

    def _install_training_exercise(self):
        document = BookDocument(
            title="Route-owned Training",
            language="uk",
            blocks=[
                Exercise(
                    fen=Board.START,
                    prompt="Find the first move.",
                    answer_text="e4",
                    block_id="training-route-owner",
                )
            ],
        )
        reader = BookReader(document)
        self.app.reader = reader
        self.app.book_key = "book:training-route-owner"
        self.app._restore_book_progress(
            reader.snapshot(),
            language=self.app.shell.language,
            bookmark_name="default",
        )
        self.app.progress_store.save(self.app.book_key, self.app.reader)
        self.app.shell.open_route("books")
        self.app._focus = self.app.shell.restore_focus_target()
        self.app._repair_book_block_focus_after_rebind()
        return reader

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

    def test_open_book_route_rejection_preserves_previous_book_owner(self):
        original = self.root / "original-owner.md"
        original.write_text("# Original\n\nStable owner.\n", encoding="utf-8")
        self.app.open_book(original)
        previous_reader = self.app.reader
        previous_books = self.app.books
        previous_workflow = self.app.book_workflow
        previous_key = self.app.book_key
        previous_training = self.app.training_workspace
        self.app.browser_command("shell", "screen.library")
        origin_route = self.app.shell.current_route.route_id

        candidate = self.root / "candidate-owner.md"
        candidate.write_text("# Candidate\n\nStaged owner.\n", encoding="utf-8")
        real_open_route = self.app.shell.open_route

        def reject_books_route(route_id, *, current_focus_id=""):
            if route_id == "books":
                raise RuntimeError("synthetic Books route rejection")
            return real_open_route(route_id, current_focus_id=current_focus_id)

        real_save = self.app.progress_store.save
        with (
            patch.object(
                self.app.shell,
                "open_route",
                side_effect=reject_books_route,
            ),
            patch.object(
                self.app.progress_store,
                "save",
                wraps=real_save,
            ) as save,
        ):
            with self.assertRaises(RuntimeError):
                self.app.open_book(candidate)

        self.assertEqual(
            [call.args[0] for call in save.call_args_list],
            [previous_key],
            "rejected Books route must not persist staged candidate progress",
        )
        self.assertIs(previous_reader, self.app.reader)
        self.assertIs(previous_books, self.app.books)
        self.assertIs(previous_workflow, self.app.book_workflow)
        self.assertEqual(previous_key, self.app.book_key)
        self.assertIs(previous_training, self.app.training_workspace)
        self.assertEqual(origin_route, self.app.shell.current_route.route_id)

    def test_open_book_partial_route_commit_restores_previous_owner_and_route(self):
        original = self.root / "original-partial.md"
        original.write_text("# Original\n\nStable owner.\n", encoding="utf-8")
        self.app.open_book(original)
        previous_reader = self.app.reader
        previous_books = self.app.books
        previous_workflow = self.app.book_workflow
        previous_key = self.app.book_key
        self.app.browser_command("shell", "screen.library")
        origin_route = self.app.shell.current_route.route_id

        candidate = self.root / "candidate-partial.md"
        candidate.write_text("# Candidate\n\nStaged owner.\n", encoding="utf-8")
        real_open_route = self.app.shell.open_route

        def fail_after_books_commit(route_id, *, current_focus_id=""):
            focus = real_open_route(route_id, current_focus_id=current_focus_id)
            if route_id == "books":
                raise RuntimeError("synthetic failure after Books route commit")
            return focus

        real_save = self.app.progress_store.save
        with (
            patch.object(
                self.app.shell,
                "open_route",
                side_effect=fail_after_books_commit,
            ),
            patch.object(
                self.app.progress_store,
                "save",
                wraps=real_save,
            ) as save,
        ):
            with self.assertRaises(RuntimeError):
                self.app.open_book(candidate)

        self.assertEqual(
            [call.args[0] for call in save.call_args_list],
            [previous_key],
            "partial Books route commit must roll back before candidate persistence",
        )
        self.assertIs(previous_reader, self.app.reader)
        self.assertIs(previous_books, self.app.books)
        self.assertIs(previous_workflow, self.app.book_workflow)
        self.assertEqual(previous_key, self.app.book_key)
        self.assertEqual(origin_route, self.app.shell.current_route.route_id)

    def test_open_book_candidate_progress_runs_only_after_books_route_is_owned(self):
        original = self.root / "original-persistence-owner.md"
        original.write_text("# Original\n\nStable owner.\n", encoding="utf-8")
        self.app.open_book(original)
        previous_reader = self.app.reader
        previous_books = self.app.books
        previous_workflow = self.app.book_workflow
        previous_key = self.app.book_key
        self.app.browser_command("shell", "screen.library")
        origin_route = self.app.shell.current_route.route_id
        origin_focus = self.app.shell.restore_focus_target()

        candidate = self.root / "candidate-persistence-owner.md"
        candidate.write_text("# Candidate\n\nStaged owner.\n", encoding="utf-8")
        real_save = self.app.progress_store.save
        candidate_save_routes = []

        def fail_candidate_save(book_key, reader):
            if book_key == previous_key:
                return real_save(book_key, reader)
            candidate_save_routes.append(self.app.shell.current_route.route_id)
            raise RuntimeError("synthetic candidate persistence failure")

        with patch.object(
            self.app.progress_store,
            "save",
            side_effect=fail_candidate_save,
        ):
            with self.assertRaises(RuntimeError):
                self.app.open_book(candidate)

        self.assertEqual(
            ["books"],
            candidate_save_routes,
            "candidate persistence must not run until Books route ownership commits",
        )
        self.assertIs(previous_reader, self.app.reader)
        self.assertIs(previous_books, self.app.books)
        self.assertIs(previous_workflow, self.app.book_workflow)
        self.assertEqual(previous_key, self.app.book_key)
        self.assertEqual(origin_route, self.app.shell.current_route.route_id)
        self.assertEqual(origin_focus, self.app.shell.restore_focus_target())

    def test_open_book_durability_unknown_accepts_exact_canonical_candidate(self):
        original = self.root / "original-durability-owner.md"
        original.write_text("# Original\n\nStable owner.\n", encoding="utf-8")
        self.app.open_book(original)
        previous_key = self.app.book_key
        self.app.browser_command("shell", "screen.library")

        candidate = self.root / "candidate-durability-owner.md"
        candidate.write_text("# Candidate\n\nCanonical staged owner.\n", encoding="utf-8")
        real_save = self.app.progress_store.save
        ambiguity_seen = []

        def publish_then_report_unknown(book_key, reader):
            result = real_save(book_key, reader)
            if book_key != previous_key:
                ambiguity_seen.append(book_key)
                raise BookProgressStoreError(
                    "synthetic post-publication durability ambiguity",
                    code=BookProgressStoreErrorCode.DURABILITY_UNKNOWN,
                )
            return result

        with patch.object(
            self.app.progress_store,
            "save",
            side_effect=publish_then_report_unknown,
        ):
            warning_count = self.app.open_book(candidate)

        self.assertEqual(0, warning_count)
        self.assertEqual(1, len(ambiguity_seen))
        self.assertEqual(ambiguity_seen[0], self.app.book_key)
        self.assertNotEqual(previous_key, self.app.book_key)
        self.assertEqual("books", self.app.shell.current_route.route_id)
        canonical = self.app.progress_store.restore_primary(
            self.app.book_key,
            self.app.reader.document,
        )
        self.assertEqual(self.app.reader.snapshot(), canonical.snapshot())

    def test_open_book_durability_unknown_without_canonical_candidate_rolls_back(self):
        original = self.root / "original-missing-canonical.md"
        original.write_text("# Original\n\nStable owner.\n", encoding="utf-8")
        self.app.open_book(original)
        previous_reader = self.app.reader
        previous_books = self.app.books
        previous_workflow = self.app.book_workflow
        previous_key = self.app.book_key
        self.app.browser_command("shell", "screen.library")
        origin_route = self.app.shell.current_route.route_id

        candidate = self.root / "candidate-missing-canonical.md"
        candidate.write_text("# Candidate\n\nNever published.\n", encoding="utf-8")
        real_save = self.app.progress_store.save

        def reject_candidate_as_unknown(book_key, reader):
            if book_key == previous_key:
                return real_save(book_key, reader)
            raise BookProgressStoreError(
                "synthetic ambiguity without canonical publication",
                code=BookProgressStoreErrorCode.DURABILITY_UNKNOWN,
            )

        with patch.object(
            self.app.progress_store,
            "save",
            side_effect=reject_candidate_as_unknown,
        ):
            with self.assertRaises(BookProgressStoreError) as caught:
                self.app.open_book(candidate)

        self.assertEqual(
            BookProgressStoreErrorCode.DURABILITY_UNKNOWN,
            caught.exception.code,
        )
        self.assertIs(previous_reader, self.app.reader)
        self.assertIs(previous_books, self.app.books)
        self.assertIs(previous_workflow, self.app.book_workflow)
        self.assertEqual(previous_key, self.app.book_key)
        self.assertEqual(origin_route, self.app.shell.current_route.route_id)

    def test_training_route_rejection_discards_staged_training_owner(self):
        reader = self._install_training_exercise()
        origin_route = self.app.shell.current_route.route_id
        origin_focus = self.app.shell.restore_focus_target()
        real_open_route = self.app.shell.open_route

        def reject_training_route(route_id, *, current_focus_id=""):
            if route_id == "training":
                raise RuntimeError("synthetic Training route rejection")
            return real_open_route(route_id, current_focus_id=current_focus_id)

        with patch.object(
            self.app.shell,
            "open_route",
            side_effect=reject_training_route,
        ):
            result = self.app.browser_command("shell", "screen.training")

        self.assertEqual("error", result["kind"])
        self.assertIs(reader, self.app.reader)
        self.assertIsNone(self.app.training_workspace)
        self.assertIsNone(self.app.training)
        self.assertEqual(origin_route, self.app.shell.current_route.route_id)
        self.assertEqual(origin_focus, self.app.shell.restore_focus_target())

    def test_training_reentry_route_rejection_preserves_retained_owner_internals(self):
        self._install_training_exercise()
        opened = self.app.browser_command("shell", "screen.training")
        self.assertEqual("route", opened["kind"])
        retained_workspace = self.app.training_workspace
        retained_bridge = self.app.training
        retained_session = retained_workspace.session
        self.app.browser_command("shell", "screen.books")
        origin_focus = self.app.shell.restore_focus_target()
        real_open_route = self.app.shell.open_route

        def reject_training_route(route_id, *, current_focus_id=""):
            if route_id == "training":
                raise RuntimeError("synthetic Training re-entry route rejection")
            return real_open_route(route_id, current_focus_id=current_focus_id)

        with patch.object(
            self.app.shell,
            "open_route",
            side_effect=reject_training_route,
        ):
            result = self.app.browser_command("shell", "screen.training")

        self.assertEqual("error", result["kind"])
        self.assertIs(retained_workspace, self.app.training_workspace)
        self.assertIs(retained_bridge, self.app.training)
        self.assertIs(retained_bridge, retained_workspace.bridge)
        self.assertIs(retained_session, retained_workspace.session)
        self.assertEqual("books", self.app.shell.current_route.route_id)
        self.assertEqual(origin_focus, self.app.shell.restore_focus_target())

    def test_training_partial_route_commit_restores_books_and_discards_stage(self):
        reader = self._install_training_exercise()
        origin_route = self.app.shell.current_route.route_id
        origin_focus = self.app.shell.restore_focus_target()
        real_open_route = self.app.shell.open_route

        def fail_after_training_commit(route_id, *, current_focus_id=""):
            focus = real_open_route(route_id, current_focus_id=current_focus_id)
            if route_id == "training":
                raise RuntimeError("synthetic failure after Training route commit")
            return focus

        with patch.object(
            self.app.shell,
            "open_route",
            side_effect=fail_after_training_commit,
        ):
            result = self.app.browser_command("shell", "screen.training")

        self.assertEqual("error", result["kind"])
        self.assertIs(reader, self.app.reader)
        self.assertIsNone(self.app.training_workspace)
        self.assertIsNone(self.app.training)
        self.assertEqual(origin_route, self.app.shell.current_route.route_id)
        self.assertEqual(origin_focus, self.app.shell.restore_focus_target())

    def test_set_document_route_rejection_preserves_previous_pgn_owner(self):
        self._load_pgn_workspace()
        self.app.browser_command("review", "pgn.open_on_board")
        previous_session = self.app.session
        previous_bridge = self.app.pgn
        self.app.browser_command("shell", "screen.library")
        origin_route = self.app.shell.current_route.route_id

        candidate = self.root / "replacement.pgn"
        candidate.write_text(
            '[Event "Replacement"]\n[Result "*"]\n\n1. d4 *\n',
            encoding="utf-8",
        )
        replacement = open_pgn(candidate)
        real_open_route = self.app.shell.open_route

        def reject_pgn_route(route_id, *, current_focus_id=""):
            if route_id == "pgn":
                raise RuntimeError("synthetic replacement route rejection")
            return real_open_route(route_id, current_focus_id=current_focus_id)

        with patch.object(
            self.app.shell,
            "open_route",
            side_effect=reject_pgn_route,
        ):
            with self.assertRaises(RuntimeError):
                self.app.set_document(replacement)

        self.assertIs(previous_session, self.app.session)
        self.assertIs(previous_bridge, self.app.pgn)
        self.assertTrue(self.app.pgn_board_active)
        self.assertEqual(origin_route, self.app.shell.current_route.route_id)

    def test_set_document_partial_route_commit_restores_previous_owner_and_route(self):
        self._load_pgn_workspace()
        previous_session = self.app.session
        previous_bridge = self.app.pgn
        self.app.browser_command("shell", "screen.library")
        origin_route = self.app.shell.current_route.route_id

        candidate = self.root / "replacement-partial.pgn"
        candidate.write_text(
            '[Event "Replacement partial"]\n[Result "*"]\n\n1. c4 *\n',
            encoding="utf-8",
        )
        replacement = open_pgn(candidate)
        real_open_route = self.app.shell.open_route

        def fail_after_pgn_commit(route_id, *, current_focus_id=""):
            focus = real_open_route(route_id, current_focus_id=current_focus_id)
            if route_id == "pgn":
                raise RuntimeError("synthetic failure after PGN route commit")
            return focus

        with patch.object(
            self.app.shell,
            "open_route",
            side_effect=fail_after_pgn_commit,
        ):
            with self.assertRaises(RuntimeError):
                self.app.set_document(replacement)

        self.assertIs(previous_session, self.app.session)
        self.assertIs(previous_bridge, self.app.pgn)
        self.assertEqual(origin_route, self.app.shell.current_route.route_id)

    def test_book_board_owner_blocks_pgn_open_after_navigate_to_pgn(self):
        self._load_pgn_workspace()
        origin = self._open_board()
        self.app.browser_command("shell", "screen.pgn")
        projected_before = tuple(self.projected_positions)

        result = self.app.browser_command("review", "pgn.open_on_board")

        self.assertEqual("error", result["kind"])
        self.assertTrue(self.app.book_workflow.active)
        self.assertFalse(self.app.pgn_board_active)
        self.assertEqual("pgn", self.app.shell.current_route.route_id)
        self.assertEqual(projected_before, tuple(self.projected_positions))
        self.assertEqual(origin, self.app.reader.location())

    def test_pgn_board_owner_blocks_book_open_after_navigate_to_books(self):
        self._load_pgn_workspace()
        opened = self.app.browser_command("review", "pgn.open_on_board")
        self.assertEqual("review", opened["kind"])
        self.assertTrue(self.app.pgn_board_active)
        self.assertEqual("board", self.app.shell.current_route.route_id)
        projected_before = tuple(self.projected_positions)

        self.app.browser_command("shell", "screen.books")
        origin = self._open_game_book()
        result = self.app.browser_command("books", "book.open_game")

        self.assertEqual("error", result["kind"])
        self.assertFalse(self.app.book_workflow.active)
        self.assertTrue(self.app.pgn_board_active)
        self.assertEqual("books", self.app.shell.current_route.route_id)
        self.assertEqual(projected_before, tuple(self.projected_positions))
        self.assertEqual(origin, self.app.reader.location())

    def test_hidden_pgn_webview_cannot_edit_canonical_document(self):
        self._load_pgn_workspace()
        selected = self.app.browser_command(
            "pgn",
            "pgn.select",
            {"node_id": "g0:main/m0"},
        )
        self.assertNotEqual("error", selected["kind"])
        self.assertFalse(self.app.session.dirty)
        self.app.browser_command("shell", "screen.library")

        result = self.app.browser_command(
            "pgn",
            "pgn.comment_edit",
            {"text": "hidden stale edit"},
        )

        self.assertEqual("error", result["kind"])
        self.assertFalse(self.app.session.dirty)
        self.assertEqual("library", self.app.shell.current_route.route_id)

    def test_modal_blocks_pgn_webview_edit_before_document_mutation(self):
        self._load_pgn_workspace()
        selected = self.app.browser_command(
            "pgn",
            "pgn.select",
            {"node_id": "g0:main/m0"},
        )
        self.assertNotEqual("error", selected["kind"])
        self.assertFalse(self.app.session.dirty)
        opened = self.app.adapter.open_dialog(
            "pgn-edit-modal",
            opener_focus_id="pgn-game-list",
            initial_focus_id="pgn-edit-modal-confirm",
        )
        self.assertEqual("dialog-open", opened.kind)

        result = self.app.browser_command(
            "pgn",
            "pgn.comment_edit",
            {"text": "modal-hidden edit"},
        )

        self.assertEqual("error", result["kind"])
        self.assertFalse(self.app.session.dirty)
        self.assertEqual("pgn", self.app.shell.current_route.route_id)
        self.assertEqual("pgn-edit-modal", self.app.shell.active_dialog_id)

    def test_hidden_native_pgn_navigation_cannot_mutate_cursor(self):
        self._load_pgn_workspace()
        selected = self.app.browser_command(
            "pgn",
            "pgn.select",
            {"node_id": "g0:main/m0"},
        )
        self.assertNotEqual("error", selected["kind"])
        before_cursor = self.app.session.workspace.cursor
        self.app.browser_command("shell", "screen.library")

        with self.assertRaises(ValueError):
            self.app.router.dispatch("pgn.next_item")

        self.assertEqual(before_cursor, self.app.session.workspace.cursor)
        self.assertEqual("library", self.app.shell.current_route.route_id)

    def test_modal_blocks_native_pgn_edit_before_document_mutation(self):
        self._load_pgn_workspace()
        selected = self.app.browser_command(
            "pgn",
            "pgn.select",
            {"node_id": "g0:main/m0"},
        )
        self.assertNotEqual("error", selected["kind"])
        self.assertFalse(self.app.session.dirty)
        opened = self.app.adapter.open_dialog(
            "pgn-native-edit-modal",
            opener_focus_id="pgn-game-list",
            initial_focus_id="pgn-native-edit-modal-confirm",
        )
        self.assertEqual("dialog-open", opened.kind)

        with self.assertRaises(ValueError):
            self.app.router.dispatch(
                "pgn.comment_edit",
                {"text": "native modal-hidden edit"},
            )

        self.assertFalse(self.app.session.dirty)
        self.assertEqual("pgn", self.app.shell.current_route.route_id)
        self.assertEqual("pgn-native-edit-modal", self.app.shell.active_dialog_id)

    def test_hidden_pgn_board_navigation_cannot_mutate_cursor(self):
        self._load_pgn_workspace()
        self.assertEqual(
            "review",
            self.app.browser_command("review", "pgn.open_on_board")["kind"],
        )
        before_cursor = self.app.session.workspace.cursor
        projected_before = tuple(self.projected_positions)
        self.app.browser_command("shell", "screen.library")

        result = self.app.browser_command("review", "pgn.board_next_move")

        self.assertEqual("error", result["kind"])
        self.assertEqual(before_cursor, self.app.session.workspace.cursor)
        self.assertEqual(projected_before, tuple(self.projected_positions))
        self.assertTrue(self.app.pgn_board_active)
        self.assertEqual("library", self.app.shell.current_route.route_id)

    def test_hidden_pgn_return_cannot_release_board_owner(self):
        self._load_pgn_workspace()
        self.app.browser_command("review", "pgn.open_on_board")
        self.app.browser_command("shell", "screen.library")

        result = self.app.browser_command("review", "pgn.return")

        self.assertEqual("error", result["kind"])
        self.assertTrue(self.app.pgn_board_active)
        self.assertEqual("library", self.app.shell.current_route.route_id)

    def test_visible_pgn_return_remains_usable(self):
        self._load_pgn_workspace()
        self.app.browser_command("review", "pgn.open_on_board")
        self.app.browser_command("shell", "screen.pgn")

        result = self.app.browser_command("review", "pgn.return")

        self.assertEqual("review", result["kind"])
        self.assertFalse(self.app.pgn_board_active)
        self.assertEqual("pgn", self.app.shell.current_route.route_id)

    def test_pgn_open_partial_route_commit_restores_pgn_before_projection(self):
        self._load_pgn_workspace()
        self.projected_positions.clear()
        real_open_route = self.app.shell.open_route

        def fail_after_board_commit(route_id, *, current_focus_id=""):
            focus = real_open_route(route_id, current_focus_id=current_focus_id)
            if route_id == "board":
                raise RuntimeError("synthetic PGN Board route tail failure")
            return focus

        with patch.object(
            self.app.shell,
            "open_route",
            side_effect=fail_after_board_commit,
        ):
            result = self.app.browser_command("review", "pgn.open_on_board")

        self.assertEqual("error", result["kind"])
        self.assertFalse(self.app.pgn_board_active)
        self.assertEqual("pgn", self.app.shell.current_route.route_id)
        self.assertEqual([], self.projected_positions)

    def test_pgn_projection_rejection_falls_back_off_board_if_pgn_recovery_rejects(self):
        self._load_pgn_workspace()
        self.projected_positions.clear()
        self.app._board_position_projector = lambda fen: (
            self.projected_positions.append(fen) or {"ok": False}
        )
        real_open_route = self.app.shell.open_route

        def reject_recovery_pgn(route_id, *, current_focus_id=""):
            if route_id == "pgn" and self.app.shell.current_route.route_id == "board":
                raise RuntimeError("synthetic PGN recovery rejection")
            return real_open_route(route_id, current_focus_id=current_focus_id)

        with patch.object(
            self.app.shell,
            "open_route",
            side_effect=reject_recovery_pgn,
        ):
            result = self.app.browser_command("review", "pgn.open_on_board")

        self.assertEqual("error", result["kind"])
        self.assertFalse(self.app.pgn_board_active)
        self.assertEqual("library", self.app.shell.current_route.route_id)
        self.assertEqual(1, len(self.projected_positions))

    def test_pgn_projection_rejection_accepts_partial_safe_pgn_recovery_commit(self):
        self._load_pgn_workspace()
        self.projected_positions.clear()
        self.app._board_position_projector = lambda fen: (
            self.projected_positions.append(fen) or {"ok": False}
        )
        real_open_route = self.app.shell.open_route

        def fail_after_recovery_pgn_commit(route_id, *, current_focus_id=""):
            focus = real_open_route(route_id, current_focus_id=current_focus_id)
            if route_id == "pgn" and self.app.shell.current_route.route_id == "pgn":
                raise RuntimeError("synthetic PGN recovery focus-tail failure")
            return focus

        with patch.object(
            self.app.shell,
            "open_route",
            side_effect=fail_after_recovery_pgn_commit,
        ):
            result = self.app.browser_command("review", "pgn.open_on_board")

        self.assertEqual("error", result["kind"])
        self.assertFalse(self.app.pgn_board_active)
        self.assertEqual("pgn", self.app.shell.current_route.route_id)
        self.assertEqual(
            self.app.shell.restore_focus_target(),
            self.app._focus,
        )
        self.assertEqual(1, len(self.projected_positions))

    def test_pgn_projection_rejection_restores_pgn_route_without_owner(self):
        self._load_pgn_workspace()
        self.projected_positions.clear()
        self.app._board_position_projector = lambda fen: (
            self.projected_positions.append(fen) or {"ok": False}
        )

        result = self.app.browser_command("review", "pgn.open_on_board")

        self.assertEqual("error", result["kind"])
        self.assertFalse(self.app.pgn_board_active)
        self.assertEqual("pgn", self.app.shell.current_route.route_id)
        self.assertEqual(1, len(self.projected_positions))

    def test_pgn_board_navigation_is_blocked_while_modal_owns_focus(self):
        self._load_pgn_workspace()
        self.app.browser_command("review", "pgn.open_on_board")
        before_cursor = self.app.session.workspace.cursor
        projected_before = tuple(self.projected_positions)
        opened = self.app.adapter.open_dialog(
            "pgn-board-modal",
            opener_focus_id="board-launcher",
            initial_focus_id="pgn-board-modal-confirm",
        )
        self.assertEqual("dialog-open", opened.kind)

        result = self.app.browser_command("review", "pgn.board_next_move")

        self.assertEqual("error", result["kind"])
        self.assertEqual(before_cursor, self.app.session.workspace.cursor)
        self.assertEqual(projected_before, tuple(self.projected_positions))
        self.assertTrue(self.app.pgn_board_active)
        self.assertEqual("board", self.app.shell.current_route.route_id)

    def test_book_double_projection_failure_keeps_owner_if_recovery_route_rejects(self):
        self._open_board()
        before = self.app.book_delegate.view()
        attempted = []

        def reject_projection(fen):
            attempted.append(fen)
            return {"ok": False}

        self.app._board_position_projector = reject_projection
        real_open_route = self.app.shell.open_route

        def reject_books_route(route_id, *, current_focus_id=""):
            if route_id == "books":
                raise RuntimeError("synthetic Books recovery route rejection")
            return real_open_route(route_id, current_focus_id=current_focus_id)

        with patch.object(
            self.app.shell,
            "open_route",
            side_effect=reject_books_route,
        ):
            result = self.app.browser_command("review", "book.board_next_move")

        self.assertEqual("error", result["kind"])
        after = self.app.book_delegate.view()
        self.assertEqual(before.cursor, after.cursor)
        self.assertEqual(before.current_fen, after.current_fen)
        self.assertGreaterEqual(len(attempted), 2)
        self.assertTrue(self.app.book_workflow.active)
        self.assertEqual("board", self.app.shell.current_route.route_id)

    def test_pgn_double_projection_failure_relinquishes_unknown_board(self):
        self._load_pgn_workspace()
        self.app.browser_command("review", "pgn.open_on_board")
        before_cursor = self.app.session.workspace.cursor
        before_fen = self.app.pgn_commands.current_fen()
        attempted: list[str] = []

        def reject_projection(fen):
            attempted.append(fen)
            return {"ok": False}

        self.app._board_position_projector = reject_projection
        result = self.app.browser_command("review", "pgn.board_next_move")

        self.assertEqual("error", result["kind"])
        self.assertEqual(before_cursor, self.app.session.workspace.cursor)
        self.assertEqual(before_fen, self.app.pgn_commands.current_fen())
        self.assertGreaterEqual(len(attempted), 2)
        self.assertEqual(before_fen, attempted[-1])
        self.assertFalse(self.app.pgn_board_active)
        self.assertEqual("pgn", self.app.shell.current_route.route_id)

    def test_pgn_double_projection_failure_keeps_owner_if_recovery_route_rejects(self):
        self._load_pgn_workspace()
        self.app.browser_command("review", "pgn.open_on_board")
        before_cursor = self.app.session.workspace.cursor
        before_fen = self.app.pgn_commands.current_fen()
        attempted = []

        def reject_projection(fen):
            attempted.append(fen)
            return {"ok": False}

        self.app._board_position_projector = reject_projection
        real_open_route = self.app.shell.open_route

        def reject_pgn_route(route_id, *, current_focus_id=""):
            if route_id == "pgn":
                raise RuntimeError("synthetic PGN recovery route rejection")
            return real_open_route(route_id, current_focus_id=current_focus_id)

        with patch.object(
            self.app.shell,
            "open_route",
            side_effect=reject_pgn_route,
        ):
            result = self.app.browser_command("review", "pgn.board_next_move")

        self.assertEqual("error", result["kind"])
        self.assertEqual(before_cursor, self.app.session.workspace.cursor)
        self.assertEqual(before_fen, self.app.pgn_commands.current_fen())
        self.assertGreaterEqual(len(attempted), 2)
        self.assertTrue(self.app.pgn_board_active)
        self.assertEqual("board", self.app.shell.current_route.route_id)

    def test_pgn_return_partial_route_commit_preserves_board_owner(self):
        self._load_pgn_workspace()
        self.app.browser_command("review", "pgn.open_on_board")
        real_open_route = self.app.shell.open_route

        def fail_after_pgn_commit(route_id, *, current_focus_id=""):
            focus = real_open_route(route_id, current_focus_id=current_focus_id)
            if route_id == "pgn":
                raise RuntimeError("synthetic PGN return route tail failure")
            return focus

        with patch.object(
            self.app.shell,
            "open_route",
            side_effect=fail_after_pgn_commit,
        ):
            result = self.app.browser_command("review", "pgn.return")

        self.assertEqual("error", result["kind"])
        self.assertTrue(self.app.pgn_board_active)
        self.assertEqual("board", self.app.shell.current_route.route_id)

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
