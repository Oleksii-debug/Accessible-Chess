from __future__ import annotations

import unittest

from acs.book_training import build_book_training_material
from acs.bookdocument import Diagram, Exercise, Paragraph, VariationTree
from acs.chesscore import Board
from acs.starter_books_training_quality import (
    MIN_SUBSTANTIAL_WORDS,
    STARTER_QUALITY_LICENSE_ID,
    build_p0f_starter_course,
    build_substantial_starter_materials,
    starter_quality_manifest,
)


class StarterP0FQualityFixForwardTests(unittest.TestCase):
    def test_manifest_has_per_item_provenance_license_and_substantial_materials(self) -> None:
        manifest = starter_quality_manifest()
        self.assertEqual(2, manifest["schema_version"])
        self.assertEqual("uk", manifest["language"])
        self.assertEqual("CC-BY-4.0", manifest["license_id"])
        self.assertEqual(STARTER_QUALITY_LICENSE_ID, manifest["license_id"])
        self.assertGreaterEqual(manifest["material_count"], 24)
        self.assertGreaterEqual(manifest["exercise_count"], 100)
        self.assertEqual(manifest["material_count"], len(manifest["materials"]))
        for item in manifest["materials"]:
            self.assertEqual("project-authored", item["source_type"])
            self.assertTrue(str(item["source_uri"]).startswith("urn:accessible-chess:starter:"))
            self.assertEqual(STARTER_QUALITY_LICENSE_ID, item["license_id"])
            self.assertTrue(str(item["license_terms"]).strip())
            self.assertTrue(str(item["attribution"]).strip())
            self.assertGreaterEqual(item["word_count"], MIN_SUBSTANTIAL_WORDS)
            self.assertEqual(5, item["exercise_count"])
            self.assertTrue(item["has_diagram"])
            self.assertTrue(item["has_variation_tree"])

    def test_each_material_is_self_contained_substantial_and_semantically_structured(self) -> None:
        materials = build_substantial_starter_materials()
        self.assertGreaterEqual(len(materials), 24)
        self.assertEqual(len(materials), len({material.title for material in materials}))
        for material in materials:
            self.assertEqual([], material.validate_structure())
            self.assertIn(STARTER_QUALITY_LICENSE_ID, material.source_rights or "")
            self.assertTrue((material.source_uri or "").startswith("urn:accessible-chess:starter:"))
            paragraphs = [block for block in material.blocks if isinstance(block, Paragraph)]
            exercises = [block for block in material.blocks if isinstance(block, Exercise)]
            self.assertGreaterEqual(len(paragraphs), 10)
            self.assertGreaterEqual(sum(len(block.text.split()) for block in paragraphs), MIN_SUBSTANTIAL_WORDS)
            self.assertEqual(5, len(exercises))
            self.assertEqual(1, sum(isinstance(block, Diagram) for block in material.blocks))
            self.assertEqual(1, sum(isinstance(block, VariationTree) for block in material.blocks))

    def test_all_training_exercises_are_position_specific_and_canonical_legal(self) -> None:
        course = build_p0f_starter_course()
        exercises = course.exercises()
        self.assertEqual(135, len(exercises))
        self.assertGreaterEqual(len({exercise.fen for exercise in exercises}), 24)
        self.assertEqual(135, len({(exercise.fen, exercise.answer_text) for exercise in exercises}))
        self.assertNotIn("Відповідай подумки", " ".join(exercise.prompt for exercise in exercises))

        indexes = [
            index for index, block in enumerate(course.blocks) if isinstance(block, Exercise)
        ]
        self.assertEqual(len(exercises), len(indexes))
        for index in indexes:
            exercise = course.blocks[index]
            self.assertIsInstance(exercise, Exercise)
            self.assertIsNotNone(exercise.answer_text)
            Board(exercise.fen).parse_move(exercise.answer_text or "")
            material = build_book_training_material(course, index)
            self.assertEqual(1, len(material.definition.steps))
            self.assertTrue(material.definition.steps[0].accepted_moves)

    def test_course_contains_representative_diagrams_and_variation_trees(self) -> None:
        course = build_p0f_starter_course()
        diagrams = [block for block in course.blocks if isinstance(block, Diagram)]
        variations = [block for block in course.blocks if isinstance(block, VariationTree)]
        self.assertGreaterEqual(len(diagrams), 24)
        self.assertGreaterEqual(len(variations), 24)
        self.assertGreaterEqual(len({diagram.fen for diagram in diagrams}), 24)
        self.assertTrue(all(diagram.alt_text and diagram.alt_text.strip() for diagram in diagrams))
        self.assertTrue(all(tree.root_fen and tree.pgn.strip() for tree in variations))
        ids = [block.block_id for block in course.blocks if block.block_id]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertEqual([], course.validate_structure())


if __name__ == "__main__":
    unittest.main()
