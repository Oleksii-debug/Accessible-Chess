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
from acs.classroom_pairing import PairingMode
from acs.classroom_prepared_position_deployment import (
    DeploymentTarget,
    DeploymentTargetKind,
)
from acs.education_workspace import EducationWorkspace, save_prepared_position
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


class Version2ClassroomOrchestrationBindingTests(unittest.TestCase):
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
        workspace = EducationWorkspace.empty(self._classroom())
        workspace = save_prepared_position(
            workspace,
            position_id="prep-1",
            source=TeachingPositionSource(PositionSourceKind.START),
            expected_position_revision=0,
        )
        self.workspace = workspace
        self.app.replace_education_workspace(workspace, expected_revision=None)
        self.app.start_teaching_session(self._plan())

    @staticmethod
    def _classroom() -> ClassroomSnapshot:
        students = tuple(
            Student(f"student-{index}", f"Student {index}", ConsentState.GRANTED)
            for index in range(1, 5)
        )
        return ClassroomSnapshot(
            students=students,
            classes=(ClassroomClass("class-1", "Class", ("group-1",)),),
            groups=(Group("group-1", "class-1", "Group"),),
            courses=(Course("course-1", "Course", ("lesson-1",)),),
            cohorts=(
                Cohort(
                    "cohort-1",
                    "course-1",
                    tuple(item.student_id for item in students),
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
            ("student-1", "student-2", "student-3", "student-4"),
            "cohort-1",
        )

    def test_pairing_plan_retry_and_membership_preserving_override(self) -> None:
        batch = self.app.plan_classroom_pairings(
            batch_id="round-1",
            game_session_ids=("game-1", "game-2"),
            mode=PairingMode.SEQUENTIAL,
            base_seconds=300,
            increment_seconds=2,
        )
        retry = self.app.plan_classroom_pairings(
            batch_id="round-1",
            game_session_ids=("game-1", "game-2"),
            mode=PairingMode.SEQUENTIAL,
            base_seconds=300,
            increment_seconds=2,
        )
        self.assertIs(retry, batch)
        first = batch.pairings[0]
        updated = self.app.override_classroom_pairing(
            pairing_id=first.pairing_id,
            white_student_id=first.black_student_id,
            black_student_id=first.white_student_id,
            base_seconds=600,
            increment_seconds=5,
        )
        changed = updated.pairings[0]
        self.assertEqual(first.game_session_id, changed.game_session_id)
        self.assertEqual(first.white_student_id, changed.black_student_id)
        self.assertEqual(600, changed.base_seconds)
        status = self.app.snapshot()["product_status"]
        self.assertTrue(status["classroom_pairing_planned"])
        self.assertEqual(2, status["classroom_pair_count"])

    def test_pairing_batch_id_cannot_be_reused_with_changed_payload(self) -> None:
        self.app.plan_classroom_pairings(
            batch_id="round-stable",
            game_session_ids=("game-1", "game-2"),
            base_seconds=300,
        )
        with self.assertRaisesRegex(RuntimeError, "reused with changed payload"):
            self.app.plan_classroom_pairings(
                batch_id="round-stable",
                game_session_ids=("game-1", "game-2"),
                base_seconds=301,
            )

    def test_prepared_position_selected_deployment_is_idempotent_and_resolvable(self) -> None:
        target = DeploymentTarget(
            DeploymentTargetKind.SELECTED,
            ("student-1", "student-3"),
        )
        batch = self.app.plan_uniform_prepared_position_deployment(
            batch_id="deploy-1",
            position_id="prep-1",
            target=target,
        )
        retry = self.app.plan_uniform_prepared_position_deployment(
            batch_id="deploy-1",
            position_id="prep-1",
            target=target,
        )
        self.assertIs(retry, batch)
        self.assertEqual(
            ("student-1", "student-3"),
            tuple(item.student_id for item in batch.assignments),
        )
        source = self.app.resolve_prepared_position_assignment(
            batch.assignments[0].assignment_id
        )
        self.assertIs(source.kind, PositionSourceKind.START)
        status = self.app.snapshot()["product_status"]
        self.assertTrue(status["prepared_position_deployment_planned"])
        self.assertEqual(2, status["prepared_position_assignment_count"])

    def test_d10_replacement_invalidates_transient_orchestration_plans(self) -> None:
        self.app.plan_classroom_pairings(
            batch_id="round-clear",
            game_session_ids=("game-1", "game-2"),
        )
        self.app.plan_uniform_prepared_position_deployment(
            batch_id="deploy-clear",
            position_id="prep-1",
        )
        revision = self.app.education_revision
        self.app.replace_education_workspace(
            self.workspace,
            expected_revision=revision,
        )
        self.assertIsNone(self.app.active_pairing_batch)
        self.assertIsNone(self.app.active_prepared_position_deployment)
        status = self.app.snapshot()["product_status"]
        self.assertFalse(status["classroom_pairing_planned"])
        self.assertFalse(status["prepared_position_deployment_planned"])

    def test_stop_teaching_session_discards_transient_classroom_plans(self) -> None:
        self.app.plan_classroom_pairings(
            batch_id="round-stop",
            game_session_ids=("game-1", "game-2"),
        )
        self.app.plan_uniform_prepared_position_deployment(
            batch_id="deploy-stop",
            position_id="prep-1",
        )
        self.app.stop_teaching_session()
        self.assertIsNone(self.app.active_pairing_batch)
        self.assertIsNone(self.app.active_prepared_position_deployment)
        status = self.app.snapshot()["product_status"]
        self.assertFalse(status["teacher_session_active"])
        self.assertFalse(status["classroom_pairing_planned"])
        self.assertFalse(status["prepared_position_deployment_planned"])


if __name__ == "__main__":
    unittest.main()
