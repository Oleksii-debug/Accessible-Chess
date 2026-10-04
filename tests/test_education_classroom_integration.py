from pathlib import Path
import tempfile
import unittest

from acs import classroom_domain as cd
from acs import education_workspace as ew
from acs import education_workspace_store as ews
from acs.remote_session import RemoteEventKind, RemoteSessionEvent, RemoteSessionLog
from acs.teaching_classroom_adapter import (
    TEACHER_SET_ACTIVE_STUDENT_ACTION_ID,
    apply_classroom_action,
    classroom_view_to_payload,
    project_classroom_view,
)
from acs.teaching_session import (
    LessonSession,
    PositionSourceKind,
    TeachingActivity,
    TeachingPositionSource,
    TeachingStep,
    default_policy,
    start_session,
)
from acs.teaching_session_adapter import TeachingAudience


STAMP = "2026-08-24T14:20:00Z"


def classroom() -> cd.ClassroomSnapshot:
    return cd.ClassroomSnapshot(
        students=(
            cd.Student("s1", "Knight-17", cd.ConsentState.GRANTED),
            cd.Student("s2", "Bishop-9", cd.ConsentState.GRANTED),
        ),
        classes=(cd.ClassroomClass("class1", "Class", ("group1",)),),
        groups=(cd.Group("group1", "class1", "Group"),),
        courses=(cd.Course("course1", "Course", ("lesson1",)),),
        cohorts=(cd.Cohort("cohort1", "course1", ("s1", "s2"), "group1"),),
        lessons=(cd.Lesson("lesson1", "course1", "Lesson", (), STAMP),),
    )


def lesson_session() -> LessonSession:
    activity = TeachingActivity.MAKE_MOVE
    return LessonSession(
        session_id="session1",
        lesson_id="lesson1",
        source=TeachingPositionSource(PositionSourceKind.START),
        steps=(
            TeachingStep(
                "step1",
                activity,
                "Play e4",
                default_policy(activity),
            ),
        ),
        student_ids=("s1", "s2"),
        cohort_id="cohort1",
    )


class EducationClassroomIntegrationTests(unittest.TestCase):
    def test_live_classroom_remote_checkpoint_and_reopen_are_one_provenance_chain(self) -> None:
        roster = classroom()
        plan = lesson_session()
        state = start_session(plan)

        state = apply_classroom_action(
            plan,
            state,
            roster,
            TEACHER_SET_ACTIVE_STUDENT_ACTION_ID,
            {"student_id": "s1"},
            expected_revision=0,
        )
        state = apply_classroom_action(
            plan,
            state,
            roster,
            "student.hover",
            {"square": "g8"},
            expected_revision=1,
            actor_student_id="s2",
        )
        state = apply_classroom_action(
            plan,
            state,
            roster,
            "student.move",
            {"raw_text": "e4"},
            expected_revision=2,
            actor_student_id="s1",
        )

        student_two = classroom_view_to_payload(
            project_classroom_view(
                plan,
                state,
                roster,
                audience=TeachingAudience.STUDENT,
                viewer_student_id="s2",
            )
        )
        self.assertNotIn("Knight-17", repr(student_two))
        self.assertNotIn('"s1"', repr(student_two))
        self.assertFalse(student_two["session"]["viewer_is_active"])

        remote = RemoteSessionLog(plan.session_id)
        remote.extend(
            (
                RemoteSessionEvent(
                    plan.session_id,
                    1,
                    RemoteEventKind.POSITION,
                    payload={"fen": state.position_fen},
                ),
                RemoteSessionEvent(
                    plan.session_id,
                    2,
                    RemoteEventKind.ACTIVE_STUDENT,
                    payload={"student_id": "s1"},
                ),
                RemoteSessionEvent(
                    plan.session_id,
                    3,
                    RemoteEventKind.POINTER,
                    actor_id="s2",
                    payload={"square": "g8"},
                ),
            )
        )
        self.assertEqual(remote.state.position_fen, state.position_fen)
        self.assertEqual(remote.state.active_student_id, state.active_student_id)

        workspace = ew.checkpoint_remote_session(
            ew.EducationWorkspace.empty(roster),
            record_id="remote1",
            operation_id="checkpoint1",
            lesson_session=plan,
            remote_session_log=remote,
            started_at=STAMP,
            closed_at=None,
            expected_session_revision=0,
            expected_revision=0,
        )
        record = workspace.ledger.remote_sessions[0]
        self.assertEqual(record.session_id, plan.session_id)
        self.assertEqual(record.student_ids, plan.student_ids)
        self.assertEqual(record.last_remote_sequence, remote.state.last_sequence)
        self.assertEqual(record.snapshot_digest, remote.to_snapshot()["digest"])

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "education-workspace.json"
            store = ews.EducationWorkspaceStore(path)
            revision = store.save(workspace, expected_revision=None)
            reopened = ews.EducationWorkspaceStore(path).load()
            self.assertEqual(reopened.revision, revision)
            self.assertEqual(reopened.workspace, workspace)
            self.assertEqual(reopened.workspace.classroom, roster)

            stale = RemoteSessionLog(plan.session_id)
            stale.append(
                RemoteSessionEvent(
                    plan.session_id,
                    1,
                    RemoteEventKind.POSITION,
                    payload={"fen": state.position_fen},
                )
            )
            before = reopened.workspace.to_json()
            with self.assertRaises(ew.EducationWorkspaceError):
                ew.checkpoint_remote_session(
                    reopened.workspace,
                    record_id="remote1",
                    operation_id="stale",
                    lesson_session=plan,
                    remote_session_log=stale,
                    started_at=STAMP,
                    closed_at=None,
                    expected_session_revision=0,
                    expected_revision=1,
                )
            self.assertEqual(reopened.workspace.to_json(), before)
