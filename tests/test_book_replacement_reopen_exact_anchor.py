from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from acs.acsdb import AcsDatabase
from acs.analysis_service import AnalysisService
from acs.book_progress_store import BookProgressStore
from acs.engine_assisted_workflows import EngineAssistedWorkflowService
from acs.version2_application import Version2Application


class BookReplacementReopenExactAnchorTests(unittest.TestCase):
    def test_same_path_replacement_uses_new_identity_and_old_bytes_reopen_exact_old_cursor(self) -> None:
        with tempfile.TemporaryDirectory() as root_text:
            root = Path(root_text)
            database = AcsDatabase(root / "library.acsdb")
            self.addCleanup(database.close)
            analysis = AnalysisService(lambda: None)
            self.addCleanup(analysis.close)
            progress = BookProgressStore(root / "book-progress.json")
            app = Version2Application(
                database,
                progress_store=progress,
                engine_assistance=EngineAssistedWorkflowService(analysis),
                board_dispatch=lambda *_: None,
            )
            book = root / "same-path.md"
            old_text = (
                "# Old source\n\n"
                + "\n\n".join(f"Old semantic paragraph {index}" for index in range(260))
                + "\n"
            )
            replacement_text = old_text.replace(
                "Old semantic paragraph 17",
                "Replacement semantic paragraph 17",
                1,
            )

            book.write_text(old_text, encoding="utf-8")
            app.open_book(book)
            app.reader.go_to(173)
            app.save_book_progress()
            old_key = app.book_key
            old_location = app.reader.location()
            old_snapshot = app.reader.snapshot()

            language = app.browser_command(
                "books",
                "book.language",
                {"language": "en"},
            )
            self.assertEqual(language["kind"], "render")
            self.assertEqual(app.reader.snapshot(), old_snapshot)

            book.write_text(replacement_text, encoding="utf-8")
            app.open_book(book)
            replacement_key = app.book_key
            self.assertNotEqual(replacement_key, old_key)
            self.assertEqual(app.reader.index, 0)
            self.assertNotEqual(app.reader.location().block_id, old_location.block_id)
            app.reader.go_to(41)
            app.save_book_progress()

            book.write_text(old_text, encoding="utf-8")
            app.open_book(book)
            self.assertEqual(app.book_key, old_key)
            self.assertEqual(app.reader.location().block_id, old_location.block_id)
            self.assertEqual(app.reader.location().source_anchor, old_location.source_anchor)
            self.assertEqual(app.reader.location().kind, old_location.kind)
            self.assertEqual(app.reader.index, old_location.index)


if __name__ == "__main__":
    unittest.main()
