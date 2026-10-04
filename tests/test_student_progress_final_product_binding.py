from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from acs.classroom_domain import (
    ClassroomClass,
    ClassroomSnapshot,
    Cohort,
    ConsentState,
    Course,
    Group,
    Lesson,
    Student,
)
from acs.education_workspace import EducationWorkspace
from acs.student_progress import (
    ReviewKind,
    StudentProgressLedger,
    StudentReviewRecord,
)
from acs.teaching_session import (
    LessonSession,
    PositionSourceKind,
    TeachingActivity,
    TeachingPositionSource,
    TeachingStep,
    default_policy,
)
from acs.version2_upgrade_status_release import create_version2_release_application


class _Engine:
    def analyze(self, fen, multipv=5, depth=16):
        return ()

    def best_move(self, fen, skill_level=10, movetime_ms=500):
        return None

    def close(self):
        return None


class _Runtime:
    def __init__(self) -> None:
        self.engine = _Engine()
        self.closed = False

    def provider(self):
        if self.closed:
            raise RuntimeError("test engine runtime is closed")
        return self.engine

    def close(self) -> None:
        self.engine.close()
        self.closed = True


class _SilentPlayback:
    def play(self, event, *, volume):
        return None


def _classroom() -> ClassroomSnapshot:
    return ClassroomSnapshot(
        students=(Student("student-1", "Knight", ConsentState.GRANTED),),
        classes=(ClassroomClass("class-1", "Class", ("group-1",)),),
        groups=(Group("group-1", "class-1", "Group"),),
        courses=(Course("course-1", "Course", ("lesson-1",)),),
        cohorts=(Cohort("cohort-1", "course-1", ("student-1",), "group-1"),),
        lessons=(
            Lesson(
                "lesson-1",
                "course-1",
                "Lesson",
                (),
                "2026-10-04T10:00:00Z",
            ),
        ),
    )


def _plan() -> LessonSession:
    activity = TeachingActivity.TEACHER_EXPLAINS
    return LessonSession(
        "session-1",
        "lesson-1",
        TeachingPositionSource(PositionSourceKind.START),
        (
            TeachingStep(
                "step-1",
                activity,
                "Explain the position",
                default_policy(activity),
            ),
        ),
        ("student-1",),
        "cohort-1",
    )


class StudentProgressFinalProductBindingTests(unittest.TestCase):
    def test_release_composition_binds_progress_store_to_canonical_data_root(self) -> None:
        runtime = _Runtime()
        application = None
        api = None
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "v2-user-data"
            try:
                api, application, composed_runtime, _native_runtime_factory = (
                    create_version2_release_application(
                        runtime_factory=lambda _config: runtime,
                        sound_playback=_SilentPlayback(),
                        data_root=root,
                        copy_text=lambda _value: None,
                    )
                )
                self.assertIs(composed_runtime, runtime)
                store = application._student_progress_store
                self.assertIsNotNone(store)
                assert store is not None
                self.assertEqual(root / "student-progress.json", store.path)

                ledger = StudentProgressLedger()
                ledger.append(
                    StudentReviewRecord(
                        record_id="review-1",
                        student_id="student-1",
                        session_id="session-1",
                        kind=ReviewKind.GAME,
                        source_id="game-1",
                        source_revision="revision-1",
                        sequence=1,
                        attempts=0,
                        mistakes=0,
                        hints_used=0,
                        completed=True,
                    )
                )
                store.save(ledger, expected_revision=None)

                application.replace_education_workspace(
                    EducationWorkspace.empty(_classroom()),
                    expected_revision=application.education_revision,
                )
                application.start_teaching_session(_plan())
                payload = application.current_student_coaching_context("student-1")
                self.assertEqual(1, payload["record_count"])
                self.assertEqual(1, payload["game_reviews"])
                self.assertNotIn("student_id", payload)
                self.assertNotIn("session_id", payload)
            finally:
                try:
                    if application is not None:
                        application.shutdown()
                finally:
                    try:
                        if api is not None:
                            api.close_analysis()
                    finally:
                        runtime.close()
        self.assertTrue(runtime.closed)


if __name__ == "__main__":
    unittest.main()
