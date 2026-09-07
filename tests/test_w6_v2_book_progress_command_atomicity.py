from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from acs.acsdb import AcsDatabase
from acs.analysis_service import AnalysisService
from acs.book_progress_store import BookProgressStore
from acs.engine_assisted_workflows import EngineAssistedWorkflowService
from acs.version2_application import Version2Application


class Version2BookProgressCommandAtomicityEvidenceTests(unittest.TestCase):
    """RED-first evidence for application-owned Book progress publication.

    Commands that mutate durable BookReader progress must roll back live reader
    state if publication fails. Presentation-only commands such as language
    changes must not depend on Book progress I/O at all.
    """

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
            board_dispatch=lambda *_: None,
        )
        self.book = self.root / "lesson.md"
        self.book.write_text(
            "# Lesson\n\nFirst paragraph.\n\nSecond paragraph.\n",
            encoding="utf-8",
        )
        self.app.open_book(self.book)

    def test_failed_progress_save_does_not_commit_navigation(self):
        before = self.app.reader.snapshot()

        with patch.object(
            self.progress_store,
            "save",
            side_effect=OSError("simulated durable progress failure"),
        ):
            result = self.app.browser_command("books", "book.next")

        self.assertEqual(result["kind"], "error")
        self.assertEqual(
            self.app.reader.snapshot(),
            before,
            "failed durable progress publication committed a new live Book cursor",
        )

    def test_failed_progress_save_does_not_commit_bookmark(self):
        before = self.app.reader.snapshot()

        with patch.object(
            self.progress_store,
            "save",
            side_effect=OSError("simulated durable progress failure"),
        ):
            result = self.app.browser_command(
                "books",
                "book.bookmark.save",
                {"name": "checkpoint"},
            )

        self.assertEqual(result["kind"], "error")
        self.assertEqual(
            self.app.reader.snapshot(),
            before,
            "failed durable progress publication committed a new live bookmark",
        )

    def test_presentation_language_does_not_depend_on_progress_io(self):
        before_reader = self.app.reader.snapshot()

        with patch.object(
            self.progress_store,
            "save",
            side_effect=OSError("progress store intentionally unavailable"),
        ):
            result = self.app.browser_command(
                "books",
                "book.language",
                {"language": "en"},
            )

        self.assertEqual(
            result["kind"],
            "render",
            "presentation-only language change was incorrectly coupled to progress I/O",
        )
        self.assertEqual(result["payload"]["snapshot"]["document"]["lang"], "en")
        self.assertEqual(self.app.reader.snapshot(), before_reader)


if __name__ == "__main__":
    unittest.main()
