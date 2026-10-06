from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from acs.acsdb import AcsDatabase
from acs.analysis_service import AnalysisService
from acs.book_progress_store import BookProgressStore
from acs.child_coaching_application import ChildCoachingApplication
from acs.child_coaching_prepared_positions import ChildCoachingPreparedPositionError
from acs.child_coaching_store import ChildCoachingTemplateStore
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
from acs.education_workspace import EducationWorkspace, save_prepared_position
from acs.engine_assisted_workflows import EngineAssistedWorkflowService
from acs.teaching_session import PositionSourceKind, TeachingPositionSource
from acs.version2_final_product_application import Version2FinalProductApplication


class Version2PreparedChildLessonBindingTests(unittest.TestCase):
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
            position_id="prep-start",
            source=TeachingPositionSource(PositionSourceKind.START),
            expected_position_revision=0,
        )
        workspace = save_prepared_position(
            workspace,
            position_id="prep-fen",
            source=TeachingPositionSource(
                PositionSourceKind.FEN,
                fen="8/8/8/8/8/8/2K5/6k1 w - - 0 1",
            ),
            expected_position_revision=0,
        )
        self.workspace = workspace
        self.app.replace_education_workspace(workspace, expected_revision=None)
        self.child = ChildCoachingApplication(
            ChildCoachingTemplateStore(self.root / "child-coaching.json")
        )
        self.app.bind_child_coaching_application(self.child)

    @staticmethod
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

    def test_next_previous_navigation_never_duplicates_prepared_persistence(self) -> None:
        before = self.workspace.to_json()
        first = self.app.prepared_position_snapshot()
        self.assertEqual("prep-start", first.selected_position_id)
        second = self.app.next_prepared_position()
        self.assertEqual("prep-fen", second.selected_position_id)
        back = self.app.previous_prepared_position()
        self.assertEqual("prep-start", back.selected_position_id)
        self.assertEqual(before, self.app._education_provider().to_json())

    def test_navigation_boundary_fails_without_wrapping_or_mutating_selection(self) -> None:
        self.app.select_prepared_position("prep-fen")
        with self.assertRaisesRegex(
            ChildCoachingPreparedPositionError,
            "boundary reached",
        ):
            self.app.next_prepared_position()
        self.assertEqual(
            "prep-fen",
            self.app.prepared_position_snapshot().selected_position_id,
        )

    def test_one_call_starts_reviewed_template_from_exact_prepared_source(self) -> None:
        catalog = self.app.open_child_coaching_catalog()
        selected = self.app.select_prepared_position("prep-fen")
        selected_summary = next(item for item in selected.positions if item.selected)

        state = self.app.start_prepared_child_lesson(
            "preset-preschool-4-6",
            session_id="prepared-session",
            lesson_id="lesson-1",
            student_ids=("student-1",),
            cohort_id="cohort-1",
            require_no_notation=True,
            expected_template_revision=catalog.revision,
            expected_position_revision=selected_summary.revision,
        )

        self.assertEqual("prepared-session", state.session_id)
        plan = self.app._teaching_plan
        self.assertIsNotNone(plan)
        assert plan is not None
        self.assertIs(plan.source.kind, PositionSourceKind.FEN)
        self.assertEqual(
            "8/8/8/8/8/8/2K5/6k1 w - - 0 1",
            plan.source.fen,
        )
        self.assertTrue(self.app.snapshot()["product_status"]["teacher_session_active"])

    def test_stale_reviewed_position_revision_fails_before_session_publication(self) -> None:
        catalog = self.app.open_child_coaching_catalog()
        selected = self.app.select_prepared_position("prep-fen")
        reviewed = next(item for item in selected.positions if item.selected)

        newer = save_prepared_position(
            self.workspace,
            position_id="prep-fen",
            source=TeachingPositionSource(
                PositionSourceKind.FEN,
                fen="8/8/8/8/8/8/3K4/6k1 w - - 0 1",
            ),
            expected_position_revision=reviewed.revision,
        )
        self.app.replace_education_workspace(
            newer,
            expected_revision=self.app.education_revision,
        )

        with self.assertRaisesRegex(
            ChildCoachingPreparedPositionError,
            "changed; review it before launching",
        ):
            self.app.start_prepared_child_lesson(
                "preset-preschool-4-6",
                session_id="stale-session",
                lesson_id="lesson-1",
                student_ids=("student-1",),
                cohort_id="cohort-1",
                require_no_notation=True,
                expected_template_revision=catalog.revision,
                expected_position_revision=reviewed.revision,
            )
        self.assertIsNone(self.app._teaching_plan)
        self.assertFalse(self.app.snapshot()["product_status"]["teacher_session_active"])

    def test_corrupt_template_catalog_sets_recovery_required_without_blocking_navigation(self) -> None:
        bad_root = self.root / "bad"
        bad_root.mkdir()
        bad_path = bad_root / "child-coaching.json"
        bad_path.write_text("{bad-json", encoding="utf-8")
        other = Version2FinalProductApplication(
            self.database,
            progress_store=BookProgressStore(bad_root / "book-progress.json"),
            engine_assistance=EngineAssistedWorkflowService(self.analysis),
            board_dispatch=lambda *_: None,
            board_position_projector=lambda fen: {"ok": bool(fen)},
            copy_text=lambda _text: None,
            education_workspace_path=bad_root / "education-workspace.json",
        )
        other.replace_education_workspace(self.workspace, expected_revision=None)
        other.bind_child_coaching_application(
            ChildCoachingApplication(ChildCoachingTemplateStore(bad_path))
        )
        self.assertEqual("prep-start", other.prepared_position_snapshot().selected_position_id)
        with self.assertRaisesRegex(RuntimeError, "templates require recovery"):
            other.open_child_coaching_catalog()
        status = other.snapshot()["product_status"]
        self.assertTrue(status["prepared_position_navigation_available"])
        self.assertTrue(status["child_coaching_recovery_required"])


if __name__ == "__main__":
    unittest.main()
