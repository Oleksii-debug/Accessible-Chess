import inspect
import unittest

import acs.book_training as book_training
from acs.book_training import BookTrainingError, BookTrainingErrorCode, build_book_training_material
from acs.bookdocument import BookDocument, Exercise


START_FEN = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"


class BookTrainingCanonicalIngressTests(unittest.TestCase):
    def _book(self, solution_pgn: str) -> BookDocument:
        return BookDocument(
            "Canonical ingress",
            language="uk",
            source_name="canonical-ingress-test",
            blocks=[
                Exercise(
                    fen=START_FEN,
                    prompt="Play the authored line.",
                    solution_pgn=solution_pgn,
                    block_id="exercise",
                )
            ],
        )

    def test_book_training_does_not_bypass_d06_with_direct_parse_games(self):
        source = inspect.getsource(book_training)
        self.assertNotIn("from .gametree import GameTreeContractError", source)
        self.assertNotIn("parse_games(solution_pgn)", source)
        self.assertIn("parse_pgn_text(solution_pgn, strict=False)", source)

    def test_attached_symbolic_annotation_is_normalized_then_rejected_structurally(self):
        with self.assertRaises(BookTrainingError) as caught:
            build_book_training_material(self._book("1. e4?! *"), "block:exercise")
        self.assertEqual(
            caught.exception.code,
            BookTrainingErrorCode.UNSUPPORTED_SOLUTION_STRUCTURE,
        )

    def test_plain_mainline_still_builds_canonical_training_steps(self):
        material = build_book_training_material(
            self._book("1. e4 e5 2. Nf3 *"),
            "block:exercise",
        )
        self.assertEqual(
            tuple(next(iter(step.accepted_moves)) for step in material.definition.steps),
            ("e4", "e5", "Nf3"),
        )


if __name__ == "__main__":
    unittest.main()
