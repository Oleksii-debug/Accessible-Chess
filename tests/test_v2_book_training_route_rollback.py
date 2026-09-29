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
        self.assertEqual(route["payload"]["focus_target"], "training-prompt")
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


if __name__ == "__main__":
    unittest.main()
