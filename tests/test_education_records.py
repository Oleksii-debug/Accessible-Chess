import unittest
from unittest.mock import patch

from acs import classroom_domain as cd
from acs import education_records as er


STAMP = "2026-08-23T12:30:00Z"
DIGEST_A = "a" * 64
DIGEST_B = "b" * 64


def sample_classroom():
    s1 = cd.Student("s1", "Knight-17")
    s2 = cd.Student("s2", "Bishop-9")
    klass = cd.ClassroomClass("class1", "Endgame class", ("group1",))
    group = cd.Group("group1", "class1", "Sunday group")
    lesson = cd.Lesson("lesson1", "course1", "Rook endings", (), STAMP)
    course = cd.Course("course1", "Endgames", ("lesson1",))
    cohort = cd.Cohort("cohort1", "course1", ("s1", "s2"), "group1")
    assignment = cd.Assignment(
        "a1", "lesson1", "cohort1", "Lucena practice", STAMP
    )
    return cd.ClassroomSnapshot(
        students=(s1, s2),
        classes=(klass,),
        groups=(group,),
        courses=(course,),
        cohorts=(cohort,),
        lessons=(lesson,),
        assignments=(assignment,),
    )


def submit(
    ledger,
    classroom,
    student_id,
    submission_id,
    operation_id,
    response_ref,
    *,
    expected_revision=None,
):
    if expected_revision is None:
        expected_revision = ledger.revision
    return er.submit_assignment(
        ledger,
        classroom,
        submission_id=submission_id,
        operation_id=operation_id,
        student_id=student_id,
        assignment_id="a1",
        response_ref=response_ref,
        submitted_at=STAMP,
        expected_revision=expected_revision,
    )


