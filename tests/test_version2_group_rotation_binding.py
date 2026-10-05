from __future__ import annotations

from pathlib import Path
import tempfile
import unittest
from unittest import mock

from acs.acsdb import AcsDatabase
from acs.analysis_service import AnalysisService
from acs.book_progress_store import BookProgressStore
from acs.child_coaching_rotation import advance_rotation
from acs.child_coaching_rotation_store import (
    ChildCoachingRotationStore,
    ChildCoachingRotationStoreConflictError,
)
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


class Version2GroupRotationBindingTests(unittest.TestCase):
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
        self.workspace = EducationWorkspace.empty(self._classroom())
        self.app.replace_education_workspace(self.workspace, expected_revision=None)
        self.plan = self._plan()
        self.app.start_teaching_session(self.plan)
        self.store = ChildCoachingRotationStore(
            self.root / "child-coaching-rotation.json"
        )
        self.app.bind_child_coaching_rotation_store(self.store)

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

    def _reach_pair_round(self):
        state = self.app.begin_or_resume_default_group_rotation("rotation-1")
        state = self.app.advance_group_rotation(
            expected_rotation_revision=state.revision
        )
        state = self.app.advance_group_rotation(
            expected_rotation_revision=state.revision
        )
        self.assertEqual("pair_play", self.app.group_rotation_snapshot()["activity"])
        return state

    def test_pair_round_requires_exact_current_pairing_then_advances_to_review(self) -> None:
        state = self._reach_pair_round()
        with self.assertRaisesRegex(
            ValueError,
            "cannot advance before external pair-play batch",
        ):
            self.app.advance_group_rotation(
                expected_rotation_revision=state.revision
            )

        batch = self.app.plan_classroom_pairings(
            batch_id="pair-round-1",
            game_session_ids=("game-1", "game-2"),
            base_seconds=300,
            increment_seconds=2,
        )
        first = batch.pairings[0]
        updated = self.app.override_classroom_pairing(
            pairing_id=first.pairing_id,
            white_student_id=first.black_student_id,
            black_student_id=first.white_student_id,
            base_seconds=600,
            increment_seconds=5,
        )
        self.assertEqual(600, updated.pairings[0].base_seconds)
        self.assertEqual(5, updated.pairings[0].increment_seconds)

        bound = self.app.bind_current_pairing_to_group_rotation(
            expected_rotation_revision=state.revision
        )
        self.assertEqual("pair-round-1", bound.pair_play_batch_ref)
        persisted = self.store.load()
        self.assertIsNotNone(persisted)
        assert persisted is not None
        self.assertEqual(bound, persisted.state)

        review = self.app.advance_group_rotation(
            expected_rotation_revision=bound.revision
        )
        self.assertIsNone(review.pair_play_batch_ref)
        snap = self.app.group_rotation_snapshot()
        self.assertEqual("review", snap["activity"])
        self.assertFalse(snap["pair_play_bound"])

    def test_reconnect_resumes_exact_durable_round_for_same_lesson(self) -> None:
        state = self.app.begin_or_resume_default_group_rotation("rotation-1")
        state = self.app.advance_group_rotation(
            expected_rotation_revision=state.revision
        )
        expected_index = state.round_index
        expected_revision = state.revision

        self.app.stop_teaching_session()
        self.app.start_teaching_session(self.plan)
        resumed = self.app.begin_or_resume_default_group_rotation("rotation-1")

        self.assertEqual(expected_index, resumed.round_index)
        self.assertEqual(expected_revision, resumed.revision)

    def test_different_rotation_id_never_overwrites_existing_durable_rotation(self) -> None:
        self.app.begin_or_resume_default_group_rotation("rotation-1")
        before = self.store.path.read_bytes()
        with self.assertRaisesRegex(RuntimeError, "different durable group rotation"):
            self.app.begin_or_resume_default_group_rotation("rotation-2")
        self.assertEqual(before, self.store.path.read_bytes())

    def test_durable_rotation_for_different_lesson_fails_closed(self) -> None:
        self.app.begin_or_resume_default_group_rotation("rotation-1")
        self.app.stop_teaching_session()
        other = LessonSession(
            "session-2",
            "lesson-1",
            TeachingPositionSource(PositionSourceKind.START),
            self.plan.steps,
            self.plan.student_ids,
            self.plan.cohort_id,
        )
        self.app.start_teaching_session(other)
        with self.assertRaisesRegex(RuntimeError, "different teaching session"):
            self.app.begin_or_resume_default_group_rotation("rotation-1")
        self.assertTrue(
            self.app.snapshot()["product_status"]["group_rotation_recovery_required"]
        )

    def test_advance_store_io_failure_marks_rotation_recovery_required(self) -> None:
        state = self.app.begin_or_resume_default_group_rotation("rotation-1")
        with mock.patch.object(
            self.store,
            "save",
            side_effect=OSError("simulated durable sync failure"),
        ):
            with self.assertRaisesRegex(OSError, "durable sync failure"):
                self.app.advance_group_rotation(
                    expected_rotation_revision=state.revision
                )
        self.assertTrue(
            self.app.snapshot()["product_status"]["group_rotation_recovery_required"]
        )

    def test_pair_bind_store_io_failure_marks_rotation_recovery_required(self) -> None:
        state = self._reach_pair_round()
        self.app.plan_classroom_pairings(
            batch_id="pair-round-failure",
            game_session_ids=("game-1", "game-2"),
            base_seconds=300,
            increment_seconds=2,
        )
        with mock.patch.object(
            self.store,
            "save",
            side_effect=OSError("simulated pair durable sync failure"),
        ):
            with self.assertRaisesRegex(OSError, "pair durable sync failure"):
                self.app.bind_current_pairing_to_group_rotation(
                    expected_rotation_revision=state.revision
                )
        self.assertTrue(
            self.app.snapshot()["product_status"]["group_rotation_recovery_required"]
        )

    def test_post_publication_failure_blocks_mutation_until_exact_reload(self) -> None:
        state = self.app.begin_or_resume_default_group_rotation("rotation-1")
        real_save = self.store.save

        def publish_then_fail(plan, next_state, *, expected_revision):
            real_save(
                plan,
                next_state,
                expected_revision=expected_revision,
            )
            raise OSError("simulated failure after durable publication")

        with mock.patch.object(
            self.store,
            "save",
            side_effect=publish_then_fail,
        ):
            with self.assertRaisesRegex(
                OSError,
                "after durable publication",
            ):
                self.app.advance_group_rotation(
                    expected_rotation_revision=state.revision
                )

        durable = self.store.load()
        self.assertIsNotNone(durable)
        assert durable is not None
        self.assertEqual(state.revision + 1, durable.state.revision)
        self.assertEqual(
            state.revision,
            self.app.group_rotation_snapshot()["revision"],
        )
        self.assertTrue(
            self.app.snapshot()["product_status"]["group_rotation_recovery_required"]
        )

        keyboard = self.app._rotation_keyboard_result()
        self.assertTrue(keyboard["recovery_required"])
        spoken = keyboard["announcement"].casefold()
        self.assertTrue("recovery" in spoken or "віднов" in spoken)

        with self.assertRaisesRegex(RuntimeError, "requires recovery"):
            self.app.advance_group_rotation(
                expected_rotation_revision=state.revision
            )

        resumed = self.app.begin_or_resume_default_group_rotation("rotation-1")
        self.assertEqual(durable.state, resumed)
        self.assertFalse(
            self.app.snapshot()["product_status"]["group_rotation_recovery_required"]
        )
        recovered_keyboard = self.app._rotation_keyboard_result()
        self.assertFalse(recovered_keyboard["recovery_required"])
        self.assertEqual(
            durable.state.revision,
            recovered_keyboard["revision"],
        )

    def test_external_store_writer_causes_cas_conflict_not_silent_overwrite(self) -> None:
        state = self.app.begin_or_resume_default_group_rotation("rotation-1")
        loaded = self.store.load()
        self.assertIsNotNone(loaded)
        assert loaded is not None
        external_state = advance_rotation(
            loaded.plan,
            loaded.state,
            expected_revision=loaded.state.revision,
        )
        self.store.save(
            loaded.plan,
            external_state,
            expected_revision=loaded.revision,
        )

        with self.assertRaises(ChildCoachingRotationStoreConflictError):
            self.app.advance_group_rotation(
                expected_rotation_revision=state.revision
            )
        self.assertTrue(
            self.app.snapshot()["product_status"]["group_rotation_recovery_required"]
        )


if __name__ == "__main__":
    unittest.main()
