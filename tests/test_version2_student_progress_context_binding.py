from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from acs.acsdb import AcsDatabase
from acs.analysis_service import AnalysisService
from acs.book_progress_store import BookProgressStore
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
from acs.engine_assisted_workflows import EngineAssistedWorkflowService
from acs.student_progress import (
    ReviewKind,
    StudentProgressLedger,
    StudentReviewRecord,
)
from acs.student_progress_store import StudentProgressStore
from acs.teaching_session import (
    LessonSession,
    PositionSourceKind,
    TeachingActivity,
    TeachingPositionSource,
    TeachingStep,
    default_policy,
)
from acs.version2_final_product_application import Version2FinalProductApplication


class Version2StudentProgressContextBindingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.database = AcsDatabase(self.root / "library.acsdb")
        self.addCleanup(self.database.close)
        self.analysis = AnalysisService(lambda: None)
        self.addCleanup(self.analysis.close)
        self.app = Version2FinalProductApplication(
            self.database,
            progress_store=BookProgressStore(self.root / "book-progress.json"),
            engine_assistance=EngineAssistedWorkflowService(self.analysis),
            board_dispatch=lambda *_: None,
            board_position_projector=lambda fen: {"ok": bool(fen)},
            copy_text=lambda _text: None,
            education_workspace_path=self.root / "education-workspace.json",
        )
        self.app.replace_education_workspace(
            EducationWorkspace.empty(self._classroom()),
            expected_revision=None,
        )
        self.app.start_teaching_session(self._plan())

    @staticmethod
    def _classroom() -> ClassroomSnapshot:
        return ClassroomSnapshot(
            students=(
                Student("student-1", "Knight", ConsentState.GRANTED),
                Student("student-2", "Bishop", ConsentState.GRANTED),
            ),
            classes=(ClassroomClass("class-1", "Class", ("group-1",)),),
            groups=(Group("group-1", "class-1", "Group"),),
            courses=(Course("course-1", "Course", ("lesson-1",)),),
            cohorts=(
                Cohort(
                    "cohort-1",
                    "course-1",
                    ("student-1", "student-2"),
                    "group-1",
                ),
            ),
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

    @staticmethod
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

    @staticmethod
    def _ledger() -> StudentProgressLedger:
        ledger = StudentProgressLedger()
        ledger.append(
            StudentReviewRecord(
                record_id="review-1",
                student_id="student-1",
                session_id="session-1",
                kind=ReviewKind.TRAINING,
                source_id="exercise-1",
                source_revision="revision-1",
                sequence=1,
                attempts=5,
                mistakes=1,
                hints_used=1,
                completed=True,
            )
        )
        return ledger

    def test_bound_store_projects_only_factual_aggregate_context(self) -> None:
        store = StudentProgressStore(self.root / "student-progress.json")
        store.save(self._ledger(), expected_revision=None)
        self.app.bind_student_progress_store(store)

        payload = self.app.current_student_coaching_context("student-1")

        self.assertEqual("Knight", payload["student_label"])
        self.assertEqual(1, payload["record_count"])
        self.assertEqual(5, payload["attempts"])
        self.assertEqual(1, payload["mistakes"])
        self.assertEqual("80.0%", payload["accuracy_percent"])
        self.assertNotIn("student_id", payload)
        self.assertNotIn("session_id", payload)
        self.assertNotIn("exercise-1", repr(payload))
        status = self.app.snapshot()["product_status"]
        self.assertTrue(status["student_progress_available"])
        self.assertFalse(status["student_progress_recovery_required"])

    def test_missing_progress_file_is_neutral_not_corrupt(self) -> None:
        store = StudentProgressStore(self.root / "student-progress.json")
        self.app.bind_student_progress_store(store)

        payload = self.app.current_student_coaching_context("student-1")

        self.assertEqual(0, payload["record_count"])
        self.assertIsNone(payload["accuracy_percent"])
        self.assertIn("Knight", payload["accessible_text"])
        self.assertTrue(self.app.snapshot()["product_status"]["student_progress_available"])

    def test_corrupt_progress_never_becomes_clean_first_run_and_can_recover(self) -> None:
        path = self.root / "student-progress.json"
        path.write_bytes(b"{not-json")
        store = StudentProgressStore(path)

        self.app.bind_student_progress_store(store)
        status = self.app.snapshot()["product_status"]
        self.assertFalse(status["student_progress_available"])
        self.assertTrue(status["student_progress_recovery_required"])
        with self.assertRaisesRegex(RuntimeError, "requires recovery"):
            self.app.current_student_coaching_context("student-1")

        path.unlink()
        store.save(self._ledger(), expected_revision=None)
        payload = self.app.current_student_coaching_context("student-1")
        self.assertEqual(1, payload["record_count"])
        status = self.app.snapshot()["product_status"]
        self.assertTrue(status["student_progress_available"])
        self.assertFalse(status["student_progress_recovery_required"])

    def test_context_is_scoped_to_application_owned_active_lesson(self) -> None:
        store = StudentProgressStore(self.root / "student-progress.json")
        self.app.bind_student_progress_store(store)

        with self.assertRaisesRegex(RuntimeError, "outside the active teaching session"):
            self.app.current_student_coaching_context("student-2")

        self.app.stop_teaching_session()
        with self.assertRaisesRegex(RuntimeError, "No application-owned teaching session"):
            self.app.current_student_coaching_context("student-1")

    def test_different_progress_store_cannot_replace_bound_authority(self) -> None:
        first = StudentProgressStore(self.root / "student-progress.json")
        second = StudentProgressStore(self.root / "other-progress.json")
        self.app.bind_student_progress_store(first)

        with self.assertRaisesRegex(RuntimeError, "already bound"):
            self.app.bind_student_progress_store(second)


if __name__ == "__main__":
    unittest.main()
