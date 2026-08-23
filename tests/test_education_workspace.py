import json
from dataclasses import replace
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from acs import classroom_domain as cd
from acs import education_records as er
from acs import education_workspace as ew
from acs import education_workspace_store as ews


STAMP = "2026-08-23T13:05:00Z"
DIGEST_A = "a" * 64


def sample_classroom() -> cd.ClassroomSnapshot:
    s1 = cd.Student("s1", "Knight-17", cd.ConsentState.GRANTED)
    s2 = cd.Student("s2", "Bishop-9")
    klass = cd.ClassroomClass("class1", "Endgame class", ("group1",))
    group = cd.Group("group1", "class1", "Sunday group")
    lesson = cd.Lesson("lesson1", "course1", "Rook endings", (), STAMP)
    course = cd.Course("course1", "Endgames", ("lesson1",))
    cohort = cd.Cohort("cohort1", "course1", ("s1", "s2"), "group1")
    assignment = cd.Assignment(
        "a1", "lesson1", "cohort1", "Lucena practice", STAMP
    )
    h1 = cd.Homework("h1", "a1", "s1")
    h2 = cd.Homework("h2", "a1", "s2")
    p1 = cd.Progress("p1", "s1", "course1", (), 0)
    p2 = cd.Progress("p2", "s2", "course1", (), 0)
    note = cd.TeacherNote("n1", "s1", "Private coaching note", STAMP)
    return cd.ClassroomSnapshot(
        students=(s1, s2),
        classes=(klass,),
        groups=(group,),
        courses=(course,),
        cohorts=(cohort,),
        lessons=(lesson,),
        assignments=(assignment,),
        homework=(h1, h2),
        progress=(p1, p2),
        teacher_notes=(note,),
    )


def submit(
    workspace: ew.EducationWorkspace,
    *,
    student_id: str = "s1",
    homework_id: str = "h1",
    submission_id: str = "sub1",
    operation_id: str = "submit-op-1",
    response_ref: str = "response.s1.1",
    attempt: int = 1,
    expected_ledger_revision: int | None = None,
) -> ew.EducationWorkspace:
    if expected_ledger_revision is None:
        expected_ledger_revision = workspace.ledger.revision
    return ew.submit_homework(
        workspace,
        homework_id=homework_id,
        submission_id=submission_id,
        operation_id=operation_id,
        student_id=student_id,
        assignment_id="a1",
        response_ref=response_ref,
        submitted_at=STAMP,
        attempt=attempt,
        expected_ledger_revision=expected_ledger_revision,
    )


