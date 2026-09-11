from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from acs.acsdb import AcsDatabase
from acs.analysis_service import AnalysisService
from acs.book_progress_store import BookProgressStore
from acs.book_training import build_book_training_material
from acs.bookdocument import Exercise, Heading, Paragraph
from acs.engine_assisted_workflows import EngineAssistedWorkflowService
from acs.starter_books_training_content import STARTER_COURSE_BOOK_KEY
from acs.starter_books_training_release import (
    STARTER_BOOKLET_CHAPTERS,
    STARTER_BOOKLET_COUNT,
    STARTER_RELEASE_LICENSE_ID,
    STARTER_RELEASE_LICENSE_TERMS_UK,
    build_release_booklets,
    build_training_task_catalogue,
    starter_release_manifest,
)
from acs.starter_books_training_runtime import build_training_ready_starter_course
from acs.version2_starter_content_application import Version2StarterContentApplication


EXPECTED_BOOKLETS = 24
EXPECTED_TRAINING_EXERCISES = 144
MIN_UNIQUE_TRAINING_FENS = 64


class StarterBooksTrainingReleaseTests(unittest.TestCase):
    def test_release_manifest_meets_p0f_volume_license_and_substance_gate(self) -> None:
        manifest = starter_release_manifest()
        self.assertEqual(1, manifest["schema_version"])
        self.assertEqual("uk", manifest["language"])
        self.assertEqual(STARTER_RELEASE_LICENSE_ID, manifest["license"]["id"])
        self.assertTrue(STARTER_RELEASE_LICENSE_TERMS_UK.strip())
        self.assertEqual(EXPECTED_BOOKLETS, manifest["material_count"])
        self.assertGreaterEqual(manifest["material_count"], 24)
        self.assertEqual(EXPECTED_TRAINING_EXERCISES, manifest["training_exercise_count"])
        self.assertGreaterEqual(manifest["training_exercise_count"], 100)
        self.assertGreaterEqual(manifest["training_unique_fen_count"], MIN_UNIQUE_TRAINING_FENS)

        materials = manifest["materials"]
        self.assertEqual(EXPECTED_BOOKLETS, len(materials))
        self.assertEqual(EXPECTED_BOOKLETS, len({item["material_id"] for item in materials}))
        self.assertEqual(EXPECTED_BOOKLETS, len({item["title"] for item in materials}))
        for item in materials:
            self.assertEqual(STARTER_BOOKLET_CHAPTERS, item["chapter_count"])
            self.assertGreaterEqual(item["word_count"], 1000)
            self.assertEqual(STARTER_RELEASE_LICENSE_ID, item["license_id"])
            self.assertTrue(item["source"].strip())

    def test_release_booklets_are_substantial_canonical_bookdocuments(self) -> None:
        booklets = build_release_booklets()
        self.assertEqual(STARTER_BOOKLET_COUNT, len(booklets))
        self.assertEqual(STARTER_BOOKLET_COUNT, len({book.title for book in booklets}))
        for book in booklets:
            self.assertEqual("uk", book.language)
            self.assertIn(STARTER_RELEASE_LICENSE_ID, book.source_rights)
            self.assertEqual([], book.validate_structure())
            headings = [block for block in book.blocks if isinstance(block, Heading)]
            paragraphs = [block for block in book.blocks if isinstance(block, Paragraph)]
            exercises = [block for block in book.blocks if isinstance(block, Exercise)]
            self.assertEqual(1 + STARTER_BOOKLET_CHAPTERS, len(headings))
            self.assertGreaterEqual(len(paragraphs), STARTER_BOOKLET_CHAPTERS * 8)
            self.assertEqual([], exercises)
            self.assertGreaterEqual(
                sum(len(block.text.split()) for block in headings + paragraphs),
                1000,
            )

    def test_training_catalogue_is_position_specific_legal_and_varied(self) -> None:
        tasks = build_training_task_catalogue()
        self.assertEqual(EXPECTED_TRAINING_EXERCISES, len(tasks))
        self.assertEqual(len(tasks), len({task.task_id for task in tasks}))
        self.assertGreaterEqual(len({task.opening for task in tasks}), 16)
        self.assertGreaterEqual(len({task.fen for task in tasks}), MIN_UNIQUE_TRAINING_FENS)
        self.assertEqual({"w", "b"}, {task.fen.split()[1] for task in tasks})

        course = build_training_ready_starter_course()
        self.assertEqual("uk", course.language)
        self.assertIn(STARTER_RELEASE_LICENSE_ID, course.source_rights)
        self.assertEqual([], course.validate_structure())
        exercises = [block for block in course.blocks if isinstance(block, Exercise)]
        self.assertEqual(EXPECTED_TRAINING_EXERCISES, len(exercises))
        self.assertGreaterEqual(
            len({exercise.fen for exercise in exercises}),
            MIN_UNIQUE_TRAINING_FENS,
        )

        exercise_indexes = [
            index for index, block in enumerate(course.blocks) if isinstance(block, Exercise)
        ]
        for index in exercise_indexes:
            material = build_book_training_material(course, index)
            self.assertEqual(1, len(material.definition.steps))
            self.assertTrue(material.definition.steps[0].accepted_moves)

    def test_release_inventory_text_is_derived_from_current_catalogue(self) -> None:
        manifest = starter_release_manifest()
        course = build_training_ready_starter_course()
        introduction = course.blocks[1]
        self.assertIsInstance(introduction, Paragraph)
        self.assertIn(str(manifest["material_count"]), introduction.text)
        self.assertIn(str(manifest["training_exercise_count"]), introduction.text)
        self.assertNotIn("120 вправ", introduction.text)

    def test_final_product_application_preloads_books_and_starts_real_training(self) -> None:
        with tempfile.TemporaryDirectory(prefix="accessible-chess-w3-p0f-release-") as raw:
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
                    self.assertEqual(
                        EXPECTED_TRAINING_EXERCISES,
                        len(app.reader.document.exercises()),
                    )

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
