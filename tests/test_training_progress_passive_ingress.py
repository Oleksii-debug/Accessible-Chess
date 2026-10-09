from __future__ import annotations

from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from acs.chesscore import Board
from acs.training import ExerciseDefinition, ExerciseSession, ExerciseStep
from acs.training_progress_store import (
    TRAINING_PROGRESS_STORE_SCHEMA_VERSION,
    TrainingProgressStore,
)


class TrainingProgressPassiveIngressTests(unittest.TestCase):
    @staticmethod
    def _definition() -> ExerciseDefinition:
        return ExerciseDefinition(
            "passive-progress",
            Board.START,
            (ExerciseStep(frozenset({"e4"})),),
        )

    def test_load_rejects_definition_subclass_before_disk_read_or_field_hook(self) -> None:
        class HostileDefinition(ExerciseDefinition):
            touched = False

            def __getattribute__(self, name):
                if name in {"exercise_id", "start_fen", "steps", "metadata"}:
                    type(self).touched = True
                    raise AssertionError("definition subclass hook must not execute")
                return super().__getattribute__(name)

        hostile = HostileDefinition.__new__(HostileDefinition)

        with tempfile.TemporaryDirectory(prefix="training-passive-load-") as raw:
            store = TrainingProgressStore(Path(raw) / "progress.json")
            with patch.object(
                store,
                "_read_progress_bytes",
                side_effect=AssertionError("disk read must not occur"),
            ) as read_progress:
                with self.assertRaisesRegex(
                    TypeError,
                    "^definition must be an ExerciseDefinition$",
                ):
                    store.load(hostile)

        read_progress.assert_not_called()
        self.assertFalse(HostileDefinition.touched)

    def test_save_rejects_session_subclass_before_lock_or_snapshot_hook(self) -> None:
        class HostileSession(ExerciseSession):
            touched = False

            def snapshot(self):
                type(self).touched = True
                raise AssertionError("session subclass snapshot hook must not execute")

        hostile = HostileSession.__new__(HostileSession)

        with tempfile.TemporaryDirectory(prefix="training-passive-save-") as raw:
            store = TrainingProgressStore(Path(raw) / "progress.json")
            with patch.object(
                store,
                "_exclusive_access",
                side_effect=AssertionError("store lock must not be entered"),
            ) as exclusive:
                with self.assertRaisesRegex(
                    TypeError,
                    "^session must be an ExerciseSession$",
                ):
                    store.save(hostile, expected_revision=None)

        exclusive.assert_not_called()
        self.assertFalse(HostileSession.touched)

    def test_load_rejects_decoded_dict_subclass_before_mapping_hooks_or_restore(self) -> None:
        class HostileSnapshot(dict):
            touched = False

            def __len__(self):
                type(self).touched = True
                raise AssertionError("snapshot len hook must not execute")

            def __iter__(self):
                type(self).touched = True
                raise AssertionError("snapshot iteration hook must not execute")

            def __getitem__(self, key):
                type(self).touched = True
                raise AssertionError("snapshot item hook must not execute")

        payload = {
            "schema_version": TRAINING_PROGRESS_STORE_SCHEMA_VERSION,
            "snapshot": HostileSnapshot(),
        }

        with tempfile.TemporaryDirectory(prefix="training-passive-json-") as raw:
            store = TrainingProgressStore(Path(raw) / "progress.json")
            with (
                patch.object(store, "_read_progress_bytes", return_value=b"{}"),
                patch("acs.training_progress_store.json.loads", return_value=payload),
                patch(
                    "acs.training_progress_store.ExerciseSession.restore",
                    side_effect=AssertionError("canonical restore must not run"),
                ) as restore,
            ):
                with self.assertRaisesRegex(
                    TypeError,
                    "^training progress snapshot must be a mapping$",
                ):
                    store.load(self._definition())

        restore.assert_not_called()
        self.assertFalse(HostileSnapshot.touched)

    def test_exact_session_round_trip_remains_unchanged(self) -> None:
        definition = self._definition()
        session = ExerciseSession(definition)
        session.submit("e4")

        with tempfile.TemporaryDirectory(prefix="training-passive-roundtrip-") as raw:
            store = TrainingProgressStore(Path(raw) / "progress.json")
            revision = store.save(session, expected_revision=None)
            loaded = store.load(definition)

        self.assertIsNotNone(loaded)
        assert loaded is not None
        self.assertEqual(loaded.revision, revision)
        self.assertEqual(loaded.session.snapshot(), session.snapshot())


if __name__ == "__main__":
    unittest.main()
