import unittest

from acs.training import (
    ExerciseDefinition,
    ExerciseSession,
    ExerciseStatus,
    ExerciseStep,
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


if __name__ == "__main__":
    unittest.main()
