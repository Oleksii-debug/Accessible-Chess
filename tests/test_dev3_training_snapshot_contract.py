import unittest

from acs.training import (
    TRAINING_SNAPSHOT_SCHEMA_VERSION,
    ExerciseDefinition,
    ExerciseSession,
    ExerciseStatus,
    ExerciseStep,
)


class TrainingSnapshotContractTests(unittest.TestCase):
    def make_definition(self, **overrides):
        values = {
            "exercise_id": "snapshot-001",
            "start_fen": "7k/6pp/8/8/8/8/6PP/7K w - - 0 1",
            "steps": (
                ExerciseStep(frozenset({"Qh6"}), hint="Force the king"),
                ExerciseStep(frozenset({"Qg7#"})),
            ),
            "title": "Original title",
            "tags": ("mate",),
            "source_id": "source-a",
            "metadata": {"author": "trainer"},
        }
        values.update(overrides)
        return ExerciseDefinition(**values)

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
                "definition_digest": "089f1d101706351d3f62643a34fe38f15192d2e15c2c3e005ea20e425eab809e",
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
        for invalid in (True, "2", 2.0):
            with self.subTest(invalid=invalid):
                candidate = dict(snapshot)
                candidate["schema_version"] = invalid
                with self.assertRaisesRegex(TypeError, "schema_version must be an integer"):
                    ExerciseSession.restore(definition, candidate)

        for unsupported in (1, TRAINING_SNAPSHOT_SCHEMA_VERSION + 1):
            with self.subTest(unsupported=unsupported):
                candidate = dict(snapshot)
                candidate["schema_version"] = unsupported
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

    def test_restore_does_not_coerce_identity_status_or_digest(self):
        definition, snapshot = self.progressed_snapshot()

        candidate = dict(snapshot)
        candidate["exercise_id"] = 123
        with self.assertRaisesRegex(TypeError, "exercise_id must be a string"):
            ExerciseSession.restore(definition, candidate)

        candidate = dict(snapshot)
        candidate["status"] = 1
        with self.assertRaisesRegex(TypeError, "status must be a string"):
            ExerciseSession.restore(definition, candidate)

        candidate = dict(snapshot)
        candidate["definition_digest"] = 123
        with self.assertRaisesRegex(TypeError, "definition_digest must be a string"):
            ExerciseSession.restore(definition, candidate)

    def test_restore_rejects_malformed_definition_digest(self):
        definition, snapshot = self.progressed_snapshot()
        for invalid in (
            "",
            "0" * 63,
            "0" * 65,
            "G" * 64,
            snapshot["definition_digest"].upper(),
        ):
            with self.subTest(invalid=invalid):
                candidate = dict(snapshot)
                candidate["definition_digest"] = invalid
                with self.assertRaisesRegex(ValueError, "invalid exercise snapshot definition_digest"):
                    ExerciseSession.restore(definition, candidate)

    def test_restore_rejects_changed_start_position_with_same_exercise_id(self):
        _, snapshot = self.progressed_snapshot()
        changed = self.make_definition(start_fen="7k/6pp/8/8/8/8/6PP/7K b - - 0 1")
        with self.assertRaisesRegex(ValueError, "different exercise revision"):
            ExerciseSession.restore(changed, snapshot)

    def test_restore_rejects_changed_solution_sequence_with_same_exercise_id(self):
        _, snapshot = self.progressed_snapshot()
        changed = self.make_definition(
            steps=(
                ExerciseStep(frozenset({"Qh6"}), hint="Force the king"),
                ExerciseStep(frozenset({"Qf8#"})),
            )
        )
        with self.assertRaisesRegex(ValueError, "different exercise revision"):
            ExerciseSession.restore(changed, snapshot)

    def test_restore_rejects_reordered_solution_steps_with_same_exercise_id(self):
        _, snapshot = self.progressed_snapshot()
        changed = self.make_definition(
            steps=(
                ExerciseStep(frozenset({"Qg7#"})),
                ExerciseStep(frozenset({"Qh6"}), hint="Force the king"),
            )
        )
        with self.assertRaisesRegex(ValueError, "different exercise revision"):
            ExerciseSession.restore(changed, snapshot)

    def test_presentation_only_definition_edits_preserve_progress_compatibility(self):
        _, snapshot = self.progressed_snapshot()
        changed = self.make_definition(
            title="Retitled",
            tags=("calculation", "mate"),
            source_id="source-b",
            metadata={"author": "editor", "difficulty": "hard"},
            steps=(
                ExerciseStep(frozenset({"Qh6"}), hint="New hint", explanation="New explanation"),
                ExerciseStep(frozenset({"Qg7#"}), hint="Finish", explanation="Mate"),
            ),
        )
        restored = ExerciseSession.restore(changed, snapshot)
        self.assertEqual(restored.step_index, 1)
        self.assertEqual(restored.attempts, 2)
        self.assertEqual(restored.mistakes, 1)
        self.assertEqual(restored.hints_used, 1)
        self.assertEqual(restored.status, ExerciseStatus.IN_PROGRESS)
        self.assertEqual(restored.snapshot(), snapshot)

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