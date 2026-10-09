import copy
from dataclasses import replace
from datetime import datetime
import unittest
from unittest.mock import patch

from acs import classroom_domain as cd


STAMP = "2026-08-22T19:00:00Z"


def sample_snapshot(*, consent=cd.ConsentState.GRANTED):
    student = cd.Student("s1", "Knight-17", consent=consent)
    class_record = cd.ClassroomClass("class1", "Advanced chess", ("group1",))
    group = cd.Group("group1", "class1", "Evening")
    material = cd.LessonMaterial("mat1", "book", "Lucena", "book.ref.1")
    lesson = cd.Lesson("lesson1", "course1", "Rook endings", ("mat1",), STAMP)
    course = cd.Course("course1", "Endgames", ("lesson1",))
    cohort = cd.Cohort("cohort1", "course1", ("s1",), "group1")
    assignment = cd.Assignment(
        "a1", "lesson1", "cohort1", "Practice", STAMP, "2026-09-01T18:00:00Z"
    )
    homework = cd.Homework("hw1", "a1", "s1", cd.HomeworkStatus.SUBMITTED, "submission.1")
    game = cd.StudentGame("sg1", "s1", "game.123", "a1")
    result = cd.Result("r1", "s1", "a1", "passed", 8750)
    progress = cd.Progress("p1", "s1", "course1", ("lesson1",), 2)
    notes = ()
    if consent is cd.ConsentState.GRANTED:
        notes = (cd.TeacherNote("n1", "s1", "Needs more rook checks.", STAMP),)
    return cd.ClassroomSnapshot(
        students=(student,),
        classes=(class_record,),
        groups=(group,),
        courses=(course,),
        cohorts=(cohort,),
        materials=(material,),
        lessons=(lesson,),
        assignments=(assignment,),
        homework=(homework,),
        student_games=(game,),
        results=(result,),
        progress=(progress,),
        teacher_notes=notes,
    )


