from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import patch

from acs.acsdb import AcsDatabase
from acs.analysis_service import AnalysisService
from acs.book_progress_store import BookProgressStore
from acs.bookdocument import BookDocument, Exercise
from acs.engine_assisted_workflows import EngineAssistedWorkflowService
from acs.full_product_ui_shell import UILanguage
from acs.version2_application import Version2Application


START_FEN = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"


class Version2BookTrainingRouteRollbackTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.database = AcsDatabase(self.root / "library.acsdb")
        self.addCleanup(self.database.close)
        self.analysis = AnalysisService(lambda: None)
        self.addCleanup(self.analysis.close)
        self.progress_store = BookProgressStore(self.root / "book-progress.json")
        self.app = Version2Application(
            self.database,
            progress_store=self.progress_store,
            engine_assistance=EngineAssistedWorkflowService(self.analysis),
            board_dispatch=lambda *_args: None,
        )

    def _open_exercise_book(self) -> None:
        source = self.root / "training-route-rollback.md"
        source.write_text("# Training route rollback\n", encoding="utf-8")
        document = BookDocument(
            title="Training route rollback",
            language="en",
            source_name=source.name,
            blocks=[
                Exercise(
                    fen=START_FEN,
                    prompt="First exercise",
                    answer_text="e4",
                    block_id="exercise-one",
                    source_anchor="chapter-1:exercise-1",
                ),
                Exercise(
                    fen=START_FEN,
                    prompt="Second exercise",
                    answer_text="d4",
                    block_id="exercise-two",
                    source_anchor="chapter-1:exercise-2",
                ),
            ],
        )
        imported = SimpleNamespace(
            book_key="training-route-rollback-book",
            document=document,
            warnings=(),
        )
        with patch("acs.version2_application.import_text_book", return_value=imported):
            self.app.open_book(source)

    def test_hidden_book_command_cannot_discard_live_training_route(self):
        self._open_exercise_book()
        reader_before = self.app.reader

        route = self.app.browser_command("shell", "screen.training")
        self.assertEqual(route["kind"], "route")
        self.assertEqual(route["payload"]["route_id"], "training")
        self.assertEqual(route["payload"]["focus_target"], "training-answer")
        self.assertEqual(self.app.shell.current_route.route_id, "training")
        self.assertIsNotNone(self.app.training_workspace)
        self.assertIsNotNone(self.app.training)
        self.assertIs(self.app.training_workspace.reader, reader_before)

        completed = self.app.browser_command(
            "training",
            "training.submit",
            {"answer": "e4"},
        )
        self.assertEqual(completed["kind"], "render")
        self.assertTrue(completed["payload"]["snapshot"]["progress"]["completed"])
        progress_files = tuple(self.app.training_progress_root.glob("*.json"))
        self.assertEqual(len(progress_files), 1)
        durable_training_before = progress_files[0].read_bytes()
        reader_snapshot_before = self.app.reader.snapshot()
        training_workspace_before = self.app.training_workspace
        training_bridge_before = self.app.training
        training_snapshot_before = training_workspace_before.snapshot()
        self.app.drain_events()

        with patch.object(
            self.progress_store,
            "save",
            side_effect=OSError("hidden Book command must not reach persistence"),
        ) as save:
            result = self.app.browser_command("books", "book.next")

        self.assertEqual(result["kind"], "error")
        save.assert_not_called()
        self.assertIs(self.app.reader, reader_before)
        self.assertEqual(self.app.reader.snapshot(), reader_snapshot_before)
        self.assertIs(self.app.training_workspace, training_workspace_before)
        self.assertIs(self.app.training, training_bridge_before)
        self.assertEqual(self.app.training_workspace.snapshot(), training_snapshot_before)
        self.assertEqual(progress_files[0].read_bytes(), durable_training_before)

        snapshot = self.app.snapshot()
        self.assertEqual(self.app.shell.current_route.route_id, "training")
        self.assertEqual(snapshot["screen"]["route_id"], "training")
        self.assertIsNotNone(snapshot["training"])
        self.assertEqual(self.app.drain_events(), ())

    def test_whitespace_hidden_book_commands_cannot_bypass_route_authority(self):
        self._open_exercise_book()
        reader_before = self.app.reader.snapshot()
        language_before = self.app.books.projection.language

        routed = self.app.browser_command("shell", "screen.settings")
        self.assertEqual("route", routed["kind"])
        self.assertEqual("settings", self.app.shell.current_route.route_id)
        self.app.drain_events()

        with patch.object(
            self.progress_store,
            "save",
            side_effect=AssertionError(
                "hidden whitespace Book command must not reach persistence"
            ),
        ) as save:
            navigation = self.app.browser_command("books", " book.next ", {})
            language = self.app.browser_command(
                "books",
                " book.language ",
                {"language": "en"},
            )
            board = self.app.browser_command("books", " book.open_position ", {})

        save.assert_not_called()
        self.assertEqual("error", navigation["kind"])
        self.assertEqual("error", language["kind"])
        self.assertEqual("error", board["kind"])
        self.assertEqual(reader_before, self.app.reader.snapshot())
        self.assertEqual(language_before, self.app.books.projection.language)
        self.assertFalse(self.app.book_workflow.active)
        self.assertEqual("settings", self.app.shell.current_route.route_id)
        self.assertEqual((), self.app.drain_events())

    def test_book_return_keeps_exact_origin_when_durability_acknowledgement_fails(self):
        self._open_exercise_book()
        self.app._board_position_projector = lambda _fen: {"ok": True}

        origin = self.app.reader.snapshot()
        opened = self.app.browser_command("books", "book.open_position", {})
        self.assertEqual("delegated", opened["kind"])
        self.assertTrue(self.app.book_workflow.active)
        self.assertEqual("board", self.app.shell.current_route.route_id)
        self.assertEqual(origin, self.app.reader.snapshot())
        self.app.drain_events()

        with patch.object(
            self.progress_store,
            "save",
            side_effect=AssertionError(
                "read-only Book Board return must not write progress"
            ),
        ) as save:
            returned = self.app.browser_command(
                "books",
                "book.return_from_board",
                {"presentation_token": self.app.snapshot()["books"]["presentation_token"]},
            )

        self.assertEqual("error", returned["kind"])
        save.assert_called_once()
        self.assertFalse(self.app.book_workflow.active)
        self.assertEqual("books", self.app.shell.current_route.route_id)
        self.assertEqual(origin, self.app.reader.snapshot())

    def test_whitespace_training_continue_uses_outer_book_persistence_transaction(self):
        self._open_exercise_book()
        opened = self.app.browser_command("shell", "screen.training")
        self.assertEqual("route", opened["kind"])
        self.assertEqual("training", self.app.shell.current_route.route_id)

        completed = self.app.browser_command(
            "training",
            "training.submit",
            {"answer": "e4"},
        )
        self.assertEqual("render", completed["kind"])
        self.assertTrue(completed["payload"]["snapshot"]["progress"]["completed"])

        before_reader = self.app.reader.snapshot()
        before_workspace = self.app.training_workspace
        before_training = before_workspace.snapshot()
        progress_files = tuple(self.app.training_progress_root.glob("*.json"))
        self.assertEqual(1, len(progress_files))
        durable_before = progress_files[0].read_bytes()

        with patch.object(
            self.progress_store,
            "save",
            side_effect=OSError("simulated outer Book progress failure"),
        ) as save:
            rejected = self.app.browser_command(
                "training",
                " training.continue ",
                {},
            )

        self.assertEqual("error", rejected["kind"])
        save.assert_called()
        self.assertEqual(before_reader, self.app.reader.snapshot())
        self.assertEqual("training", self.app.shell.current_route.route_id)
        self.assertIsNotNone(self.app.training_workspace)
        self.assertEqual(before_training, self.app.training_workspace.snapshot())
        self.assertEqual(durable_before, progress_files[0].read_bytes())

    def test_hidden_book_command_cannot_clobber_unrelated_active_route(self):
        self._open_exercise_book()
        reader_before = self.app.reader
        training_route = self.app.browser_command("shell", "screen.training")
        self.assertEqual(training_route["kind"], "route")
        self.assertIsNotNone(self.app.training_workspace)
        settings_route = self.app.browser_command("shell", "screen.settings")
        self.assertEqual(settings_route["kind"], "route")
        self.assertEqual(self.app.shell.current_route.route_id, "settings")

        reader_snapshot_before = self.app.reader.snapshot()
        training_workspace_before = self.app.training_workspace
        training_bridge_before = self.app.training
        training_snapshot_before = training_workspace_before.snapshot()
        self.app.drain_events()

        with patch.object(
            self.progress_store,
            "save",
            side_effect=OSError("hidden Book command must not reach persistence"),
        ) as save:
            result = self.app.browser_command("books", "book.next")

        self.assertEqual(result["kind"], "error")
        save.assert_not_called()
        self.assertIs(self.app.reader, reader_before)
        self.assertEqual(self.app.reader.snapshot(), reader_snapshot_before)
        self.assertIs(self.app.training_workspace, training_workspace_before)
        self.assertIs(self.app.training, training_bridge_before)
        self.assertEqual(self.app.training_workspace.snapshot(), training_snapshot_before)
        self.assertEqual(self.app.shell.current_route.route_id, "settings")
        self.assertEqual(self.app.shell.restore_focus_target(), "settings-list")
        self.assertEqual(self.app.drain_events(), ())



    def test_browser_focusin_survives_same_route_presentation_rollback(self):
        self._open_exercise_book()
        self.assertEqual("books", self.app.shell.current_route.route_id)
        before = self.app.shell._capture_presentation_state()
        sequence_before = self.app.shell._focus_observation_sequence

        self.app.record_focus("book-bookmark-name")
        self.assertGreater(
            self.app.shell._focus_observation_sequence,
            sequence_before,
        )
        self.assertEqual("book-bookmark-name", self.app._focus)

        self.app.shell._restore_presentation_state(before)

        self.assertEqual("books", self.app.shell.current_route.route_id)
        self.assertEqual(
            "book-bookmark-name",
            self.app.shell.restore_focus_target(),
        )
        self.assertEqual("book-bookmark-name", self.app._focus)


    def test_acknowledged_training_route_rolls_back_unpublished_owner_and_focus(self):
        self._open_exercise_book()
        prior_route = self.app.shell.current_route.route_id
        prior_focus = self.app._focus
        prior_shell_focus = self.app.shell.restore_focus_target()
        prior_workspace = self.app.training_workspace
        prior_training = self.app.training

        routed = self.app.browser_command(
            "shell",
            "screen.training",
            {"publication_protocol": "ack-v1", "request_id": 101},
        )

        self.assertEqual("route", routed["kind"])
        token = routed["payload"]["publication_token"]
        self.assertIs(type(token), int)
        self.assertGreater(token, 0)
        self.assertEqual("training", self.app.shell.current_route.route_id)
        self.assertIsNotNone(self.app.training_workspace)
        self.assertIsNotNone(self.app.training)

        rolled_back = self.app.browser_command(
            "shell",
            "shell.presentation_rollback",
            {"token": token},
        )

        self.assertEqual("presentation-rollback", rolled_back["kind"])
        self.assertEqual(token, rolled_back["payload"]["token"])
        self.assertEqual(prior_route, rolled_back["payload"]["route_id"])
        self.assertEqual(prior_focus, rolled_back["payload"]["focus_target"])
        self.assertEqual(prior_route, self.app.shell.current_route.route_id)
        self.assertEqual(prior_focus, self.app._focus)
        self.assertEqual(prior_shell_focus, self.app.shell.restore_focus_target())
        self.assertIs(prior_workspace, self.app.training_workspace)
        self.assertIs(prior_training, self.app.training)
        self.assertIsNone(self.app._pending_shell_publication)
        self.assertFalse(self.app.shell._publication_hold_active)

        duplicate_rollback = self.app.browser_command(
            "shell",
            "shell.presentation_rollback",
            {"token": token},
        )
        self.assertEqual("presentation-rollback", duplicate_rollback["kind"])
        self.assertEqual(prior_route, self.app.shell.current_route.route_id)

        opposite_commit = self.app.browser_command(
            "shell",
            "shell.presentation_commit",
            {"token": token},
        )
        self.assertEqual("error", opposite_commit["kind"])
        self.assertEqual(prior_route, self.app.shell.current_route.route_id)

    def test_acknowledged_route_commit_is_single_pending_one_shot(self):
        self._open_exercise_book()
        self.app.drain_events()
        queued_event = {"kind": "status", "payload": {"message": "before-route"}}
        self.app._events.append(queued_event)
        routed = self.app.browser_command(
            "shell",
            "screen.library",
            {"publication_protocol": "ack-v1", "request_id": 102},
        )
        self.assertEqual("route", routed["kind"])
        token = routed["payload"]["publication_token"]
        self.assertEqual("library", self.app.shell.current_route.route_id)

        blocked = self.app.browser_command(
            "shell",
            "screen.settings",
            {"publication_protocol": "ack-v1", "request_id": 103},
        )
        self.assertEqual("error", blocked["kind"])
        self.assertEqual("library", self.app.shell.current_route.route_id)
        self.assertTrue(self.app.shell._publication_hold_active)
        self.assertEqual((), self.app.drain_events())
        self.assertEqual(1, len(self.app._events))

        native_style = self.app.adapter.activate_action(
            "screen.settings",
            current_focus_id=self.app._focus,
        )
        self.assertEqual("error", native_style.kind)
        self.assertEqual("library", self.app.shell.current_route.route_id)
        self.assertTrue(self.app.shell._publication_hold_active)

        language_before = self.app.shell.language
        with self.assertRaisesRegex(RuntimeError, "publication"):
            self.app.shell.set_language(UILanguage.EN)
        with self.assertRaisesRegex(RuntimeError, "publication"):
            self.app.shell.open_dialog(
                "settings-dialog",
                opener_focus_id="library-search-player",
                initial_focus_id="settings-list",
            )
        self.assertIs(language_before, self.app.shell.language)
        self.assertIsNone(self.app.shell.active_dialog_id)
        self.assertEqual("library", self.app.shell.current_route.route_id)

        library_before = self.app.library.projection.snapshot()
        stale_surface = self.app.browser_command(
            "library",
            "library.search",
            {"player": "must-not-run"},
        )
        self.assertEqual("error", stale_surface["kind"])
        self.assertEqual(library_before, self.app.library.projection.snapshot())

        committed = self.app.browser_command(
            "shell",
            "shell.presentation_commit",
            {"token": token},
        )
        self.assertEqual("presentation-commit", committed["kind"])
        self.assertEqual(token, committed["payload"]["token"])
        self.assertIsNone(self.app._pending_shell_publication)
        self.assertFalse(self.app.shell._publication_hold_active)
        self.assertEqual("library", self.app.shell.current_route.route_id)
        self.assertEqual((queued_event,), self.app.drain_events())

        duplicate_commit = self.app.browser_command(
            "shell",
            "shell.presentation_commit",
            {"token": token},
        )
        self.assertEqual("presentation-commit", duplicate_commit["kind"])
        self.assertEqual(token, duplicate_commit["payload"]["token"])
        self.assertEqual("library", self.app.shell.current_route.route_id)

        replay = self.app.browser_command(
            "shell",
            "shell.presentation_rollback",
            {"token": token},
        )
        self.assertEqual("error", replay["kind"])
        self.assertEqual("library", self.app.shell.current_route.route_id)

    def test_shutdown_rolls_back_unpublished_training_before_progress_save(self):
        self._open_exercise_book()
        self.assertEqual("books", self.app.shell.current_route.route_id)

        routed = self.app.browser_command(
            "shell",
            "screen.training",
            {"publication_protocol": "ack-v1", "request_id": 203},
        )
        self.assertEqual("route", routed["kind"])
        self.assertIsNotNone(self.app._pending_shell_publication)
        staged_workspace = self.app.training_workspace
        self.assertIsNotNone(staged_workspace)

        with (
            patch.object(staged_workspace, "save") as staged_save,
            patch.object(self.app, "save_book_progress", return_value=None),
            patch.object(self.database, "close") as close_database,
        ):
            self.assertTrue(self.app.shutdown())

        staged_save.assert_not_called()
        close_database.assert_called_once_with()
        self.assertIsNone(self.app._pending_shell_publication)
        self.assertFalse(self.app.shell._publication_hold_active)
        self.assertEqual("books", self.app.shell.current_route.route_id)
        self.assertIsNone(self.app.training_workspace)
        self.assertIsNone(self.app.training)

    def test_acknowledged_route_start_replays_exact_request_without_second_transition(self):
        self._open_exercise_book()
        request = {"publication_protocol": "ack-v1", "request_id": 290}

        routed = self.app.browser_command("shell", "screen.library", request)
        self.assertEqual("route", routed["kind"])
        token = routed["payload"]["publication_token"]
        self.assertEqual("library", self.app.shell.current_route.route_id)

        replayed = self.app.browser_command("shell", "screen.library", request)
        self.assertEqual(routed, replayed)
        self.assertEqual(token, replayed["payload"]["publication_token"])
        self.assertEqual("library", self.app.shell.current_route.route_id)
        self.assertTrue(self.app.shell._publication_hold_active)
        self.assertEqual(
            token,
            self.app.snapshot()["shell_publication_token"],
        )

        conflicting = self.app.browser_command(
            "shell",
            "screen.settings",
            {"publication_protocol": "ack-v1", "request_id": 291},
        )
        self.assertEqual("error", conflicting["kind"])
        self.assertEqual("library", self.app.shell.current_route.route_id)

        committed = self.app.browser_command(
            "shell",
            "shell.presentation_commit",
            {"token": token},
        )
        self.assertEqual("presentation-commit", committed["kind"])
        self.assertFalse(self.app.shell._publication_hold_active)
        self.assertEqual(0, self.app.snapshot()["shell_publication_token"])


    def test_invalid_publication_protocol_fails_before_route_or_training_staging(self):
        self._open_exercise_book()
        prior_route = self.app.shell.current_route.route_id
        prior_focus = self.app._focus
        prior_workspace = self.app.training_workspace
        prior_training = self.app.training

        rejected = self.app.browser_command(
            "shell",
            "screen.training",
            {"publication_protocol": "future-v2", "request_id": 301},
        )

        self.assertEqual("error", rejected["kind"])
        self.assertEqual(prior_route, self.app.shell.current_route.route_id)
        self.assertEqual(prior_focus, self.app._focus)
        self.assertIs(prior_workspace, self.app.training_workspace)
        self.assertIs(prior_training, self.app.training)
        self.assertIsNone(self.app._pending_shell_publication)


if __name__ == "__main__":
    unittest.main()
