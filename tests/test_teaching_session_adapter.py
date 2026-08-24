from __future__ import annotations

from dataclasses import asdict, replace
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
from acs.teaching_session import (
    LessonSession,
    PositionSourceKind,
    TeachingActivity,
    TeachingInputKind,
    TeachingResponse,
    TeachingPositionSource,
    TeachingSessionPhase,
    TeachingStep,
    default_policy,
    start_session,
    submit_selection,
)
from acs.teaching_session_adapter import (
    TeachingAdapterError,
    TeachingAudience,
    accessible_teaching_summary,
    apply_teaching_action,
    project_teaching_session,
    teaching_view_to_payload,
)


class TeachingSessionAdapterTests(unittest.TestCase):
    def classroom(self) -> ClassroomSnapshot:
        return ClassroomSnapshot(
            students=(
                Student("student-1", "Anna", ConsentState.GRANTED),
                Student("student-2", "Bohdan"),
            ),
            classes=(ClassroomClass("class-1", "Class", ("group-1",)),),
            groups=(Group("group-1", "class-1", "Group"),),
            courses=(Course("course-1", "Course", ("lesson-1",)),),
            cohorts=(Cohort("cohort-1", "course-1", ("student-1", "student-2"), "group-1"),),
            lessons=(Lesson("lesson-1", "course-1", "Lesson", (), "2026-08-23T10:00:00Z"),),
        )

    def step(self, activity: TeachingActivity, **kwargs) -> TeachingStep:
        policy = kwargs.pop("policy", default_policy(activity, timer_seconds=kwargs.pop("timer_seconds", None)))
        return TeachingStep("step-1", activity, kwargs.pop("prompt", "Prompt"), policy, **kwargs)

    def plan(self, step: TeachingStep) -> LessonSession:
        return LessonSession(
            "session-1",
            "lesson-1",
            TeachingPositionSource(PositionSourceKind.START),
            (step,),
            ("student-1", "student-2"),
            "cohort-1",
        )

    def test_teacher_projection_uses_pseudonym_and_hides_internal_state(self) -> None:
        plan = self.plan(self.step(TeachingActivity.SHOW_SQUARE, target_square="e4"))
        state = submit_selection(plan, start_session(plan), "student-1", "e4", 0)
        view = project_teaching_session(plan, state, self.classroom(), audience=TeachingAudience.TEACHER)
        payload = teaching_view_to_payload(view)

        self.assertEqual(view.active_student_label, "Anna")
        self.assertEqual(view.target_square, "e4")
        self.assertEqual(view.last_response.student_label, "Anna")
        self.assertEqual(view.last_response.value, "e4")
        forbidden = {
            "session_id",
            "student_id",
            "position_fen",
            "fen",
            "source_ref",
            "plan_digest",
            "revision",
        }
        self.assertTrue(forbidden.isdisjoint(payload))
        self.assertNotIn("student-1", repr(payload))
        self.assertNotIn(Board.START, repr(payload))

    def test_student_projection_hides_answer_target_and_other_student_response(self) -> None:
        plan = self.plan(self.step(TeachingActivity.SHOW_SQUARE, target_square="e4"))
        state = submit_selection(plan, start_session(plan), "student-1", "e4", 0)
        view = project_teaching_session(
            plan,
            state,
            self.classroom(),
            audience=TeachingAudience.STUDENT,
            viewer_student_id="student-2",
        )
        payload = teaching_view_to_payload(view)

        self.assertIsNone(view.target_square)
        self.assertIsNone(view.target_piece)
        self.assertIsNone(view.last_response)
        self.assertEqual(view.active_student_label, "")
        self.assertFalse(view.viewer_is_active)
        self.assertNotIn("Anna", repr(payload))
        self.assertNotIn("student-1", repr(payload))

    def test_student_projection_can_show_only_own_response_without_raw_identity(self) -> None:
        plan = self.plan(self.step(TeachingActivity.STUDENT_RESPONDS))
        state = submit_selection(plan, start_session(plan), "student-1", "d5", 0)
        view = project_teaching_session(
            plan,
            state,
            self.classroom(),
            audience=TeachingAudience.STUDENT,
            viewer_student_id="student-1",
        )
        self.assertTrue(view.viewer_is_active)
        self.assertIsNotNone(view.last_response)
        self.assertEqual(view.last_response.student_label, "")
        self.assertEqual(view.last_response.value, "d5")
        self.assertNotIn("student-1", repr(teaching_view_to_payload(view)))

    def test_show_piece_answer_is_teacher_only(self) -> None:
        plan = self.plan(self.step(TeachingActivity.SHOW_PIECE, target_square="e4", target_piece="P"))
        state = start_session(plan)
        teacher = project_teaching_session(plan, state, self.classroom(), audience=TeachingAudience.TEACHER)
        student = project_teaching_session(
            plan,
            state,
            self.classroom(),
            audience=TeachingAudience.STUDENT,
            viewer_student_id="student-1",
        )
        self.assertEqual((teacher.target_square, teacher.target_piece), ("e4", "P"))
        self.assertEqual((student.target_square, student.target_piece), (None, None))

    def test_solution_reveal_is_exposed_only_by_canonical_policy(self) -> None:
        plan = self.plan(self.step(TeachingActivity.SOLUTION_REVEAL, solution_text="Qh7+"))
        state = start_session(plan)
        student = project_teaching_session(
            plan,
            state,
            self.classroom(),
            audience=TeachingAudience.STUDENT,
            viewer_student_id="student-1",
        )
        self.assertEqual(student.solution_text, "Qh7+")
        self.assertTrue(student.engine_visible)
        self.assertFalse(student.can_submit_move)
        self.assertFalse(student.can_submit_selection)

    def test_engine_visibility_is_audience_specific(self) -> None:
        policy = default_policy(
            TeachingActivity.TEACHER_EXPLAINS,
            engine_visibility=EngineVisibilityPolicy.VISIBLE_TO_TEACHER,
        )
        plan = self.plan(self.step(TeachingActivity.TEACHER_EXPLAINS, policy=policy))
        state = start_session(plan)
        teacher = project_teaching_session(plan, state, self.classroom(), audience=TeachingAudience.TEACHER)
        student = project_teaching_session(
            plan,
            state,
            self.classroom(),
            audience=TeachingAudience.STUDENT,
            viewer_student_id="student-1",
        )
        self.assertTrue(teacher.engine_visible)
        self.assertFalse(student.engine_visible)

    def test_student_view_requires_out_of_band_authorized_identity(self) -> None:
        plan = self.plan(self.step(TeachingActivity.STUDENT_RESPONDS))
        state = start_session(plan)
        for viewer in (None, "outsider"):
            with self.subTest(viewer=viewer):
                with self.assertRaises(TeachingAdapterError):
                    project_teaching_session(
                        plan,
                        state,
                        self.classroom(),
                        audience=TeachingAudience.STUDENT,
                        viewer_student_id=viewer,
                    )

    def test_teacher_view_rejects_irrelevant_student_identity(self) -> None:
        plan = self.plan(self.step(TeachingActivity.TEACHER_EXPLAINS))
        with self.assertRaises(TeachingAdapterError):
            project_teaching_session(
                plan,
                start_session(plan),
                self.classroom(),
                audience=TeachingAudience.TEACHER,
                viewer_student_id="student-1",
            )

    def test_forged_active_student_is_rejected_at_projection_boundary(self) -> None:
        plan = self.plan(self.step(TeachingActivity.STUDENT_RESPONDS))
        state = start_session(plan)
        forged_presentation = replace(state.presentation, active_student_id="outsider")
        forged = replace(state, active_student_id="outsider", presentation=forged_presentation)
        with self.assertRaisesRegex(TeachingAdapterError, "cannot be projected safely"):
            project_teaching_session(plan, forged, self.classroom(), audience=TeachingAudience.TEACHER)

    def test_forged_response_step_is_rejected_at_projection_boundary(self) -> None:
        plan = self.plan(self.step(TeachingActivity.STUDENT_RESPONDS))
        state = start_session(plan)
        response = TeachingResponse("student-1", "wrong-step", TeachingInputKind.SELECTION, "e4")
        projection = replace(state.presentation, active_student_id="student-1")
        forged = replace(
            state,
            active_student_id="student-1",
            presentation=projection,
            last_response=response,
        )
        with self.assertRaises(TeachingAdapterError):
            project_teaching_session(plan, forged, self.classroom(), audience=TeachingAudience.TEACHER)

    def test_forged_response_kind_is_rejected_at_projection_boundary(self) -> None:
        plan = self.plan(self.step(TeachingActivity.STUDENT_RESPONDS))
        state = start_session(plan)
        response = TeachingResponse("student-1", "step-1", TeachingInputKind.MOVE, "e4")
        projection = replace(state.presentation, active_student_id="student-1")
        forged = replace(
            state,
            active_student_id="student-1",
            presentation=projection,
            last_response=response,
        )
        with self.assertRaises(TeachingAdapterError):
            project_teaching_session(plan, forged, self.classroom(), audience=TeachingAudience.TEACHER)

    def test_student_selection_action_uses_actor_identity_not_payload_identity(self) -> None:
        plan = self.plan(self.step(TeachingActivity.STUDENT_RESPONDS))
        before = start_session(plan)
        after = apply_teaching_action(
            plan,
            before,
            "student.select",
            {"square": "e4"},
            expected_revision=0,
            actor_student_id="student-1",
        )
        self.assertEqual(after.position_fen, before.position_fen)
        self.assertEqual(after.last_response.student_id, "student-1")
        self.assertEqual(after.last_response.value, "e4")
        self.assertEqual(before.revision, 0)

    def test_student_action_rejects_payload_identity_spoof(self) -> None:
        plan = self.plan(self.step(TeachingActivity.STUDENT_RESPONDS))
        before = start_session(plan)
        with self.assertRaises(TeachingAdapterError):
            apply_teaching_action(
                plan,
                before,
                "student.select",
                {"square": "e4", "student_id": "student-2"},
                expected_revision=0,
                actor_student_id="student-1",
            )
        self.assertEqual(before.revision, 0)

    def test_student_move_action_uses_canonical_board_and_is_atomic(self) -> None:
        plan = self.plan(self.step(TeachingActivity.MAKE_MOVE))
        before = start_session(plan)
        after = apply_teaching_action(
            plan,
            before,
            "student.move",
            {"raw_text": "e4"},
            expected_revision=0,
            actor_student_id="student-1",
        )
        board = Board(Board.START)
        board.push_text("e4")
        self.assertEqual(after.position_fen, board.fen())
        self.assertEqual(before.position_fen, Board.START)
        with self.assertRaises(TeachingAdapterError):
            apply_teaching_action(
                plan,
                before,
                "student.move",
                {"raw_text": "e9"},
                expected_revision=0,
                actor_student_id="student-1",
            )
        self.assertEqual(before.position_fen, Board.START)

    def test_student_action_requires_authenticated_actor_context(self) -> None:
        plan = self.plan(self.step(TeachingActivity.STUDENT_RESPONDS))
        with self.assertRaises(TeachingAdapterError):
            apply_teaching_action(
                plan,
                start_session(plan),
                "student.select",
                {"square": "e4"},
                expected_revision=0,
            )

    def test_teacher_action_rejects_student_actor_context(self) -> None:
        plan = self.plan(self.step(TeachingActivity.TEACHER_EXPLAINS))
        with self.assertRaises(TeachingAdapterError):
            apply_teaching_action(
                plan,
                start_session(plan),
                "teacher.pointer_input",
                {"square": "e4"},
                expected_revision=0,
                actor_student_id="student-1",
            )

    def test_pointer_and_annotations_never_mutate_position(self) -> None:
        plan = self.plan(self.step(TeachingActivity.TEACHER_EXPLAINS))
        initial = start_session(plan)
        pointer = apply_teaching_action(
            plan, initial, "teacher.pointer_input", {"square": "e4"}, expected_revision=0
        )
        highlight = apply_teaching_action(
            plan,
            pointer,
            "teacher.highlight",
            {"square": "d5", "purpose": "target"},
            expected_revision=1,
        )
        arrow = apply_teaching_action(
            plan,
            highlight,
            "teacher.arrow",
            {"start_square": "d5", "end_square": "e6", "purpose": "idea"},
            expected_revision=2,
        )
        cleared = apply_teaching_action(
            plan, arrow, "teacher.clear_annotations", {}, expected_revision=3
        )
        self.assertEqual(cleared.position_fen, initial.position_fen)
        self.assertEqual(arrow.presentation.pointer.square, "e4")
        self.assertEqual(arrow.presentation.highlights[0].square, "d5")
        self.assertEqual(arrow.presentation.arrows[0].end_square, "e6")
        self.assertEqual(cleared.presentation.highlights, ())
        self.assertEqual(cleared.presentation.arrows, ())

    def test_pause_resume_and_advance_delegate_to_canonical_session(self) -> None:
        steps = (
            TeachingStep("step-1", TeachingActivity.TEACHER_EXPLAINS, "Explain", default_policy(TeachingActivity.TEACHER_EXPLAINS)),
            TeachingStep("step-2", TeachingActivity.MAKE_MOVE, "Move", default_policy(TeachingActivity.MAKE_MOVE)),
        )
        plan = LessonSession(
            "session-1",
            "lesson-1",
            TeachingPositionSource(PositionSourceKind.START),
            steps,
            ("student-1", "student-2"),
            "cohort-1",
        )
        active = start_session(plan)
        paused = apply_teaching_action(plan, active, "teaching.pause", {}, expected_revision=0)
        self.assertEqual(paused.phase, TeachingSessionPhase.PAUSED)
        resumed = apply_teaching_action(plan, paused, "teaching.resume", {}, expected_revision=1)
        self.assertEqual(resumed.phase, TeachingSessionPhase.ACTIVE)
        second = apply_teaching_action(plan, resumed, "teaching.advance", {}, expected_revision=2)
        self.assertEqual(second.step_index, 1)
        self.assertEqual(second.position_fen, active.position_fen)

    def test_tick_action_requires_exact_payload_and_preserves_position(self) -> None:
        plan = self.plan(self.step(TeachingActivity.STUDENT_RESPONDS, timer_seconds=5))
        before = start_session(plan)
        after = apply_teaching_action(
            plan,
            before,
            "teaching.tick",
            {"elapsed_seconds": 2},
            expected_revision=0,
        )
        self.assertEqual(after.remaining_seconds, 3)
        self.assertEqual(after.position_fen, before.position_fen)
        with self.assertRaises(TeachingAdapterError):
            apply_teaching_action(
                plan,
                before,
                "teaching.tick",
                {"elapsed_seconds": True},
                expected_revision=0,
            )

    def test_unknown_actions_and_extra_fields_fail_closed(self) -> None:
        plan = self.plan(self.step(TeachingActivity.TEACHER_EXPLAINS))
        state = start_session(plan)
        with self.assertRaises(TeachingAdapterError):
            apply_teaching_action(plan, state, "debug.dump_state", {}, expected_revision=0)
        with self.assertRaises(TeachingAdapterError):
            apply_teaching_action(
                plan,
                state,
                "teacher.pointer_input",
                {"square": "e4", "fen": Board.START},
                expected_revision=0,
            )
        self.assertEqual(state.revision, 0)

    def test_payload_is_closed_world_and_not_dataclass_dump(self) -> None:
        plan = self.plan(self.step(TeachingActivity.SHOW_SQUARE, target_square="e4"))
        view = project_teaching_session(plan, start_session(plan), self.classroom(), audience=TeachingAudience.TEACHER)
        payload = teaching_view_to_payload(view)
        self.assertEqual(set(payload), set(asdict(view)))
        self.assertNotIn("audience", repr(view.last_response) if view.last_response else "")
        self.assertNotIn("plan_digest", payload)
        self.assertNotIn("position_fen", payload)

    def test_accessible_summary_is_role_safe_and_localized(self) -> None:
        plan = self.plan(self.step(TeachingActivity.SHOW_SQUARE, target_square="e4", prompt="Find the square"))
        state = start_session(plan)
        teacher = project_teaching_session(plan, state, self.classroom(), audience=TeachingAudience.TEACHER)
        student = project_teaching_session(
            plan,
            state,
            self.classroom(),
            audience=TeachingAudience.STUDENT,
            viewer_student_id="student-1",
        )
        uk_teacher = accessible_teaching_summary(teacher, language="uk")
        en_student = accessible_teaching_summary(student, language="en")
        self.assertIn("Цільова клітинка: e4", uk_teacher)
        self.assertNotIn("Target square: e4", en_student)
        self.assertNotIn("student-1", uk_teacher + en_student)
        with self.assertRaises(TeachingAdapterError):
            accessible_teaching_summary(student, language="de")

    def test_projection_is_pure_and_deterministic(self) -> None:
        plan = self.plan(self.step(TeachingActivity.STUDENT_RESPONDS))
        state = start_session(plan)
        before = state.to_json()
        first = project_teaching_session(
            plan,
            state,
            self.classroom(),
            audience=TeachingAudience.STUDENT,
            viewer_student_id="student-1",
        )
        second = project_teaching_session(
            plan,
            state,
            self.classroom(),
            audience=TeachingAudience.STUDENT,
            viewer_student_id="student-1",
        )
        self.assertEqual(first, second)
        self.assertEqual(state.to_json(), before)


if __name__ == "__main__":
    unittest.main()
