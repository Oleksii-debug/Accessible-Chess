from __future__ import annotations

from dataclasses import replace
import unittest

from acs import classroom_domain as cd
from acs import education_workspace as ew


STAMP = "2026-09-11T13:00:00Z"


def _rich_classroom() -> cd.ClassroomSnapshot:
    s1 = cd.Student("s1", "Knight-17", cd.ConsentState.GRANTED)
    s2 = cd.Student("s2", "Bishop-9")

    class1 = cd.ClassroomClass("class1", "Main class", ("group1", "group2"))
    class2 = cd.ClassroomClass("class2", "Archive-safe class")
    group1 = cd.Group("group1", "class1", "Primary group")
    group2 = cd.Group("group2", "class1", "Spare group")

    material1 = cd.LessonMaterial("material1", "text", "Rook endings")
    material2 = cd.LessonMaterial("material2", "text", "Unattached notes")
    lesson1 = cd.Lesson("lesson1", "course1", "Lucena", ("material1",), STAMP)
    lesson2 = cd.Lesson("lesson2", "course1", "Philidor", (), STAMP)
    course1 = cd.Course("course1", "Endgames", ("lesson1", "lesson2"))
    course2 = cd.Course("course2", "Independent course", ())

    cohort1 = cd.Cohort("cohort1", "course1", ("s1", "s2"), "group1")
    cohort2 = cd.Cohort("cohort2", "course1", ("s2",), None)
    assignment1 = cd.Assignment("assignment1", "lesson1", "cohort1", "Practice", STAMP)
    assignment2 = cd.Assignment("assignment2", "lesson1", "cohort1", "Optional", STAMP)
    homework1 = cd.Homework("homework1", "assignment1", "s1")
    homework2 = cd.Homework("homework2", "assignment1", "s2")
    student_game = cd.StudentGame("student-game1", "s1", "canonical-game-1", "assignment1")
    result = cd.Result("result1", "s1", "assignment1", "complete", 9000)
    progress = cd.Progress("progress1", "s1", "course1", ("lesson1",), 2)
    note = cd.TeacherNote("note1", "s1", "Private coaching note", STAMP)

    return cd.ClassroomSnapshot(
        students=(s1, s2),
        classes=(class1, class2),
        groups=(group1, group2),
        courses=(course1, course2),
        cohorts=(cohort1, cohort2),
        materials=(material1, material2),
        lessons=(lesson1, lesson2),
        assignments=(assignment1, assignment2),
        homework=(homework1, homework2),
        student_games=(student_game,),
        results=(result,),
        progress=(progress,),
        teacher_notes=(note,),
    )


def _drop_identity(snapshot: cd.ClassroomSnapshot, collection: str, identity: str) -> cd.ClassroomSnapshot:
    if collection == "classes":
        return replace(
            snapshot,
            classes=tuple(item for item in snapshot.classes if item.class_id != identity),
        )
    if collection == "groups":
        groups = tuple(item for item in snapshot.groups if item.group_id != identity)
        classes = tuple(
            replace(item, group_ids=tuple(group_id for group_id in item.group_ids if group_id != identity))
            for item in snapshot.classes
        )
        cohorts = tuple(
            replace(item, group_id=None) if item.group_id == identity else item
            for item in snapshot.cohorts
        )
        return replace(snapshot, groups=groups, classes=classes, cohorts=cohorts)
    if collection == "courses":
        return replace(
            snapshot,
            courses=tuple(item for item in snapshot.courses if item.course_id != identity),
        )
    if collection == "cohorts":
        return replace(
            snapshot,
            cohorts=tuple(item for item in snapshot.cohorts if item.cohort_id != identity),
        )
    if collection == "materials":
        return replace(
            snapshot,
            materials=tuple(item for item in snapshot.materials if item.material_id != identity),
        )
    if collection == "lessons":
        lessons = tuple(item for item in snapshot.lessons if item.lesson_id != identity)
        courses = tuple(
            replace(item, lesson_ids=tuple(lesson_id for lesson_id in item.lesson_ids if lesson_id != identity))
            for item in snapshot.courses
        )
        return replace(snapshot, lessons=lessons, courses=courses)
    if collection == "assignments":
        return replace(
            snapshot,
            assignments=tuple(item for item in snapshot.assignments if item.assignment_id != identity),
        )
    if collection == "homework":
        return replace(
            snapshot,
            homework=tuple(item for item in snapshot.homework if item.homework_id != identity),
        )
    if collection == "student_games":
        return replace(
            snapshot,
            student_games=tuple(
                item for item in snapshot.student_games if item.student_game_id != identity
            ),
        )
    if collection == "results":
        return replace(
            snapshot,
            results=tuple(item for item in snapshot.results if item.result_id != identity),
        )
    if collection == "progress":
        return replace(
            snapshot,
            progress=tuple(item for item in snapshot.progress if item.progress_id != identity),
        )
    if collection == "teacher_notes":
        return replace(
            snapshot,
            teacher_notes=tuple(item for item in snapshot.teacher_notes if item.note_id != identity),
        )
    raise AssertionError(f"unsupported collection: {collection}")


