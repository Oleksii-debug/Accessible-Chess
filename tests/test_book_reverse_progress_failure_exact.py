from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from acs.acsdb import AcsDatabase
from acs.analysis_service import AnalysisService
from acs.book_progress_store import BookProgressStore
from acs.bookdocument import BookDocument
from acs.chesscore import Board
from acs.engine_assisted_workflows import EngineAssistedWorkflowService
from acs.full_product_ui_shell import UILanguage
from acs.version2_application import Version2Application


PGN_ONE = """[Event "Reverse progress one"]
[Result "*"]

1. e4 e5 *
"""

PGN_TWO = """[Event "Reverse progress two"]
[Result "*"]

1. d4 d5 *
"""


class BookReverseProgressFailureExactTests(unittest.TestCase):
    @contextmanager
    def _app(self, root: Path):
        database = AcsDatabase(root / "library.acsdb")
        analysis = None
        try:
            analysis = AnalysisService(lambda: None)
            progress = BookProgressStore(root / "book-progress.json")
            app = Version2Application(
                database,
                progress_store=progress,
                engine_assistance=EngineAssistedWorkflowService(analysis),
                board_dispatch=lambda *_: None,
                board_position_projector=lambda _fen: {"ok": True},
            )
            book = root / "reverse-progress.md"
            book.write_text(
                "# Reverse progress\n\n"
                "First position.\n\n"
                "```fen\n" + Board.START + "\nFirst position\n```\n\n"
                "Between positions.\n\n"
                "```fen\n" + Board.START + "\nSecond position\n```\n\n"
                "```pgn\n" + PGN_ONE + "```\n\n"
                "Between games.\n\n"
                "```pgn\n" + PGN_TWO + "```\n",
                encoding="utf-8",
            )
            app.open_book(book)
            yield app, progress
        finally:
            if analysis is not None:
                analysis.close()
            database.close()

    def _durable_snapshot(self, app: Version2Application, progress: BookProgressStore):
        restored = progress.restore(
            app.book_key,
            BookDocument.from_dict(app.reader.document.as_dict()),
        )
        return restored.snapshot()

    def _assert_failed_reverse_is_atomic(self, app, progress, command: str) -> None:
        language_result = app.browser_command(
            "books",
            "book.language",
            {"language": UILanguage.EN.value},
        )
        self.assertEqual(language_result["kind"], "render")
        bookmark_result = app.browser_command(
            "books",
            "book.bookmark.save",
            {"name": "atomic-origin"},
        )
        self.assertEqual(bookmark_result["kind"], "render")

        before_reader = app.reader.snapshot()
        before_durable = self._durable_snapshot(app, progress)
        before_language = app.books.projection.language
        before_bookmark_name = app.books.projection.bookmark_name

        with patch.object(
            progress,
            "save",
            side_effect=OSError(f"simulated {command} progress failure"),
        ):
            result = app.browser_command("books", command)

        self.assertEqual(result["kind"], "error")
        self.assertEqual(app.reader.snapshot(), before_reader)
        self.assertEqual(self._durable_snapshot(app, progress), before_durable)
        self.assertEqual(app.books.projection.language, before_language)
        self.assertEqual(app.books.projection.bookmark_name, before_bookmark_name)
        self.assertEqual(before_language, UILanguage.EN)
        self.assertEqual(before_bookmark_name, "atomic-origin")

    def test_previous_position_rolls_back_exact_reader_and_durable_progress(self) -> None:
        with tempfile.TemporaryDirectory() as root_text:
            with self._app(Path(root_text)) as (app, progress):
                self.assertEqual(
                    app.browser_command("books", "book.next_position")["kind"],
                    "render",
                )
                self.assertEqual(
                    app.browser_command("books", "book.next_position")["kind"],
                    "render",
                )
                self._assert_failed_reverse_is_atomic(
                    app,
                    progress,
                    "book.previous_position",
                )

    def test_previous_game_rolls_back_exact_reader_and_durable_progress(self) -> None:
        with tempfile.TemporaryDirectory() as root_text:
            with self._app(Path(root_text)) as (app, progress):
                self.assertEqual(
                    app.browser_command("books", "book.next_game")["kind"],
                    "render",
                )
                self.assertEqual(
                    app.browser_command("books", "book.next_game")["kind"],
                    "render",
                )
                self._assert_failed_reverse_is_atomic(
                    app,
                    progress,
                    "book.previous_game",
                )


    def test_shared_action_adapter_keeps_reverse_progress_failure_atomic(self) -> None:
        with tempfile.TemporaryDirectory() as root_text:
            with self._app(Path(root_text)) as (app, progress):
                self.assertEqual(
                    app.browser_command("books", "book.next_position")["kind"],
                    "render",
                )
                self.assertEqual(
                    app.browser_command("books", "book.next_position")["kind"],
                    "render",
                )
                before_reader = app.reader.snapshot()
                before_durable = self._durable_snapshot(app, progress)

                with patch.object(
                    progress,
                    "save",
                    side_effect=OSError("simulated native-route progress failure"),
                ):
                    result = app.adapter.activate_action("book.previous_position")

                self.assertEqual(result.kind, "error")
                self.assertEqual(app.reader.snapshot(), before_reader)
                self.assertEqual(self._durable_snapshot(app, progress), before_durable)



    def test_successful_reverse_commands_publish_exact_durable_restart_state(self) -> None:
        with tempfile.TemporaryDirectory() as root_text:
            with self._app(Path(root_text)) as (app, progress):
                app.browser_command("books", "book.next_position")
                app.browser_command("books", "book.next_position")
                result = app.browser_command("books", "book.previous_position")
                self.assertEqual(result["kind"], "render")
                self.assertEqual(
                    self._durable_snapshot(app, progress),
                    app.reader.snapshot(),
                )

                app.browser_command("books", "book.next_game")
                app.browser_command("books", "book.next_game")
                result = app.browser_command("books", "book.previous_game")
                self.assertEqual(result["kind"], "render")
                self.assertEqual(
                    self._durable_snapshot(app, progress),
                    app.reader.snapshot(),
                )

    def test_shared_action_adapter_rejects_reverse_payload_without_state_change(self) -> None:
        with tempfile.TemporaryDirectory() as root_text:
            with self._app(Path(root_text)) as (app, progress):
                app.browser_command("books", "book.next_position")
                app.browser_command("books", "book.next_position")
                before_reader = app.reader.snapshot()
                before_durable = self._durable_snapshot(app, progress)

                result = app.adapter.activate_action(
                    "book.previous_position",
                    {"index": 0},
                )

                self.assertEqual(result.kind, "error")
                self.assertEqual(app.reader.snapshot(), before_reader)
                self.assertEqual(self._durable_snapshot(app, progress), before_durable)



    def test_unreachable_reverse_boundary_never_writes_progress_or_changes_ui_state(self) -> None:
        with tempfile.TemporaryDirectory() as root_text:
            with self._app(Path(root_text)) as (app, progress):
                language_result = app.browser_command(
                    "books",
                    "book.language",
                    {"language": UILanguage.EN.value},
                )
                self.assertEqual(language_result["kind"], "render")
                before_reader = app.reader.snapshot()
                before_durable = self._durable_snapshot(app, progress)
                before_language = app.books.projection.language
                before_bookmark_name = app.books.projection.bookmark_name

                for command in ("book.previous_position", "book.previous_game"):
                    with self.subTest(command=command):
                        with patch.object(
                            progress,
                            "save",
                            side_effect=AssertionError(
                                "unreachable reverse navigation must not publish progress"
                            ),
                        ) as save:
                            result = app.browser_command("books", command)

                        self.assertEqual(result["kind"], "error")
                        save.assert_not_called()
                        self.assertEqual(app.reader.snapshot(), before_reader)
                        self.assertEqual(self._durable_snapshot(app, progress), before_durable)
                        self.assertEqual(app.books.projection.language, before_language)
                        self.assertEqual(app.books.projection.bookmark_name, before_bookmark_name)



    def test_native_command_queues_reverse_refresh_contract(self) -> None:
        cases = (
            ("book.next_position", "book.previous_position"),
            ("book.next_game", "book.previous_game"),
        )
        for forward, reverse in cases:
            with self.subTest(reverse=reverse):
                with tempfile.TemporaryDirectory() as root_text:
                    with self._app(Path(root_text)) as (app, progress):
                        self.assertEqual(app.browser_command("books", forward)["kind"], "render")
                        self.assertEqual(app.browser_command("books", forward)["kind"], "render")
                        app.drain_events()

                        command = app.adapter.activate_action(reverse)
                        self.assertEqual(command.kind, "delegated")
                        self.assertEqual(command.payload, {"action_id": reverse})
                        self.assertEqual(
                            self._durable_snapshot(app, progress),
                            app.reader.snapshot(),
                        )

                        app.native_command(command)
                        self.assertEqual(
                            app.drain_events(),
                            ({"kind": "delegated", "payload": {"action_id": reverse}},),
                        )
                        current_block = app.snapshot()["books"]["block"]
                        self.assertEqual(
                            current_block["dom_id"],
                            f"book-block-{app.reader.index}",
                        )



    def test_reverse_actions_cannot_move_hidden_reader_during_board_review(self) -> None:
        cases = (
            ("book.next_position", "book.previous_position"),
            ("book.next_game", "book.previous_game"),
        )
        for forward, reverse in cases:
            with self.subTest(reverse=reverse):
                with tempfile.TemporaryDirectory() as root_text:
                    with self._app(Path(root_text)) as (app, progress):
                        self.assertEqual(app.browser_command("books", forward)["kind"], "render")
                        self.assertEqual(app.browser_command("books", forward)["kind"], "render")
                        origin = app.reader.snapshot()
                        opened = app.browser_command("books", "book.open_position")
                        self.assertEqual(opened["kind"], "delegated")
                        self.assertTrue(app.book_workflow.active)
                        before_durable = self._durable_snapshot(app, progress)

                        with patch.object(
                            progress,
                            "save",
                            side_effect=AssertionError(
                                "hidden reader navigation must not publish progress"
                            ),
                        ) as save:
                            result = app.adapter.activate_action(reverse)

                        self.assertEqual(result.kind, "error")
                        save.assert_not_called()
                        self.assertTrue(app.book_workflow.active)
                        self.assertEqual(app.reader.snapshot(), origin)
                        self.assertEqual(self._durable_snapshot(app, progress), before_durable)

                        returned = app.browser_command("books", "book.return_from_board")
                        self.assertEqual(returned["kind"], "render")
                        self.assertFalse(app.book_workflow.active)
                        self.assertEqual(app.reader.snapshot(), origin)



    def test_active_board_blocks_every_book_progress_command_before_surface_dispatch(self) -> None:
        with tempfile.TemporaryDirectory() as root_text:
            with self._app(Path(root_text)) as (app, progress):
                self.assertEqual(
                    app.browser_command("books", "book.next_position")["kind"],
                    "render",
                )
                opened = app.browser_command("books", "book.open_position")
                self.assertEqual(opened["kind"], "delegated")
                self.assertTrue(app.book_workflow.active)
                # Book Board ownership deliberately survives temporary route
                # changes; prove the workflow fence rather than only route scope.
                routed = app.browser_command("shell", "screen.books")
                self.assertEqual(routed["kind"], "route")
                self.assertEqual(app.shell.current_route.route_id, "books")
                before_reader = app.reader.snapshot()
                before_durable = self._durable_snapshot(app, progress)

                payloads = {
                    "book.bookmark.save": {"name": "hidden-save"},
                    "book.bookmark.restore": {"name": "default"},
                }
                for command in sorted(app._BOOK_PROGRESS_COMMANDS):
                    with self.subTest(command=command):
                        with patch.object(
                            app.books,
                            "dispatch",
                            side_effect=AssertionError(
                                "active Board review must intercept Book progress commands"
                            ),
                        ) as dispatch, patch.object(
                            progress,
                            "save",
                            side_effect=AssertionError(
                                "active Board review must not persist hidden Book progress"
                            ),
                        ) as save:
                            result = app.browser_command(
                                "books",
                                command,
                                payloads.get(command),
                            )

                        self.assertEqual(result["kind"], "error")
                        dispatch.assert_not_called()
                        save.assert_not_called()
                        self.assertEqual(app.reader.snapshot(), before_reader)
                        self.assertEqual(self._durable_snapshot(app, progress), before_durable)
                        self.assertTrue(app.book_workflow.active)

                returned = app.browser_command("books", "book.return_from_board")
                self.assertEqual(returned["kind"], "render")
                self.assertFalse(app.book_workflow.active)



    def test_off_route_native_reverse_action_cannot_move_hidden_book_progress(self) -> None:
        cases = (
            ("book.next_position", "book.previous_position"),
            ("book.next_game", "book.previous_game"),
        )
        for forward, reverse in cases:
            with self.subTest(reverse=reverse):
                with tempfile.TemporaryDirectory() as root_text:
                    with self._app(Path(root_text)) as (app, progress):
                        self.assertEqual(app.browser_command("books", forward)["kind"], "render")
                        self.assertEqual(app.browser_command("books", forward)["kind"], "render")
                        before_reader = app.reader.snapshot()
                        before_durable = self._durable_snapshot(app, progress)

                        routed = app.browser_command("shell", "screen.library")
                        self.assertEqual(routed["kind"], "route")
                        self.assertEqual(app.shell.current_route.route_id, "library")

                        with patch.object(
                            progress,
                            "save",
                            side_effect=AssertionError(
                                "off-route native Book navigation must not publish progress"
                            ),
                        ) as save:
                            result = app.adapter.activate_action(reverse)

                        self.assertEqual(result.kind, "error")
                        save.assert_not_called()
                        self.assertEqual(app.reader.snapshot(), before_reader)
                        self.assertEqual(self._durable_snapshot(app, progress), before_durable)

                        routed = app.browser_command("shell", "screen.books")
                        self.assertEqual(routed["kind"], "route")
                        result = app.adapter.activate_action(reverse)
                        self.assertEqual(result.kind, "delegated")
                        self.assertNotEqual(app.reader.snapshot(), before_reader)
                        self.assertEqual(
                            self._durable_snapshot(app, progress),
                            app.reader.snapshot(),
                        )



    def test_off_route_native_board_open_cannot_open_hidden_book(self) -> None:
        with tempfile.TemporaryDirectory() as root_text:
            with self._app(Path(root_text)) as (app, progress):
                self.assertEqual(
                    app.browser_command("books", "book.next_position")["kind"],
                    "render",
                )
                before_reader = app.reader.snapshot()
                before_durable = self._durable_snapshot(app, progress)

                routed = app.browser_command("shell", "screen.library")
                self.assertEqual(routed["kind"], "route")
                self.assertEqual(app.shell.current_route.route_id, "library")

                with patch.object(
                    app.books,
                    "dispatch",
                    side_effect=AssertionError(
                        "off-route Book open must not enter Book surface"
                    ),
                ) as dispatch:
                    browser_result = app.browser_command(
                        "books",
                        "book.open_position",
                    )
                    native_result = app.adapter.activate_action("book.open_position")

                self.assertEqual(browser_result["kind"], "error")
                self.assertEqual(native_result.kind, "error")
                dispatch.assert_not_called()
                self.assertFalse(app.book_workflow.active)
                self.assertEqual(app.shell.current_route.route_id, "library")
                self.assertEqual(app.reader.snapshot(), before_reader)
                self.assertEqual(self._durable_snapshot(app, progress), before_durable)


    def test_active_board_rejects_second_native_open_even_if_books_route_is_visible(self) -> None:
        with tempfile.TemporaryDirectory() as root_text:
            with self._app(Path(root_text)) as (app, progress):
                self.assertEqual(
                    app.browser_command("books", "book.next_position")["kind"],
                    "render",
                )
                opened = app.browser_command("books", "book.open_position")
                self.assertEqual(opened["kind"], "delegated")
                self.assertTrue(app.book_workflow.active)
                origin = app.reader.snapshot()
                before_durable = self._durable_snapshot(app, progress)

                routed = app.browser_command("shell", "screen.books")
                self.assertEqual(routed["kind"], "route")
                self.assertEqual(app.shell.current_route.route_id, "books")

                with patch.object(
                    app.books,
                    "dispatch",
                    side_effect=AssertionError(
                        "active Book Board ownership must reject a second open"
                    ),
                ) as dispatch:
                    result = app.adapter.activate_action("book.open_position")

                self.assertEqual(result.kind, "error")
                dispatch.assert_not_called()
                self.assertTrue(app.book_workflow.active)
                self.assertEqual(app.reader.snapshot(), origin)
                self.assertEqual(self._durable_snapshot(app, progress), before_durable)

                returned = app.browser_command("books", "book.return_from_board")
                self.assertEqual(returned["kind"], "render")
                self.assertFalse(app.book_workflow.active)
                self.assertEqual(app.reader.snapshot(), origin)


    def test_hidden_active_book_board_rejects_native_mutations_but_allows_return(self) -> None:
        with tempfile.TemporaryDirectory() as root_text:
            with self._app(Path(root_text)) as (app, progress):
                self.assertEqual(
                    app.browser_command("books", "book.next_position")["kind"],
                    "render",
                )
                opened = app.browser_command("books", "book.open_position")
                self.assertEqual(opened["kind"], "delegated")
                self.assertTrue(app.book_workflow.active)
                origin = app.reader.snapshot()
                board_before = app.book_workflow.view()
                durable_before = self._durable_snapshot(app, progress)

                routed = app.browser_command("shell", "screen.library")
                self.assertEqual(routed["kind"], "route")
                self.assertEqual(app.shell.current_route.route_id, "library")

                with patch.object(
                    app.book_workflow,
                    "dispatch",
                    side_effect=AssertionError(
                        "hidden Book Board commands must be rejected before workflow dispatch"
                    ),
                ) as dispatch:
                    for action in sorted(app._BOOK_BOARD_ACTIVE_COMMANDS):
                        with self.subTest(action=action):
                            result = app.adapter.activate_action(action)
                            self.assertEqual(result.kind, "error")

                dispatch.assert_not_called()
                self.assertTrue(app.book_workflow.active)
                self.assertEqual(app.book_workflow.view(), board_before)
                self.assertEqual(app.reader.snapshot(), origin)
                self.assertEqual(self._durable_snapshot(app, progress), durable_before)

                returned = app.adapter.activate_action("book.return")
                self.assertEqual(returned.kind, "delegated")
                self.assertFalse(app.book_workflow.active)
                self.assertEqual(app.shell.current_route.route_id, "books")
                self.assertEqual(app.reader.snapshot(), origin)


    def test_hidden_active_book_board_rejects_review_browser_mutation_ingress(self) -> None:
        with tempfile.TemporaryDirectory() as root_text:
            with self._app(Path(root_text)) as (app, progress):
                self.assertEqual(
                    app.browser_command("books", "book.next_position")["kind"],
                    "render",
                )
                opened = app.browser_command("books", "book.open_position")
                self.assertEqual(opened["kind"], "delegated")
                self.assertTrue(app.book_workflow.active)
                board_before = app.book_workflow.view()
                durable_before = self._durable_snapshot(app, progress)

                routed = app.browser_command("shell", "screen.library")
                self.assertEqual(routed["kind"], "route")
                self.assertEqual(app.shell.current_route.route_id, "library")

                with patch.object(
                    app.book_workflow,
                    "dispatch",
                    side_effect=AssertionError(
                        "hidden review ingress must not reach Book Board workflow"
                    ),
                ) as dispatch:
                    result = app.browser_command(
                        "review",
                        "book.board_next_move",
                    )

                self.assertEqual(result["kind"], "error")
                dispatch.assert_not_called()
                self.assertTrue(app.book_workflow.active)
                self.assertEqual(app.book_workflow.view(), board_before)
                self.assertEqual(self._durable_snapshot(app, progress), durable_before)

                returned = app.browser_command("review", "book.return")
                self.assertEqual(returned["kind"], "review")
                self.assertFalse(app.book_workflow.active)
                self.assertEqual(app.shell.current_route.route_id, "books")


    def test_modal_dialog_blocks_book_progress_commands_before_dispatch(self) -> None:
        with tempfile.TemporaryDirectory() as root_text:
            with self._app(Path(root_text)) as (app, progress):
                self.assertEqual(
                    app.browser_command("books", "book.next_position")["kind"],
                    "render",
                )
                before_reader = app.reader.snapshot()
                before_durable = self._durable_snapshot(app, progress)
                opened = app.adapter.open_dialog(
                    "book-progress-modal",
                    opener_focus_id="book-reader",
                    initial_focus_id="book-progress-modal-confirm",
                )
                self.assertEqual("dialog-open", opened.kind)

                with patch.object(
                    app.books,
                    "dispatch",
                    side_effect=AssertionError(
                        "modal Book progress commands must be rejected before surface dispatch"
                    ),
                ) as dispatch, patch.object(
                    progress,
                    "save",
                    side_effect=AssertionError(
                        "modal Book progress commands must not publish progress"
                    ),
                ) as save:
                    browser_result = app.browser_command(
                        "books",
                        "book.next_position",
                    )
                    native_result = app.adapter.activate_action("book.next_position")

                self.assertEqual("error", browser_result["kind"])
                self.assertEqual("error", native_result.kind)
                dispatch.assert_not_called()
                save.assert_not_called()
                self.assertEqual(before_reader, app.reader.snapshot())
                self.assertEqual(before_durable, self._durable_snapshot(app, progress))
                self.assertEqual("book-progress-modal", app.shell.active_dialog_id)


    def test_native_board_open_progress_failure_does_not_publish_partial_review(self) -> None:
        """Native/NVDA open must not leave a transient BookBoard after save failure."""
        with tempfile.TemporaryDirectory() as root_text:
            with self._app(Path(root_text)) as (app, progress):
                self.assertEqual(
                    app.browser_command("books", "book.next_position")["kind"],
                    "render",
                )
                before_reader = app.reader.snapshot()
                durable_before = self._durable_snapshot(app, progress)
                before_route = app.shell.current_route.route_id

                with patch.object(
                    progress,
                    "save",
                    side_effect=OSError("simulated native board-open progress failure"),
                ):
                    result = app.adapter.activate_action("book.open_position")

                self.assertEqual(result.kind, "error")
                self.assertFalse(app.book_workflow.active)
                self.assertEqual(app.shell.current_route.route_id, before_route)
                self.assertEqual(before_route, "books")
                self.assertEqual(app.reader.snapshot(), before_reader)
                self.assertEqual(self._durable_snapshot(app, progress), durable_before)
                self.assertNotIn("simulated", str(result.payload.get("message", "")))


    def test_native_return_progress_failure_is_sanitized_and_keeps_exact_origin(self) -> None:
        """Native/NVDA Book return must share the browser return durability boundary."""
        with tempfile.TemporaryDirectory() as root_text:
            with self._app(Path(root_text)) as (app, progress):
                self.assertEqual(
                    app.browser_command("books", "book.next_game")["kind"],
                    "render",
                )
                origin = app.reader.snapshot()
                durable_before = self._durable_snapshot(app, progress)

                opened = app.browser_command("books", "book.open_position")
                self.assertEqual(opened["kind"], "delegated")
                self.assertTrue(app.book_workflow.active)

                # Move inside the transient Board review so return has real
                # review state to discard before the required progress write.
                app.router.dispatch("book.board_next_move")
                self.assertTrue(app.book_workflow.active)

                with patch.object(
                    progress,
                    "save",
                    side_effect=OSError("simulated native return progress failure"),
                ):
                    result = app.adapter.activate_action("book.return")

                self.assertEqual(result.kind, "error")
                self.assertFalse(app.book_workflow.active)
                self.assertEqual(app.shell.current_route.route_id, "books")
                self.assertEqual(app.reader.snapshot(), origin)
                self.assertEqual(self._durable_snapshot(app, progress), durable_before)
                self.assertNotIn("simulated", str(result.payload.get("message", "")))


if __name__ == "__main__":
    unittest.main()
