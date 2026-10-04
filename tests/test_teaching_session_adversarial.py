from __future__ import annotations

from dataclasses import replace
import unittest

from acs.interaction_contracts import (
    BoardPermissionState,
    EngineVisibilityPolicy,
    PresentationState,
    StudentSelectionEvent,
    VisualArrow,
    presentation_state_to_payload,
)
from acs.teaching_session import (
    LessonSession,
    PositionSourceKind,
    TeachingActivity,
    TeachingPositionSource,
    TeachingSessionError,
    TeachingSessionPhase,
    TeachingSessionState,
    TeachingStep,
    advance_step,
    apply_annotation,
    default_policy,
    start_session,
    submit_selection,
)
from acs.interaction_contracts import AnnotationCommand, AnnotationOperation


class TeachingSessionAdversarialTests(unittest.TestCase):
    def plan(self, activity: TeachingActivity = TeachingActivity.STUDENT_RESPONDS) -> LessonSession:
        kwargs = {}
        if activity in {
            TeachingActivity.SHOW_SQUARE,
            TeachingActivity.WHERE_CAN_PIECE_MOVE,
            TeachingActivity.ATTACK_DEFENCE,
        }:
            kwargs["target_square"] = "e4"
        elif activity is TeachingActivity.SHOW_PIECE:
            kwargs.update(target_square="e4", target_piece="P")
        elif activity is TeachingActivity.SOLUTION_REVEAL:
            kwargs["solution_text"] = "Answer"
        return LessonSession(
            "session-1",
            "lesson-1",
            TeachingPositionSource(PositionSourceKind.START),
            (TeachingStep("step-1", activity, "Prompt", default_policy(activity), **kwargs),),
            ("student-1", "student-2"),
        )

    def test_state_rejects_active_student_projection_mismatch(self) -> None:
        state = start_session(self.plan())
        with self.assertRaises(TeachingSessionError):
            replace(state, active_student_id="student-1")

    def test_paused_and_completed_states_require_locked_hidden_projection(self) -> None:
        active = start_session(self.plan(TeachingActivity.MAKE_MOVE))
        with self.assertRaises(TeachingSessionError):
            replace(active, phase=TeachingSessionPhase.PAUSED)

        reveal = start_session(self.plan(TeachingActivity.SOLUTION_REVEAL))
        self.assertEqual(reveal.presentation.engine_visibility, EngineVisibilityPolicy.VISIBLE_TO_STUDENT)
        with self.assertRaises(TeachingSessionError):
            replace(reveal, phase=TeachingSessionPhase.COMPLETED, remaining_seconds=None)

    def test_last_response_student_must_match_active_student(self) -> None:
        plan = self.plan()
        answered = submit_selection(plan, start_session(plan), "student-1", "e4", 0)
        forged_projection = replace(answered.presentation, active_student_id="student-2")
        with self.assertRaises(TeachingSessionError):
            replace(answered, active_student_id="student-2", presentation=forged_projection)

    def test_student_selection_resource_limit_raises_teaching_error_atomically(self) -> None:
        plan = self.plan()
        base = start_session(plan)
        history = tuple(
            StudentSelectionEvent("e4", student_id="student-1", sequence=index)
            for index in range(256)
        )
        full = replace(base, presentation=replace(base.presentation, student_pointer_history=history))

        with self.assertRaises(TeachingSessionError):
            submit_selection(plan, full, "student-1", "e5", 0)

        self.assertEqual(full.revision, 0)
        self.assertEqual(len(full.presentation.student_pointer_history), 256)
        self.assertEqual(full.position_fen, base.position_fen)

    def test_annotation_resource_limit_raises_teaching_error_atomically(self) -> None:
        plan = self.plan(TeachingActivity.TEACHER_EXPLAINS)
        base = start_session(plan)
        squares = [f"{file_name}{rank}" for rank in range(1, 9) for file_name in "abcdefgh"]
        pairs = [(a, b) for a in squares for b in squares if a != b]
        arrows = tuple(VisualArrow(a, b, "teacher") for a, b in pairs[:64])
        full = replace(base, presentation=replace(base.presentation, arrows=arrows))
        next_start, next_end = pairs[64]

        with self.assertRaises(TeachingSessionError):
            apply_annotation(
                plan,
                full,
                AnnotationCommand(
                    AnnotationOperation.ADD_ARROW,
                    start_square=next_start,
                    end_square=next_end,
                    tag="teacher",
                ),
                0,
            )

        self.assertEqual(full.revision, 0)
        self.assertEqual(len(full.presentation.arrows), 64)
        self.assertEqual(full.position_fen, base.position_fen)

    def test_state_restore_wraps_oversized_presentation_payload_as_teaching_error(self) -> None:
        plan = self.plan()
        state = start_session(plan)
        events = tuple(
            StudentSelectionEvent("e4", student_id="student-1", sequence=index)
            for index in range(256)
        )
        payload = presentation_state_to_payload(
            PresentationState(
                board_permission=BoardPermissionState.SELECT_ONLY,
                student_pointer_history=events,
            )
        )
        payload["student_pointer_history"].append(dict(payload["student_pointer_history"][0]))
        record = state.to_record()
        record["presentation"] = payload
        record["digest"] = "0" * 64

        with self.assertRaises(TeachingSessionError):
            TeachingSessionState.from_record(record)

    def test_completed_state_from_api_is_hidden_locked_and_stable(self) -> None:
        plan = self.plan(TeachingActivity.TEACHER_EXPLAINS)
        completed = advance_step(plan, start_session(plan), 0)
        self.assertEqual(completed.phase, TeachingSessionPhase.COMPLETED)
        self.assertEqual(completed.presentation.board_permission, BoardPermissionState.LOCKED)
        self.assertEqual(completed.presentation.engine_visibility, EngineVisibilityPolicy.HIDDEN)
        self.assertIsNone(completed.remaining_seconds)


if __name__ == "__main__":
    unittest.main()
