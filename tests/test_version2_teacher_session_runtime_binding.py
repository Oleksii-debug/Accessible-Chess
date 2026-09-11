from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from acs.acsdb import AcsDatabase
from acs.analysis_service import AnalysisService
from acs.book_progress_store import BookProgressStore
from acs.chesscore import Board
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
from acs.teaching_session import (
    LessonSession,
    PositionSourceKind,
    TeachingActivity,
    TeachingPositionSource,
    TeachingStep,
    default_policy,
)
from acs.version2_final_product_application import Version2FinalProductApplication


class Version2TeacherSessionRuntimeBindingTests(unittest.TestCase):
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
        classroom = self._classroom()
        self.app.replace_education_workspace(
            EducationWorkspace.empty(classroom),
            expected_revision=None,
        )

    @staticmethod
    def _classroom() -> ClassroomSnapshot:
        return ClassroomSnapshot(
            students=(Student("student-1", "Anna", ConsentState.GRANTED),),
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
                    "2026-09-11T12:00:00Z",
                ),
            ),
        )

    @staticmethod
    def _plan(*, lesson_id: str = "lesson-1") -> LessonSession:
        activity = TeachingActivity.TEACHER_EXPLAINS
        return LessonSession(
            "session-1",
            lesson_id,
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

    def test_trusted_start_binds_teacher_to_one_canonical_session_revision(self) -> None:
        started = self.app.start_teaching_session(self._plan())
        self.assertEqual(0, started.revision)
        self.assertEqual(Board.START, started.position_fen)
        self.assertTrue(self.app.snapshot()["product_status"]["teacher_session_active"])

        event = self.app.browser_command(
            "teacher",
            "teacher.pointer_input",
            {"coordinate": "e4"},
        )

        self.assertEqual("render-pointer", event["kind"])
        state = self.app._owned_teaching_state()
        self.assertEqual(1, state.revision)
        self.assertEqual(Board.START, state.position_fen)
        self.assertEqual("e4", state.presentation.pointer.square)
        self.assertEqual("e4", event["payload"]["snapshot"]["pointer"]["square"])

    def test_invalid_d10_scope_fails_before_teacher_surface_is_published(self) -> None:
        with self.assertRaises(Exception):
            self.app.start_teaching_session(self._plan(lesson_id="missing-lesson"))

        self.assertIsNone(self.app.teacher)
        self.assertIsNone(self.app._teaching_plan)
        self.assertIsNone(self.app._teaching_state)
        self.assertFalse(self.app.snapshot()["product_status"]["teacher_session_active"])

    def test_changed_classroom_scope_rejects_mutation_without_advancing_state(self) -> None:
        self.app.start_teaching_session(self._plan())
        before = self.app._owned_teaching_state()
        revision = self.app.education_revision
        self.app.replace_education_workspace(
            EducationWorkspace.empty(ClassroomSnapshot()),
            expected_revision=revision,
        )

        event = self.app.browser_command(
            "teacher",
            "teacher.pointer_input",
            {"coordinate": "e4"},
        )

        self.assertEqual("error", event["kind"])
        after = self.app._owned_teaching_state()
        self.assertIs(after, before)
        self.assertEqual(0, after.revision)
        self.assertEqual(Board.START, after.position_fen)
        self.assertIsNone(after.presentation.pointer.square)

    def test_stop_unbinds_teacher_and_discards_only_live_session_ownership(self) -> None:
        self.app.start_teaching_session(self._plan())
        self.app.stop_teaching_session()

        self.assertIsNone(self.app.teacher)
        self.assertIsNone(self.app._teaching_plan)
        self.assertIsNone(self.app._teaching_state)
        self.assertEqual(
            "error",
            self.app.browser_command("teacher", "teacher.snapshot")["kind"],
        )
        self.assertFalse(self.app.snapshot()["product_status"]["teacher_session_active"])

    def test_external_binding_cannot_replace_application_owned_session(self) -> None:
        self.app.start_teaching_session(self._plan())

        with self.assertRaises(RuntimeError):
            self.app.bind_teaching_session(
                self.app._owned_teaching_state,
                lambda _action_id, _payload: None,
            )

        state = self.app._owned_teaching_state()
        self.assertEqual(0, state.revision)
        self.assertIsNotNone(self.app.teacher)


if __name__ == "__main__":
    unittest.main()
