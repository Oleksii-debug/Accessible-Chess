from __future__ import annotations

import unittest

from acs.chesscore import Board
from acs.classroom_domain import (
    ClassroomClass,
    ClassroomSnapshot,
    Cohort,
    ConsentState,
    Course,
    Group,
    Lesson,
    Student,
)
from acs.teaching_classroom_adapter import (
    CLASSROOM_ACTIONS,
    TEACHER_CLEAR_ACTIVE_STUDENT_ACTION_ID,
    TEACHER_SET_ACTIVE_STUDENT_ACTION_ID,
    TeachingClassroomAdapterError,
    apply_classroom_action,
    classroom_view_to_payload,
    project_classroom_view,
)
from acs.teaching_session import (
    LessonSession,
    PositionSourceKind,
    TeachingActivity,
    TeachingPositionSource,
    TeachingStep,
    default_policy,
    start_session,
)
from acs.teaching_session_adapter import TeachingAudience


class TeachingClassroomFloorControlTests(unittest.TestCase):
    def classroom(self) -> ClassroomSnapshot:
        return ClassroomSnapshot(
            students=(
                Student("student-1", "Anna", ConsentState.GRANTED),
                Student("student-2", "Bohdan", ConsentState.GRANTED),
            ),
            classes=(ClassroomClass("class-1", "Class", ("group-1",)),),
            groups=(Group("group-1", "class-1", "Group"),),
            courses=(Course("course-1", "Course", ("lesson-1",)),),
            cohorts=(Cohort("cohort-1", "course-1", ("student-1", "student-2"), "group-1"),),
            lessons=(Lesson("lesson-1", "course-1", "Lesson", (), "2026-08-23T10:00:00Z"),),
        )

    def plan(self, activity: TeachingActivity) -> LessonSession:
        return LessonSession(
            "session-1",
            "lesson-1",
            TeachingPositionSource(PositionSourceKind.START),
            (
                TeachingStep(
                    "step-1",
                    activity,
                    "Prompt",
                    default_policy(activity),
                ),
            ),
            ("student-1", "student-2"),
            "cohort-1",
        )

    def test_floor_actions_are_explicit_classroom_actions(self) -> None:
        self.assertIn(TEACHER_SET_ACTIVE_STUDENT_ACTION_ID, CLASSROOM_ACTIONS)
        self.assertIn(TEACHER_CLEAR_ACTIVE_STUDENT_ACTION_ID, CLASSROOM_ACTIONS)
        self.assertNotEqual(TEACHER_SET_ACTIVE_STUDENT_ACTION_ID, "student.select")
        self.assertNotEqual(TEACHER_SET_ACTIVE_STUDENT_ACTION_ID, "student.move")

    def test_teacher_assigns_responder_without_mutating_position_or_presentation_semantics(self) -> None:
        plan = self.plan(TeachingActivity.STUDENT_RESPONDS)
        state = start_session(plan)
        initial_fen = state.position_fen
        updated = apply_classroom_action(
            plan,
            state,
            self.classroom(),
            TEACHER_SET_ACTIVE_STUDENT_ACTION_ID,
            {"student_id": "student-1"},
            expected_revision=0,
        )
        self.assertEqual(updated.position_fen, initial_fen)
        self.assertEqual(updated.active_student_id, "student-1")
        self.assertEqual(updated.presentation.active_student_id, "student-1")
        self.assertEqual(updated.presentation.board_permission, state.presentation.board_permission)
        self.assertEqual(updated.presentation.engine_visibility, state.presentation.engine_visibility)
        self.assertEqual(updated.presentation.pointer, state.presentation.pointer)
        self.assertEqual(updated.presentation.highlights, state.presentation.highlights)
        self.assertEqual(updated.presentation.arrows, state.presentation.arrows)
        self.assertEqual(updated.presentation.student_pointer_history, state.presentation.student_pointer_history)
        self.assertIsNone(updated.last_response)
        self.assertEqual(updated.revision, 1)

    def test_only_active_responder_can_click_select_or_move(self) -> None:
        for activity, action, payload in (
            (TeachingActivity.STUDENT_RESPONDS, "student.click", {"square": "g1"}),
            (TeachingActivity.STUDENT_RESPONDS, "student.select", {"square": "e4"}),
            (TeachingActivity.MAKE_MOVE, "student.move", {"raw_text": "e4"}),
        ):
            with self.subTest(action=action):
                plan = self.plan(activity)
                state = start_session(plan)
                state = apply_classroom_action(
                    plan,
                    state,
                    self.classroom(),
                    TEACHER_SET_ACTIVE_STUDENT_ACTION_ID,
                    {"student_id": "student-1"},
                    expected_revision=0,
                )
                before = state
                with self.assertRaises(TeachingClassroomAdapterError):
                    apply_classroom_action(
                        plan,
                        state,
                        self.classroom(),
                        action,
                        payload,
                        expected_revision=1,
                        actor_student_id="student-2",
                    )
                self.assertEqual(state, before)
                accepted = apply_classroom_action(
                    plan,
                    state,
                    self.classroom(),
                    action,
                    payload,
                    expected_revision=1,
                    actor_student_id="student-1",
                )
                if action == "student.move":
                    self.assertNotEqual(accepted.position_fen, Board.START)
                else:
                    self.assertEqual(accepted.position_fen, Board.START)
                self.assertEqual(accepted.active_student_id, "student-1")

    def test_hover_remains_observation_only_even_when_another_student_holds_floor(self) -> None:
        plan = self.plan(TeachingActivity.STUDENT_RESPONDS)
        state = start_session(plan)
        state = apply_classroom_action(
            plan,
            state,
            self.classroom(),
            TEACHER_SET_ACTIVE_STUDENT_ACTION_ID,
            {"student_id": "student-1"},
            expected_revision=0,
        )
        hovered = apply_classroom_action(
            plan,
            state,
            self.classroom(),
            "student.hover",
            {"square": "g8"},
            expected_revision=1,
            actor_student_id="student-2",
        )
        self.assertEqual(hovered.position_fen, Board.START)
        self.assertEqual(hovered.active_student_id, "student-1")
        self.assertIsNone(hovered.last_response)
        self.assertEqual(hovered.presentation.student_pointer_history[-1].student_id, "student-2")

    def test_student_projection_disables_submit_for_non_active_viewer_without_identity_leak(self) -> None:
        plan = self.plan(TeachingActivity.STUDENT_RESPONDS)
        state = start_session(plan)
        state = apply_classroom_action(
            plan,
            state,
            self.classroom(),
            TEACHER_SET_ACTIVE_STUDENT_ACTION_ID,
            {"student_id": "student-1"},
            expected_revision=0,
        )
        active_view = project_classroom_view(
            plan,
            state,
            self.classroom(),
            audience=TeachingAudience.STUDENT,
            viewer_student_id="student-1",
        )
        inactive_view = project_classroom_view(
            plan,
            state,
            self.classroom(),
            audience=TeachingAudience.STUDENT,
            viewer_student_id="student-2",
        )
        teacher_view = project_classroom_view(
            plan,
            state,
            self.classroom(),
            audience=TeachingAudience.TEACHER,
        )
        self.assertTrue(active_view.session.can_submit_selection)
        self.assertFalse(inactive_view.session.can_submit_selection)
        self.assertTrue(active_view.session.viewer_is_active)
        self.assertFalse(inactive_view.session.viewer_is_active)
        self.assertEqual(teacher_view.session.active_student_label, "Anna")
        inactive_payload = classroom_view_to_payload(inactive_view)
        self.assertEqual(inactive_payload["session"]["active_student_label"], "")
        self.assertNotIn("student-1", repr(inactive_payload))
        self.assertNotIn("Anna", repr(inactive_payload))

    def test_clear_floor_reopens_response_and_clears_old_response_identity(self) -> None:
        plan = self.plan(TeachingActivity.STUDENT_RESPONDS)
        state = start_session(plan)
        state = apply_classroom_action(
            plan,
            state,
            self.classroom(),
            TEACHER_SET_ACTIVE_STUDENT_ACTION_ID,
            {"student_id": "student-1"},
            expected_revision=0,
        )
        state = apply_classroom_action(
            plan,
            state,
            self.classroom(),
            "student.click",
            {"square": "g1"},
            expected_revision=1,
            actor_student_id="student-1",
        )
        self.assertIsNotNone(state.last_response)
        cleared = apply_classroom_action(
            plan,
            state,
            self.classroom(),
            TEACHER_CLEAR_ACTIVE_STUDENT_ACTION_ID,
            {},
            expected_revision=2,
        )
        self.assertEqual(cleared.position_fen, Board.START)
        self.assertIsNone(cleared.active_student_id)
        self.assertIsNone(cleared.presentation.active_student_id)
        self.assertIsNone(cleared.last_response)
        student_two = project_classroom_view(
            plan,
            cleared,
            self.classroom(),
            audience=TeachingAudience.STUDENT,
            viewer_student_id="student-2",
        )
        self.assertTrue(student_two.session.can_submit_selection)

    def test_floor_control_is_cas_guarded_teacher_only_and_fail_closed(self) -> None:
        plan = self.plan(TeachingActivity.STUDENT_RESPONDS)
        state = start_session(plan)
        bad_payloads = (
            None,
            {},
            {"student_id": "student-3"},
            {"student_id": "student-1", "extra": True},
            {"student_id": 1},
        )
        for payload in bad_payloads:
            with self.subTest(payload=payload):
                with self.assertRaises(TeachingClassroomAdapterError):
                    apply_classroom_action(
                        plan,
                        state,
                        self.classroom(),
                        TEACHER_SET_ACTIVE_STUDENT_ACTION_ID,
                        payload,
                        expected_revision=0,
                    )
        with self.assertRaises(TeachingClassroomAdapterError):
            apply_classroom_action(
                plan,
                state,
                self.classroom(),
                TEACHER_SET_ACTIVE_STUDENT_ACTION_ID,
                {"student_id": "student-1"},
                expected_revision=0,
                actor_student_id="student-1",
            )
        state = apply_classroom_action(
            plan,
            state,
            self.classroom(),
            TEACHER_SET_ACTIVE_STUDENT_ACTION_ID,
            {"student_id": "student-1"},
            expected_revision=0,
        )
        with self.assertRaises(TeachingClassroomAdapterError):
            apply_classroom_action(
                plan,
                state,
                self.classroom(),
                TEACHER_CLEAR_ACTIVE_STUDENT_ACTION_ID,
                {},
                expected_revision=0,
            )
        self.assertEqual(state.active_student_id, "student-1")
        self.assertEqual(state.revision, 1)


if __name__ == "__main__":
    unittest.main()
