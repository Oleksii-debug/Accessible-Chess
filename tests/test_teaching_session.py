from __future__ import annotations

import json
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
    AnnotationCommand,
    AnnotationOperation,
    BoardPermissionState,
    EngineVisibilityPolicy,
)
from acs.teaching_session import (
    MAX_TIMER_SECONDS,
    LessonSession,
    PositionSourceKind,
    TeachingActivity,
    TeachingInputKind,
    TeachingInputPolicy,
    TeachingPositionSource,
    TeachingSessionError,
    TeachingSessionPhase,
    TeachingSessionState,
    TeachingStep,
    advance_step,
    apply_annotation,
    current_step,
    default_policy,
    pause_session,
    resume_session,
    set_teacher_pointer,
    start_session,
    submit_move,
    submit_selection,
    tick_timer,
    validate_lesson_session_scope,
)


class TeachingSessionDomainTests(unittest.TestCase):
    def step(self, step_id: str, activity: TeachingActivity, **kwargs) -> TeachingStep:
        policy = kwargs.pop("policy", default_policy(activity, timer_seconds=kwargs.pop("timer_seconds", None)))
        return TeachingStep(step_id, activity, kwargs.pop("prompt", step_id), policy, **kwargs)

    def plan(self, *steps: TeachingStep, source: TeachingPositionSource | None = None) -> LessonSession:
        return LessonSession(
            session_id="session-1",
            lesson_id="lesson-1",
            source=source or TeachingPositionSource(PositionSourceKind.START),
            steps=tuple(steps) or (self.step("s1", TeachingActivity.TEACHER_EXPLAINS),),
            student_ids=("student-1", "student-2"),
            cohort_id="cohort-1",
        )

    def classroom(self) -> ClassroomSnapshot:
        return ClassroomSnapshot(
            students=(
                Student("student-1", "A", ConsentState.GRANTED),
                Student("student-2", "B"),
            ),
            classes=(ClassroomClass("class-1", "Class", ("group-1",)),),
            groups=(Group("group-1", "class-1", "Group"),),
            courses=(Course("course-1", "Course", ("lesson-1",)),),
            cohorts=(Cohort("cohort-1", "course-1", ("student-1", "student-2"), "group-1"),),
            lessons=(Lesson("lesson-1", "course-1", "Lesson", (), "2026-08-22T19:00:00Z"),),
        )

    def test_default_policies_cover_every_teaching_activity(self) -> None:
        expected = {
            TeachingActivity.TEACHER_EXPLAINS: (TeachingInputKind.NONE, BoardPermissionState.LOCKED),
            TeachingActivity.STUDENT_RESPONDS: (TeachingInputKind.SELECTION, BoardPermissionState.SELECT_ONLY),
            TeachingActivity.SHOW_SQUARE: (TeachingInputKind.SELECTION, BoardPermissionState.SELECT_ONLY),
            TeachingActivity.SHOW_PIECE: (TeachingInputKind.SELECTION, BoardPermissionState.SELECT_ONLY),
            TeachingActivity.MAKE_MOVE: (TeachingInputKind.MOVE, BoardPermissionState.MOVE_ALLOWED),
            TeachingActivity.WHERE_CAN_PIECE_MOVE: (TeachingInputKind.SELECTION, BoardPermissionState.SELECT_ONLY),
            TeachingActivity.ATTACK_DEFENCE: (TeachingInputKind.SELECTION, BoardPermissionState.SELECT_ONLY),
            TeachingActivity.SOLUTION_REVEAL: (TeachingInputKind.NONE, BoardPermissionState.LOCKED),
        }
        self.assertEqual(set(expected), set(TeachingActivity))
        for activity, (input_kind, permission) in expected.items():
            with self.subTest(activity=activity):
                policy = default_policy(activity)
                self.assertEqual(policy.input_kind, input_kind)
                self.assertEqual(policy.board_permission, permission)
                self.assertEqual(policy.solution_visible, activity is TeachingActivity.SOLUTION_REVEAL)
        self.assertEqual(
            default_policy(TeachingActivity.SOLUTION_REVEAL).engine_visibility,
            EngineVisibilityPolicy.VISIBLE_TO_STUDENT,
        )

    def test_policy_rejects_inconsistent_permission_and_scalar_coercion(self) -> None:
        with self.assertRaises(TeachingSessionError):
            TeachingInputPolicy(TeachingInputKind.MOVE, BoardPermissionState.SELECT_ONLY)
        with self.assertRaises(TeachingSessionError):
            TeachingInputPolicy(TeachingInputKind.NONE, BoardPermissionState.LOCKED, timer_seconds=True)
        with self.assertRaises(TeachingSessionError):
            default_policy(TeachingActivity.MAKE_MOVE, timer_seconds=MAX_TIMER_SECONDS + 1)

    def test_position_sources_cover_start_fen_pgn_book_and_database_without_second_core(self) -> None:
        four_field = "8/8/8/8/8/8/4K3/7k w - -"
        canonical = Board(four_field).fen()
        sources = (
            TeachingPositionSource(PositionSourceKind.START),
            TeachingPositionSource(PositionSourceKind.FEN, four_field),
            TeachingPositionSource(PositionSourceKind.PGN, four_field, "pgn-1", 3),
            TeachingPositionSource(PositionSourceKind.BOOK, four_field, "book-position-7"),
            TeachingPositionSource(PositionSourceKind.DATABASE, four_field, "database-position-9"),
        )
        self.assertEqual(sources[0].fen, Board.START)
        self.assertTrue(all(source.fen == canonical for source in sources[1:]))
        with self.assertRaises(TeachingSessionError):
            TeachingPositionSource(PositionSourceKind.PGN, four_field, "pgn-1")
        with self.assertRaises(TeachingSessionError):
            TeachingPositionSource(PositionSourceKind.START, four_field)
        with self.assertRaises(TeachingSessionError):
            TeachingPositionSource(PositionSourceKind.FEN, "")

    def test_step_shapes_are_activity_specific_and_fail_closed(self) -> None:
        self.step("a", TeachingActivity.SHOW_SQUARE, target_square="e4")
        self.step("b", TeachingActivity.SHOW_PIECE, target_square="e4", target_piece="P")
        self.step("c", TeachingActivity.WHERE_CAN_PIECE_MOVE, target_square="g1")
        self.step("d", TeachingActivity.ATTACK_DEFENCE, target_square="e4")
        self.step(
            "e",
            TeachingActivity.SOLUTION_REVEAL,
            solution_text="The tactical point is Qh7+.",
        )
        with self.assertRaises(TeachingSessionError):
            self.step("bad", TeachingActivity.SHOW_SQUARE)
        with self.assertRaises(TeachingSessionError):
            self.step("bad", TeachingActivity.SHOW_PIECE, target_square="e4")
        with self.assertRaises(TeachingSessionError):
            self.step("bad", TeachingActivity.MAKE_MOVE, target_square="e4")
        with self.assertRaises(TeachingSessionError):
            TeachingStep(
                "bad",
                TeachingActivity.MAKE_MOVE,
                "Move",
                default_policy(TeachingActivity.STUDENT_RESPONDS),
            )

    def test_lesson_session_requires_unique_bounded_steps_and_students(self) -> None:
        step = self.step("s1", TeachingActivity.TEACHER_EXPLAINS)
        with self.assertRaises(TeachingSessionError):
            LessonSession("session-1", "lesson-1", TeachingPositionSource(PositionSourceKind.START), ())
        with self.assertRaises(TeachingSessionError):
            LessonSession(
                "session-1",
                "lesson-1",
                TeachingPositionSource(PositionSourceKind.START),
                (step, step),
            )
        with self.assertRaises(TeachingSessionError):
            LessonSession(
                "session-1",
                "lesson-1",
                TeachingPositionSource(PositionSourceKind.START),
                (step,),
                ("student-1", "student-1"),
            )

    def test_lesson_session_json_is_deterministic_tamper_evident_and_closed_world(self) -> None:
        plan = self.plan(
            self.step("s1", TeachingActivity.SHOW_SQUARE, target_square="e4", timer_seconds=30),
            self.step("s2", TeachingActivity.MAKE_MOVE),
        )
        text = plan.to_json()
        self.assertEqual(LessonSession.from_json(text), plan)
        self.assertEqual(LessonSession.from_json(text).to_json(), text)
        record = plan.to_record()
        record["lesson_id"] = "lesson-other"
        with self.assertRaises(TeachingSessionError):
            LessonSession.from_record(record)
        record = plan.to_record()
        record["unknown"] = 1
        with self.assertRaises(TeachingSessionError):
            LessonSession.from_record(record)
        duplicate = text[:-1] + ',"version":1}'
        with self.assertRaises(TeachingSessionError):
            LessonSession.from_json(duplicate)

    def test_scope_validation_connects_plan_to_classroom_without_storage_ownership(self) -> None:
        plan = self.plan(self.step("s1", TeachingActivity.TEACHER_EXPLAINS))
        validate_lesson_session_scope(plan, self.classroom())
        wrong_course = ClassroomSnapshot(
            students=self.classroom().students,
            classes=self.classroom().classes,
            groups=self.classroom().groups,
            courses=(
                Course("course-1", "Course", ("lesson-1",)),
                Course("course-2", "Other", ()),
            ),
            cohorts=(Cohort("cohort-1", "course-2", ("student-1", "student-2"), "group-1"),),
            lessons=self.classroom().lessons,
        )
        with self.assertRaises(TeachingSessionError):
            validate_lesson_session_scope(plan, wrong_course)

    def test_start_uses_same_canonical_position_and_step_policy(self) -> None:
        fen = "8/8/8/8/8/8/4K3/7k w - -"
        step = self.step("s1", TeachingActivity.SHOW_SQUARE, target_square="e2", timer_seconds=17)
        state = start_session(self.plan(step, source=TeachingPositionSource(PositionSourceKind.FEN, fen)))
        self.assertEqual(state.position_fen, Board(fen).fen())
        self.assertEqual(state.presentation.board_permission, BoardPermissionState.SELECT_ONLY)
        self.assertEqual(state.presentation.engine_visibility, EngineVisibilityPolicy.HIDDEN)
        self.assertEqual(state.remaining_seconds, 17)
        self.assertEqual(state.phase, TeachingSessionPhase.ACTIVE)

    def test_selection_is_presentation_only_and_records_explicit_student_response(self) -> None:
        plan = self.plan(self.step("s1", TeachingActivity.SHOW_SQUARE, target_square="e4"))
        before = start_session(plan)
        after = submit_selection(plan, before, "student-1", "e4", 0)
        self.assertEqual(after.position_fen, before.position_fen)
        self.assertEqual(after.last_response.value, "e4")
        self.assertEqual(after.active_student_id, "student-1")
        self.assertEqual(len(after.presentation.student_pointer_history), 1)
        self.assertEqual(after.revision, 1)
        with self.assertRaises(TeachingSessionError):
            submit_selection(plan, before, "outsider", "e4", 0)
        self.assertEqual(before.revision, 0)
        self.assertIsNone(before.last_response)

    def test_student_move_uses_chesscore_and_invalid_move_is_atomic(self) -> None:
        plan = self.plan(self.step("s1", TeachingActivity.MAKE_MOVE))
        before = start_session(plan)
        after = submit_move(plan, before, "student-1", "e4", 0)
        board = Board(Board.START)
        san = board.push_text("e4")
        self.assertEqual(san, "e4")
        self.assertEqual(after.position_fen, board.fen())
        self.assertEqual(after.last_response.value, "e4")
        with self.assertRaises(TeachingSessionError):
            submit_move(plan, before, "student-1", "e9", 0)
        self.assertEqual(before.position_fen, Board.START)
        self.assertEqual(before.revision, 0)

    def test_input_mode_separation_prevents_selection_move_confusion(self) -> None:
        selection_plan = self.plan(self.step("s1", TeachingActivity.STUDENT_RESPONDS))
        move_plan = self.plan(self.step("s1", TeachingActivity.MAKE_MOVE))
        with self.assertRaises(TeachingSessionError):
            submit_move(selection_plan, start_session(selection_plan), "student-1", "e4", 0)
        with self.assertRaises(TeachingSessionError):
            submit_selection(move_plan, start_session(move_plan), "student-1", "e4", 0)

    def test_teacher_pointer_and_annotations_never_mutate_position(self) -> None:
        plan = self.plan(self.step("s1", TeachingActivity.TEACHER_EXPLAINS))
        state = start_session(plan)
        pointed = set_teacher_pointer(plan, state, "e4", 0)
        highlighted = apply_annotation(
            plan,
            pointed,
            AnnotationCommand(AnnotationOperation.SET_HIGHLIGHT, start_square="d5", tag="focus"),
            1,
        )
        arrowed = apply_annotation(
            plan,
            highlighted,
            AnnotationCommand(AnnotationOperation.ADD_ARROW, start_square="d5", end_square="e6", tag="line"),
            2,
        )
        self.assertEqual(arrowed.position_fen, state.position_fen)
        self.assertEqual(arrowed.presentation.pointer.square, "e4")
        self.assertEqual(arrowed.presentation.highlights[0].square, "d5")
        self.assertEqual(arrowed.presentation.arrows[0].end_square, "e6")
        cleared = apply_annotation(
            plan,
            arrowed,
            AnnotationCommand(AnnotationOperation.CLEAR),
            3,
        )
        self.assertEqual(cleared.position_fen, state.position_fen)
        self.assertEqual(cleared.presentation.highlights, ())
        self.assertEqual(cleared.presentation.arrows, ())

    def test_pause_resume_lock_student_board_without_changing_position(self) -> None:
        plan = self.plan(self.step("s1", TeachingActivity.MAKE_MOVE))
        active = start_session(plan)
        paused = pause_session(plan, active, 0)
        self.assertEqual(paused.phase, TeachingSessionPhase.PAUSED)
        self.assertEqual(paused.presentation.board_permission, BoardPermissionState.LOCKED)
        self.assertEqual(paused.presentation.engine_visibility, EngineVisibilityPolicy.HIDDEN)
        self.assertEqual(paused.position_fen, active.position_fen)
        with self.assertRaises(TeachingSessionError):
            submit_move(plan, paused, "student-1", "e4", 1)
        resumed = resume_session(plan, paused, 1)
        self.assertEqual(resumed.phase, TeachingSessionPhase.ACTIVE)
        self.assertEqual(resumed.presentation.board_permission, BoardPermissionState.MOVE_ALLOWED)
        self.assertEqual(resumed.position_fen, active.position_fen)

    def test_step_advance_changes_policy_not_position_and_completion_locks_board(self) -> None:
        plan = self.plan(
            self.step("s1", TeachingActivity.TEACHER_EXPLAINS),
            self.step("s2", TeachingActivity.MAKE_MOVE, timer_seconds=20),
        )
        first = start_session(plan)
        second = advance_step(plan, first, 0)
        self.assertEqual(second.step_index, 1)
        self.assertEqual(current_step(plan, second).step_id, "s2")
        self.assertEqual(second.position_fen, first.position_fen)
        self.assertEqual(second.presentation.board_permission, BoardPermissionState.MOVE_ALLOWED)
        self.assertEqual(second.remaining_seconds, 20)
        complete = advance_step(plan, second, 1)
        self.assertEqual(complete.phase, TeachingSessionPhase.COMPLETED)
        self.assertEqual(complete.position_fen, first.position_fen)
        self.assertEqual(complete.presentation.board_permission, BoardPermissionState.LOCKED)
        self.assertIsNone(complete.remaining_seconds)

    def test_timer_is_optional_bounded_and_never_invents_chess_outcome(self) -> None:
        timed_plan = self.plan(self.step("s1", TeachingActivity.STUDENT_RESPONDS, timer_seconds=5))
        state = start_session(timed_plan)
        state = tick_timer(timed_plan, state, 3, 0)
        self.assertEqual(state.remaining_seconds, 2)
        expired = tick_timer(timed_plan, state, 9, 1)
        self.assertEqual(expired.remaining_seconds, 0)
        self.assertEqual(expired.phase, TeachingSessionPhase.ACTIVE)
        self.assertEqual(expired.position_fen, Board.START)
        untimed = self.plan(self.step("s1", TeachingActivity.TEACHER_EXPLAINS))
        with self.assertRaises(TeachingSessionError):
            tick_timer(untimed, start_session(untimed), 1, 0)

    def test_stale_revision_and_wrong_plan_fail_without_partial_state(self) -> None:
        plan = self.plan(self.step("s1", TeachingActivity.SHOW_SQUARE, target_square="e4"))
        state = start_session(plan)
        with self.assertRaises(TeachingSessionError):
            submit_selection(plan, state, "student-1", "e4", 7)
        other = LessonSession(
            "session-1",
            "lesson-1",
            plan.source,
            (self.step("different", TeachingActivity.TEACHER_EXPLAINS),),
            plan.student_ids,
            plan.cohort_id,
        )
        with self.assertRaises(TeachingSessionError):
            current_step(other, state)
        self.assertEqual(state.revision, 0)
        self.assertEqual(state.position_fen, Board.START)

    def test_state_snapshot_round_trip_is_exact_and_tamper_evident(self) -> None:
        plan = self.plan(self.step("s1", TeachingActivity.MAKE_MOVE, timer_seconds=30))
        state = submit_move(plan, start_session(plan), "student-1", "e4", 0)
        text = state.to_json()
        restored = TeachingSessionState.from_json(text)
        self.assertEqual(restored, state)
        self.assertEqual(restored.to_json(), text)
        record = state.to_record()
        record["position_fen"] = Board.START
        with self.assertRaises(TeachingSessionError):
            TeachingSessionState.from_record(record)
        record = state.to_record()
        record["revision"] = True
        with self.assertRaises(TeachingSessionError):
            TeachingSessionState.from_record(record)

    def test_hostile_json_surrogate_huge_integer_and_deep_nesting_fail_as_domain_errors(self) -> None:
        plan = self.plan(self.step("s1", TeachingActivity.TEACHER_EXPLAINS))
        for text in (
            "\ud800",
            '{"version":' + "9" * 5000 + '}',
            "[" * 1500 + "0" + "]" * 1500,
        ):
            with self.subTest(length=len(text)):
                with self.assertRaises(TeachingSessionError):
                    LessonSession.from_json(text)
        record = plan.to_record()
        record["steps"][0]["prompt"] = "bad\ud800"
        escaped = json.dumps(record, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
        with self.assertRaises(TeachingSessionError):
            LessonSession.from_json(escaped)

    def test_valid_unicode_prompts_and_solutions_round_trip(self) -> None:
        plan = self.plan(
            self.step(
                "s1",
                TeachingActivity.SOLUTION_REVEAL,
                prompt="Розв’язання ♞",
                solution_text="Кінь іде на f7.",
            )
        )
        self.assertEqual(LessonSession.from_json(plan.to_json()), plan)


if __name__ == "__main__":
    unittest.main()
