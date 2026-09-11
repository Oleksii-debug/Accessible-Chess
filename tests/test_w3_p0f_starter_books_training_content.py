from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from acs.acsdb import AcsDatabase
from acs.analysis_service import AnalysisService
from acs.book_progress_store import BookProgressStore
from acs.bookdocument import Exercise, Heading, Paragraph
from acs.engine_assisted_workflows import EngineAssistedWorkflowService
from acs.starter_books_training_content import (
    STARTER_CONTENT_LANGUAGE,
    STARTER_CONTENT_RIGHTS,
    STARTER_COURSE_BOOK_KEY,
    build_starter_course,
    build_starter_materials,
    starter_content_manifest,
)
from acs.version2_starter_content_application import Version2StarterContentApplication


class StarterBooksTrainingContentTests(unittest.TestCase):
    def test_manifest_meets_p0f_volume_and_provenance_gate(self) -> None:
        manifest = starter_content_manifest()
        self.assertEqual(1, manifest["schema_version"])
        self.assertEqual("uk", manifest["language"])
        self.assertEqual(STARTER_CONTENT_RIGHTS, manifest["rights"])
        self.assertEqual(24, manifest["material_count"])
        self.assertGreaterEqual(manifest["exercise_count"], 100)
        self.assertEqual(120, manifest["exercise_count"])
        self.assertEqual(24, len(manifest["materials"]))
        self.assertEqual(24, len({item["material_id"] for item in manifest["materials"]}))
        self.assertTrue(all(item["exercise_count"] == 5 for item in manifest["materials"]))

    def test_all_24_materials_are_substantial_canonical_bookdocuments(self) -> None:
        materials = build_starter_materials()
        self.assertEqual(24, len(materials))
        self.assertEqual(24, len({material.title for material in materials}))
        for material in materials:
            self.assertEqual(STARTER_CONTENT_LANGUAGE, material.language)
            self.assertEqual(STARTER_CONTENT_RIGHTS, material.source_rights)
            self.assertEqual([], material.validate_structure())
            self.assertEqual(1, sum(isinstance(block, Heading) for block in material.blocks))
            paragraphs = [block for block in material.blocks if isinstance(block, Paragraph)]
            exercises = [block for block in material.blocks if isinstance(block, Exercise)]
            self.assertEqual(3, len(paragraphs))
            self.assertEqual(5, len(exercises))
            self.assertGreaterEqual(sum(len(block.text.split()) for block in paragraphs), 35)
            self.assertTrue(all(block.prompt.strip() for block in exercises))
            self.assertTrue(all(block.answer_text and block.answer_text.strip() for block in exercises))
            self.assertTrue(all(block.fen.strip() for block in exercises))

    def test_aggregate_course_is_offline_training_ready(self) -> None:
        course = build_starter_course()
        self.assertEqual("Accessible Chess: стартовий курс", course.title)
        self.assertEqual(STARTER_CONTENT_LANGUAGE, course.language)
        self.assertEqual(120, len(course.exercises()))
        self.assertEqual([], course.validate_structure())
        ids = [block.block_id for block in course.blocks if block.block_id]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertNotIn("http://", repr(course.as_dict()))
        self.assertNotIn("https://", repr(course.as_dict()))

    def test_final_product_application_preloads_books_and_starts_training(self) -> None:
        with tempfile.TemporaryDirectory(prefix="accessible-chess-w3-p0f-") as raw:
            root = Path(raw)
            database = AcsDatabase(root / "library.acsdb")
            analysis = AnalysisService(lambda: None)
            try:
                app = Version2StarterContentApplication(
                    database,
                    progress_store=BookProgressStore(root / "book-progress.json"),
                    engine_assistance=EngineAssistedWorkflowService(analysis),
                    board_dispatch=lambda *_: None,
                    board_position_projector=lambda _fen: {"ok": True},
                )
                try:
                    self.assertEqual(STARTER_COURSE_BOOK_KEY, app.book_key)
                    self.assertIsNotNone(app.reader)
                    self.assertIsNotNone(app.books)
                    self.assertEqual("Heading", app.reader.location().kind)
                    self.assertEqual(120, len(app.reader.document.exercises()))

                    self.assertTrue(app._start_training_from_current_book())
                    self.assertEqual("Exercise", app.reader.location().kind)
                    self.assertIsNotNone(app.training_workspace)
                    self.assertIsNotNone(app.training)
                    snapshot = app.training_workspace.snapshot()
                    self.assertIsNotNone(snapshot)
                    self.assertTrue(snapshot["title"].strip())
                finally:
                    app.shutdown()
            finally:
                analysis.close()
                database.close()


if __name__ == "__main__":
    unittest.main()
