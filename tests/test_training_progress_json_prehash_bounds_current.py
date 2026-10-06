from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from acs.chesscore import Board
from acs.training import ExerciseDefinition, ExerciseSession, ExerciseStep
from acs.training_progress_store import (
    MAX_TRAINING_PROGRESS_BYTES,
    MAX_TRAINING_PROGRESS_JSON_KEY_CHARS,
    MAX_TRAINING_PROGRESS_JSON_OBJECT_MEMBERS,
    TrainingProgressResourceError,
    TrainingProgressStore,
)


class TrainingProgressJsonPrehashBoundsTests(unittest.TestCase):
    @staticmethod
    def _definition() -> ExerciseDefinition:
        return ExerciseDefinition(
            "current-training-progress-json-prehash",
            Board.START,
            (ExerciseStep(frozenset({"e4"})),),
        )

    def test_oversized_json_object_key_fails_before_duplicate_hashing(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "training-progress.json"
            hostile_key = "k" * (MAX_TRAINING_PROGRESS_JSON_KEY_CHARS + 1)
            raw = ("{" + json.dumps(hostile_key) + ":0}").encode("utf-8")
            self.assertLess(len(raw), MAX_TRAINING_PROGRESS_BYTES)
            path.write_bytes(raw)

            with self.assertRaisesRegex(
                TrainingProgressResourceError,
                "object key exceeds the resource limit",
            ):
                TrainingProgressStore(path).load(self._definition())

            self.assertEqual(raw, path.read_bytes())

    def test_json_object_member_count_fails_before_duplicate_hashing(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "training-progress.json"
            members = ",".join(
                f'"k{index}":0'
                for index in range(MAX_TRAINING_PROGRESS_JSON_OBJECT_MEMBERS + 1)
            )
            raw = ("{" + members + "}").encode("utf-8")
            self.assertLess(len(raw), MAX_TRAINING_PROGRESS_BYTES)
            path.write_bytes(raw)

            with self.assertRaisesRegex(
                TrainingProgressResourceError,
                "object contains too many members",
            ):
                TrainingProgressStore(path).load(self._definition())

            self.assertEqual(raw, path.read_bytes())

    def test_decoder_recursion_failure_is_fail_closed_and_preserves_bytes(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "training-progress.json"
            raw = b'{"schema_version":1,"snapshot":{}}'
            path.write_bytes(raw)

            with mock.patch(
                "acs.training_progress_store.json.loads",
                side_effect=RecursionError("maximum recursion depth exceeded"),
            ):
                with self.assertRaisesRegex(
                    TrainingProgressResourceError,
                    "nesting depth exceeds the resource limit",
                ):
                    TrainingProgressStore(path).load(self._definition())

            self.assertEqual(raw, path.read_bytes())

    def test_canonical_training_progress_round_trip_remains_valid(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "training-progress.json"
            definition = self._definition()
            session = ExerciseSession(definition)
            session.submit("e4")
            store = TrainingProgressStore(path)

            revision = store.save(session, expected_revision=None)
            loaded = store.load(definition)

            self.assertIsNotNone(loaded)
            assert loaded is not None
            self.assertEqual(revision, loaded.revision)
            self.assertEqual(("e4",), loaded.session.accepted_path)
            self.assertTrue(loaded.session.completed)


if __name__ == "__main__":
    unittest.main()