class EducationWorkspaceDomainTests(unittest.TestCase):
    def test_workspace_round_trip_and_anchor_are_deterministic(self):
        classroom = sample_classroom()
        workspace = ew.EducationWorkspace.empty(classroom)
        text = workspace.to_json()
        restored = ew.EducationWorkspace.from_json(text)
        self.assertEqual(restored, workspace)
        self.assertEqual(restored.to_json(), text)
        self.assertEqual(restored.ledger.classroom_digest, restored.classroom.digest)

        bad_ledger = replace(workspace.ledger, classroom_digest="f" * 64)
        with self.assertRaises(ew.EducationWorkspaceError):
            ew.EducationWorkspace(classroom, bad_ledger)

    def test_submit_homework_commits_current_state_and_history_together(self):
        workspace = ew.EducationWorkspace.empty(sample_classroom())
        committed = submit(workspace)
        current = next(item for item in committed.classroom.homework if item.homework_id == "h1")
        self.assertIs(current.status, cd.HomeworkStatus.SUBMITTED)
        self.assertEqual(current.response_ref, "response.s1.1")
        self.assertEqual(len(committed.ledger.submissions), 1)
        self.assertEqual(committed.ledger.submissions[0].response_ref, "response.s1.1")
        self.assertEqual(committed.ledger.classroom_digest, committed.classroom.digest)
        self.assertEqual(committed.ledger.revision, 2)

        retry = submit(committed, expected_ledger_revision=0)
        self.assertIs(retry, committed)

        before = committed.to_json()
        with self.assertRaises(ew.EducationWorkspaceError):
            submit(
                committed,
                operation_id="submit-op-1",
                response_ref="different.response",
                expected_ledger_revision=0,
            )
        self.assertEqual(committed.to_json(), before)

    def test_attempt_sequence_is_monotonic_and_failure_is_atomic(self):
        workspace = ew.EducationWorkspace.empty(sample_classroom())
        before = workspace.to_json()
        with self.assertRaises(ew.EducationWorkspaceError):
            submit(workspace, attempt=2)
        self.assertEqual(workspace.to_json(), before)

        first = submit(workspace)
        second = submit(
            first,
            submission_id="sub2",
            operation_id="submit-op-2",
            response_ref="response.s1.2",
            attempt=2,
        )
        self.assertEqual(
            tuple(item.attempt for item in second.ledger.submissions),
            (1, 2),
        )
        self.assertEqual(second.ledger.revision, 4)

    def test_consent_withdrawal_and_exact_retry_are_one_atomic_workspace_change(self):
        workspace = ew.EducationWorkspace.empty(sample_classroom())
        changed = ew.set_student_consent(
            workspace,
            student_id="s1",
            consent=cd.ConsentState.WITHDRAWN,
            operation_id="consent-op",
            expected_student_revision=0,
            expected_ledger_revision=0,
        )
        student = next(item for item in changed.classroom.students if item.student_id == "s1")
        self.assertIs(student.consent, cd.ConsentState.WITHDRAWN)
        self.assertEqual(student.revision, 1)
        self.assertEqual(changed.classroom.teacher_notes, ())
        self.assertEqual(changed.ledger.classroom_digest, changed.classroom.digest)

        retry = ew.set_student_consent(
            changed,
            student_id="s1",
            consent=cd.ConsentState.WITHDRAWN,
            operation_id="consent-op",
            expected_student_revision=0,
            expected_ledger_revision=0,
        )
        self.assertIs(retry, changed)

    def test_student_deletion_purges_private_history_and_remote_membership_atomically(self):
        workspace = ew.EducationWorkspace.empty(sample_classroom())
        workspace = ew.checkpoint_remote_session(
            workspace,
            record_id="remote1",
            operation_id="remote-op",
            session_id="session1",
            student_ids=("s1", "s2"),
            started_at=STAMP,
            closed_at=None,
            last_remote_sequence=4,
            snapshot_digest=DIGEST_A,
            expected_session_revision=0,
            expected_revision=0,
        )
        workspace = submit(
            workspace,
            expected_ledger_revision=workspace.ledger.revision,
        )
        before_revision = workspace.ledger.revision
        deleted = ew.delete_student(
            workspace,
            student_id="s1",
            operation_id="delete-op",
            expected_student_revision=0,
            expected_ledger_revision=before_revision,
        )

        student = next(item for item in deleted.classroom.students if item.student_id == "s1")
        self.assertTrue(student.deleted)
        self.assertEqual(student.pseudonym, "")
        self.assertEqual(tuple(item.student_id for item in deleted.ledger.submissions), ())
        self.assertEqual(deleted.ledger.remote_sessions[0].student_ids, ("s2",))
        self.assertEqual(deleted.ledger.remote_sessions[0].revision, 1)
        self.assertFalse(any(item.student_id == "s1" for item in deleted.classroom.homework))
        self.assertFalse(any(item.student_id == "s1" for item in deleted.classroom.progress))
        self.assertEqual(deleted.ledger.classroom_digest, deleted.classroom.digest)
        with self.assertRaises(er.EducationRecordsError):
            deleted.student_view("s1")

        retry = ew.delete_student(
            deleted,
            student_id="s1",
            operation_id="delete-op",
            expected_student_revision=0,
            expected_ledger_revision=before_revision,
        )
        self.assertIs(retry, deleted)

    def test_deleted_student_tombstone_cannot_disappear_or_revive(self):
        workspace = ew.EducationWorkspace.empty(sample_classroom())
        deleted = ew.delete_student(
            workspace,
            student_id="s1",
            operation_id="delete-op",
            expected_student_revision=0,
            expected_ledger_revision=0,
        )
        s2 = next(item for item in deleted.classroom.students if item.student_id == "s2")
        disappeared = replace(deleted.classroom, students=(s2,))
        with self.assertRaises(ew.EducationWorkspaceError):
            ew.commit_classroom(
                deleted,
                disappeared,
                operation_id="bad-drop",
                expected_ledger_revision=deleted.ledger.revision,
            )

        revived = replace(
            deleted.classroom,
            students=(cd.Student("s1", "Revived"), s2),
        )
        with self.assertRaises(ew.EducationWorkspaceError):
            ew.commit_classroom(
                deleted,
                revived,
                operation_id="bad-revive",
                expected_ledger_revision=deleted.ledger.revision,
            )

    def test_duplicate_keys_future_version_and_outer_tamper_fail_closed(self):
        workspace = ew.EducationWorkspace.empty(sample_classroom())
        with self.assertRaises(ew.EducationWorkspaceError):
            ew.EducationWorkspace.from_json('{"version":1,"version":1}')
        record = workspace.to_record()
        record["version"] = 2
        with self.assertRaises(ew.EducationWorkspaceError):
            ew.EducationWorkspace.from_record(record)
        record = workspace.to_record()
        record["digest"] = "0" * 64
        with self.assertRaises(ew.EducationWorkspaceError):
            ew.EducationWorkspace.from_record(record)


