from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from acs.bookdocument import BookDocument, Exercise
from acs.bookreader import BookReader
from acs.full_product_ui_shell import UILanguage
from acs.training_progress_store import TrainingProgressConflictError
from acs.version2_profile import VERSION2_ROUTE_IDS, build_version2_action_registry
from acs.version2_training_workspace import Version2BookTrainingWorkspace


START_FEN = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"


def make_book() -> BookDocument:
    return BookDocument(
        title="V2 Training journey",
        language="en",
        source_name=r"C:\Users\Reader\private-training-book.md",
        blocks=[
            Exercise(
                fen=START_FEN,
                prompt="First exercise",
                answer_text="e4",
                block_id="exercise-one",
                source_anchor="chapter-1:exercise-1",
            ),
            Exercise(
                fen=START_FEN,
                prompt="Second exercise",
                answer_text="d4",
                block_id="exercise-two",
                source_anchor="chapter-1:exercise-2",
            ),
        ],
    )


class Version2TrainingCurrentRuntimeTests(unittest.TestCase):
    def test_v2_profile_exposes_training_without_teacher_or_classes(self) -> None:
        self.assertIn("training", VERSION2_ROUTE_IDS)
        ids = {item.action_id for item in build_version2_action_registry().definitions()}
        self.assertIn("screen.training", ids)
        self.assertIn("training.submit", ids)
        self.assertNotIn("screen.teacher", ids)
        self.assertNotIn("screen.classes", ids)

    def test_book_training_continues_deterministically_and_resumes(self) -> None:
        document = make_book()
        reader = BookReader(document)
        with tempfile.TemporaryDirectory(prefix="accessible-chess-v2-training-") as raw:
            root = Path(raw)
            workspace = Version2BookTrainingWorkspace(
                reader,
                progress_root=root,
                language=UILanguage.EN,
            )
            bridge = workspace.start_current()
            first = bridge.projection.snapshot()
            self.assertEqual("First exercise", first["title"])
            self.assertNotIn(START_FEN, repr(first))
            self.assertNotIn("private-training-book", repr(first))

            completed = workspace.dispatch("training.submit", {"answer": "e4"})
            completed_snapshot = completed.payload["snapshot"]
            self.assertTrue(completed_snapshot["progress"]["completed"])
            actions = {item["command"]: item for item in completed_snapshot["actions"]}
            self.assertIn("training.continue", actions)
            self.assertTrue(actions["training.continue"]["enabled"])
            self.assertEqual(1, len(tuple(root.glob("*.json"))))

            continued = workspace.dispatch("training.continue", {})
            self.assertEqual(1, reader.location().index)
            self.assertEqual("Second exercise", continued.payload["snapshot"]["title"])
            self.assertFalse(continued.payload["snapshot"]["progress"]["completed"])

            second = workspace.dispatch("training.submit", {"answer": "d4"})
            self.assertTrue(second.payload["snapshot"]["progress"]["completed"])
            second_actions = {item["command"]: item for item in second.payload["snapshot"]["actions"]}
            self.assertFalse(second_actions["training.continue"]["enabled"])
            self.assertEqual(2, len(tuple(root.glob("*.json"))))

            reopened = Version2BookTrainingWorkspace(
                reader,
                progress_root=root,
                language=UILanguage.EN,
            )
            reopened.start_current()
            restored = reopened.snapshot()
            self.assertIsNotNone(restored)
            assert restored is not None
            self.assertEqual("Second exercise", restored["title"])
            self.assertTrue(restored["progress"]["completed"])

    def test_stale_persistence_conflict_rolls_back_in_memory_session(self) -> None:
        document = make_book()
        first_reader = BookReader(document)
        second_reader = BookReader(document)
        with tempfile.TemporaryDirectory(prefix="accessible-chess-v2-training-cas-") as raw:
            root = Path(raw)
            first = Version2BookTrainingWorkspace(first_reader, progress_root=root)
            second = Version2BookTrainingWorkspace(second_reader, progress_root=root)
            first.start_current()
            second.start_current()

            first.dispatch("training.submit", {"answer": "e4"})
            with self.assertRaises(TrainingProgressConflictError):
                second.dispatch("training.submit", {"answer": "e4"})

            self.assertFalse(second.session.completed)
            self.assertEqual(0, second.session.step_index)
            self.assertEqual(0, second.session.attempts)


if __name__ == "__main__":
    unittest.main()
