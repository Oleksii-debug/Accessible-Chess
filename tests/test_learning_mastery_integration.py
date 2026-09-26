from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from acs.learning_mastery import (
    LearningMode,
    MasteryError,
    MasteryState,
    record_training_outcome,
)
from acs.learning_mastery_store import (
    MasteryStore,
    MasteryStoreBusyError,
    MasteryStoreConflictError,
)
from acs.learning_mastery_training import outcome_from_completed_training
from acs.training import ExerciseDefinition, ExerciseSession, ExerciseStep


class MasteryTrainingAdapterTests(unittest.TestCase):
    def _session(self, *, exercise_id: str = "lesson with authored identity") -> ExerciseSession:
        definition = ExerciseDefinition(
            exercise_id=exercise_id,
            start_fen="8/8/8/8/8/8/P6k/K7 w - - 0 1",
            steps=(ExerciseStep(frozenset({"a3"}), hint="Move the pawn."),),
            title="One move",
        )
        return ExerciseSession(definition)

    def test_incomplete_session_cannot_be_recorded(self) -> None:
        with self.assertRaises(MasteryError):
            outcome_from_completed_training(
                self._session(),
                sequence=1,
                event_id="completion.1",
                practice_date="2026-09-26",
            )

    def test_completed_session_projects_only_canonical_summary_metrics(self) -> None:
        session = self._session()
        session.request_hint()
        session.submit("a4")
        result = session.submit("a3")
        self.assertTrue(result.completed)

        outcome = outcome_from_completed_training(
            session,
            sequence=1,
            event_id="completion.1",
            practice_date="2026-09-26",
            duration_seconds=73,
        )
        self.assertTrue(outcome.completed)
        self.assertEqual(outcome.correct_steps, 1)
        self.assertEqual(outcome.total_steps, 1)
        self.assertEqual(outcome.mistakes, 1)
        self.assertEqual(outcome.hints_used, 1)
        self.assertEqual(outcome.duration_seconds, 73)
        self.assertTrue(outcome.activity_id.startswith("training:"))
        self.assertNotIn(session.definition.exercise_id, outcome.activity_id)

    def test_same_authored_exercise_id_has_stable_bounded_activity_identity(self) -> None:
        first = self._session(exercise_id="unicode ♟ lesson identity")
        second = self._session(exercise_id="unicode ♟ lesson identity")
        first.submit("a3")
        second.submit("a3")
        left = outcome_from_completed_training(
            first,
            sequence=1,
            event_id="completion.a",
            practice_date="2026-09-26",
        )
        right = outcome_from_completed_training(
            second,
            sequence=2,
            event_id="completion.b",
            practice_date="2026-09-27",
        )
        self.assertEqual(left.activity_id, right.activity_id)
        self.assertLessEqual(len(left.activity_id), 128)

    def test_reusing_event_id_for_new_sequence_fails_closed(self) -> None:
        session = self._session()
        session.submit("a3")
        first = outcome_from_completed_training(
            session,
            sequence=1,
            event_id="completion.same",
            practice_date="2026-09-26",
        )
        state = record_training_outcome(MasteryState.empty(), first).state
        second = outcome_from_completed_training(
            session,
            sequence=2,
            event_id="completion.same",
            practice_date="2026-09-27",
        )
        with self.assertRaises(MasteryError):
            record_training_outcome(state, second)


class MasteryStoreTests(unittest.TestCase):
    def test_missing_store_loads_as_none(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = MasteryStore(Path(tmp) / "mastery.json")
            self.assertIsNone(store.load())

    def test_create_load_and_update_roundtrip_with_exact_cas(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = MasteryStore(Path(tmp) / "nested" / "mastery.json")
            initial = MasteryState.empty(LearningMode.CHILD)
            revision1 = store.save(initial, expected_revision=None)
            loaded1 = store.load()
            self.assertIsNotNone(loaded1)
            assert loaded1 is not None
            self.assertEqual(loaded1.state, initial)
            self.assertEqual(loaded1.revision, revision1)

            changed = MasteryState.empty(LearningMode.ADULT)
            revision2 = store.save(changed, expected_revision=revision1)
            self.assertNotEqual(revision2, revision1)
            loaded2 = store.load()
            assert loaded2 is not None
            self.assertEqual(loaded2.state, changed)
            self.assertEqual(loaded2.revision, revision2)

    def test_create_only_and_stale_update_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = MasteryStore(Path(tmp) / "mastery.json")
            revision = store.save(MasteryState.empty(), expected_revision=None)
            with self.assertRaises(MasteryStoreConflictError):
                store.save(MasteryState.empty(), expected_revision=None)
            with self.assertRaises(MasteryStoreConflictError):
                store.save(
                    MasteryState.empty(LearningMode.CHILD),
                    expected_revision="0" * 64,
                )
            loaded = store.load()
            assert loaded is not None
            self.assertEqual(loaded.revision, revision)
            self.assertEqual(loaded.state.mode, LearningMode.ADULT)

    def test_corrupt_or_tampered_file_never_recovers_as_valid_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "mastery.json"
            store = MasteryStore(path)
            store.save(MasteryState.empty(), expected_revision=None)
            text = path.read_text(encoding="utf-8")
            path.write_text(text.replace('"total_points":0', '"total_points":1'), encoding="utf-8")
            with self.assertRaises(MasteryError):
                store.load()

    def test_symlink_mastery_path_is_rejected_without_touching_target(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            target = root / "target.json"
            target.write_text(MasteryState.empty().to_json(), encoding="utf-8")
            link = root / "mastery.json"
            try:
                link.symlink_to(target)
            except OSError as exc:
                self.skipTest(f"symlink creation unavailable: {type(exc).__name__}")
            original = target.read_bytes()
            store = MasteryStore(link)
            with self.assertRaises(ValueError):
                store.load()
            with self.assertRaises((ValueError, MasteryStoreConflictError)):
                store.save(MasteryState.empty(), expected_revision=None)
            self.assertEqual(target.read_bytes(), original)

    def test_peer_advisory_lock_blocks_second_writer(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = MasteryStore(Path(tmp) / "mastery.json")
            with store._exclusive_access():
                with self.assertRaises(MasteryStoreBusyError):
                    store.save(MasteryState.empty(), expected_revision=None)

    def test_invalid_expected_revision_is_rejected_before_write(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "mastery.json"
            store = MasteryStore(path)
            with self.assertRaises(ValueError):
                store.save(MasteryState.empty(), expected_revision="not-a-revision")
            self.assertFalse(path.exists())


if __name__ == "__main__":
    unittest.main()
