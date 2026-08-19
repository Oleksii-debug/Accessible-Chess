import unittest

from acs.training import (
    TRAINING_SNAPSHOT_SCHEMA_VERSION,
    ExerciseDefinition,
    ExerciseSession,
    ExerciseStatus,
    ExerciseStep,
    TrainingError,
    TrainingErrorCode,
)


class ExerciseSessionTests(unittest.TestCase):
    def make_definition(self):
        return ExerciseDefinition(
            "mate-001",
            "7k/6pp/8/8/8/8/6PP/7K w - - 0 1",
            (
                ExerciseStep(frozenset({"Qh6"}), hint="Look for a forcing queen move", explanation="Create the mating net."),
                ExerciseStep(frozenset({"Qg7#", "Qg7++"}), hint="Finish on g7", explanation="Checkmate."),
            ),
            title="Two-step tactic",
            tags=("Mate", "Calculation"),
            source_id="local-pack-1",
        )

    def test_definition_normalizes_tags_and_preserves_source(self):
        definition = self.make_definition()
        self.assertEqual(definition.tags, ("mate", "calculation"))
        self.assertEqual(definition.source_id, "local-pack-1")

    def test_correct_move_advances_exactly_one_step(self):
        session = ExerciseSession(self.make_definition())
        result = session.submit("  Qh6  ")
        self.assertTrue(result.accepted)
        self.assertEqual(result.step_index, 1)
        self.assertEqual(result.status, ExerciseStatus.IN_PROGRESS)
        self.assertEqual(result.explanation, "Create the mating net.")

    def test_incorrect_move_does_not_advance(self):
        session = ExerciseSession(self.make_definition())
        result = session.submit("Qh5")
        self.assertFalse(result.accepted)
        self.assertEqual(result.step_index, 0)
        self.assertEqual(session.step_index, 0)
        self.assertEqual(session.attempts, 1)
        self.assertEqual(session.mistakes, 1)

    def test_multiple_accepted_moves_can_complete_step(self):
        session = ExerciseSession(self.make_definition())
        session.submit("Qh6")
        result = session.submit("Qg7++")
        self.assertTrue(result.accepted)
        self.assertTrue(result.completed)
        self.assertEqual(result.status, ExerciseStatus.COMPLETED)

    def test_completed_session_rejects_extra_submission(self):
        session = ExerciseSession(self.make_definition())
        session.submit("Qh6")
        session.submit("Qg7#")
        with self.assertRaisesRegex(ValueError, "already completed"):
            session.submit("Kh2")

    def test_hint_does_not_advance_or_count_as_attempt(self):
        session = ExerciseSession(self.make_definition())
        hint = session.request_hint()
        self.assertTrue(hint.available)
        self.assertEqual(hint.hints_used, 1)
        self.assertEqual(session.step_index, 0)
        self.assertEqual(session.attempts, 0)

    def test_reset_restores_clean_session_state(self):
        session = ExerciseSession(self.make_definition())
        session.request_hint()
        session.submit("Qh5")
        session.submit("Qh6")
        session.reset()
        self.assertEqual(session.status, ExerciseStatus.READY)
        self.assertEqual(session.step_index, 0)
        self.assertEqual(session.attempts, 0)
        self.assertEqual(session.mistakes, 0)
        self.assertEqual(session.hints_used, 0)

    def test_snapshot_roundtrip_restores_progress(self):
        definition = self.make_definition()
        session = ExerciseSession(definition)
        session.request_hint()
        session.submit("Qh5")
        session.submit("Qh6")
        restored = ExerciseSession.restore(definition, session.snapshot())
        self.assertEqual(restored.step_index, 1)
        self.assertEqual(restored.attempts, 2)
        self.assertEqual(restored.mistakes, 1)
        self.assertEqual(restored.hints_used, 1)
        self.assertEqual(restored.status, ExerciseStatus.IN_PROGRESS)

    def test_snapshot_from_other_exercise_is_rejected(self):
        definition = self.make_definition()
        snapshot = ExerciseSession(definition).snapshot()
        other = ExerciseDefinition("other", definition.start_fen, definition.steps)
        with self.assertRaisesRegex(ValueError, "different exercise"):
            ExerciseSession.restore(other, snapshot)

    def test_invalid_snapshot_cannot_claim_false_completion(self):
        definition = self.make_definition()
        snapshot = ExerciseSession(definition).snapshot()
        snapshot["status"] = "completed"
        with self.assertRaisesRegex(ValueError, "unfinished"):
            ExerciseSession.restore(definition, snapshot)

    def test_empty_move_and_empty_step_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "at least one"):
            ExerciseStep(frozenset())
        session = ExerciseSession(self.make_definition())
        with self.assertRaisesRegex(ValueError, "move must not be empty"):
            session.submit("   ")

    def test_definition_rejects_scalar_and_container_coercion(self):
        valid = self.make_definition()
        cases = (
            lambda: ExerciseDefinition(True, valid.start_fen, valid.steps),
            lambda: ExerciseDefinition(valid.exercise_id, True, valid.steps),
            lambda: ExerciseDefinition(
                valid.exercise_id,
                valid.start_fen,
                list(valid.steps),
            ),
            lambda: ExerciseDefinition(
                valid.exercise_id,
                valid.start_fen,
                (object(),),
            ),
            lambda: ExerciseDefinition(
                valid.exercise_id,
                valid.start_fen,
                valid.steps,
                title=True,
            ),
            lambda: ExerciseDefinition(
                valid.exercise_id,
                valid.start_fen,
                valid.steps,
                tags="mate",
            ),
            lambda: ExerciseDefinition(
                valid.exercise_id,
                valid.start_fen,
                valid.steps,
                tags=(True,),
            ),
            lambda: ExerciseDefinition(
                valid.exercise_id,
                valid.start_fen,
                valid.steps,
                source_id=7,
            ),
            lambda: ExerciseDefinition(
                valid.exercise_id,
                valid.start_fen,
                valid.steps,
                metadata=[("pack", "one")],
            ),
            lambda: ExerciseDefinition(
                valid.exercise_id,
                valid.start_fen,
                valid.steps,
                metadata={"pack": True},
            ),
            lambda: ExerciseDefinition(
                valid.exercise_id,
                valid.start_fen,
                valid.steps,
                metadata={" pack ": "one", "pack": "two"},
            ),
        )
        for construct in cases:
            with self.subTest(construct=construct):
                with self.assertRaises(TrainingError) as caught:
                    construct()
                self.assertEqual(
                    caught.exception.code,
                    TrainingErrorCode.INVALID_DEFINITION,
                )

        with self.assertRaises(TrainingError) as caught:
            ExerciseSession(object())
        self.assertEqual(caught.exception.code, TrainingErrorCode.INVALID_DEFINITION)

    def test_definition_metadata_is_detached_and_read_only(self):
        metadata = {"pack": "one"}
        valid = self.make_definition()
        definition = ExerciseDefinition(
            valid.exercise_id,
            valid.start_fen,
            valid.steps,
            metadata=metadata,
        )

        metadata["pack"] = "external"
        self.assertEqual(definition.metadata["pack"], "one")
        with self.assertRaises(TypeError):
            definition.metadata["pack"] = "mutated"

        session = ExerciseSession(definition)
        with self.assertRaises(AttributeError):
            session.definition = self.make_definition()

    def test_step_requires_exact_move_container_and_text_metadata(self):
        cases = (
            lambda: ExerciseStep({"Qh6"}),
            lambda: ExerciseStep(["Qh6"]),
            lambda: ExerciseStep("Qh6"),
            lambda: ExerciseStep(frozenset({True})),
            lambda: ExerciseStep(frozenset({"Qh6"}), hint=""),
            lambda: ExerciseStep(frozenset({"Qh6"}), explanation=7),
        )
        for construct in cases:
            with self.subTest(construct=construct):
                with self.assertRaises(TrainingError) as caught:
                    construct()
                self.assertEqual(
                    caught.exception.code,
                    TrainingErrorCode.INVALID_DEFINITION,
                )

    def test_invalid_submission_is_atomic_and_rejects_scalar_coercion(self):
        session = ExerciseSession(self.make_definition())
        before = session.snapshot()

        for invalid in (True, False, 7, 1.0, None, b"Qh6", "   "):
            with self.subTest(move=invalid):
                with self.assertRaises(TrainingError) as caught:
                    session.submit(invalid)
                self.assertEqual(
                    caught.exception.code,
                    TrainingErrorCode.INVALID_COMMAND,
                )
                self.assertEqual(session.snapshot(), before)

    def test_snapshot_schema_is_explicit_with_bounded_legacy_read(self):
        definition = self.make_definition()
        session = ExerciseSession(definition)
        session.submit("Qh5")
        snapshot = session.snapshot()
        self.assertEqual(
            snapshot["schema_version"],
            TRAINING_SNAPSHOT_SCHEMA_VERSION,
        )

        legacy = dict(snapshot)
        legacy.pop("schema_version")
        restored = ExerciseSession.restore(definition, legacy)
        self.assertEqual(restored.snapshot(), snapshot)

        for invalid_version in (True, False, "1", 0, 2, -1):
            invalid = dict(snapshot, schema_version=invalid_version)
            with self.subTest(version=invalid_version):
                with self.assertRaises(TrainingError) as caught:
                    ExerciseSession.restore(definition, invalid)
                self.assertEqual(
                    caught.exception.code,
                    TrainingErrorCode.UNSUPPORTED_SCHEMA,
                )

    def test_snapshot_rejects_unknown_missing_and_non_mapping_payloads(self):
        definition = self.make_definition()
        snapshot = ExerciseSession(definition).snapshot()
        cases = (
            [],
            {**snapshot, "unknown": "lost"},
            {key: value for key, value in snapshot.items() if key != "attempts"},
        )
        for invalid in cases:
            with self.subTest(snapshot=invalid):
                with self.assertRaises(TrainingError) as caught:
                    ExerciseSession.restore(definition, invalid)
                self.assertEqual(
                    caught.exception.code,
                    TrainingErrorCode.INVALID_SNAPSHOT,
                )

    def test_snapshot_counters_require_exact_integer_scalars(self):
        definition = self.make_definition()
        snapshot = ExerciseSession(definition).snapshot()
        for field in ("step_index", "attempts", "mistakes", "hints_used"):
            for invalid_value in (True, False, "0", 0.0, None):
                invalid = dict(snapshot, **{field: invalid_value})
                with self.subTest(field=field, value=invalid_value):
                    with self.assertRaises(TrainingError) as caught:
                        ExerciseSession.restore(definition, invalid)
                    self.assertEqual(
                        caught.exception.code,
                        TrainingErrorCode.INVALID_SNAPSHOT,
                    )

    def test_snapshot_rejects_impossible_counter_and_status_combinations(self):
        definition = self.make_definition()
        snapshot = ExerciseSession(definition).snapshot()
        changes = (
            {"attempts": 1, "status": "in_progress"},
            {"attempts": 1, "mistakes": 1, "status": "ready"},
            {"status": "in_progress"},
            {"step_index": 1, "attempts": 1, "status": "ready"},
            {"step_index": 1, "attempts": 1, "status": "completed"},
            {"step_index": 2, "attempts": 2, "status": "in_progress"},
            {"mistakes": -1},
        )
        for change in changes:
            invalid = dict(snapshot, **change)
            with self.subTest(change=change):
                with self.assertRaises(TrainingError) as caught:
                    ExerciseSession.restore(definition, invalid)
                self.assertEqual(
                    caught.exception.code,
                    TrainingErrorCode.INVALID_STATE,
                )

    def test_snapshot_exercise_identity_and_status_are_exact(self):
        definition = self.make_definition()
        snapshot = ExerciseSession(definition).snapshot()

        for invalid_id in (True, None, 7, ""):
            with self.subTest(exercise_id=invalid_id):
                with self.assertRaises(TrainingError) as caught:
                    ExerciseSession.restore(
                        definition,
                        dict(snapshot, exercise_id=invalid_id),
                    )
                self.assertEqual(
                    caught.exception.code,
                    TrainingErrorCode.INVALID_SNAPSHOT,
                )

        for other_id in ("other", " mate-001 "):
            with self.subTest(exercise_id=other_id):
                with self.assertRaises(TrainingError) as caught:
                    ExerciseSession.restore(
                        definition,
                        dict(snapshot, exercise_id=other_id),
                    )
                self.assertEqual(
                    caught.exception.code,
                    TrainingErrorCode.EXERCISE_MISMATCH,
                )

        for status in (True, 1, None, "COMPLETE"):
            with self.subTest(status=status):
                with self.assertRaises(TrainingError) as caught:
                    ExerciseSession.restore(
                        definition,
                        dict(snapshot, status=status),
                    )
                self.assertEqual(
                    caught.exception.code,
                    TrainingErrorCode.INVALID_SNAPSHOT,
                )


if __name__ == "__main__":
    unittest.main()