class ClassroomDomainTests(unittest.TestCase):
    def test_snapshot_round_trip_is_deterministic_and_lossless(self):
        source = sample_snapshot()
        text = source.to_json()
        restored = cd.ClassroomSnapshot.from_json(text)
        self.assertEqual(restored, source)
        self.assertEqual(restored.to_json(), text)
        self.assertEqual(restored.digest, source.digest)

    def test_snapshot_digest_rejects_known_field_tampering(self):
        record = sample_snapshot().to_record()
        record["students"][0]["pseudonym"] = "Changed"
        with self.assertRaises(cd.ClassroomDomainError):
            cd.ClassroomSnapshot.from_record(record)

    def test_duplicate_json_keys_and_nonfinite_values_fail_closed(self):
        with self.assertRaises(cd.ClassroomDomainError):
            cd.ClassroomSnapshot.from_json('{"version":1,"version":1}')
        with self.assertRaises(cd.ClassroomDomainError):
            cd.ClassroomSnapshot.from_json('{"version":NaN}')

    def test_closed_world_student_schema_rejects_personal_data_fields(self):
        record = sample_snapshot().to_record()
        record["students"][0]["full_name"] = "Private Name"
        with self.assertRaises(cd.ClassroomDomainError):
            cd.ClassroomSnapshot.from_record(record)
        record = sample_snapshot().to_record()
        record["students"][0]["email"] = "private@example.invalid"
        with self.assertRaises(cd.ClassroomDomainError):
            cd.ClassroomSnapshot.from_record(record)

    def test_unknown_top_level_fields_fail_closed(self):
        record = sample_snapshot().to_record()
        record["future"] = []
        with self.assertRaises(cd.ClassroomDomainError):
            cd.ClassroomSnapshot.from_record(record)

    def test_exact_scalar_boundaries_reject_bool_and_datetime_coercion(self):
        with self.assertRaises(cd.ClassroomDomainError):
            cd.Student("s1", "Alias", revision=True)
        with self.assertRaises(cd.ClassroomDomainError):
            cd.Result("r1", "s1", "a1", "ok", True)
        with self.assertRaises(cd.ClassroomDomainError):
            cd.Lesson("l1", "c1", "Title", (), datetime.now())
        with self.assertRaises(cd.ClassroomDomainError):
            cd.Assignment("a1", "l1", "co1", "Title", STAMP, " 2026-09-01T00:00:00Z")

    def test_in_process_collections_require_exact_tuples(self):
        with self.assertRaises(cd.ClassroomDomainError):
            cd.ClassroomSnapshot(students=[cd.Student("s1", "Alias")])
        with self.assertRaises(cd.ClassroomDomainError):
            cd.Cohort("co1", "course1", ["s1"])

    def test_duplicate_record_ids_fail_closed(self):
        student = cd.Student("s1", "Alias")
        with self.assertRaises(cd.ClassroomDomainError):
            cd.ClassroomSnapshot(students=(student, student))

    def test_relational_indexes_must_be_complete(self):
        lesson = cd.Lesson("l1", "c1", "Lesson", (), STAMP)
        course = cd.Course("c1", "Course", ())
        with self.assertRaises(cd.ClassroomDomainError):
            cd.ClassroomSnapshot(courses=(course,), lessons=(lesson,))

        group = cd.Group("g1", "cl1", "G")
        klass = cd.ClassroomClass("cl1", "Class", ())
        with self.assertRaises(cd.ClassroomDomainError):
            cd.ClassroomSnapshot(classes=(klass,), groups=(group,))

    def test_assignment_cannot_cross_course_and_cohort_boundary(self):
        student = cd.Student("s1", "Alias")
        lesson = cd.Lesson("l1", "c1", "L", (), STAMP)
        c1 = cd.Course("c1", "One", ("l1",))
        c2 = cd.Course("c2", "Two", ())
        cohort = cd.Cohort("co2", "c2", ("s1",))
        assignment = cd.Assignment("a1", "l1", "co2", "A", STAMP)
        with self.assertRaises(cd.ClassroomDomainError):
            cd.ClassroomSnapshot(
                students=(student,),
                courses=(c1, c2),
                lessons=(lesson,),
                cohorts=(cohort,),
                assignments=(assignment,),
            )

    def test_assignment_student_records_require_cohort_membership(self):
        source = sample_snapshot()
        outsider = cd.Student("s2", "Outsider")
        with self.assertRaises(cd.ClassroomDomainError):
            replace(
                source,
                students=source.students + (outsider,),
                student_games=(cd.StudentGame("sg2", "s2", "game.2", "a1"),),
                homework=(),
                results=(),
                progress=(),
                teacher_notes=(),
            )

    def test_progress_cannot_reference_lesson_from_another_course(self):
        source = sample_snapshot()
        other_lesson = cd.Lesson("lesson2", "course2", "Other", (), STAMP)
        other_course = cd.Course("course2", "Other course", ("lesson2",))
        bad_progress = cd.Progress("p1", "s1", "course1", ("lesson2",))
        with self.assertRaises(cd.ClassroomDomainError):
            replace(
                source,
                courses=source.courses + (other_course,),
                lessons=source.lessons + (other_lesson,),
                progress=(bad_progress,),
            )

    def test_teacher_note_requires_explicit_consent(self):
        source = sample_snapshot(consent=cd.ConsentState.NOT_COLLECTED)
        with self.assertRaises(cd.ClassroomDomainError):
            replace(source, teacher_notes=(cd.TeacherNote("n1", "s1", "Private note", STAMP),))

    def test_withdrawing_consent_is_copy_on_write_and_removes_teacher_notes(self):
        source = sample_snapshot()
        before = source.to_json()
        updated = cd.set_student_consent(source, "s1", 0, cd.ConsentState.WITHDRAWN)
        self.assertEqual(source.to_json(), before)
        self.assertEqual(source.teacher_notes[0].note_id, "n1")
        self.assertEqual(updated.teacher_notes, ())
        self.assertEqual(updated.students[0].consent, cd.ConsentState.WITHDRAWN)
        self.assertEqual(updated.students[0].revision, 1)

    def test_stale_consent_revision_fails_without_mutation(self):
        source = sample_snapshot()
        before = source.to_json()
        with self.assertRaises(cd.ClassroomDomainError):
            cd.set_student_consent(source, "s1", 9, cd.ConsentState.WITHDRAWN)
        self.assertEqual(source.to_json(), before)

    def test_student_deletion_cascades_sensitive_and_student_scoped_state(self):
        source = sample_snapshot()
        before = source.to_json()
        updated = cd.delete_student(source, "s1", 0)
        self.assertEqual(source.to_json(), before)
        tombstone = updated.students[0]
        self.assertTrue(tombstone.deleted)
        self.assertEqual(tombstone.pseudonym, "")
        self.assertEqual(tombstone.consent, cd.ConsentState.WITHDRAWN)
        self.assertEqual(tombstone.revision, 1)
        self.assertEqual(updated.cohorts[0].student_ids, ())
        self.assertEqual(updated.homework, ())
        self.assertEqual(updated.student_games, ())
        self.assertEqual(updated.results, ())
        self.assertEqual(updated.progress, ())
        self.assertEqual(updated.teacher_notes, ())
        self.assertEqual(cd.ClassroomSnapshot.from_json(updated.to_json()), updated)

    def test_student_deletion_stale_revision_is_atomic(self):
        source = sample_snapshot()
        before = source.to_json()
        with self.assertRaises(cd.ClassroomDomainError):
            cd.delete_student(source, "s1", 1)
        self.assertEqual(source.to_json(), before)

    def test_deleted_student_cannot_be_reintroduced_via_cohort(self):
        tombstone = cd.Student("s1", "", cd.ConsentState.WITHDRAWN, True, 1)
        course = cd.Course("c1", "Course", ())
        cohort = cd.Cohort("co1", "c1", ("s1",))
        with self.assertRaises(cd.ClassroomDomainError):
            cd.ClassroomSnapshot(students=(tombstone,), courses=(course,), cohorts=(cohort,))

    def test_opaque_refs_reject_local_paths(self):
        with self.assertRaises(cd.ClassroomDomainError):
            cd.LessonMaterial("m1", "book", "Title", "C:\\private\\book.acbook")
        with self.assertRaises(cd.ClassroomDomainError):
            cd.StudentGame("sg1", "s1", "/home/user/game.pgn")

    def test_collection_and_json_resource_limits_are_enforced(self):
        with patch.object(cd, "MAX_LINKS_PER_RECORD", 1):
            with self.assertRaises(cd.ClassroomDomainError):
                cd.Cohort("co1", "c1", ("s1", "s2"))
        source = sample_snapshot()
        with patch.object(cd, "MAX_SNAPSHOT_BYTES", 10):
            with self.assertRaises(cd.ClassroomDomainError):
                source.to_json()
            with self.assertRaises(cd.ClassroomDomainError):
                cd.ClassroomSnapshot.from_json("x" * 11)

    def test_wire_list_duplicates_fail_closed(self):
        record = sample_snapshot().to_record()
        record["cohorts"][0]["student_ids"] = ["s1", "s1"]
        with self.assertRaises(cd.ClassroomDomainError):
            cd.ClassroomSnapshot.from_record(record)

    def test_source_record_is_detached_from_snapshot(self):
        source = sample_snapshot()
        record = source.to_record()
        restored = cd.ClassroomSnapshot.from_record(copy.deepcopy(record))
        record["students"][0]["pseudonym"] = "Mutated"
        record["cohorts"][0]["student_ids"].clear()
        self.assertEqual(restored.students[0].pseudonym, "Knight-17")
        self.assertEqual(restored.cohorts[0].student_ids, ("s1",))


if __name__ == "__main__":
    unittest.main()
