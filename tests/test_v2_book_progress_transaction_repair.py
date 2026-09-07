from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from acs.acsdb import AcsDatabase
from acs.analysis_service import AnalysisService
from acs.book_progress_store import BookProgressStore
from acs.engine_assisted_workflows import EngineAssistedWorkflowService
from acs.version2_application import Version2Application


class Version2BookProgressTransactionRepairTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.database = AcsDatabase(self.root / "library.acsdb")
        self.addCleanup(self.database.close)
        self.analysis = AnalysisService(lambda: None)
        self.addCleanup(self.analysis.close)
        self.progress_store = BookProgressStore(self.root / "progress.json")
        self.app = Version2Application(
            self.database,
            progress_store=self.progress_store,
            engine_assistance=EngineAssistedWorkflowService(self.analysis),
            board_dispatch=lambda *_: None,
        )
        self.book = self.root / "lesson.md"
        self.book.write_text(
            "# Lesson\n\nFirst paragraph.\n\nSecond paragraph.\n",
            encoding="utf-8",
        )
        self.app.open_book(self.book)

    def test_failed_bookmark_publication_restores_transient_bookmark_name(self):
        initial = self.app.browser_command(
            "books",
            "book.bookmark.save",
            {"name": "prior"},
        )
        self.assertEqual(initial["kind"], "render")
        before_reader = self.app.reader.snapshot()
        self.assertEqual(self.app.books.projection.bookmark_name, "prior")

        with patch.object(
            self.progress_store,
            "save",
            side_effect=OSError("simulated progress failure"),
        ):
            result = self.app.browser_command(
                "books",
                "book.bookmark.save",
                {"name": "not-committed"},
            )

        self.assertEqual(result["kind"], "error")
        self.assertEqual(self.app.reader.snapshot(), before_reader)
        self.assertEqual(self.app.books.projection.bookmark_name, "prior")

    def test_action_registry_book_navigation_uses_same_progress_transaction(self):
        before_reader = self.app.reader.snapshot()

        with patch.object(
            self.progress_store,
            "save",
            side_effect=OSError("simulated progress failure"),
        ):
            with self.assertRaisesRegex(ValueError, "book command failed"):
                self.app.router.dispatch("book.next_block")

        self.assertEqual(self.app.reader.snapshot(), before_reader)


if __name__ == "__main__":
    unittest.main()