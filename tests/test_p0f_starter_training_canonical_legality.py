from __future__ import annotations

import unittest

from acs.chesscore import Board, Move, sq_name
from acs.starter_books_training_release import build_training_task_catalogue


EXPECTED_TRAINING_TASKS = 144


def _uci(move: Move) -> str:
    """Project a canonical-core Move to the release catalogue's UCI form."""

    promotion = "" if move.promotion is None else move.promotion.lower()
    return f"{sq_name(move.frm)}{sq_name(move.to)}{promotion}"


class StarterTrainingCanonicalLegalityTests(unittest.TestCase):
    def test_every_published_fen_and_answer_round_trips_through_canonical_core(self) -> None:
        tasks = build_training_task_catalogue()
        self.assertEqual(EXPECTED_TRAINING_TASKS, len(tasks))

        for task in tasks:
            with self.subTest(task_id=task.task_id, opening=task.opening, ply=task.ply):
                # Rehydrate the published position independently instead of trusting
                # the mutable Board instance used while the catalogue was built.
                board = Board(task.fen)
                self.assertEqual(task.fen, board.fen())

                # Chess legality stays owned by acs.chesscore. This regression gate
                # only serializes canonical legal moves to the release UCI contract;
                # it does not implement a second move/rules engine in test code.
                legal_answers = {_uci(move) for move in board.legal_moves()}
                self.assertIn(
                    task.answer_uci,
                    legal_answers,
                    msg=(
                        f"starter task {task.task_id} publishes non-legal answer "
                        f"{task.answer_uci!r} for FEN {task.fen!r}"
                    ),
                )


if __name__ == "__main__":
    unittest.main()
