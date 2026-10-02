from __future__ import annotations

from pathlib import Path
import tempfile
import unittest
from unittest import mock

from acs.book_training import build_current_book_training_material
from acs.bookdocument import BookDocument, Exercise
from acs.bookreader import BookReader
from acs.full_product_ui_shell import UILanguage
from acs.learning_mastery_store import MasteryStoreBusyError
from acs.training import ExerciseSession
from acs.training_progress_store import TrainingProgressStore
from acs.version2_training_workspace import Version2BookTrainingWorkspace


START_FEN = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"


def make_book() -> BookDocument:
    return BookDocument(
        title="Mastery reachability",
        language="en",
        source_name=r"C:\private\mastery-book.md",
        blocks=[
            Exercise(
                fen=START_FEN,
                prompt="First",
                answer_text="e4",
                block_id="mastery-one",
                source_anchor="private:first",
            ),
            Exercise(
                fen=START_FEN,
                prompt="Second",
                answer_text="d4",
                block_id="mastery-two",
                source_anchor="private:second",
            ),
        ],
    )


class Version2MasteryReachabilityTests(unittest.TestCase):
    def test_two_completed_exercises_survive_restart_without_duplicate_reward(self) -> None:
        reader = BookReader(make_book())
        with tempfile.TemporaryDirectory(prefix="accessible-chess-mastery-v2-") as raw:
            root = Path(raw)
            workspace = Version2BookTrainingWorkspace(
                reader,
                progress_root=root,
                language=UILanguage.EN,
            )
            bridge = workspace.start_current()
            initial = bridge.projection.snapshot()
            self.assertTrue(initial["mastery"]["available"])
            self.assertEqual(0, initial["mastery"]["points"])

            first = workspace.dispatch("training.submit", {"answer": "e4"})
            first_mastery = first.payload["snapshot"]["mastery"]
            self.assertGreater(first_mastery["points"], 0)
            self.assertEqual(1, workspace.mastery_state.revision)
            self.assertEqual(1, workspace.mastery_state.completed_count)
            self.assertTrue((root / ".mastery" / "state.json").is_file())
            self.assertEqual(1, len(tuple(root.glob("*.json"))))

            workspace.dispatch("training.continue", {})
            second = workspace.dispatch("training.submit", {"answer": "d4"})
            second_mastery = second.payload["snapshot"]["mastery"]
            self.assertGreater(second_mastery["points"], first_mastery["points"])
            self.assertEqual(2, workspace.mastery_state.revision)
            self.assertEqual(2, workspace.mastery_state.completed_count)

            before_points = workspace.mastery_state.total_points
            before_revision = workspace.mastery_state.revision
            reopened = Version2BookTrainingWorkspace(
                reader,
                progress_root=root,
                language=UILanguage.EN,
            )
            reopened_bridge = reopened.start_current()
            restored = reopened_bridge.projection.snapshot()["mastery"]
            self.assertEqual(before_points, restored["points"])
            self.assertEqual(before_revision, reopened.mastery_state.revision)
            self.assertEqual(2, reopened.mastery_state.completed_count)

    def test_completed_training_file_is_reconciled_after_mastery_crash_gap(self) -> None:
        reader = BookReader(make_book())
        with tempfile.TemporaryDirectory(prefix="accessible-chess-mastery-recovery-") as raw:
            root = Path(raw)
            material = build_current_book_training_material(reader)
            session = ExerciseSession(material.definition)
            self.assertTrue(session.submit("e4").completed)
            progress_name = Version2BookTrainingWorkspace._exercise_filename(material)
            TrainingProgressStore(root / progress_name).save(
                session,
                expected_revision=None,
            )
            self.assertFalse((root / ".mastery" / "state.json").exists())

            recovered = Version2BookTrainingWorkspace(
                reader,
                progress_root=root,
                language=UILanguage.EN,
            )
            bridge = recovered.start_current()
            snapshot = bridge.projection.snapshot()
            self.assertTrue(snapshot["progress"]["completed"])
            self.assertGreater(snapshot["mastery"]["points"], 0)
            self.assertEqual(1, recovered.mastery_state.revision)

            points = recovered.mastery_state.total_points
            reopened = Version2BookTrainingWorkspace(
                reader,
                progress_root=root,
                language=UILanguage.EN,
            )
            reopened.start_current()
            self.assertEqual(1, reopened.mastery_state.revision)
            self.assertEqual(points, reopened.mastery_state.total_points)

    def test_busy_mastery_save_never_rolls_back_canonical_training(self) -> None:
        reader = BookReader(make_book())
        with tempfile.TemporaryDirectory(prefix="accessible-chess-mastery-busy-") as raw:
            root = Path(raw)
            workspace = Version2BookTrainingWorkspace(
                reader,
                progress_root=root,
                language=UILanguage.EN,
            )
            workspace.start_current()

            with mock.patch.object(
                workspace._mastery_store,
                "save",
                side_effect=MasteryStoreBusyError("busy"),
            ):
                event = workspace.dispatch("training.submit", {"answer": "e4"})

            self.assertTrue(event.payload["snapshot"]["progress"]["completed"])
            self.assertTrue(workspace.session.completed)
            self.assertEqual(0, workspace.mastery_state.revision)
            self.assertTrue(event.payload["snapshot"]["mastery"]["status"])
            self.assertEqual(1, len(tuple(root.glob("*.json"))))

            # The next start sees the durable completed Training snapshot and
            # fills the secondary mastery gap exactly once.
            recovered = Version2BookTrainingWorkspace(
                reader,
                progress_root=root,
                language=UILanguage.EN,
            )
            recovered.start_current()
            self.assertEqual(1, recovered.mastery_state.revision)
            self.assertGreater(recovered.mastery_state.total_points, 0)

    def test_corrupt_mastery_store_is_not_overwritten_and_training_remains_usable(self) -> None:
        reader = BookReader(make_book())
        with tempfile.TemporaryDirectory(prefix="accessible-chess-mastery-corrupt-") as raw:
            root = Path(raw)
            mastery_path = root / ".mastery" / "state.json"
            mastery_path.parent.mkdir(parents=True)
            corrupt = b'{"schema_version":1,"tampered":true}'
            mastery_path.write_bytes(corrupt)

            workspace = Version2BookTrainingWorkspace(
                reader,
                progress_root=root,
                language=UILanguage.EN,
            )
            bridge = workspace.start_current()
            initial = bridge.projection.snapshot()
            self.assertFalse(initial["mastery"]["available"])

            completed = workspace.dispatch("training.submit", {"answer": "e4"})
            self.assertTrue(completed.payload["snapshot"]["progress"]["completed"])
            self.assertFalse(completed.payload["snapshot"]["mastery"]["available"])
            self.assertEqual(corrupt, mastery_path.read_bytes())
            self.assertEqual(1, len(tuple(root.glob("*.json"))))


if __name__ == "__main__":
    unittest.main()