class D10NoImplicitDeleteCurrentRuntimeTests(unittest.TestCase):
    def test_generic_commit_rejects_implicit_entity_disappearance(self):
        cases = (
            ("classes", "class2"),
            ("groups", "group2"),
            ("courses", "course2"),
            ("cohorts", "cohort2"),
            ("materials", "material2"),
            ("lessons", "lesson2"),
            ("assignments", "assignment2"),
            ("homework", "homework2"),
            ("student_games", "student-game1"),
            ("results", "result1"),
            ("progress", "progress1"),
            ("teacher_notes", "note1"),
        )
        for collection, identity in cases:
            with self.subTest(collection=collection, identity=identity):
                classroom = _rich_classroom()
                workspace = ew.EducationWorkspace.empty(classroom)
                candidate = _drop_identity(classroom, collection, identity)
                before = workspace.to_json()
                with self.assertRaisesRegex(
                    ew.EducationWorkspaceError,
                    "cannot disappear without explicit lifecycle",
                ):
                    ew.commit_classroom(
                        workspace,
                        candidate,
                        operation_id=f"drop-{collection}",
                        expected_ledger_revision=workspace.ledger.revision,
                    )
                self.assertEqual(workspace.to_json(), before)

    def test_explicit_consent_withdrawal_can_remove_only_target_teacher_notes(self):
        classroom = _rich_classroom()
        workspace = ew.EducationWorkspace.empty(classroom)
        changed = ew.set_student_consent(
            workspace,
            student_id="s1",
            consent=cd.ConsentState.WITHDRAWN,
            operation_id="withdraw-s1",
            expected_student_revision=0,
            expected_ledger_revision=0,
        )
        self.assertFalse(any(item.student_id == "s1" for item in changed.classroom.teacher_notes))
        self.assertEqual(changed.ledger.classroom_digest, changed.classroom.digest)

    def test_explicit_student_delete_can_purge_only_student_owned_records(self):
        classroom = _rich_classroom()
        workspace = ew.EducationWorkspace.empty(classroom)
        changed = ew.delete_student(
            workspace,
            student_id="s1",
            operation_id="delete-s1",
            expected_student_revision=0,
            expected_ledger_revision=0,
        )
        deleted = next(item for item in changed.classroom.students if item.student_id == "s1")
        self.assertTrue(deleted.deleted)
        self.assertFalse(any(item.student_id == "s1" for item in changed.classroom.homework))
        self.assertFalse(any(item.student_id == "s1" for item in changed.classroom.student_games))
        self.assertFalse(any(item.student_id == "s1" for item in changed.classroom.results))
        self.assertFalse(any(item.student_id == "s1" for item in changed.classroom.progress))
        self.assertFalse(any(item.student_id == "s1" for item in changed.classroom.teacher_notes))
        self.assertTrue(any(item.homework_id == "homework2" for item in changed.classroom.homework))
        self.assertTrue(any(item.assignment_id == "assignment2" for item in changed.classroom.assignments))
        self.assertTrue(any(item.class_id == "class2" for item in changed.classroom.classes))
        self.assertEqual(changed.ledger.classroom_digest, changed.classroom.digest)


if __name__ == "__main__":
    unittest.main()
