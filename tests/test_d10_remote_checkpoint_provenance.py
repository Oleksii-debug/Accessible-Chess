from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from acs import classroom_domain as cd
from acs import education_workspace as ew
from acs import education_workspace_store as ews
from acs.remote_session import RemoteEventKind, RemoteSessionEvent, RemoteSessionLog
from acs.teaching_session import (
    LessonSession,
    PositionSourceKind,
    TeachingActivity,
    TeachingPositionSource,
    TeachingStep,
    default_policy,
)


STAMP = "2026-08-24T13:45:00Z"


def classroom() -> cd.ClassroomSnapshot:
    students = (cd.Student("s1", "Knight-17"), cd.Student("s2", "Bishop-9"))
    lesson = cd.Lesson("lesson1", "course1", "Remote lesson", (), STAMP)
    course = cd.Course("course1", "Endgames", ("lesson1",))
    cohort = cd.Cohort("cohort1", "course1", ("s1", "s2"))
    return cd.ClassroomSnapshot(
        students=students,
        courses=(course,),
        cohorts=(cohort,),
        lessons=(lesson,),
    )


def lesson_session(
    *,
    session_id: str = "session1",
    student_ids: tuple[str, ...] = ("s1", "s2"),
) -> LessonSession:
    activity = TeachingActivity.TEACHER_EXPLAINS
    return LessonSession(
        session_id=session_id,
        lesson_id="lesson1",
        source=TeachingPositionSource(PositionSourceKind.START),
        steps=(
            TeachingStep(
                "step1",
                activity,
                "Remote lesson",
                default_policy(activity),
            ),
        ),
        student_ids=student_ids,
        cohort_id="cohort1",
    )


def remote_log(
    sequence: int,
    *,
    session_id: str = "session1",
    final_square: str = "a1",
) -> RemoteSessionLog:
    log = RemoteSessionLog(session_id)
    for index in range(1, sequence + 1):
        square = final_square if index == sequence else "a1"
        log.append(
            RemoteSessionEvent(
                session_id=session_id,
                sequence=index,
                kind=RemoteEventKind.POINTER,
                payload={"square": square},
            )
        )
    return log


def checkpoint(
    workspace: ew.EducationWorkspace,
    plan: LessonSession,
    log: RemoteSessionLog,
    *,
    operation_id: str,
    expected_session_revision: int,
    expected_revision: int,
    closed_at: str | None = None,
) -> ew.EducationWorkspace:
    return ew.checkpoint_remote_session(
        workspace,
        record_id="remote1",
        operation_id=operation_id,
        lesson_session=plan,
        remote_session_log=log,
        started_at=STAMP,
        closed_at=closed_at,
        expected_session_revision=expected_session_revision,
        expected_revision=expected_revision,
    )


