import unittest
from unittest.mock import patch

from acs import classroom_domain as cd
from acs import education_records as er
from acs.remote_session import RemoteEventKind, RemoteSessionEvent, RemoteSessionLog
from acs.teaching_session import (
    LessonSession,
    PositionSourceKind,
    TeachingActivity,
    TeachingPositionSource,
    TeachingStep,
    default_policy,
)


STAMP = "2026-08-23T12:30:00Z"
DIGEST_A = "a" * 64


def sample_classroom(*, with_progress=False):
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
    progress = (
        cd.Progress("progress1", "s1", "course1", ("lesson1",), 3),
    ) if with_progress else ()
    return cd.ClassroomSnapshot(
        students=(s1, s2),
        classes=(klass,),
        groups=(group,),
        courses=(course,),
        cohorts=(cohort,),
        lessons=(lesson,),
        assignments=(assignment,),
        progress=progress,
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


def remote_checkpoint(
    last_sequence,
    *,
    student_ids=("s1", "s2"),
    session_id="session1",
    variant=0,
):
    activity = TeachingActivity.TEACHER_EXPLAINS
    lesson_session = LessonSession(
        session_id=session_id,
        lesson_id="lesson1",
        source=TeachingPositionSource(PositionSourceKind.START),
        steps=(
            TeachingStep(
                "step1",
                activity,
                "Remote checkpoint",
                default_policy(activity),
            ),
        ),
        student_ids=tuple(student_ids),
        cohort_id="cohort1",
    )
    log = RemoteSessionLog(session_id)
    for sequence in range(1, last_sequence + 1):
        square = "b1" if variant and sequence == last_sequence else "a1"
        log.append(
            RemoteSessionEvent(
                session_id=session_id,
                sequence=sequence,
                kind=RemoteEventKind.POINTER,
                payload={"square": square},
            )
        )
    return {
        "lesson_session": lesson_session,
        "remote_session_log": log,
    }


class EducationRecordsTests(unittest.TestCase):
    def test_round_trip_reopen_is_deterministic_and_lossless(self):
        classroom = sample_classroom()
        ledger = er.EducationLedger.empty(classroom)
        ledger = submit(
            ledger, classroom, "s1", "sub1", "op1", "response.s1.1"
        )
        ledger = er.checkpoint_remote_session(
            ledger,
            classroom,
            record_id="remote1",
            operation_id="op2",
            **remote_checkpoint(7),
            started_at=STAMP,
            closed_at=None,
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
            **remote_checkpoint(1),
            started_at=STAMP,
            closed_at=None,
            expected_session_revision=0,
            expected_revision=ledger.revision,
        )
        s1_view = ledger.student_view(classroom, "s1")
        s2_view = ledger.student_view(classroom, "s2")
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

    def test_student_view_projects_progress_from_canonical_classroom_only(self):
        classroom = sample_classroom(with_progress=True)
        ledger = er.EducationLedger.empty(classroom)
        s1_view = ledger.student_view(classroom, "s1")
        s2_view = ledger.student_view(classroom, "s2")
        self.assertEqual(s1_view.progress, classroom.progress)
        self.assertEqual(s2_view.progress, ())
        self.assertFalse(hasattr(ledger, "progress_events"))
        record = ledger.to_record()
        self.assertNotIn("progress", record)
        self.assertNotIn("progress_events", record)

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

    def test_remote_checkpoint_retry_is_idempotent_before_global_cas(self):
        classroom = sample_classroom()
        ledger = er.EducationLedger.empty(classroom)
        committed = er.checkpoint_remote_session(
            ledger,
            classroom,
            record_id="remote1",
            operation_id="op1",
            **remote_checkpoint(10),
            started_at=STAMP,
            closed_at=None,
            expected_session_revision=0,
            expected_revision=0,
        )
        retry = er.checkpoint_remote_session(
            committed,
            classroom,
            record_id="remote1",
            operation_id="op1",
            **remote_checkpoint(10),
            started_at=STAMP,
            closed_at=None,
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
            **remote_checkpoint(10),
            started_at=STAMP,
            closed_at=None,
            expected_session_revision=0,
            expected_revision=0,
        )
        ledger = er.checkpoint_remote_session(
            ledger,
            classroom,
            record_id="remote1",
            operation_id="op2",
            **remote_checkpoint(11),
            started_at=STAMP,
            closed_at=None,
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
                **remote_checkpoint(10),
                started_at=STAMP,
                closed_at=None,
                expected_session_revision=1,
                expected_revision=2,
            )
        with self.assertRaises(er.EducationRecordsError):
            er.checkpoint_remote_session(
                ledger,
                classroom,
                record_id="remote1",
                operation_id="op4",
                **remote_checkpoint(11, variant=1),
                started_at=STAMP,
                closed_at=None,
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
            **remote_checkpoint(1, student_ids=("s1",)),
            started_at=STAMP,
            closed_at=None,
            expected_session_revision=0,
            expected_revision=0,
        )
        ledger = er.checkpoint_remote_session(
            ledger,
            classroom,
            record_id="remote1",
            operation_id="op2",
            **remote_checkpoint(2, student_ids=("s1",)),
            started_at=STAMP,
            closed_at="2026-08-23T13:30:00Z",
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
                **remote_checkpoint(3, student_ids=("s1",)),
                started_at=STAMP,
                closed_at=None,
                expected_session_revision=1,
                expected_revision=2,
            )
        with self.assertRaises(er.EducationRecordsError):
            er.checkpoint_remote_session(
                ledger,
                classroom,
                record_id="remote1",
                operation_id="op4",
                **remote_checkpoint(3, student_ids=("s1",)),
                started_at=STAMP,
                closed_at="2026-08-23T13:30:00Z",
                expected_session_revision=1,
                expected_revision=2,
            )
        self.assertEqual(ledger.to_json(), before)

    def test_reconcile_after_deletion_purges_private_state_and_advances_session_cas(self):
        classroom = sample_classroom(with_progress=True)
        ledger = er.EducationLedger.empty(classroom)
        ledger = submit(
            ledger, classroom, "s1", "sub1", "op1", "private.s1"
        )
        ledger = submit(
            ledger, classroom, "s2", "sub2", "op2", "private.s2"
        )
        ledger = er.checkpoint_remote_session(
            ledger,
            classroom,
            record_id="remote1",
            operation_id="op3",
            **remote_checkpoint(3),
            started_at=STAMP,
            closed_at=None,
            expected_session_revision=0,
            expected_revision=ledger.revision,
        )
        deleted = cd.delete_student(classroom, "s1", 0)
        self.assertEqual(deleted.progress, ())
        original_revision = ledger.revision
        reconciled = er.reconcile_classroom(
            ledger,
            deleted,
            operation_id="op4",
            expected_revision=original_revision,
        )
        self.assertEqual(
            tuple(item.student_id for item in reconciled.submissions), ("s2",)
        )
        session = reconciled.remote_sessions[0]
        self.assertEqual(session.student_ids, ("s2",))
        self.assertEqual(session.revision, 1)
        self.assertEqual(reconciled.classroom_digest, deleted.digest)
        self.assertEqual(
            er.EducationLedger.from_json(reconciled.to_json()), reconciled
        )
        with self.assertRaises(er.EducationRecordsError):
            reconciled.student_view(deleted, "s1")
        self.assertEqual(
            reconciled.student_view(deleted, "s2").student_id, "s2"
        )

        retry = er.reconcile_classroom(
            reconciled,
            deleted,
            operation_id="op4",
            expected_revision=original_revision,
        )
        self.assertIs(retry, reconciled)

        continued = er.checkpoint_remote_session(
            reconciled,
            deleted,
            record_id="remote1",
            operation_id="op5",
            **remote_checkpoint(4, student_ids=("s2",)),
            started_at=STAMP,
            closed_at=None,
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
