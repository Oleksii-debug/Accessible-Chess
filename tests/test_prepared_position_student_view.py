from __future__ import annotations

from dataclasses import fields
import unittest

from acs.classroom_domain import (
    ClassroomClass,
    ClassroomSnapshot,
    Cohort,
    Course,
    Group,
    Lesson,
    Student,
)
from acs.classroom_prepared_position_deployment import (
    plan_uniform_prepared_position_deployment,
)
from acs.education_workspace import (
    EducationWorkspace,
    get_prepared_position,
    save_prepared_position,
)
from acs.prepared_position_student_view import (
    PreparedPositionStudentViewError,
    resolve_prepared_position_student_view,
)
from acs.teaching_session import (
    LessonSession,
    PositionSourceKind,
    TeachingActivity,
    TeachingPositionSource,
    TeachingStep,
    default_policy,
)


FEN = "8/8/8/8/8/8/4K3/6k1 w - -"
STAMP = "2026-10-03T00:00:00Z"


def _classroom() -> ClassroomSnapshot:
    return ClassroomSnapshot(
        students=(Student("s1", "Student 1"),),
        classes=(ClassroomClass("class-1", "Class", ("group-1",)),),
        groups=(Group("group-1", "class-1", "Lesson group"),),
        courses=(Course("course-1", "Course", ("lesson-1",)),),
        cohorts=(Cohort("cohort-1", "course-1", ("s1",), "group-1"),),
        lessons=(Lesson("lesson-1", "course-1", "Lesson", (), STAMP),),
    )


def _lesson() -> LessonSession:
    step = TeachingStep(
        "step-1",
        TeachingActivity.TEACHER_EXPLAINS,
        "Explain the prepared position.",
        default_policy(TeachingActivity.TEACHER_EXPLAINS),
    )
    return LessonSession(
        "session-1",
        "lesson-1",
        TeachingPositionSource(PositionSourceKind.START),
        (step,),
        student_ids=("s1",),
    )


def _workspace(*, notes: str = "Private teacher-only coaching note.") -> EducationWorkspace:
    workspace = EducationWorkspace.empty(_classroom())
    return save_prepared_position(
        workspace,
        position_id="prep-one",
        source=TeachingPositionSource(PositionSourceKind.FEN, fen=FEN),
        expected_position_revision=0,
        title="Opposition",
        student_prompt="Find the move that keeps the opposition.",
        tags=("endgame", "kings"),
        order_index=3,
        teacher_notes=notes,
    )


def _batch(workspace: EducationWorkspace, *, batch_id: str = "batch-1"):
    return plan_uniform_prepared_position_deployment(
        _lesson(),
        workspace,
        batch_id=batch_id,
        position_id="prep-one",
    )


class PreparedPositionStudentViewTests(unittest.TestCase):
    def test_student_view_exposes_prompt_and_source_but_no_teacher_metadata(self) -> None:
        secret = "Never reveal this private coaching instruction."
        workspace = _workspace(notes=secret)
        batch = _batch(workspace)
        assignment = batch.assignments[0]

        view = resolve_prepared_position_student_view(
            batch,
            assignment.assignment_id,
            _lesson(),
            workspace,
        )

        position = get_prepared_position(workspace, "prep-one")
        self.assertEqual(view.assignment_id, assignment.assignment_id)
        self.assertEqual(view.student_id, "s1")
        self.assertEqual(view.position_id, "prep-one")
        self.assertEqual(view.position_revision, position.revision)
        self.assertEqual(view.title, "Opposition")
        self.assertEqual(
            view.student_prompt,
            "Find the move that keeps the opposition.",
        )
        self.assertEqual(view.source, position.source)

        field_names = {item.name for item in fields(view)}
        self.assertNotIn("teacher_notes", field_names)
        self.assertNotIn("tags", field_names)
        self.assertNotIn("order_index", field_names)
        self.assertFalse(hasattr(view, "teacher_notes"))
        self.assertNotIn(secret, repr(view))

    def test_student_visible_metadata_revision_invalidates_old_batch(self) -> None:
        workspace = _workspace()
        old_batch = _batch(workspace)
        assignment = old_batch.assignments[0]

        updated = save_prepared_position(
            workspace,
            position_id="prep-one",
            source=get_prepared_position(workspace, "prep-one").source,
            expected_position_revision=0,
            title="Opposition",
            student_prompt="Name the key square before moving.",
        )
        self.assertEqual(get_prepared_position(updated, "prep-one").revision, 1)

        with self.assertRaisesRegex(
            PreparedPositionStudentViewError,
            "no longer valid",
        ):
            resolve_prepared_position_student_view(
                old_batch,
                assignment.assignment_id,
                _lesson(),
                updated,
            )

        fresh_batch = _batch(updated, batch_id="batch-2")
        fresh = resolve_prepared_position_student_view(
            fresh_batch,
            fresh_batch.assignments[0].assignment_id,
            _lesson(),
            updated,
        )
        self.assertEqual(fresh.position_revision, 1)
        self.assertEqual(
            fresh.student_prompt,
            "Name the key square before moving.",
        )

    def test_teacher_note_only_change_invalidates_stale_reference_without_leak(self) -> None:
        old_secret = "Old private note."
        new_secret = "New private note."
        workspace = _workspace(notes=old_secret)
        batch = _batch(workspace)

        current = get_prepared_position(workspace, "prep-one")
        updated = save_prepared_position(
            workspace,
            position_id="prep-one",
            source=current.source,
            expected_position_revision=current.revision,
            teacher_notes=new_secret,
        )

        with self.assertRaises(PreparedPositionStudentViewError):
            resolve_prepared_position_student_view(
                batch,
                batch.assignments[0].assignment_id,
                _lesson(),
                updated,
            )

        fresh_batch = _batch(updated, batch_id="batch-3")
        view = resolve_prepared_position_student_view(
            fresh_batch,
            fresh_batch.assignments[0].assignment_id,
            _lesson(),
            updated,
        )
        self.assertNotIn(old_secret, repr(view))
        self.assertNotIn(new_secret, repr(view))
        self.assertFalse(hasattr(view, "teacher_notes"))

    def test_unknown_assignment_and_invalid_assignment_type_fail_closed(self) -> None:
        workspace = _workspace()
        batch = _batch(workspace)

        with self.assertRaisesRegex(
            PreparedPositionStudentViewError,
            "unavailable",
        ):
            resolve_prepared_position_student_view(
                batch,
                "deploy-unknown",
                _lesson(),
                workspace,
            )
        with self.assertRaisesRegex(
            PreparedPositionStudentViewError,
            "exact text",
        ):
            resolve_prepared_position_student_view(
                batch,
                None,  # type: ignore[arg-type]
                _lesson(),
                workspace,
            )

    def test_whole_batch_scope_is_validated_before_requested_assignment(self) -> None:
        workspace = _workspace()
        batch = _batch(workspace)
        assignment = batch.assignments[0]

        changed_lesson = LessonSession(
            "session-1",
            "lesson-1",
            TeachingPositionSource(PositionSourceKind.START),
            (
                TeachingStep(
                    "step-changed",
                    TeachingActivity.TEACHER_EXPLAINS,
                    "Changed lesson state.",
                    default_policy(TeachingActivity.TEACHER_EXPLAINS),
                ),
            ),
            student_ids=("s1",),
        )
        with self.assertRaisesRegex(
            PreparedPositionStudentViewError,
            "no longer valid",
        ):
            resolve_prepared_position_student_view(
                batch,
                assignment.assignment_id,
                changed_lesson,
                workspace,
            )


if __name__ == "__main__":
    unittest.main()