class D10RemoteCheckpointProvenanceTests(unittest.TestCase):
    def test_forged_digest_fails_before_workspace_mutation(self) -> None:
        workspace = ew.EducationWorkspace.empty(classroom())
        plan = lesson_session()
        log = remote_log(1)
        forged = log.to_snapshot()
        forged["digest"] = "0" * 64
        before = workspace.to_json()

        with patch.object(log, "to_snapshot", return_value=forged):
            with self.assertRaises(ew.EducationWorkspaceError):
                checkpoint(
                    workspace,
                    plan,
                    log,
                    operation_id="forged",
                    expected_session_revision=0,
                    expected_revision=0,
                )
        self.assertEqual(workspace.to_json(), before)

    def test_session_and_participants_come_only_from_canonical_sources(self) -> None:
        workspace = ew.EducationWorkspace.empty(classroom())
        before = workspace.to_json()

        with self.assertRaises(ew.EducationWorkspaceError):
            ew.checkpoint_remote_session(
                workspace,
                record_id="remote1",
                operation_id="caller-values",
                session_id="session1",
                student_ids=("s1", "s2"),
                started_at=STAMP,
                closed_at=None,
                last_remote_sequence=1,
                snapshot_digest="a" * 64,
                expected_session_revision=0,
                expected_revision=0,
            )

        with self.assertRaises(ew.EducationWorkspaceError):
            checkpoint(
                workspace,
                lesson_session(session_id="session1"),
                remote_log(1, session_id="session2"),
                operation_id="wrong-session",
                expected_session_revision=0,
                expected_revision=0,
            )

        plan = lesson_session(student_ids=("s1",))
        log = RemoteSessionLog(plan.session_id)
        log.append(
            RemoteSessionEvent(
                session_id=plan.session_id,
                sequence=1,
                kind=RemoteEventKind.ACTIVE_STUDENT,
                payload={"student_id": "s2"},
            )
        )
        with self.assertRaises(ew.EducationWorkspaceError):
            checkpoint(
                workspace,
                plan,
                log,
                operation_id="wrong-participant",
                expected_session_revision=0,
                expected_revision=0,
            )
        self.assertEqual(workspace.to_json(), before)

    def test_duplicate_stale_and_conflicting_sequences_fail_closed(self) -> None:
        plan = lesson_session()
        initial = ew.EducationWorkspace.empty(classroom())
        first = checkpoint(
            initial,
            plan,
            remote_log(1),
            operation_id="first",
            expected_session_revision=0,
            expected_revision=0,
        )
        before = first.to_json()

        attacks = (
            ("duplicate", remote_log(1), 0, 1),
            ("stale-sequence", remote_log(0), 0, 1),
            ("conflicting-digest", remote_log(1, final_square="b1"), 0, 1),
            ("stale-session-cas", remote_log(2), 9, 1),
        )
        for operation_id, log, session_revision, revision in attacks:
            with self.subTest(operation_id=operation_id):
                with self.assertRaises(ew.EducationWorkspaceError):
                    checkpoint(
                        first,
                        plan,
                        log,
                        operation_id=operation_id,
                        expected_session_revision=session_revision,
                        expected_revision=revision,
                    )
                self.assertEqual(first.to_json(), before)

        exact_retry = checkpoint(
            first,
            plan,
            remote_log(1),
            operation_id="first",
            expected_session_revision=0,
            expected_revision=0,
        )
        self.assertIs(exact_retry, first)

    def test_canonical_checkpoint_store_reopen_and_stale_file_cas(self) -> None:
        plan = lesson_session()
        log1 = remote_log(1)
        committed = checkpoint(
            ew.EducationWorkspace.empty(classroom()),
            plan,
            log1,
            operation_id="first",
            expected_session_revision=0,
            expected_revision=0,
        )
        record = committed.ledger.remote_sessions[0]
        self.assertEqual(record.session_id, plan.session_id)
        self.assertEqual(record.student_ids, plan.student_ids)
        self.assertEqual(record.last_remote_sequence, log1.state.last_sequence)
        self.assertEqual(record.snapshot_digest, log1.to_snapshot()["digest"])

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "education-workspace.json"
            store = ews.EducationWorkspaceStore(path)
            revision1 = store.save(committed, expected_revision=None)
            loaded = store.load()
            self.assertEqual(loaded.workspace, committed)

            advanced = checkpoint(
                loaded.workspace,
                plan,
                remote_log(2),
                operation_id="second",
                expected_session_revision=0,
                expected_revision=1,
            )
            revision2 = store.save(advanced, expected_revision=loaded.revision)
            self.assertNotEqual(revision2, revision1)
            reopened = ews.EducationWorkspaceStore(path).load()
            self.assertEqual(reopened.workspace, advanced)
            self.assertEqual(
                reopened.workspace.ledger.remote_sessions[0].last_remote_sequence,
                2,
            )

            with self.assertRaises(ews.EducationWorkspaceConflictError):
                store.save(committed, expected_revision=revision1)
            self.assertEqual(store.load().workspace, advanced)


if __name__ == "__main__":
    unittest.main()
