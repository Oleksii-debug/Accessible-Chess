from __future__ import annotations

from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from acs.bookdocument import BookDocument, Exercise
from acs.bookreader import BookReader
from acs.full_product_ui_shell import UILanguage
from acs.training_progress_store import TrainingProgressConflictError
from acs.version2_profile import VERSION2_ROUTE_IDS, build_version2_action_registry
import acs.version2_training_workspace as training_workspace_module
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

    def test_presentation_only_commands_do_not_write_durable_progress(self) -> None:
        document = make_book()
        reader = BookReader(document)
        with tempfile.TemporaryDirectory(prefix="accessible-chess-v2-training-presentation-") as raw:
            root = Path(raw)
            workspace = Version2BookTrainingWorkspace(
                reader,
                progress_root=root,
                language=UILanguage.EN,
            )
            workspace.start_current()
            before = workspace.session.snapshot()
            before_revision = workspace._revision
            store = workspace._store
            self.assertIsNotNone(store)
            assert store is not None

            with patch.object(
                store,
                "save",
                side_effect=AssertionError(
                    "presentation-only Training command must not write durable progress"
                ),
            ) as save:
                revealed = workspace.dispatch("training.reveal", {})
                retried = workspace.dispatch(" training.retry ", {})
                localized = workspace.dispatch(
                    "training.language",
                    {"language": "uk"},
                )

            save.assert_not_called()
            self.assertEqual("render", revealed.kind)
            self.assertTrue(revealed.payload["solution"])
            self.assertEqual("render", retried.kind)
            self.assertEqual("render", localized.kind)
            self.assertEqual(before, workspace.session.snapshot())
            self.assertEqual(before_revision, workspace._revision)
            self.assertEqual(UILanguage.UA, workspace.language)
            self.assertEqual((), tuple(root.glob("*.json")))

    def test_invalid_semantic_exercise_is_not_advertised_and_next_valid_is_used(self) -> None:
        document = BookDocument(
            title="V2 Training semantic skip",
            language="en",
            blocks=[
                Exercise(
                    fen=START_FEN,
                    prompt="First exercise",
                    answer_text="e4",
                    block_id="valid-one",
                ),
                Exercise(
                    fen=START_FEN,
                    prompt="Malformed exercise",
                    answer_text="e5",
                    block_id="invalid-two",
                ),
                Exercise(
                    fen=START_FEN,
                    prompt="Third exercise",
                    answer_text="d4",
                    block_id="valid-three",
                ),
            ],
        )
        reader = BookReader(document)
        with tempfile.TemporaryDirectory(prefix="accessible-chess-v2-training-skip-") as raw:
            workspace = Version2BookTrainingWorkspace(
                reader,
                progress_root=Path(raw),
                language=UILanguage.EN,
            )
            workspace.start_current()
            completed = workspace.dispatch("training.submit", {"answer": "e4"})
            actions = {item["command"]: item for item in completed.payload["snapshot"]["actions"]}
            self.assertTrue(actions["training.continue"]["enabled"])

            continued = workspace.dispatch("training.continue", {})
            self.assertEqual(2, reader.location().index)
            self.assertEqual("Third exercise", continued.payload["snapshot"]["title"])

            finished = workspace.dispatch("training.submit", {"answer": "d4"})
            finished_actions = {
                item["command"]: item for item in finished.payload["snapshot"]["actions"]
            }
            self.assertFalse(finished_actions["training.continue"]["enabled"])

    def test_next_exercise_scan_never_traverses_live_blocks_after_indexed_snapshot(self) -> None:
        document = make_book()
        reader = BookReader(document)
        with tempfile.TemporaryDirectory(prefix="accessible-chess-v2-training-indexed-") as raw:
            workspace = Version2BookTrainingWorkspace(
                reader,
                progress_root=Path(raw),
                language=UILanguage.EN,
            )
            workspace.start_current()
            real_resolve = training_workspace_module.resolve_book_training_origin

            class HostileBlocks(list):
                armed = False
                touched = False

                def __iter__(self):
                    if type(self).armed:
                        type(self).touched = True
                        raise AssertionError("live Training scan must not iterate authoring blocks")
                    return super().__iter__()

            def mutate_live_then_resolve(indexed_document, origin):
                self.assertIsNot(indexed_document, document)
                hostile = HostileBlocks(document.blocks)
                document.blocks = hostile
                HostileBlocks.armed = True
                return real_resolve(indexed_document, origin)

            with patch.object(
                training_workspace_module,
                "resolve_book_training_origin",
                side_effect=mutate_live_then_resolve,
            ):
                with self.assertRaisesRegex(RuntimeError, "changed after BookReader creation"):
                    workspace._next_exercise_material()

            self.assertFalse(HostileBlocks.touched)
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
