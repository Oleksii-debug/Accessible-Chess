import unittest
from unittest.mock import patch

import acs.training as training_module

from acs.training import (
    TRAINING_SNAPSHOT_SCHEMA_VERSION,
    ExerciseDefinition,
    ExerciseSession,
    ExerciseStatus,
    ExerciseStep,
    SolutionRevealPolicy,
    TrainingError,
    TrainingErrorCode,
)


class ExerciseSessionTests(unittest.TestCase):
    def make_definition(self):
        return ExerciseDefinition(
            "mate-001",
            "7k/8/8/8/8/8/6R1/6K1 w - - 0 1",
            (
                ExerciseStep(frozenset({"Rh2+"}), hint="Use the open file", explanation="Force the king away."),
                ExerciseStep(frozenset({"Kg8", "Kg8!"}), hint="Leave the rook file", explanation="The line is complete."),
            ),
            title="Two-step tactic",
            tags=("Mate", "Calculation"),
            source_id="local-pack-1",
        )

    def test_definition_normalizes_tags_and_preserves_source(self):
        definition = self.make_definition()
        self.assertEqual(definition.tags, ("mate", "calculation"))
        self.assertEqual(definition.source_id, "local-pack-1")

    def test_definition_wire_roundtrip_revalidates_legal_solution(self):
        definition = self.make_definition()
        self.assertEqual(
            ExerciseDefinition.from_dict(definition.as_dict()).as_dict(),
            definition.as_dict(),
        )
        payload = definition.as_dict()
        payload["steps"][0]["accepted_moves"] = ["Rh3"]
        with self.assertRaises(TrainingError):
            ExerciseDefinition.from_dict(payload)

    def test_definition_linking_has_a_bounded_operation_envelope(self):
        with patch.object(training_module, "MAX_TRAINING_LINK_OPERATIONS", 0):
            with self.assertRaises(TrainingError) as caught:
                ExerciseDefinition(
                    "bounded",
                    "7k/8/8/8/8/8/6R1/6K1 w - - 0 1",
                    (ExerciseStep(frozenset({"Rh2+"})),),
                )
        self.assertEqual(caught.exception.code, TrainingErrorCode.INVALID_DEFINITION)

    def test_correct_move_advances_exactly_one_step(self):
        session = ExerciseSession(self.make_definition())
        result = session.submit("  Rh2+  ")
        self.assertTrue(result.accepted)
        self.assertEqual(result.step_index, 1)
        self.assertEqual(result.status, ExerciseStatus.IN_PROGRESS)
        self.assertEqual(result.explanation, "Force the king away.")
        self.assertEqual(
            result.position_fen,
            "7k/8/8/8/8/8/7R/6K1 b - - 1 1",
        )

    def test_incorrect_move_does_not_advance(self):
        session = ExerciseSession(self.make_definition())
        result = session.submit("Rh3")
        self.assertFalse(result.accepted)
        self.assertEqual(result.step_index, 0)
        self.assertEqual(session.step_index, 0)
        self.assertEqual(session.attempts, 1)
        self.assertEqual(session.mistakes, 1)

    def test_multiple_accepted_moves_can_complete_step(self):
        session = ExerciseSession(self.make_definition())
        session.submit("Rh2+")
        result = session.submit("Kg8!")
        self.assertTrue(result.accepted)
        self.assertTrue(result.completed)
        self.assertEqual(result.status, ExerciseStatus.COMPLETED)

    def test_completed_session_rejects_extra_submission(self):
        session = ExerciseSession(self.make_definition())
        session.submit("Rh2+")
        session.submit("Kg8")
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
        session.submit("Rh3")
        session.submit("Rh2+")
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
        session.submit("Rh3")
        session.submit("Rh2+")
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
            lambda: ExerciseStep({"Rh2+"}),
            lambda: ExerciseStep(["Rh2+"]),
            lambda: ExerciseStep("Rh2+"),
            lambda: ExerciseStep(frozenset({True})),
            lambda: ExerciseStep(frozenset({"Rh2+"}), hint=""),
            lambda: ExerciseStep(frozenset({"Rh2+"}), explanation=7),
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

        for invalid in (True, False, 7, 1.0, None, b"Rh2+", "   "):
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
        session.submit("Rh2+")
        snapshot = session.snapshot()
        self.assertEqual(
            snapshot["schema_version"],
            TRAINING_SNAPSHOT_SCHEMA_VERSION,
        )

        legacy = {
            key: snapshot[key]
            for key in (
                "exercise_id",
                "step_index",
                "attempts",
                "mistakes",
                "hints_used",
                "status",
            )
        }
        restored = ExerciseSession.restore(definition, legacy)
        self.assertEqual(restored.snapshot(), snapshot)

        for invalid_version in (True, False, "2", 0, 3, -1):
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
        for field in (
            "step_index",
            "attempts",
            "mistakes",
            "hints_used",
            "current_step_attempts",
            "current_step_hints",
        ):
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

    def test_definition_rejects_invalid_fen_and_illegal_solution_lines(self):
        cases = (
            lambda: ExerciseDefinition(
                "bad-fen",
                "8/8/8/8/8/8/8/8 w - - 0 1",
                (ExerciseStep(frozenset({"Ka2"})),),
            ),
            lambda: ExerciseDefinition(
                "illegal-line",
                "8/8/8/8/8/8/8/K6k w - - 0 1",
                (ExerciseStep(frozenset({"Ka3"})),),
            ),
            lambda: ExerciseDefinition(
                "wrong-turn",
                "7k/8/8/8/8/8/6R1/6K1 w - - 0 1",
                (
                    ExerciseStep(frozenset({"Rh2+"})),
                    ExerciseStep(frozenset({"Rh8"})),
                ),
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

    def test_session_uses_canonical_legality_and_preserves_board_on_mistake(self):
        definition = self.make_definition()
        self.assertEqual(definition.steps[1].accepted_moves, frozenset({"Kg8"}))
        session = ExerciseSession(definition)
        before = session.position_fen

        illegal = session.submit("Rh3")
        self.assertFalse(illegal.accepted)
        self.assertEqual(session.position_fen, before)
        accepted = session.submit("g2h2")
        self.assertTrue(accepted.accepted)
        self.assertEqual(accepted.move, "Rh2+")
        self.assertEqual(session.move_history, ("Rh2+",))

    def test_snapshot_binds_progress_to_exact_move_history_and_fen(self):
        definition = self.make_definition()
        session = ExerciseSession(definition)
        session.submit("Rh2+")
        snapshot = session.snapshot()

        tampered = (
            dict(snapshot, move_history=["Rg2"]),
            dict(snapshot, move_history=[]),
            dict(snapshot, current_fen=definition.start_fen),
            dict(snapshot, current_fen=True),
        )
        for payload in tampered:
            with self.subTest(payload=payload):
                with self.assertRaises(TrainingError):
                    ExerciseSession.restore(definition, payload)

    def test_solution_reveal_is_policy_gated_and_does_not_advance(self):
        definition = self.make_definition()
        session = ExerciseSession(definition)
        self.assertFalse(session.reveal_solution().available)
        session.submit("Rh3")
        reveal = session.reveal_solution()
        self.assertTrue(reveal.available)
        self.assertEqual(reveal.moves, ("Rh2+",))
        self.assertEqual(session.step_index, 0)
        self.assertEqual(session.position_fen, definition.start_fen)

        after_hint = ExerciseDefinition(
            "hint-policy",
            definition.start_fen,
            definition.steps,
            solution_reveal_policy=SolutionRevealPolicy.AFTER_HINT,
        )
        hinted = ExerciseSession(after_hint)
        self.assertFalse(hinted.reveal_solution().available)
        hinted.request_hint()
        self.assertTrue(hinted.reveal_solution().available)

        never = ExerciseDefinition(
            "never-policy",
            definition.start_fen,
            definition.steps,
            solution_reveal_policy=SolutionRevealPolicy.NEVER,
        )
        hidden = ExerciseSession(never)
        hidden.submit("Rh3")
        self.assertFalse(hidden.reveal_solution().available)

    def test_analysis_policy_activates_only_after_legal_completion(self):
        session = ExerciseSession(self.make_definition())
        self.assertFalse(session.analysis_allowed)
        session.submit("Rh2+")
        self.assertFalse(session.analysis_allowed)
        session.submit("Kg8")
        self.assertTrue(session.analysis_allowed)

        definition = self.make_definition()
        blocked = ExerciseDefinition(
            "no-analysis",
            definition.start_fen,
            definition.steps,
            allow_analysis_after_completion=False,
        )
        session = ExerciseSession(blocked)
        session.submit("Rh2+")
        session.submit("Kg8")
        self.assertFalse(session.analysis_allowed)


if __name__ == "__main__":
    unittest.main()
