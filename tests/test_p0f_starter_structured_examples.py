from __future__ import annotations

import unittest

from acs.bookdocument import BookDocument, Diagram, VariationTree
from acs.starter_books_training_runtime import build_training_ready_starter_course
from acs.starter_structured_examples import (
    STRUCTURED_EXAMPLE_COUNT,
    build_structured_starter_examples,
    structured_examples_manifest,
)


class StarterStructuredExamplesTests(unittest.TestCase):
    def test_catalogue_is_representative_deterministic_and_has_real_rav(self) -> None:
        examples = build_structured_starter_examples()
        self.assertEqual(16, STRUCTURED_EXAMPLE_COUNT)
        self.assertEqual(STRUCTURED_EXAMPLE_COUNT, len(examples))
        self.assertEqual(STRUCTURED_EXAMPLE_COUNT, len({item.opening for item in examples}))
        self.assertEqual(STRUCTURED_EXAMPLE_COUNT, len({item.root_fen for item in examples}))
        for item in examples:
            self.assertTrue(item.theme_uk.strip())
            self.assertTrue(item.main_san.strip())
            self.assertTrue(item.alternative_san.strip())
            self.assertNotEqual(item.main_san, item.alternative_san)
            self.assertIn('[SetUp "1"]', item.variation_pgn)
            self.assertIn(f'[FEN "{item.root_fen}"]', item.variation_pgn)
            self.assertIn("(", item.variation_pgn)
            self.assertIn(")", item.variation_pgn)

    def test_runtime_course_publishes_accessible_diagrams_and_variation_trees(self) -> None:
        course = build_training_ready_starter_course()
        diagrams = [block for block in course.blocks if isinstance(block, Diagram)]
        variations = [block for block in course.blocks if isinstance(block, VariationTree)]

        self.assertEqual(STRUCTURED_EXAMPLE_COUNT, len(diagrams))
        self.assertEqual(STRUCTURED_EXAMPLE_COUNT, len(variations))
        self.assertEqual(
            {diagram.fen for diagram in diagrams},
            {tree.root_fen for tree in variations},
        )
        self.assertEqual([], course.validate_structure())
        for diagram in diagrams:
            self.assertTrue(diagram.alt_text and diagram.alt_text.strip())
            self.assertTrue(diagram.caption and diagram.caption.strip())
        for tree in variations:
            self.assertTrue(tree.title and tree.title.strip())
            self.assertIn("(", tree.pgn)
            self.assertIn(")", tree.pgn)

        restored = BookDocument.from_dict(course.as_dict())
        self.assertEqual(course.as_dict(), restored.as_dict())

    def test_structured_manifest_exposes_binding_acceptance_counts(self) -> None:
        manifest = structured_examples_manifest()
        self.assertEqual(STRUCTURED_EXAMPLE_COUNT, manifest["diagram_count"])
        self.assertEqual(STRUCTURED_EXAMPLE_COUNT, manifest["variation_tree_count"])
        self.assertEqual(STRUCTURED_EXAMPLE_COUNT, manifest["unique_root_fen_count"])
        self.assertEqual(STRUCTURED_EXAMPLE_COUNT, manifest["accessible_alt_text_count"])
        self.assertEqual(STRUCTURED_EXAMPLE_COUNT, manifest["rav_example_count"])
        self.assertTrue(str(manifest["source"]).strip())


if __name__ == "__main__":
    unittest.main()