class EducationRecordsTests(unittest.TestCase):
    def test_round_trip_reopen_is_deterministic_and_lossless(self):
        classroom = sample_classroom()
        ledger = er.EducationLedger.empty(classroom)
        ledger = submit(
            ledger, classroom, "s1", "sub1", "op1", "response.s1.1"
        )
        ledger = er.record_progress(
            ledger,
            classroom,
            event_id="progress1",
            operation_id="op2",
            student_id="s1",
            course_id="course1",
            lesson_id="lesson1",
            completed_at=STAMP,
            score_basis_points=8750,
            expected_revision=ledger.revision,
        )
        ledger = er.checkpoint_remote_session(
            ledger,
            classroom,
            record_id="remote1",
            operation_id="op3",
            session_id="session1",
            student_ids=("s1", "s2"),
            started_at=STAMP,
            closed_at=None,
            last_remote_sequence=7,
            snapshot_digest=DIGEST_A,
            expected_session_revision=0,
            expected_revision=ledger.revision,
        )
        text = ledger.to_json()
        restored = er.EducationLedger.from_json(text)
        self.assertEqual(restored, ledger)
        self.assertEqual(restored.to_json(), text)
        self.assertEqual(restored.digest, ledger.digest)

    def test_student_projection_never_exposes_another_students_private_response(self):
        classroom = sample_classroom()
        ledger = er.EducationLedger.empty(classroom)
        ledger = submit(
            ledger, classroom, "s1", "sub1", "op1", "private.response.s1"
        )
        ledger = submit(
            ledger, classroom, "s2", "sub2", "op2", "private.response.s2"
        )
        ledger = er.checkpoint_remote_session(
            ledger,
            classroom,
            record_id="remote1",
            operation_id="op3",
            session_id="session1",
            student_ids=("s1", "s2"),
            started_at=STAMP,
            closed_at=None,
            last_remote_sequence=1,
            snapshot_digest=DIGEST_A,
            expected_session_revision=0,
            expected_revision=ledger.revision,
        )
        s1_view = ledger.student_view("s1")
        s2_view = ledger.student_view("s2")
        self.assertEqual(
            tuple(item.response_ref for item in s1_view.submissions),
            ("private.response.s1",),
        )
        self.assertEqual(
            tuple(item.response_ref for item in s2_view.submissions),
            ("private.response.s2",),
        )
        self.assertNotIn("private.response.s2", repr(s1_view))
        self.assertNotIn("private.response.s1", repr(s2_view))
        self.assertEqual(s1_view.sessions[0].session_id, "session1")
        self.assertFalse(hasattr(s1_view.sessions[0], "student_ids"))

    def test_assignment_submission_requires_current_cohort_membership(self):
        classroom = sample_classroom()
        outsider = cd.Student("s3", "Rook-5")
        classroom = cd.ClassroomSnapshot(
            students=classroom.students + (outsider,),
            classes=classroom.classes,
            groups=classroom.groups,
            courses=classroom.courses,
            cohorts=classroom.cohorts,
            lessons=classroom.lessons,
            assignments=classroom.assignments,
        )
        ledger = er.EducationLedger.empty(classroom)
        before = ledger.to_json()
        with self.assertRaises(er.EducationRecordsError):
            submit(
                ledger,
                classroom,
                "s3",
                "sub3",
                "op3",
                "response.s3",
            )
        self.assertEqual(ledger.to_json(), before)

    def test_stale_ledger_revision_fails_without_partial_mutation(self):
        classroom = sample_classroom()
        ledger = er.EducationLedger.empty(classroom)
        before = ledger.to_json()
        with self.assertRaises(er.EducationRecordsError):
            submit(
                ledger,
                classroom,
                "s1",
                "sub1",
                "op1",
                "response.s1",
                expected_revision=9,
            )
        self.assertEqual(ledger.to_json(), before)

    def test_exact_retry_is_idempotent_even_with_original_stale_revision(self):
        classroom = sample_classroom()
        ledger = er.EducationLedger.empty(classroom)
        committed = submit(
            ledger,
            classroom,
            "s1",
            "sub1",
            "op1",
            "response.s1",
            expected_revision=0,
        )
        retry = submit(
            committed,
            classroom,
            "s1",
            "sub1",
            "op1",
            "response.s1",
            expected_revision=0,
        )
        self.assertIs(retry, committed)
        with self.assertRaises(er.EducationRecordsError):
            submit(
                committed,
                classroom,
                "s1",
                "sub1",
                "op1",
                "different.response",
                expected_revision=0,
            )

    def test_progress_requires_enrollment_and_lesson_course_match(self):
        classroom = sample_classroom()
        ledger = er.EducationLedger.empty(classroom)
        with self.assertRaises(er.EducationRecordsError):
            er.record_progress(
                ledger,
                classroom,
                event_id="p1",
                operation_id="op1",
                student_id="s1",
                course_id="other-course",
                lesson_id="lesson1",
                completed_at=STAMP,
                expected_revision=0,
            )
        self.assertEqual(ledger.progress_events, ())
        updated = er.record_progress(
            ledger,
            classroom,
            event_id="p1",
            operation_id="op1",
            student_id="s1",
            course_id="course1",
            lesson_id="lesson1",
            completed_at=STAMP,
            expected_revision=0,
        )
        self.assertEqual(updated.progress_events[0].student_id, "s1")

    def test_remote_checkpoint_retry_is_idempotent_before_global_cas(self):
        classroom = sample_classroom()
        ledger = er.EducationLedger.empty(classroom)
        committed = er.checkpoint_remote_session(
            ledger,
            classroom,
            record_id="remote1",
            operation_id="op1",
            session_id="session1",
            student_ids=("s1", "s2"),
            started_at=STAMP,
            closed_at=None,
            last_remote_sequence=10,
            snapshot_digest=DIGEST_A,
            expected_session_revision=0,
            expected_revision=0,
        )
        retry = er.checkpoint_remote_session(
            committed,
            classroom,
            record_id="remote1",
            operation_id="op1",
            session_id="session1",
            student_ids=("s1", "s2"),
            started_at=STAMP,
            closed_at=None,
            last_remote_sequence=10,
            snapshot_digest=DIGEST_A,
            expected_session_revision=0,
            expected_revision=0,
        )
        self.assertIs(retry, committed)

    def test_remote_session_checkpoint_uses_cas_and_rejects_sequence_conflicts(self):
        classroom = sample_classroom()
        ledger = er.EducationLedger.empty(classroom)
        ledger = er.checkpoint_remote_session(
            ledger,
            classroom,
            record_id="remote1",
            operation_id="op1",
            session_id="session1",
            student_ids=("s1", "s2"),
            started_at=STAMP,
            closed_at=None,
            last_remote_sequence=10,
            snapshot_digest=DIGEST_A,
            expected_session_revision=0,
            expected_revision=0,
        )
        ledger = er.checkpoint_remote_session(
            ledger,
            classroom,
            record_id="remote1",
            operation_id="op2",
            session_id="session1",
            student_ids=("s1", "s2"),
            started_at=STAMP,
            closed_at=None,
            last_remote_sequence=11,
            snapshot_digest=DIGEST_B,
            expected_session_revision=0,
            expected_revision=1,
        )
        self.assertEqual(ledger.remote_sessions[0].revision, 1)
        before = ledger.to_json()
        with self.assertRaises(er.EducationRecordsError):
            er.checkpoint_remote_session(
                ledger,
                classroom,
                record_id="remote1",
                operation_id="op3",
                session_id="session1",
                student_ids=("s1", "s2"),
                started_at=STAMP,
                closed_at=None,
                last_remote_sequence=10,
                snapshot_digest=DIGEST_A,
                expected_session_revision=1,
                expected_revision=2,
            )
        with self.assertRaises(er.EducationRecordsError):
            er.checkpoint_remote_session(
                ledger,
                classroom,
                record_id="remote1",
                operation_id="op4",
                session_id="session1",
                student_ids=("s1", "s2"),
                started_at=STAMP,
                closed_at=None,
                last_remote_sequence=11,
                snapshot_digest=DIGEST_A,
                expected_session_revision=1,
                expected_revision=2,
            )
        self.assertEqual(ledger.to_json(), before)

    def test_remote_session_close_is_one_way(self):
        classroom = sample_classroom()
        ledger = er.EducationLedger.empty(classroom)
        ledger = er.checkpoint_remote_session(
            ledger,
            classroom,
            record_id="remote1",
            operation_id="op1",
            session_id="session1",
            student_ids=("s1",),
            started_at=STAMP,
            closed_at=None,
            last_remote_sequence=1,
            snapshot_digest=DIGEST_A,
            expected_session_revision=0,
            expected_revision=0,
        )
        ledger = er.checkpoint_remote_session(
            ledger,
            classroom,
            record_id="remote1",
            operation_id="op2",
            session_id="session1",
            student_ids=("s1",),
            started_at=STAMP,
            closed_at="2026-08-23T13:30:00Z",
            last_remote_sequence=2,
            snapshot_digest=DIGEST_B,
            expected_session_revision=0,
            expected_revision=1,
        )
        before = ledger.to_json()
        with self.assertRaises(er.EducationRecordsError):
            er.checkpoint_remote_session(
                ledger,
                classroom,
                record_id="remote1",
                operation_id="op3",
                session_id="session1",
                student_ids=("s1",),
                started_at=STAMP,
                closed_at=None,
                last_remote_sequence=3,
                snapshot_digest="c" * 64,
                expected_session_revision=1,
                expected_revision=2,
            )
        self.assertEqual(ledger.to_json(), before)

    def test_reconcile_after_deletion_purges_private_state_and_advances_session_cas(self):
        classroom = sample_classroom()
        ledger = er.EducationLedger.empty(classroom)
        ledger = submit(
            ledger, classroom, "s1", "sub1", "op1", "private.s1"
        )
        ledger = submit(
            ledger, classroom, "s2", "sub2", "op2", "private.s2"
        )
        ledger = er.record_progress(
            ledger,
            classroom,
            event_id="p1",
            operation_id="op3",
            student_id="s1",
            course_id="course1",
            lesson_id="lesson1",
            completed_at=STAMP,
            expected_revision=ledger.revision,
        )
        ledger = er.checkpoint_remote_session(
            ledger,
            classroom,
            record_id="remote1",
            operation_id="op4",
            session_id="session1",
            student_ids=("s1", "s2"),
            started_at=STAMP,
            closed_at=None,
            last_remote_sequence=3,
            snapshot_digest=DIGEST_A,
            expected_session_revision=0,
            expected_revision=ledger.revision,
        )
        deleted = cd.delete_student(classroom, "s1", 0)
        original_revision = ledger.revision
        reconciled = er.reconcile_classroom(
            ledger,
            deleted,
            operation_id="op5",
            expected_revision=original_revision,
        )
        self.assertEqual(
            tuple(item.student_id for item in reconciled.submissions), ("s2",)
        )
        self.assertEqual(reconciled.progress_events, ())
        session = reconciled.remote_sessions[0]
        self.assertEqual(session.student_ids, ("s2",))
        self.assertEqual(session.revision, 1)
        self.assertEqual(reconciled.classroom_digest, deleted.digest)
        self.assertEqual(
            er.EducationLedger.from_json(reconciled.to_json()), reconciled
        )

        retry = er.reconcile_classroom(
            reconciled,
            deleted,
            operation_id="op5",
            expected_revision=original_revision,
        )
        self.assertIs(retry, reconciled)

        continued = er.checkpoint_remote_session(
            reconciled,
            deleted,
            record_id="remote1",
            operation_id="op6",
            session_id="session1",
            student_ids=("s2",),
            started_at=STAMP,
            closed_at=None,
            last_remote_sequence=4,
            snapshot_digest=DIGEST_B,
            expected_session_revision=1,
            expected_revision=reconciled.revision,
        )
        self.assertEqual(continued.remote_sessions[0].revision, 2)

    def test_reconcile_is_cas_guarded(self):
        classroom = sample_classroom()
        ledger = er.EducationLedger.empty(classroom)
        before = ledger.to_json()
        with self.assertRaises(er.EducationRecordsError):
            er.reconcile_classroom(
                ledger,
                classroom,
                operation_id="op1",
                expected_revision=1,
            )
        self.assertEqual(ledger.to_json(), before)

    def test_digest_duplicate_keys_and_exact_scalar_boundaries_fail_closed(self):
        classroom = sample_classroom()
        ledger = er.EducationLedger.empty(classroom)
        record = ledger.to_record()
        record["revision"] = 1
        with self.assertRaises(er.EducationRecordsError):
            er.EducationLedger.from_record(record)
        with self.assertRaises(er.EducationRecordsError):
            er.EducationLedger.from_json('{"version":1,"version":1}')
        with self.assertRaises(er.EducationRecordsError):
            er.EducationLedger(classroom.digest, revision=True)
        with self.assertRaises(er.EducationRecordsError):
            er.SubmissionRecord(
                "sub1", "a1", "s1", "response.1", STAMP, True
            )
        with self.assertRaises(er.EducationRecordsError):
            er.RemoteSessionRecord(
                "r1", "session1", ["s1"], STAMP, None, 0, DIGEST_A
            )

    def test_json_resource_limit_is_enforced_on_write_and_reopen(self):
        classroom = sample_classroom()
        ledger = er.EducationLedger.empty(classroom)
        text = ledger.to_json()
        with patch.object(er, "MAX_SNAPSHOT_BYTES", 10):
            with self.assertRaises(er.EducationRecordsError):
                ledger.to_json()
            with self.assertRaises(er.EducationRecordsError):
                er.EducationLedger.from_json(text)


if __name__ == "__main__":
    unittest.main()
