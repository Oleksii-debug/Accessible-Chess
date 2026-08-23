from __future__ import annotations

from dataclasses import replace
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
from acs.interaction_contracts import (
    EngineVisibilityPolicy,
    StudentHoverEvent,
    StudentSelectionEvent,
)
from acs.teaching_reverse_channel import (
    TeachingReverseChannelError,
    StudentPointerKind,
    accessible_student_pointer_summary,
    apply_student_hover_action,
    pointer_history_to_payload,
    project_teacher_pointer_history,
    record_student_hover,
)
from acs.teaching_session import (
    LessonSession,
    PositionSourceKind,
    TeachingActivity,
    TeachingPositionSource,
    TeachingStep,
    default_policy,
    pause_session,
    start_session,
    submit_move,
    submit_selection,
)


class TeachingReverseChannelTests(unittest.TestCase):
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

    def plan(
        self,
        activity: TeachingActivity,
        *,
        engine_visibility: EngineVisibilityPolicy | None = None,
    ) -> LessonSession:
        policy = default_policy(activity, engine_visibility=engine_visibility)
        step = TeachingStep("step-1", activity, "Prompt", policy)
        return LessonSession(
            "session-1",
            "lesson-1",
            TeachingPositionSource(PositionSourceKind.START),
            (step,),
            ("student-1", "student-2"),
            "cohort-1",
        )

    def test_hover_is_allowed_on_locked_teacher_board_and_never_mutates_position(self) -> None:
        plan = self.plan(TeachingActivity.TEACHER_EXPLAINS)
        before = start_session(plan)
        after = apply_student_hover_action(
            plan,
            before,
            self.classroom(),
            {"square": "g1"},
            expected_revision=0,
            actor_student_id="student-1",
        )

        self.assertEqual(before.position_fen, Board.START)
        self.assertEqual(after.position_fen, before.position_fen)
        self.assertEqual(after.presentation.board_permission, before.presentation.board_permission)
        self.assertEqual(after.presentation.engine_visibility, before.presentation.engine_visibility)
        self.assertIsNone(after.active_student_id)
        self.assertIsNone(after.last_response)
        self.assertEqual(after.revision, 1)
        self.assertEqual(len(after.presentation.student_pointer_history), 1)
        event = after.presentation.student_pointer_history[0]
        self.assertIs(type(event), StudentHoverEvent)
        self.assertEqual((event.square, event.piece, event.student_id, event.sequence), ("g1", "N", "student-1", 1))

    def test_browser_cannot_spoof_student_identity_or_piece(self) -> None:
        plan = self.plan(TeachingActivity.TEACHER_EXPLAINS)
        before = start_session(plan)
        for payload in (
            {"square": "e4", "student_id": "student-2"},
            {"square": "e4", "piece": "Q"},
            {"square": "E4"},
            {"square": " e4"},
        ):
            with self.subTest(payload=payload):
                with self.assertRaises(TeachingReverseChannelError):
                    apply_student_hover_action(
                        plan,
                        before,
                        self.classroom(),
                        payload,
                        expected_revision=0,
                        actor_student_id="student-1",
                    )
        self.assertEqual(before.revision, 0)
        self.assertEqual(before.presentation.student_pointer_history, ())

    def test_hover_actor_must_be_out_of_band_authorized_student(self) -> None:
        plan = self.plan(TeachingActivity.TEACHER_EXPLAINS)
        before = start_session(plan)
        for actor in (None, "outsider"):
            with self.subTest(actor=actor):
                with self.assertRaises(TeachingReverseChannelError):
                    apply_student_hover_action(
                        plan,
                        before,
                        self.classroom(),
                        {"square": "e4"},
                        expected_revision=0,
                        actor_student_id=actor,
                    )

    def test_hover_does_not_become_move_even_when_move_mode_is_enabled(self) -> None:
        plan = self.plan(TeachingActivity.MAKE_MOVE)
        before = start_session(plan)
        hovered = record_student_hover(
            plan,
            before,
            self.classroom(),
            actor_student_id="student-1",
            square="e4",
            expected_revision=0,
        )
        self.assertEqual(hovered.position_fen, Board.START)
        self.assertIsNone(hovered.last_response)

        moved = submit_move(plan, hovered, "student-1", "e4", 1)
        self.assertNotEqual(moved.position_fen, Board.START)
        self.assertEqual(moved.last_response.value, "e4")

    def test_hover_and_selection_are_distinct_ordered_events(self) -> None:
        plan = self.plan(TeachingActivity.STUDENT_RESPONDS)
        before = start_session(plan)
        hovered = record_student_hover(
            plan,
            before,
            self.classroom(),
            actor_student_id="student-1",
            square="g1",
            expected_revision=0,
        )
        selected = submit_selection(plan, hovered, "student-1", "e4", 1)
        events = selected.presentation.student_pointer_history

        self.assertEqual(tuple(type(item) for item in events), (StudentHoverEvent, StudentSelectionEvent))
        self.assertEqual(tuple(item.sequence for item in events), (1, 2))
        self.assertEqual(tuple(item.square for item in events), ("g1", "e4"))
        self.assertEqual(selected.position_fen, before.position_fen)
        self.assertEqual(selected.last_response.value, "e4")

    def test_hover_uses_session_revision_cas_and_stale_attempt_is_atomic(self) -> None:
        plan = self.plan(TeachingActivity.TEACHER_EXPLAINS)
        before = start_session(plan)
        with self.assertRaisesRegex(TeachingReverseChannelError, "stale"):
            record_student_hover(
                plan,
                before,
                self.classroom(),
                actor_student_id="student-1",
                square="e4",
                expected_revision=1,
            )
        self.assertEqual(before.revision, 0)
        self.assertEqual(before.presentation.student_pointer_history, ())
        self.assertEqual(before.position_fen, Board.START)

    def test_hover_is_rejected_while_paused_without_partial_state(self) -> None:
        plan = self.plan(TeachingActivity.TEACHER_EXPLAINS)
        active = start_session(plan)
        paused = pause_session(plan, active, 0)
        with self.assertRaises(TeachingReverseChannelError):
            record_student_hover(
                plan,
                paused,
                self.classroom(),
                actor_student_id="student-1",
                square="e4",
                expected_revision=1,
            )
        self.assertEqual(paused.presentation.student_pointer_history, ())
        self.assertEqual(paused.position_fen, Board.START)

    def test_hover_preserves_teacher_only_engine_visibility_policy(self) -> None:
        plan = self.plan(
            TeachingActivity.TEACHER_EXPLAINS,
            engine_visibility=EngineVisibilityPolicy.VISIBLE_TO_TEACHER,
        )
        before = start_session(plan)
        after = record_student_hover(
            plan,
            before,
            self.classroom(),
            actor_student_id="student-2",
            square="d7",
            expected_revision=0,
        )
        self.assertIs(after.presentation.engine_visibility, EngineVisibilityPolicy.VISIBLE_TO_TEACHER)
        self.assertEqual(after.position_fen, before.position_fen)

    def test_teacher_history_projection_is_ordered_pseudonymized_and_closed_world(self) -> None:
        plan = self.plan(TeachingActivity.TEACHER_EXPLAINS)
        state = start_session(plan)
        state = record_student_hover(
            plan,
            state,
            self.classroom(),
            actor_student_id="student-1",
            square="g1",
            expected_revision=0,
        )
        state = record_student_hover(
            plan,
            state,
            self.classroom(),
            actor_student_id="student-2",
            square="d7",
            expected_revision=1,
        )
        items = project_teacher_pointer_history(plan, state, self.classroom())
        payload = pointer_history_to_payload(items)

        self.assertEqual([item.student_label for item in items], ["Anna", "Bohdan"])
        self.assertEqual([item.kind for item in items], [StudentPointerKind.HOVER, StudentPointerKind.HOVER])
        self.assertEqual([item.square for item in items], ["g1", "d7"])
        self.assertEqual([item.piece_symbol for item in items], ["N", "p"])
        self.assertEqual([item.sequence for item in items], [1, 2])
        self.assertNotIn("student-1", repr(payload))
        self.assertNotIn("student-2", repr(payload))
        self.assertNotIn("position_fen", repr(payload))
        self.assertEqual(
            set(payload[0]),
            {"kind", "student_label", "square", "piece_symbol", "sequence"},
        )

    def test_projection_limit_keeps_latest_events_in_original_order(self) -> None:
        plan = self.plan(TeachingActivity.TEACHER_EXPLAINS)
        state = start_session(plan)
        for revision, square in enumerate(("a2", "b2", "c2")):
            state = record_student_hover(
                plan,
                state,
                self.classroom(),
                actor_student_id="student-1",
                square=square,
                expected_revision=revision,
            )
        latest = project_teacher_pointer_history(plan, state, self.classroom(), limit=2)
        self.assertEqual(tuple(item.square for item in latest), ("b2", "c2"))

    def test_projection_rejects_forged_nonmonotonic_or_anonymous_history(self) -> None:
        plan = self.plan(TeachingActivity.TEACHER_EXPLAINS)
        state = start_session(plan)
        bad_histories = (
            (
                StudentHoverEvent("e4", student_id="student-1", sequence=2),
                StudentHoverEvent("d4", student_id="student-2", sequence=1),
            ),
            (StudentHoverEvent("e4", sequence=1),),
        )
        for history in bad_histories:
            with self.subTest(history=history):
                forged = replace(state, presentation=replace(state.presentation, student_pointer_history=history))
                with self.assertRaises(TeachingReverseChannelError):
                    project_teacher_pointer_history(plan, forged, self.classroom())

    def test_history_resource_bound_fails_closed_instead_of_dropping_events(self) -> None:
        plan = self.plan(TeachingActivity.TEACHER_EXPLAINS)
        state = start_session(plan)
        history = tuple(
            StudentHoverEvent("e4", student_id="student-1", sequence=index)
            for index in range(1, 257)
        )
        bounded = replace(
            state,
            presentation=replace(state.presentation, student_pointer_history=history),
            revision=256,
        )
        with self.assertRaises(TeachingReverseChannelError):
            record_student_hover(
                plan,
                bounded,
                self.classroom(),
                actor_student_id="student-1",
                square="d4",
                expected_revision=256,
            )
        self.assertEqual(len(bounded.presentation.student_pointer_history), 256)
        self.assertEqual(bounded.position_fen, Board.START)

    def test_accessible_event_summary_is_concise_localized_and_role_safe(self) -> None:
        plan = self.plan(TeachingActivity.TEACHER_EXPLAINS)
        state = record_student_hover(
            plan,
            start_session(plan),
            self.classroom(),
            actor_student_id="student-1",
            square="g1",
            expected_revision=0,
        )
        item = project_teacher_pointer_history(plan, state, self.classroom())[0]
        self.assertEqual(
            accessible_student_pointer_summary(item, language="uk"),
            "Учень Anna показує: g1, білий кінь.",
        )
        self.assertEqual(
            accessible_student_pointer_summary(item, language="en"),
            "Student Anna points to: g1, white knight.",
        )
        for text in (
            accessible_student_pointer_summary(item, language="uk"),
            accessible_student_pointer_summary(item, language="en"),
        ):
            self.assertNotIn("student-1", text)
            self.assertNotIn(Board.START, text)


if __name__ == "__main__":
    unittest.main()
