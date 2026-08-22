from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from acs.training import ExerciseDefinition, ExerciseSession, ExerciseStep
from acs.training_progress_store import (
    TRAINING_PROGRESS_STORE_SCHEMA_VERSION,
    TrainingProgressBusyError,
    TrainingProgressConflictError,
    TrainingProgressStore,
)


def _definition(*, second_move: str = "Nf3") -> ExerciseDefinition:
    return ExerciseDefinition(
        exercise_id="fork-001",
        start_fen="8/8/8/8/8/8/8/8 w - - 0 1",
        steps=(
            ExerciseStep(frozenset({"e4"}), hint="first"),
            ExerciseStep(frozenset({second_move}), hint="second"),
        ),
    )


class Dev3TrainingProgressStoreTests(unittest.TestCase):
    def test_create_load_and_revision_bound_update_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "progress.json"
            store = TrainingProgressStore(path)
            definition = _definition()
            session = ExerciseSession(definition)
            session.submit("e4")

            revision1 = store.save(session, expected_revision=None)
            loaded = store.load(definition)
            self.assertIsNotNone(loaded)
            assert loaded is not None
            self.assertEqual(loaded.revision, revision1)
            self.assertEqual(loaded.session.step_index, 1)
            self.assertEqual(loaded.session.attempts, 1)

            loaded.session.request_hint()
            revision2 = store.save(loaded.session, expected_revision=loaded.revision)
            self.assertNotEqual(revision2, revision1)
            reloaded = store.load(definition)
            assert reloaded is not None
            self.assertEqual(reloaded.revision, revision2)
            self.assertEqual(reloaded.session.hints_used, 1)

    def test_create_only_and_stale_writer_fail_without_overwriting_newer_progress(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "progress.json"
            store = TrainingProgressStore(path)
            definition = _definition()

            original = ExerciseSession(definition)
            revision1 = store.save(original, expected_revision=None)
            first_reader = store.load(definition)
            stale_reader = store.load(definition)
            assert first_reader is not None and stale_reader is not None

            with self.assertRaises(TrainingProgressConflictError):
                store.save(ExerciseSession(definition), expected_revision=None)
            self.assertEqual(store.load(definition).revision, revision1)  # type: ignore[union-attr]

            first_reader.session.submit("e4")
            revision2 = store.save(
                first_reader.session,
                expected_revision=first_reader.revision,
            )
            stale_reader.session.request_hint()
            with self.assertRaises(TrainingProgressConflictError):
                store.save(
                    stale_reader.session,
                    expected_revision=stale_reader.revision,
                )

            final = store.load(definition)
            assert final is not None
            self.assertEqual(final.revision, revision2)
            self.assertEqual(final.session.step_index, 1)
            self.assertEqual(final.session.hints_used, 0)

    def test_definition_revision_and_corrupt_envelope_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "progress.json"
            store = TrainingProgressStore(path)
            store.save(ExerciseSession(_definition()), expected_revision=None)

            with self.assertRaisesRegex(ValueError, "different exercise revision"):
                store.load(_definition(second_move="Nc3"))

            path.write_text(
                json.dumps(
                    {
                        "schema_version": TRAINING_PROGRESS_STORE_SCHEMA_VERSION + 1,
                        "snapshot": {},
                    }
                ),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "unsupported training progress schema_version"):
                store.load(_definition())

            path.write_bytes(b"{not-json")
            with self.assertRaisesRegex(ValueError, "invalid training progress file"):
                store.load(_definition())

    def test_expected_revision_is_strict_and_busy_lock_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "progress.json"
            store = TrainingProgressStore(path)
            session = ExerciseSession(_definition())

            for bad in (True, 7, "A" * 64, "abc"):
                with self.subTest(value=bad):
                    with self.assertRaises((TypeError, ValueError)):
                        store.save(session, expected_revision=bad)  # type: ignore[arg-type]

            lock_path = path.with_name(f".{path.name}.lock")
            lock_path.mkdir()
            try:
                with self.assertRaises(TrainingProgressBusyError):
                    store.save(session, expected_revision=None)
                self.assertFalse(path.exists())
            finally:
                lock_path.rmdir()

    def test_publication_failure_preserves_previous_progress_and_cleans_temp(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "progress.json"
            store = TrainingProgressStore(path)
            definition = _definition()
            revision = store.save(ExerciseSession(definition), expected_revision=None)
            before = path.read_bytes()

            loaded = store.load(definition)
            assert loaded is not None
            loaded.session.submit("e4")
            with mock.patch(
                "acs.training_progress_store.os.replace",
                side_effect=OSError("synthetic publish failure"),
            ):
                with self.assertRaisesRegex(OSError, "synthetic publish failure"):
                    store.save(loaded.session, expected_revision=revision)

            self.assertEqual(path.read_bytes(), before)
            self.assertEqual(store.load(definition).revision, revision)  # type: ignore[union-attr]
            self.assertFalse(path.with_name(f".{path.name}.lock").exists())
            self.assertEqual(list(root.glob(f".{path.name}.*.tmp")), [])


if __name__ == "__main__":
    unittest.main()
