from dataclasses import replace
import unittest

from acs.chesscore import Board
from acs.interaction_contracts import (
    AnnotationCommand,
    AnnotationOperation,
    SquareHighlight,
    TeacherPointerState,
    VisualArrow,
)
from acs.teaching_pointer_actions import (
    DEFAULT_TEACHER_ANNOTATION_PURPOSE,
    TeachingPointerActionError,
    apply_teacher_annotation,
    clear_teacher_pointer,
    commit_teacher_pointer_input,
)
from acs.teaching_session import (
    LessonSession,
    PositionSourceKind,
    TeachingActivity,
    TeachingPositionSource,
    TeachingStep,
    advance_step,
    default_policy,
    start_session,
)
from acs.teaching_visual_board import LEGAL_MOVE_HIGHLIGHT_PURPOSE


class TeachingPointerActionTests(unittest.TestCase):
    def plan(self) -> LessonSession:
        activity = TeachingActivity.TEACHER_EXPLAINS
        return LessonSession(
            "session-pointer",
            "lesson-pointer",
            TeachingPositionSource(PositionSourceKind.START),
            (TeachingStep("step-1", activity, "Explain", default_policy(activity)),),
            ("student-1",),
        )

    def test_typed_square_commits_immediately_with_clear_and_keep_focus_contract(self) -> None:
        plan = self.plan()
        before = start_session(plan)
        after, commit = commit_teacher_pointer_input(
            plan,
            before,
            " F3 ",
            expected_revision=0,
        )
        self.assertEqual(commit.square, "f3")
        self.assertTrue(commit.clear_input)
        self.assertTrue(commit.keep_focus)
        self.assertEqual(after.presentation.pointer.square, "f3")
        self.assertEqual(after.position_fen, Board.START)
        self.assertEqual(after.revision, 1)
        self.assertIsNone(after.last_response)
        self.assertIsNone(after.active_student_id)

    def test_next_coordinate_replaces_pointer_but_preserves_manual_overlays(self) -> None:
        plan = self.plan()
        state = start_session(plan)
        state = replace(
            state,
            presentation=replace(
                state.presentation,
                pointer=TeacherPointerState("a1"),
                highlights=(SquareHighlight("d4", "teacher"),),
                arrows=(VisualArrow("e2", "e4", "plan"),),
            ),
        )
        updated, commit = commit_teacher_pointer_input(
            plan,
            state,
            "c7",
            expected_revision=0,
        )
        self.assertEqual(commit.square, "c7")
        self.assertEqual(updated.presentation.pointer.square, "c7")
        self.assertEqual(updated.presentation.highlights, state.presentation.highlights)
        self.assertEqual(updated.presentation.arrows, state.presentation.arrows)
        self.assertEqual(updated.position_fen, state.position_fen)

    def test_invalid_pointer_input_is_atomic(self) -> None:
        plan = self.plan()
        before = start_session(plan)
        for value in ("z9", "e", "", 12, None):
            with self.subTest(value=value):
                with self.assertRaises(TeachingPointerActionError):
                    commit_teacher_pointer_input(
                        plan,
                        before,
                        value,
                        expected_revision=0,
                    )
        self.assertIsNone(before.presentation.pointer.square)
        self.assertEqual(before.revision, 0)
        self.assertEqual(before.position_fen, Board.START)

    def test_student_identity_stale_revision_and_completed_session_fail_closed(self) -> None:
        plan = self.plan()
        before = start_session(plan)
        with self.assertRaisesRegex(TeachingPointerActionError, "student identity"):
            commit_teacher_pointer_input(
                plan,
                before,
                "e4",
                expected_revision=0,
                actor_student_id="student-1",
            )
        with self.assertRaisesRegex(TeachingPointerActionError, "stale"):
            commit_teacher_pointer_input(plan, before, "e4", expected_revision=1)
        completed = advance_step(plan, before, 0)
        with self.assertRaisesRegex(TeachingPointerActionError, "completed"):
            commit_teacher_pointer_input(plan, completed, "e4", expected_revision=1)

    def test_clear_pointer_is_idempotent_and_does_not_clear_overlays(self) -> None:
        plan = self.plan()
        empty = start_session(plan)
        self.assertIs(clear_teacher_pointer(plan, empty, expected_revision=0), empty)
        pointed, _ = commit_teacher_pointer_input(plan, empty, "e4", expected_revision=0)
        pointed = replace(
            pointed,
            presentation=replace(
                pointed.presentation,
                highlights=(SquareHighlight("d4", "teacher"),),
                arrows=(VisualArrow("e2", "e4", "teacher"),),
            ),
        )
        cleared = clear_teacher_pointer(plan, pointed, expected_revision=1)
        self.assertIsNone(cleared.presentation.pointer.square)
        self.assertEqual(cleared.presentation.highlights, pointed.presentation.highlights)
        self.assertEqual(cleared.presentation.arrows, pointed.presentation.arrows)
        self.assertEqual(cleared.position_fen, pointed.position_fen)
        self.assertEqual(cleared.revision, 2)

    def test_manual_highlight_and_arrow_are_presentation_only_and_deduplicated(self) -> None:
        plan = self.plan()
        state, _ = commit_teacher_pointer_input(
            plan, start_session(plan), "f3", expected_revision=0
        )
        state = apply_teacher_annotation(
            plan,
            state,
            AnnotationCommand(
                AnnotationOperation.SET_HIGHLIGHT,
                start_square="e4",
                tag="idea",
            ),
            expected_revision=1,
        )
        state = apply_teacher_annotation(
            plan,
            state,
            AnnotationCommand(
                AnnotationOperation.ADD_ARROW,
                start_square="e2",
                end_square="e4",
                tag="idea",
            ),
            expected_revision=2,
        )
        state = apply_teacher_annotation(
            plan,
            state,
            AnnotationCommand(
                AnnotationOperation.SET_HIGHLIGHT,
                start_square="e4",
                tag="idea",
            ),
            expected_revision=3,
        )
        self.assertEqual(state.presentation.pointer.square, "f3")
        self.assertEqual(
            state.presentation.highlights.count(SquareHighlight("e4", "idea")),
            1,
        )
        self.assertEqual(
            state.presentation.arrows,
            (VisualArrow("e2", "e4", "idea"),),
        )
        self.assertEqual(state.position_fen, Board.START)
        self.assertEqual(state.revision, 4)

    def test_clear_all_manual_annotations_preserves_legal_move_layer(self) -> None:
        plan = self.plan()
        state = start_session(plan)
        state = replace(
            state,
            presentation=replace(
                state.presentation,
                highlights=(
                    SquareHighlight("f3", LEGAL_MOVE_HIGHLIGHT_PURPOSE),
                    SquareHighlight("e4", "teacher"),
                    SquareHighlight("d4", "idea"),
                ),
                arrows=(
                    VisualArrow("e2", "e4", "teacher"),
                    VisualArrow("d2", "d4", "idea"),
                ),
            ),
        )
        cleared = apply_teacher_annotation(
            plan,
            state,
            AnnotationCommand(AnnotationOperation.CLEAR),
            expected_revision=0,
        )
        self.assertEqual(
            cleared.presentation.highlights,
            (SquareHighlight("f3", LEGAL_MOVE_HIGHLIGHT_PURPOSE),),
        )
        self.assertEqual(cleared.presentation.arrows, ())
        self.assertEqual(cleared.position_fen, Board.START)

    def test_scoped_clear_removes_only_matching_manual_purpose(self) -> None:
        plan = self.plan()
        state = start_session(plan)
        state = replace(
            state,
            presentation=replace(
                state.presentation,
                highlights=(
                    SquareHighlight("e4", "idea"),
                    SquareHighlight("d4", DEFAULT_TEACHER_ANNOTATION_PURPOSE),
                ),
                arrows=(
                    VisualArrow("e2", "e4", "idea"),
                    VisualArrow(
                        "d2",
                        "d4",
                        DEFAULT_TEACHER_ANNOTATION_PURPOSE,
                    ),
                ),
            ),
        )
        cleared = apply_teacher_annotation(
            plan,
            state,
            AnnotationCommand(AnnotationOperation.CLEAR, tag="idea"),
            expected_revision=0,
        )
        self.assertEqual(
            cleared.presentation.highlights,
            (SquareHighlight("d4", DEFAULT_TEACHER_ANNOTATION_PURPOSE),),
        )
        self.assertEqual(
            cleared.presentation.arrows,
            (
                VisualArrow(
                    "d2",
                    "d4",
                    DEFAULT_TEACHER_ANNOTATION_PURPOSE,
                ),
            ),
        )

    def test_manual_annotation_cannot_impersonate_reserved_legal_move_layer(self) -> None:
        plan = self.plan()
        before = start_session(plan)
        with self.assertRaisesRegex(TeachingPointerActionError, "reserved"):
            apply_teacher_annotation(
                plan,
                before,
                AnnotationCommand(
                    AnnotationOperation.SET_HIGHLIGHT,
                    start_square="e4",
                    tag=LEGAL_MOVE_HIGHLIGHT_PURPOSE,
                ),
                expected_revision=0,
            )
        self.assertEqual(before.presentation.highlights, ())
        self.assertEqual(before.revision, 0)

    def test_presentation_bound_failure_is_atomic(self) -> None:
        plan = self.plan()
        before = start_session(plan)
        full = tuple(
            SquareHighlight(f"{file}{rank}", "manual")
            for rank in "12345678"
            for file in "abcdefgh"
        )
        state = replace(
            before,
            presentation=replace(before.presentation, highlights=full),
        )
        with self.assertRaises(TeachingPointerActionError):
            apply_teacher_annotation(
                plan,
                state,
                AnnotationCommand(
                    AnnotationOperation.SET_HIGHLIGHT,
                    start_square="e4",
                    tag="extra",
                ),
                expected_revision=0,
            )
        self.assertEqual(state.presentation.highlights, full)
        self.assertEqual(state.revision, 0)
        self.assertEqual(state.position_fen, Board.START)


if __name__ == "__main__":
    unittest.main()
