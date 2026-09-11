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


class Version2BookRollbackHostPublicationTests(unittest.TestCase):
    def setUp(self) -> None:
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
        source = self.root / "rollback-host.md"
        source.write_text("# Rollback host\n", encoding="utf-8")
        document = BookDocument(
            title="Rollback host",
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
            book_key="rollback-host-book",
            document=document,
            warnings=(),
        )
        with patch("acs.version2_application.import_text_book", return_value=imported):
            self.app.open_book(source)
        self.assertEqual(self.app.snapshot()["screen"]["route_id"], "books")
        self.assertEqual(
            self.app.snapshot()["books"]["block"]["dom_id"],
            "book-block-0",
        )

    def _open_training_via_public_route(self) -> None:
        routed = self.app.browser_command("shell", "screen.training", {})
        self.assertNotEqual(routed["kind"], "error")
        snapshot = self.app.snapshot()
        self.assertEqual(snapshot["screen"]["route_id"], "training")
        self.assertIsNotNone(snapshot["training"])
        self.app.drain_events()

    def test_failed_book_persistence_from_training_publishes_books_refresh_event(self) -> None:
        self._open_exercise_book()
        self._open_training_via_public_route()
        before = self.app.reader.snapshot()

        with patch.object(
            self.progress_store,
            "save",
            side_effect=OSError("simulated durable Book progress failure"),
        ):
            result = self.app.browser_command("books", "book.next", {})

        self.assertEqual(result["kind"], "error")
        self.assertEqual(self.app.reader.snapshot(), before)
        self.assertIsNone(self.app.training_workspace)
        self.assertIsNone(self.app.training)
        snapshot = self.app.snapshot()
        self.assertEqual(snapshot["screen"]["route_id"], "books")
        self.assertEqual(snapshot["books"]["block"]["dom_id"], "book-block-0")

        events = self.app.drain_events()
        recovery = tuple(event for event in events if event.get("kind") == "route-recovered")
        self.assertEqual(len(recovery), 1)
        self.assertEqual(recovery[0]["payload"]["focus_target"], "book-block-0")
        self.assertNotIn("announcement", recovery[0]["payload"])

    def test_failed_book_persistence_does_not_rewrite_unrelated_active_route(self) -> None:
        self._open_exercise_book()
        self._open_training_via_public_route()
        routed = self.app.browser_command("shell", "screen.settings", {})
        self.assertNotEqual(routed["kind"], "error")
        self.assertEqual(self.app.snapshot()["screen"]["route_id"], "settings")
        self.app.drain_events()

        with patch.object(
            self.progress_store,
            "save",
            side_effect=OSError("simulated durable Book progress failure"),
        ):
            result = self.app.browser_command("books", "book.next", {})

        self.assertEqual(result["kind"], "error")
        self.assertEqual(self.app.snapshot()["screen"]["route_id"], "settings")
        self.assertFalse(
            any(event.get("kind") == "route-recovered" for event in self.app.drain_events())
        )


if __name__ == "__main__":
    unittest.main()
