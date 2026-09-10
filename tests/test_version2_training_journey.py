from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from acs.bookdocument import BookDocument, Exercise, Paragraph
from acs.full_product_ui_shell import UILanguage
from acs.version2_profile import VERSION2_ROUTE_IDS, build_version2_action_registry
from acs.version2_training_workspace import Version2TrainingWorkspace


START_FEN = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"


def _document() -> BookDocument:
    return BookDocument(
        title="QA Training Book",
        language="uk",
        blocks=[
            Paragraph(
                text=(
                    "Звичайний текст може згадувати FEN, e4, d4 або ASCII-дошку, "
                    "але не є вправою."
                )
            ),
            Exercise(
                block_id="exercise-one",
                fen=START_FEN,
                prompt="Зіграйте 1.e4",
                answer_text="e4",
            ),
            Paragraph(text="Пояснення між явними семантичними вправами."),
            Exercise(
                block_id="exercise-two",
                fen=START_FEN,
                prompt="Зіграйте 1.d4",
                answer_text="d4",
            ),
        ],
    )


class Version2TrainingJourneyTests(unittest.TestCase):
    def test_v2_profile_exposes_training_without_reenabling_deferred_classroom(self) -> None:
        self.assertIn("training", VERSION2_ROUTE_IDS)
        action_ids = {
            definition.action_id
            for definition in build_version2_action_registry().definitions()
        }
        self.assertIn("screen.training", action_ids)
        self.assertIn("training.submit", action_ids)
        self.assertIn("training.hint", action_ids)
        self.assertNotIn("screen.teacher", action_ids)
        self.assertNotIn("screen.classes", action_ids)
        self.assertNotIn("remote.connect", action_ids)

    def test_only_explicit_valid_semantic_exercises_enter_training_collection(self) -> None:
        document = BookDocument(
            title="No fabricated training",
            blocks=[
                Paragraph(text="Position: startpos; answer e4; diagram follows in prose."),
                Exercise(
                    block_id="invalid-answer",
                    fen=START_FEN,
                    prompt="Invalid authored solution",
                    answer_text="e5",
                ),
            ],
        )
        with tempfile.TemporaryDirectory(prefix="accessible-chess-training-") as raw:
            workspace = Version2TrainingWorkspace(document, Path(raw))
            self.assertFalse(workspace.available)
            self.assertEqual(workspace.entry_count, 0)

    def test_complete_next_and_restart_restore_use_canonical_progress(self) -> None:
        document = _document()
        with tempfile.TemporaryDirectory(prefix="accessible-chess-training-") as raw:
            root = Path(raw)
            workspace = Version2TrainingWorkspace(document, root, language=UILanguage.UA)
            self.assertTrue(workspace.available)
            self.assertEqual(workspace.entry_count, 2)
            self.assertEqual(workspace.current_block_index, 1)

            first = workspace.snapshot()
            self.assertEqual(first["title"], "Зіграйте 1.e4")
            self.assertFalse(first["progress"]["completed"])
            self.assertNotIn(
                "training.next",
                {action["command"] for action in first["actions"]},
            )

            completed = workspace.dispatch("training.submit", {"answer": "e4"})
            self.assertEqual(completed.kind, "render")
            completed_snapshot = completed.payload["snapshot"]
            self.assertTrue(completed_snapshot["progress"]["completed"])
            self.assertIn(
                "training.next",
                {action["command"] for action in completed_snapshot["actions"]},
            )

            reopened = Version2TrainingWorkspace(document, root, language=UILanguage.UA)
            reopened_snapshot = reopened.snapshot()
            self.assertTrue(reopened_snapshot["progress"]["completed"])
            self.assertIn(
                "training.next",
                {action["command"] for action in reopened_snapshot["actions"]},
            )

            next_event = reopened.dispatch("training.next", {})
            self.assertEqual(next_event.kind, "render")
            self.assertEqual(reopened.current_index, 1)
            self.assertEqual(reopened.current_block_index, 3)
            next_snapshot = next_event.payload["snapshot"]
            self.assertEqual(next_snapshot["title"], "Зіграйте 1.d4")
            self.assertFalse(next_snapshot["progress"]["completed"])
            self.assertEqual(next_event.payload["focus_target"], "training-answer")

            reopened.dispatch("training.submit", {"answer": "d4"})
            final = Version2TrainingWorkspace(document, root, language=UILanguage.UA)
            final.dispatch("training.next", {})
            self.assertTrue(final.snapshot()["progress"]["completed"])
            self.assertNotIn(
                "training.next",
                {action["command"] for action in final.snapshot()["actions"]},
            )

    def test_failed_progress_publication_rolls_back_in_memory_training_state(self) -> None:
        document = _document()
        with tempfile.TemporaryDirectory(prefix="accessible-chess-training-") as raw:
            workspace = Version2TrainingWorkspace(document, Path(raw))
            before = workspace.snapshot()
            self.assertIsNotNone(workspace._store)
            with mock.patch.object(workspace._store, "save", side_effect=OSError("publication failed")):
                with self.assertRaises(OSError):
                    workspace.dispatch("training.submit", {"answer": "e4"})
            after = workspace.snapshot()
            self.assertEqual(after["status"], before["status"])
            self.assertEqual(after["progress"], before["progress"])
            self.assertEqual(after["message"], before["message"])


if __name__ == "__main__":
    unittest.main()
