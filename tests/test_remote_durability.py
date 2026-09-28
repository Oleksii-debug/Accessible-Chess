from __future__ import annotations

from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from acs import classroom_domain as cd
from acs import education_workspace as ew
from acs import education_workspace_store as ews
from acs.remote_durability import D10RemoteDurability, RemoteDurabilityError
from acs.remote_session import RemoteEventKind, RemoteSessionEvent, RemoteSessionLog
from acs.teaching_session import (
    LessonSession,
    PositionSourceKind,
    TeachingActivity,
    TeachingPositionSource,
    TeachingStep,
    default_policy,
)


STAMP = "2026-09-11T14:00:00Z"
CLOSED = "2026-09-11T14:30:00Z"


def classroom() -> cd.ClassroomSnapshot:
    students = (cd.Student("s1", "Student 1"), cd.Student("s2", "Student 2"))
    lesson = cd.Lesson("lesson1", "course1", "Remote lesson", (), STAMP)
    course = cd.Course("course1", "Course", ("lesson1",))
    cohort = cd.Cohort("cohort1", "course1", ("s1", "s2"))
    return cd.ClassroomSnapshot(
        students=students,
        courses=(course,),
        cohorts=(cohort,),
        lessons=(lesson,),
    )


def plan() -> LessonSession:
    activity = TeachingActivity.TEACHER_EXPLAINS
    return LessonSession(
        session_id="session1",
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
        student_ids=("s1", "s2"),
        cohort_id="cohort1",
    )


def log_at(sequence: int) -> RemoteSessionLog:
    log = RemoteSessionLog("session1")
    for index in range(1, sequence + 1):
        log.append(
            RemoteSessionEvent(
                "session1",
                index,
                RemoteEventKind.POINTER,
                {"square": "a1" if index < sequence else "b2"},
                "s1",
            )
        )
    return log


class RemoteDurabilityTests(unittest.TestCase):
    def make_store(self, directory: str) -> ews.EducationWorkspaceStore:
        store = ews.EducationWorkspaceStore(Path(directory) / "education-workspace.json")
        store.save(ew.EducationWorkspace.empty(classroom()), expected_revision=None)
        return store

    def test_checkpoint_uses_existing_workspace_and_persists_exact_log_digest(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = self.make_store(directory)
            durability = D10RemoteDurability(
                store,
                plan(),
                record_id="remote1",
                started_at=STAMP,
            )
            self.assertIsNone(durability.current())

            log = log_at(1)
            point = durability.checkpoint(log, operation_id="remote-checkpoint-1")
            self.assertEqual(point.session_id, "session1")
            self.assertEqual(point.last_sequence, 1)
            self.assertEqual(point.snapshot_digest, log.to_snapshot()["digest"])
            self.assertFalse(point.closed)

            reopened = D10RemoteDurability(
                ews.EducationWorkspaceStore(store.path),
                plan(),
                record_id="remote1",
                started_at=STAMP,
            ).current()
            self.assertEqual(reopened, point)

    def test_advanced_checkpoint_and_close_use_d10_session_and_file_cas(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = self.make_store(directory)
            durability = D10RemoteDurability(
                store,
                plan(),
                record_id="remote1",
                started_at=STAMP,
            )
            first = durability.checkpoint(log_at(1), operation_id="checkpoint-1")
            second_log = log_at(2)
            second = durability.checkpoint(second_log, operation_id="checkpoint-2")
            self.assertGreater(second.ledger_revision, first.ledger_revision)
            self.assertGreater(second.session_revision, first.session_revision)
            self.assertEqual(second.last_sequence, 2)

            closed = durability.checkpoint(
                second_log,
                operation_id="checkpoint-close",
                closed_at=CLOSED,
            )
            self.assertTrue(closed.closed)
            self.assertEqual(closed.closed_at, CLOSED)
            self.assertGreater(closed.session_revision, second.session_revision)

            exact_retry = durability.checkpoint(
                second_log,
                operation_id="checkpoint-close",
                closed_at=CLOSED,
            )
            self.assertEqual(exact_retry, closed)

    def test_closed_checkpoint_cannot_advance_or_reopen(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            durability = D10RemoteDurability(
                self.make_store(directory),
                plan(),
                record_id="remote1",
                started_at=STAMP,
            )
            durability.checkpoint(
                log_at(1),
                operation_id="checkpoint-close",
                closed_at=CLOSED,
            )
            with self.assertRaises(RemoteDurabilityError):
                durability.checkpoint(log_at(2), operation_id="after-close")
            with self.assertRaises(RemoteDurabilityError):
                durability.checkpoint(log_at(1), operation_id="reopen", closed_at=None)

    def test_store_conflict_is_sanitized_and_does_not_publish_false_success(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = self.make_store(directory)
            durability = D10RemoteDurability(
                store,
                plan(),
                record_id="remote1",
                started_at=STAMP,
            )
            with patch.object(
                store,
                "save",
                side_effect=ews.EducationWorkspaceConflictError("stale internal detail"),
            ):
                with self.assertRaisesRegex(
                    RemoteDurabilityError,
                    "remote checkpoint could not be published",
                ):
                    durability.checkpoint(log_at(1), operation_id="conflict")
            self.assertIsNone(durability.current())

    def test_record_identity_mismatch_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = self.make_store(directory)
            first = D10RemoteDurability(
                store,
                plan(),
                record_id="remote1",
                started_at=STAMP,
            )
            first.checkpoint(log_at(1), operation_id="checkpoint-1")
            wrong = D10RemoteDurability(
                store,
                plan(),
                record_id="remote2",
                started_at=STAMP,
            )
            with self.assertRaises(RemoteDurabilityError):
                wrong.current()


if __name__ == "__main__":
    unittest.main()
