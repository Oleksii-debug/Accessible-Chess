"""Section 40: the actual product Books menu opens genuine offline advanced
Lichess puzzles and uses the existing canonical Training/Board owners.
"""
from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from acs.acsdb import AcsDatabase
from acs.analysis_service import AnalysisService
from acs.book_progress_store import BookProgressStore
from acs.bookdocument import BookDocument, Exercise
from acs.engine_assisted_workflows import EngineAssistedWorkflowService
from acs.section40_advanced_licensed_dataset import (
    original_advanced_source_bytes, SOURCE_SHA256,
)
from acs.section40_advanced_training_runtime import (
    ADVANCED_BOOK_KEY, ADVANCED_MATERIAL_ID, build_advanced_offline_material,
)
from acs.version2_starter_content_application import Version2StarterContentApplication


class GenuineAdvancedMaterialProductTests(unittest.TestCase):
    def test_genuine_source_works_with_no_tests_directory_or_network(self):
        source = original_advanced_source_bytes()
        self.assertEqual(len(source), 9454)
        self.assertEqual(16, len(build_advanced_offline_material()[1]))
        self.assertEqual(len(SOURCE_SHA256), 64)
        course, tasks = build_advanced_offline_material()
        self.assertEqual(len(course.exercises()), 16)
        self.assertEqual(len(tasks), 16)
        restored = BookDocument.from_dict(course.as_dict())
        self.assertEqual(restored.as_dict(), course.as_dict())
        self.assertTrue(all(task["puzzle_rating_lichess_not_fide"] >= 2200
                            for task in tasks))
        self.assertTrue(any("endgame" in task["themes"] for task in tasks))

    def test_real_books_ui_opens_advanced_and_preserves_training_navigation(self):
        with tempfile.TemporaryDirectory(prefix="acs-section40-advanced-prod-") as raw:
            root = Path(raw)
            db = AcsDatabase(root / "real-library.acsdb")
            analysis = AnalysisService(lambda: None)
            try:
                app = Version2StarterContentApplication(
                    db,
                    progress_store=BookProgressStore(root / "books.json"),
                    engine_assistance=EngineAssistedWorkflowService(analysis),
                    board_dispatch=lambda *_: None,
                    board_position_projector=lambda _fen: {"ok": True},
                )
                try:
                    app.browser_command("shell", "screen.books")
                    before = app.snapshot()["books"]["starter_materials"]
                    self.assertEqual(before["booklet_count"], 24)
                    self.assertEqual(before["advanced_puzzle_count"], 16)
                    self.assertIn(ADVANCED_MATERIAL_ID,
                                  [x["material_id"] for x in before["items"]])
                    result = app.browser_command(
                        "books", "book.open_starter_material",
                        {"material_id": ADVANCED_MATERIAL_ID},
                    )
                    self.assertEqual(result["kind"], "render")
                    self.assertEqual(app.book_key, ADVANCED_BOOK_KEY)
                    self.assertEqual(len(app.reader.document.exercises()), 16)
                    self.assertEqual(
                        result["payload"]["snapshot"]["starter_materials"]["current_id"],
                        ADVANCED_MATERIAL_ID,
                    )
                    self.assertEqual(app.reader.location().kind, "Heading")
                    self.assertTrue(app._start_training_from_current_book())
                    self.assertEqual(app.reader.location().kind, "Exercise")
                    self.assertIsNotNone(app.training_workspace)
                    self.assertIsNotNone(app.training_workspace.snapshot())
                finally:
                    app.shutdown()
            finally:
                analysis.close()
                db.close()


if __name__ == "__main__":
    unittest.main()
