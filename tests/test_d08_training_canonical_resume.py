import unittest

from acs.chesscore import Board
from acs.training import (
    ExerciseContentError,
    ExerciseDefinition,
    ExerciseSession,
    ExerciseStatus,
    ExerciseStep,
)


class CanonicalTrainingEvaluationTests(unittest.TestCase):
    def test_coordinate_alias_and_san_are_the_same_canonical_answer(self):
        definition = ExerciseDefinition(
            "alias",
            Board.START,
            (ExerciseStep(frozenset({"e4"})),),
        )
        session = ExerciseSession(definition)
        result = session.submit("e2e4")
        self.assertTrue(result.accepted)
        self.assertEqual("e4", result.move)
        self.assertEqual(("e4",), session.accepted_path)
        self.assertTrue(session.completed)

    def test_illegal_user_move_is_a_mistake_but_never_mutates_position(self):
        definition = ExerciseDefinition(
            "illegal-user",
            Board.START,
            (ExerciseStep(frozenset({"e4"})),),
        )
        session = ExerciseSession(definition)
        before_fen = session.current_fen
        before_path = session.accepted_path
        result = session.submit("e5")
        self.assertFalse(result.accepted)
        self.assertEqual(1, session.attempts)
        self.assertEqual(1, session.mistakes)
        self.assertEqual(0, session.step_index)
        self.assertEqual(before_fen, session.current_fen)
        self.assertEqual(before_path, session.accepted_path)

    def test_legal_but_incorrect_move_is_a_mistake_without_hidden_board_mutation(self):
        definition = ExerciseDefinition(
            "wrong-legal",
            Board.START,
            (ExerciseStep(frozenset({"e4"})),),
        )
        session = ExerciseSession(definition)
        before = session.current_fen
        result = session.submit("Nf3")
        self.assertFalse(result.accepted)
        self.assertEqual("Nf3", result.move)
        self.assertEqual(before, session.current_fen)
        self.assertEqual((), session.accepted_path)

    def test_malformed_authored_current_step_fails_before_any_session_mutation(self):
        definition = ExerciseDefinition(
            "bad-content",
            Board.START,
            (ExerciseStep(frozenset({"Qa9"})),),
        )
        session = ExerciseSession(definition)
        before = session.snapshot()
        with self.assertRaises(ExerciseContentError):
            session.submit("e4")
        self.assertEqual(before, session.snapshot())

    def test_malformed_next_step_rolls_back_preceding_correct_answer_atomically(self):
        definition = ExerciseDefinition(
            "bad-next-content",
            Board.START,
            (
                ExerciseStep(frozenset({"e4"})),
                ExerciseStep(frozenset({"Qa9"})),
            ),
        )
        session = ExerciseSession(definition)
        before = session.snapshot()
        with self.assertRaises(ExerciseContentError):
            session.submit("e4")
        self.assertEqual(before, session.snapshot())
        self.assertEqual(Board.START, session.current_fen)
        self.assertEqual((), session.accepted_path)

    def test_distinct_correct_alternatives_record_the_exact_chosen_branch(self):
        definition = ExerciseDefinition(
            "branch",
            Board.START,
            (
                ExerciseStep(frozenset({"e4", "d4"})),
                ExerciseStep(frozenset({"e5", "c5"})),
            ),
        )
        e4 = ExerciseSession(definition)
        e4.submit("e4")
        e4.submit("e5")
        d4 = ExerciseSession(definition)
        d4.submit("d4")
        d4.submit("c5")
        self.assertEqual(("e4", "e5"), e4.accepted_path)
        self.assertEqual(("d4", "c5"), d4.accepted_path)
        self.assertNotEqual(e4.current_fen, d4.current_fen)
        self.assertEqual(e4.snapshot(), ExerciseSession.restore(definition, e4.snapshot()).snapshot())
        self.assertEqual(d4.snapshot(), ExerciseSession.restore(definition, d4.snapshot()).snapshot())


