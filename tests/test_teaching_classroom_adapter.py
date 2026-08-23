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
from acs.interaction_contracts import EngineVisibilityPolicy
from acs.teaching_classroom_adapter import (
    CLASSROOM_ACTIONS,
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
from acs.teaching_session_adapter import TEACHING_SESSION_ACTIONS, TeachingAudience
from acs.teaching_reverse_channel import STUDENT_CLICK_ACTION_ID, STUDENT_HOVER_ACTION_ID
from acs.teaching_visual_board import TEACHER_VISUAL_BOARD_ACTIONS


class TeachingClassroomAdapterTests(unittest.TestCase):
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

    def plan(
        self,
        activity: TeachingActivity = TeachingActivity.TEACHER_EXPLAINS,
        *,
        engine_visibility: EngineVisibilityPolicy | None = None,
    ) -> LessonSession:
        return LessonSession(
            "session-1",
            "lesson-1",
            TeachingPositionSource(PositionSourceKind.START),
            (
                TeachingStep(
                    "step-1",
                    activity,
                    "Prompt",
                    default_policy(activity, engine_visibility=engine_visibility),
                ),
            ),
            ("student-1", "student-2"),
            "cohort-1",
        )

    def test_action_namespace_is_explicit_disjoint_composition(self) -> None:
        self.assertFalse(set(TEACHING_SESSION_ACTIONS) & set(TEACHER_VISUAL_BOARD_ACTIONS))
        for reverse_action in (STUDENT_HOVER_ACTION_ID, STUDENT_CLICK_ACTION_ID):
            with self.subTest(action=reverse_action):
                self.assertNotIn(reverse_action, TEACHING_SESSION_ACTIONS)
                self.assertNotIn(reverse_action, TEACHER_VISUAL_BOARD_ACTIONS)
        self.assertEqual(
            CLASSROOM_ACTIONS,
            frozenset(
                set(TEACHING_SESSION_ACTIONS)
                | set(TEACHER_VISUAL_BOARD_ACTIONS)
                | {STUDENT_HOVER_ACTION_ID, STUDENT_CLICK_ACTION_ID}
            ),
        )

    def test_mixed_hover_pointer_highlight_and_arrow_never_change_position(self) -> None:
        plan = self.plan()
        state = start_session(plan)
        initial_fen = state.position_fen
        actions = (
            ("student.hover", {"square": "g1"}, "student-1"),
            ("teacher.pointer_input", {"square": "e4"}, None),
            ("teacher.highlight", {"square": "d4", "purpose": "target"}, None),
            ("teacher.arrow", {"start_square": "e2", "end_square": "e4", "purpose": "plan"}, None),
            ("teacher.highlight_legal_moves", {"square": "g1"}, None),
            ("teacher.set_coordinates", {"visible": False}, None),
        )
        for expected_revision, (action, payload, actor) in enumerate(actions):
            state = apply_classroom_action(
                plan,
                state,
                self.classroom(),
                action,
                payload,
                expected_revision=expected_revision,
                actor_student_id=actor,
            )
            self.assertEqual(state.position_fen, initial_fen)
        self.assertEqual(state.presentation.pointer.square, "e4")
        self.assertFalse(state.presentation.coordinate_labels_visible)
        self.assertEqual(tuple(item.square for item in state.presentation.student_pointer_history), ("g1",))

    def test_hover_click_selection_and_move_keep_explicit_effect_boundaries(self) -> None:
        selection_plan = self.plan(TeachingActivity.STUDENT_RESPONDS)
        selection_state = start_session(selection_plan)
        hovered = apply_classroom_action(
            selection_plan,
            selection_state,
            self.classroom(),
            "student.hover",
            {"square": "e4"},
            expected_revision=0,
            actor_student_id="student-1",
        )
        clicked = apply_classroom_action(
            selection_plan,
            hovered,
            self.classroom(),
            "student.click",
            {"square": "g1"},
            expected_revision=1,
            actor_student_id="student-1",
        )
        selected = apply_classroom_action(
            selection_plan,
            clicked,
            self.classroom(),
            "student.select",
            {"square": "e4"},
            expected_revision=2,
            actor_student_id="student-1",
        )
        self.assertEqual(hovered.position_fen, Board.START)
        self.assertIsNone(hovered.last_response)
        self.assertEqual(clicked.position_fen, Board.START)
        self.assertEqual(clicked.last_response.value, "g1")
        self.assertEqual(clicked.presentation.student_pointer_history[-1].piece, "N")
        self.assertEqual(selected.position_fen, Board.START)
        self.assertEqual(selected.last_response.value, "e4")

        move_plan = self.plan(TeachingActivity.MAKE_MOVE)
        move_state = start_session(move_plan)
        hovered_move = apply_classroom_action(
            move_plan,
            move_state,
            self.classroom(),
            "student.hover",
            {"square": "e4"},
            expected_revision=0,
            actor_student_id="student-1",
        )
        with self.assertRaises(TeachingClassroomAdapterError):
            apply_classroom_action(
                move_plan,
                hovered_move,
                self.classroom(),
                "student.click",
                {"square": "e4"},
                expected_revision=1,
                actor_student_id="student-1",
            )
        moved = apply_classroom_action(
            move_plan,
            hovered_move,
            self.classroom(),
            "student.move",
            {"raw_text": "e4"},
            expected_revision=1,
            actor_student_id="student-1",
        )
        self.assertEqual(hovered_move.position_fen, Board.START)
        self.assertNotEqual(moved.position_fen, Board.START)
        self.assertEqual(moved.last_response.value, "e4")

    def test_click_on_locked_teacher_explains_mode_is_not_silent_answer(self) -> None:
        plan = self.plan(TeachingActivity.TEACHER_EXPLAINS)
        state = start_session(plan)
        with self.assertRaises(TeachingClassroomAdapterError):
            apply_classroom_action(
                plan,
                state,
                self.classroom(),
                "student.click",
                {"square": "g1"},
                expected_revision=0,
                actor_student_id="student-1",
            )
        self.assertEqual(state.position_fen, Board.START)
        self.assertEqual(state.revision, 0)
        self.assertIsNone(state.last_response)
        self.assertEqual(state.presentation.student_pointer_history, ())

    def test_role_spoofing_fails_at_unified_boundary(self) -> None:
        plan = self.plan()
        state = start_session(plan)
        with self.assertRaises(TeachingClassroomAdapterError):
            apply_classroom_action(
                plan,
                state,
                self.classroom(),
                "student.hover",
                {"square": "e4", "student_id": "student-2"},
                expected_revision=0,
                actor_student_id="student-1",
            )
        selection_plan = self.plan(TeachingActivity.STUDENT_RESPONDS)
        selection_state = start_session(selection_plan)
        with self.assertRaises(TeachingClassroomAdapterError):
            apply_classroom_action(
                selection_plan,
                selection_state,
                self.classroom(),
                "student.click",
                {"square": "g1", "student_id": "student-2"},
                expected_revision=0,
                actor_student_id="student-1",
            )
        with self.assertRaises(TeachingClassroomAdapterError):
            apply_classroom_action(
                plan,
                state,
                self.classroom(),
                "teacher.set_coordinates",
                {"visible": False},
                expected_revision=0,
                actor_student_id="student-1",
            )
        with self.assertRaises(TeachingClassroomAdapterError):
            apply_classroom_action(
                plan,
                state,
                self.classroom(),
                "student.hover",
                {"square": "e4"},
                expected_revision=0,
            )
        self.assertEqual(state.position_fen, Board.START)
        self.assertEqual(state.revision, 0)
        self.assertEqual(selection_state.position_fen, Board.START)
        self.assertEqual(selection_state.revision, 0)

    def test_teacher_view_gets_reverse_history_student_view_does_not(self) -> None:
        plan = self.plan()
        state = start_session(plan)
        state = apply_classroom_action(
            plan,
            state,
            self.classroom(),
            "student.hover",
            {"square": "g1"},
            expected_revision=0,
            actor_student_id="student-1",
        )
        state = apply_classroom_action(
            plan,
            state,
            self.classroom(),
            "teacher.pointer_input",
            {"square": "e4"},
            expected_revision=1,
        )
        state = apply_classroom_action(
            plan,
            state,
            self.classroom(),
            "teacher.highlight_legal_moves",
            {"square": "g1"},
            expected_revision=2,
        )
        teacher = project_classroom_view(
            plan,
            state,
            self.classroom(),
            audience=TeachingAudience.TEACHER,
        )
        student = project_classroom_view(
            plan,
            state,
            self.classroom(),
            audience=TeachingAudience.STUDENT,
            viewer_student_id="student-1",
        )
        self.assertEqual(teacher.teacher_pointer_square, "e4")
        self.assertEqual(student.teacher_pointer_square, "e4")
        self.assertEqual(tuple(item.square for item in teacher.highlights), ("f3", "h3"))
        self.assertEqual(tuple(item.square for item in student.highlights), ("f3", "h3"))
        self.assertEqual(len(teacher.student_pointer_history), 1)
        self.assertEqual(teacher.student_pointer_history[0].student_label, "Anna")
        self.assertEqual(student.student_pointer_history, ())

    def test_click_feedback_is_teacher_only_and_contains_no_raw_identity(self) -> None:
        plan = self.plan(TeachingActivity.STUDENT_RESPONDS)
        state = start_session(plan)
        state = apply_classroom_action(
            plan,
            state,
            self.classroom(),
            "student.click",
            {"square": "g1"},
            expected_revision=0,
            actor_student_id="student-1",
        )
        teacher = project_classroom_view(
            plan,
            state,
            self.classroom(),
            audience=TeachingAudience.TEACHER,
        )
        student = project_classroom_view(
            plan,
            state,
            self.classroom(),
            audience=TeachingAudience.STUDENT,
            viewer_student_id="student-1",
        )
        teacher_payload = classroom_view_to_payload(teacher)
        student_payload = classroom_view_to_payload(student)

        self.assertEqual(teacher_payload["student_pointer_history"][-1]["kind"], "selection")
        self.assertEqual(teacher_payload["student_pointer_history"][-1]["student_label"], "Anna")
        self.assertEqual(teacher_payload["student_pointer_history"][-1]["square"], "g1")
        self.assertEqual(teacher_payload["student_pointer_history"][-1]["piece_symbol"], "N")
        self.assertEqual(student_payload["student_pointer_history"], [])
        self.assertNotIn("student-1", repr(teacher_payload))
        self.assertNotIn("student-1", repr(student_payload))

    def test_student_payload_has_visual_lesson_but_no_reverse_history_or_internal_identity(self) -> None:
        plan = self.plan(engine_visibility=EngineVisibilityPolicy.VISIBLE_TO_TEACHER)
        state = start_session(plan)
        state = apply_classroom_action(
            plan,
            state,
            self.classroom(),
            "student.hover",
            {"square": "g1"},
            expected_revision=0,
            actor_student_id="student-2",
        )
        view = project_classroom_view(
            plan,
            state,
            self.classroom(),
            audience=TeachingAudience.STUDENT,
            viewer_student_id="student-1",
        )
        payload = classroom_view_to_payload(view)
        rendered = repr(payload)
        self.assertFalse(payload["session"]["engine_visible"])
        self.assertEqual(payload["student_pointer_history"], [])
        self.assertNotIn("student-1", rendered)
        self.assertNotIn("student-2", rendered)
        self.assertNotIn("session-1", rendered)
        self.assertNotIn(Board.START, rendered)
        self.assertNotIn("plan_digest", rendered)

    def test_teacher_only_engine_policy_remains_role_safe_through_classroom_projection(self) -> None:
        plan = self.plan(engine_visibility=EngineVisibilityPolicy.VISIBLE_TO_TEACHER)
        state = start_session(plan)
        teacher = project_classroom_view(plan, state, self.classroom(), audience=TeachingAudience.TEACHER)
        student = project_classroom_view(
            plan,
            state,
            self.classroom(),
            audience=TeachingAudience.STUDENT,
            viewer_student_id="student-1",
        )
        self.assertTrue(teacher.session.engine_visible)
        self.assertFalse(student.session.engine_visible)

    def test_cas_is_shared_across_mixed_action_families(self) -> None:
        plan = self.plan()
        state = start_session(plan)
        state = apply_classroom_action(
            plan,
            state,
            self.classroom(),
            "student.hover",
            {"square": "e4"},
            expected_revision=0,
            actor_student_id="student-1",
        )
        with self.assertRaises(TeachingClassroomAdapterError):
            apply_classroom_action(
                plan,
                state,
                self.classroom(),
                "teacher.pointer_input",
                {"square": "d4"},
                expected_revision=0,
            )
        self.assertEqual(state.revision, 1)
        self.assertIsNone(state.presentation.pointer.square)
        self.assertEqual(state.position_fen, Board.START)

    def test_unknown_action_fails_closed_without_family_guessing(self) -> None:
        plan = self.plan()
        state = start_session(plan)
        for action in ("e4", "student.drag", "teacher.move", "pointer.e4", ""):
            with self.subTest(action=action):
                with self.assertRaises(TeachingClassroomAdapterError):
                    apply_classroom_action(
                        plan,
                        state,
                        self.classroom(),
                        action,
                        {"square": "e4"},
                        expected_revision=0,
                    )
        self.assertEqual(state.revision, 0)
        self.assertEqual(state.position_fen, Board.START)


if __name__ == "__main__":
    unittest.main()