class EducationWorkspaceStoreTests(unittest.TestCase):
    def test_store_create_load_update_and_stale_writer(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "education-workspace.json"
            store = ews.EducationWorkspaceStore(path)
            workspace = ew.EducationWorkspace.empty(sample_classroom())
            rev0 = store.save(workspace, expected_revision=None)
            loaded = store.load()
            self.assertIsNotNone(loaded)
            self.assertEqual(loaded.workspace, workspace)
            self.assertEqual(loaded.revision, rev0)

            changed = submit(loaded.workspace)
            rev1 = store.save(changed, expected_revision=loaded.revision)
            self.assertNotEqual(rev1, rev0)
            reopened = store.load()
            self.assertEqual(reopened.workspace, changed)
            with self.assertRaises(ews.EducationWorkspaceConflictError):
                store.save(workspace, expected_revision=rev0)
            self.assertEqual(store.load().workspace, changed)

    def test_store_peer_lock_and_replace_failure_preserve_durable_workspace(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "education-workspace.json"
            store = ews.EducationWorkspaceStore(path)
            workspace = ew.EducationWorkspace.empty(sample_classroom())
            revision = store.save(workspace, expected_revision=None)
            original = path.read_bytes()

            store._lock_path.mkdir()
            try:
                with self.assertRaises(ews.EducationWorkspaceBusyError):
                    store.save(submit(workspace), expected_revision=revision)
            finally:
                store._lock_path.rmdir()
            self.assertEqual(path.read_bytes(), original)

            changed = submit(workspace)
            with patch("acs.education_workspace_store.os.replace", side_effect=OSError("boom")):
                with self.assertRaises(OSError):
                    store.save(changed, expected_revision=revision)
            self.assertEqual(path.read_bytes(), original)
            self.assertFalse(store._lock_path.exists())
            self.assertEqual(list(Path(tmp).glob(".education-workspace.json.*.tmp")), [])

    def test_store_rejects_oversize_corruption_and_unknown_schema(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "education-workspace.json"
            store = ews.EducationWorkspaceStore(path)
            workspace = ew.EducationWorkspace.empty(sample_classroom())
            store.save(workspace, expected_revision=None)

            path.write_text(
                json.dumps({"schema_version": 99, "workspace": workspace.to_record()}),
                encoding="utf-8",
            )
            with self.assertRaises(ews.EducationWorkspaceStoreError):
                store.load()

            path.write_bytes(b'{"schema_version":1,"schema_version":1}')
            with self.assertRaises(ews.EducationWorkspaceStoreError):
                store.load()

            path.write_bytes(b"x" * 64)
            with patch.object(ews, "MAX_WORKSPACE_STORE_BYTES", 10):
                with self.assertRaises(ews.EducationWorkspaceStoreError):
                    store.load()

    def test_store_revision_and_path_boundaries_are_exact(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = ew.EducationWorkspace.empty(sample_classroom())
            store = ews.EducationWorkspaceStore(Path(tmp) / "workspace.json")
            with self.assertRaises(ews.EducationWorkspaceStoreError):
                store.save(workspace, expected_revision=True)
            with self.assertRaises(ews.EducationWorkspaceStoreError):
                store.save(workspace, expected_revision="A" * 64)
        with self.assertRaises(TypeError):
            ews.EducationWorkspaceStore(123)
        with self.assertRaises(ValueError):
            ews.EducationWorkspaceStore(".")


if __name__ == "__main__":
    unittest.main()