class DeterministicResumeTests(unittest.TestCase):
    def make_unambiguous_definition(self):
        return ExerciseDefinition(
            "resume",
            Board.START,
            (
                ExerciseStep(frozenset({"e4", "e2e4"})),
                ExerciseStep(frozenset({"e5", "e7e5"})),
            ),
        )

    def test_schema_v3_persists_canonical_path_and_position(self):
        definition = self.make_unambiguous_definition()
        session = ExerciseSession(definition)
        session.submit("e2e4")
        snapshot = session.snapshot()
        self.assertEqual(3, snapshot["schema_version"])
        self.assertEqual(["e4"], snapshot["accepted_path"])
        self.assertEqual(session.current_fen, snapshot["position_fen"])
        restored = ExerciseSession.restore(definition, snapshot)
        self.assertEqual(("e4",), restored.accepted_path)
        self.assertEqual(session.current_fen, restored.current_fen)
        self.assertEqual(snapshot, restored.snapshot())

    def test_tampered_position_fen_is_rejected(self):
        definition = self.make_unambiguous_definition()
        session = ExerciseSession(definition)
        session.submit("e4")
        snapshot = session.snapshot()
        snapshot["position_fen"] = Board.START
        with self.assertRaisesRegex(ValueError, "position does not match"):
            ExerciseSession.restore(definition, snapshot)

    def test_tampered_path_is_rejected_even_when_move_is_legal(self):
        definition = self.make_unambiguous_definition()
        session = ExerciseSession(definition)
        session.submit("e4")
        snapshot = session.snapshot()
        snapshot["accepted_path"] = ["d4"]
        with self.assertRaisesRegex(ValueError, "not accepted"):
            ExerciseSession.restore(definition, snapshot)

    def test_unreachable_counter_equation_is_rejected(self):
        definition = self.make_unambiguous_definition()
        session = ExerciseSession(definition)
        session.submit("e4")
        snapshot = session.snapshot()
        snapshot["attempts"] = 99
        with self.assertRaisesRegex(ValueError, "counters"):
            ExerciseSession.restore(definition, snapshot)

    def test_v2_unambiguous_snapshot_migrates_by_replaying_canonical_core(self):
        definition = self.make_unambiguous_definition()
        session = ExerciseSession(definition)
        session.submit("e4")
        v3 = session.snapshot()
        legacy = {
            key: value
            for key, value in v3.items()
            if key not in {"accepted_path", "position_fen"}
        }
        legacy["schema_version"] = 2
        restored = ExerciseSession.restore(definition, legacy)
        self.assertEqual(("e4",), restored.accepted_path)
        self.assertEqual(session.current_fen, restored.current_fen)
        self.assertEqual(3, restored.snapshot()["schema_version"])

    def test_v2_distinct_alternative_snapshot_is_rejected_as_ambiguous(self):
        definition = ExerciseDefinition(
            "legacy-branch",
            Board.START,
            (
                ExerciseStep(frozenset({"e4", "d4"})),
                ExerciseStep(frozenset({"e5", "c5"})),
            ),
        )
        session = ExerciseSession(definition)
        session.submit("e4")
        v3 = session.snapshot()
        legacy = {
            key: value
            for key, value in v3.items()
            if key not in {"accepted_path", "position_fen"}
        }
        legacy["schema_version"] = 2
        with self.assertRaisesRegex(ValueError, "ambiguous"):
            ExerciseSession.restore(definition, legacy)

    def test_future_or_unknown_snapshot_fields_fail_closed(self):
        definition = self.make_unambiguous_definition()
        snapshot = ExerciseSession(definition).snapshot()
        snapshot["future_hidden_state"] = "x"
        with self.assertRaisesRegex(ValueError, "unknown fields"):
            ExerciseSession.restore(definition, snapshot)

    def test_noncanonical_recorded_san_is_rejected(self):
        definition = self.make_unambiguous_definition()
        session = ExerciseSession(definition)
        session.submit("e4")
        snapshot = session.snapshot()
        snapshot["accepted_path"] = ["e2e4"]
        with self.assertRaisesRegex(ValueError, "canonical SAN"):
            ExerciseSession.restore(definition, snapshot)


class MalformedAndResourceBoundaryTests(unittest.TestCase):
    def test_invalid_start_position_uses_canonical_fen_validation(self):
        with self.assertRaises(ValueError):
            ExerciseDefinition(
                "bad-fen",
                "8/8/8/8/8/8/8/8 w - - 0 1",
                (ExerciseStep(frozenset({"e4"})),),
            )

    def test_scalar_moves_are_not_coerced_to_text(self):
        with self.assertRaises(TypeError):
            ExerciseStep(frozenset({123}))  # type: ignore[arg-type]
        definition = ExerciseDefinition(
            "scalar",
            Board.START,
            (ExerciseStep(frozenset({"e4"})),),
        )
        session = ExerciseSession(definition)
        before = session.snapshot()
        with self.assertRaises(TypeError):
            session.submit(True)  # type: ignore[arg-type]
        self.assertEqual(before, session.snapshot())

    def test_move_text_and_accepted_move_collection_are_bounded(self):
        with self.assertRaisesRegex(ValueError, "too many"):
            ExerciseStep(frozenset(f"a{i}" for i in range(65)))
        definition = ExerciseDefinition(
            "long-move",
            Board.START,
            (ExerciseStep(frozenset({"e4"})),),
        )
        session = ExerciseSession(definition)
        with self.assertRaisesRegex(ValueError, "too long"):
            session.submit("x" * 65)

    def test_reset_after_branch_restores_start_without_reusing_hidden_board_state(self):
        definition = ExerciseDefinition(
            "reset-branch",
            Board.START,
            (
                ExerciseStep(frozenset({"d4", "e4"})),
                ExerciseStep(frozenset({"c5", "e5"})),
            ),
        )
        session = ExerciseSession(definition)
        session.submit("d4")
        session.request_hint()
        session.reset()
        self.assertEqual(Board.START, session.current_fen)
        self.assertEqual((), session.accepted_path)
        self.assertEqual(ExerciseStatus.READY, session.status)
        self.assertEqual(0, session.attempts)
        self.assertEqual(0, session.mistakes)
        self.assertEqual(0, session.hints_used)


if __name__ == "__main__":
    unittest.main()
