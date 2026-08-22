import unittest

from acs.training import (
    TRAINING_SNAPSHOT_SCHEMA_VERSION,
    ExerciseDefinition,
    ExerciseSession,
    ExerciseStatus,
    ExerciseStep,
)


class TrainingSnapshotContractTests(unittest.TestCase):
    def make_definition(self):
        return ExerciseDefinition(
            "snapshot-001",
            "7k/6pp/8/8/8/8/6PP/7K w - - 0 1",
            (
                ExerciseStep(frozenset({"Qh6"}), hint="Force the king"),
                ExerciseStep(frozenset({"Qg7#"})),
            ),
        )

    def progressed_snapshot(self):
        definition = self.make_definition()
        session = ExerciseSession(definition)
        session.request_hint()
        session.submit("Qh5")
        session.submit("Qh6")
        return definition, session.snapshot()

    def test_snapshot_is_exact_versioned_payload(self):
        definition, snapshot = self.progressed_snapshot()
        self.assertEqual(
            snapshot,
            {
                "schema_version": TRAINING_SNAPSHOT_SCHEMA_VERSION,
                "exercise_id": definition.exercise_id,
                "step_index": 1,
                "attempts": 2,
                "mistakes": 1,
                "hints_used": 1,
                "status": ExerciseStatus.IN_PROGRESS.value,
            },
        )

    def test_restore_rejects_missing_and_unknown_fields(self):
        definition, snapshot = self.progressed_snapshot()

        missing = dict(snapshot)
        missing.pop("attempts")
        with self.assertRaisesRegex(ValueError, "missing fields: attempts"):
            ExerciseSession.restore(definition, missing)

        unknown = dict(snapshot)
        unknown["score"] = 100
        with self.assertRaisesRegex(ValueError, "unknown fields: score"):
            ExerciseSession.restore(definition, unknown)

    def test_restore_requires_exact_schema_version_type_and_value(self):
        definition, snapshot = self.progressed_snapshot()
        for invalid in (True, "1", 1.0):
            with self.subTest(invalid=invalid):
                candidate = dict(snapshot)
                candidate["schema_version"] = invalid
                with self.assertRaisesRegex(TypeError, "schema_version must be an integer"):
                    ExerciseSession.restore(definition, candidate)

        candidate = dict(snapshot)
        candidate["schema_version"] = TRAINING_SNAPSHOT_SCHEMA_VERSION + 1
        with self.assertRaisesRegex(ValueError, "unsupported exercise snapshot schema_version"):
            ExerciseSession.restore(definition, candidate)

    def test_restore_does_not_coerce_counter_scalars(self):
        definition, snapshot = self.progressed_snapshot()
        for field in ("step_index", "attempts", "mistakes", "hints_used"):
            for invalid in (True, "1", 1.0):
                with self.subTest(field=field, invalid=invalid):
                    candidate = dict(snapshot)
                    candidate[field] = invalid
                    with self.assertRaisesRegex(TypeError, rf"{field} must be an integer"):
                        ExerciseSession.restore(definition, candidate)

    def test_restore_does_not_coerce_identity_or_status(self):
        definition, snapshot = self.progressed_snapshot()

        candidate = dict(snapshot)
        candidate["exercise_id"] = 123
        with self.assertRaisesRegex(TypeError, "exercise_id must be a string"):
            ExerciseSession.restore(definition, candidate)

        candidate = dict(snapshot)
        candidate["status"] = 1
        with self.assertRaisesRegex(TypeError, "status must be a string"):
            ExerciseSession.restore(definition, candidate)

    def test_restore_rejects_invalid_counter_relationships_and_completion(self):
        definition, snapshot = self.progressed_snapshot()

        candidate = dict(snapshot)
        candidate["mistakes"] = candidate["attempts"] + 1
        with self.assertRaisesRegex(ValueError, "invalid exercise counters"):
            ExerciseSession.restore(definition, candidate)

        candidate = dict(snapshot)
        candidate["status"] = ExerciseStatus.COMPLETED.value
        with self.assertRaisesRegex(ValueError, "unfinished steps"):
            ExerciseSession.restore(definition, candidate)

    def test_exact_snapshot_roundtrip_preserves_progress(self):
        definition, snapshot = self.progressed_snapshot()
        restored = ExerciseSession.restore(definition, snapshot)
        self.assertEqual(restored.snapshot(), snapshot)


if __name__ == "__main__":
    unittest.main()
