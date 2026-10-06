from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from acs.acsdb import AcsDatabase
from acs.analysis_service import AnalysisService
from acs.book_progress_store import BookProgressStore
from acs.child_coaching_rotation import (
    RotationActivity,
    RotationRound,
    RotationTarget,
    advance_rotation,
    build_rotation_plan,
    default_group_rotation,
    start_rotation,
)
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
from acs.version2_release_app import create_version2_release_application
from acs import version2_release_app as release_app_module
from acs.version2_education_mutation_release import _final_product_mutation_bindings
from acs.version2_packaged_starter_application import Version2PackagedStarterApplication
from acs.version2_upgrade_status_release import (
    create_version2_release_application as create_shipping_release_application,
)


class Version2GroupRotationBindingTests(unittest.TestCase):
    def test_packaged_release_wrapper_can_replace_and_restore_final_product_owner(self) -> None:
        default_owner = release_app_module.Version2Application
        self.assertIs(default_owner, Version2FinalProductApplication)

        with _final_product_mutation_bindings():
            self.assertIs(
                release_app_module.Version2Application,
                Version2PackagedStarterApplication,
            )

        self.assertIs(release_app_module.Version2Application, default_owner)

    def test_shipping_wrapper_instantiates_packaged_final_owner_with_rotation_store(self) -> None:
        class Runtime:
            def __init__(self, _config) -> None:
                self.closed = False

            @staticmethod
            def provider():
                return object()

            def close(self) -> None:
                self.closed = True

        class Playback:
            def play(self, _event, *, volume: int) -> None:
                self.last_volume = volume

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "shipping-release-data"
            api, build_application, runtime, _native_factory = create_shipping_release_application(
                data_root=root,
                runtime_factory=Runtime,
                sound_playback=Playback(),
                copy_text=lambda _text: None,
                defer_ui=True,
            )
            application = build_application()
            try:
                self.assertIsInstance(application, Version2PackagedStarterApplication)
                self.assertIsInstance(application, Version2FinalProductApplication)
                self.assertIs(api._version2(), application)
                self.assertIsNotNone(application._rotation_store)
                assert application._rotation_store is not None
                self.assertEqual(
                    root / "child-coaching-rotation.json",
                    application._rotation_store.path,
                )
            finally:
                application.shutdown()
                api.close_analysis()
                runtime.close()

    def test_release_composition_reaches_final_product_rotation_persistence(self) -> None:
        class Runtime:
            def __init__(self, _config) -> None:
                self.closed = False

            @staticmethod
            def provider():
                return object()

            def close(self) -> None:
                self.closed = True

        class Playback:
            def play(self, _event, *, volume: int) -> None:
                self.last_volume = volume

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "release-data"
            api, application, runtime, _native_factory = create_version2_release_application(
                data_root=root,
                runtime_factory=Runtime,
                sound_playback=Playback(),
                copy_text=lambda _text: None,
            )
            try:
                self.assertIsInstance(application, Version2FinalProductApplication)
                self.assertIs(api._version2(), application)
                self.assertIsNotNone(application._rotation_store)
                assert application._rotation_store is not None
                self.assertEqual(
                    root / "child-coaching-rotation.json",
                    application._rotation_store.path,
                )

                workspace = EducationWorkspace.empty(self._classroom())
                application.replace_education_workspace(
                    workspace,
                    expected_revision=application.education_revision,
                )
                plan = self._plan()
                application.start_teaching_session(plan)
                application.shell.open_route("teacher")

                dispatch = application.router.dispatch("teacher.rotation_start_or_resume")
                result = dispatch.value

                self.assertEqual("group-rotation", result["kind"])
                self.assertEqual("active", result["phase"])
                self.assertEqual(1, result["revision"])
                durable = application._rotation_store.load()
                self.assertIsNotNone(durable)
                assert durable is not None
                self.assertEqual(plan.session_id, durable.plan.lesson_session_id)
                self.assertEqual(result["revision"], durable.state.revision)
            finally:
                application.shutdown()
                runtime.close()

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
    def _two_group_classroom() -> ClassroomSnapshot:
        students = tuple(
            Student(f"student-{index}", f"Student {index}", ConsentState.GRANTED)
            for index in range(1, 5)
        )
        return ClassroomSnapshot(
            students=students,
            classes=(
                ClassroomClass(
                    "class-1",
                    "Class",
                    ("group-1", "group-2"),
                ),
            ),
            groups=(
                Group("group-1", "class-1", "Group 1"),
                Group("group-2", "class-1", "Group 2"),
            ),
            courses=(Course("course-1", "Course", ("lesson-1",)),),
            cohorts=(
                Cohort(
                    "cohort-1",
                    "course-1",
                    ("student-1", "student-2"),
                    "group-1",
                ),
                Cohort(
                    "cohort-2",
                    "course-1",
                    ("student-3", "student-4"),
                    "group-2",
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

    def test_rebinding_store_exposes_unfinished_foreign_owner_before_start_resume(self) -> None:
        foreign_lesson = LessonSession(
            "session-foreign",
            "lesson-1",
            TeachingPositionSource(PositionSourceKind.START),
            self.plan.steps,
            self.plan.student_ids,
            self.plan.cohort_id,
        )
        foreign_plan = default_group_rotation(
            foreign_lesson,
            rotation_id="rotation-foreign",
        )
        foreign_state = start_rotation(foreign_plan)
        self.store.save(foreign_plan, foreign_state, expected_revision=None)

        self.app.bind_child_coaching_rotation_store(self.store)

        status = self.app._rotation_keyboard_result()
        self.assertTrue(status["recovery_required"])
        spoken = status["announcement"].casefold()
        self.assertTrue("recovery" in spoken or "віднов" in spoken)
        self.assertIsNone(self.app._rotation_state)
        durable = self.store.load()
        self.assertIsNotNone(durable)
        assert durable is not None
        self.assertEqual(foreign_state, durable.state)

    def test_group_target_rejects_unknown_classroom_group_before_adoption(self) -> None:
        plan = build_rotation_plan(
            self.plan,
            rotation_id="rotation-missing-group",
            rounds=(
                RotationRound(
                    "pair",
                    RotationActivity.PAIR_PLAY,
                    "Pair missing group",
                    5,
                    RotationTarget.GROUP,
                    ("group-missing",),
                ),
            ),
        )
        state = start_rotation(plan)
        self.store.save(plan, state, expected_revision=None)
        before = self.store.path.read_bytes()

        with self.assertRaisesRegex(RuntimeError, "outside current classroom scope"):
            self.app.begin_or_resume_default_group_rotation("rotation-missing-group")

        self.assertEqual(before, self.store.path.read_bytes())
        self.assertIsNone(self.app._rotation_state)
        self.assertTrue(
            self.app.snapshot()["product_status"]["group_rotation_recovery_required"]
        )

    def test_group_pairing_must_exactly_match_classroom_group_membership(self) -> None:
        self.app.stop_teaching_session()
        workspace = EducationWorkspace.empty(self._two_group_classroom())
        self.app.replace_education_workspace(
            workspace,
            expected_revision=self.app.education_revision,
        )
        lesson = LessonSession(
            "session-two-groups",
            "lesson-1",
            TeachingPositionSource(PositionSourceKind.START),
            self.plan.steps,
            ("student-1", "student-2", "student-3", "student-4"),
            None,
        )
        self.app.start_teaching_session(lesson)
        plan = build_rotation_plan(
            lesson,
            rotation_id="rotation-group-1",
            rounds=(
                RotationRound(
                    "pair",
                    RotationActivity.PAIR_PLAY,
                    "Pair group 1",
                    5,
                    RotationTarget.GROUP,
                    ("group-1",),
                ),
            ),
        )
        state = start_rotation(plan)
        durable_revision = self.store.save(plan, state, expected_revision=None)
        resumed = self.app.begin_or_resume_default_group_rotation("rotation-group-1")
        self.assertEqual(state, resumed)
        self.assertEqual(durable_revision, self.app._rotation_store_revision)

        self.app.plan_classroom_pairings(
            batch_id="pair-all-groups",
            game_session_ids=("game-1", "game-2"),
            base_seconds=300,
            increment_seconds=2,
        )
        before = self.store.path.read_bytes()
        with self.assertRaisesRegex(
            RuntimeError,
            "does not match current rotation target",
        ):
            self.app.bind_current_pairing_to_group_rotation(
                expected_rotation_revision=state.revision
            )
        self.assertEqual(before, self.store.path.read_bytes())
        self.assertEqual(state, self.app._rotation_state)

        self.app.plan_classroom_pairings(
            batch_id="pair-group-1",
            game_session_ids=("game-group-1",),
            student_ids=("student-1", "student-2"),
            base_seconds=300,
            increment_seconds=2,
        )
        bound = self.app.bind_current_pairing_to_group_rotation(
            expected_rotation_revision=state.revision
        )
        self.assertEqual("pair-group-1", bound.pair_play_batch_ref)
        durable = self.store.load()
        self.assertIsNotNone(durable)
        assert durable is not None
        self.assertEqual(bound, durable.state)

    def test_keyboard_status_fences_group_scope_drift_after_workspace_change(self) -> None:
        self.app.stop_teaching_session()
        workspace = EducationWorkspace.empty(self._two_group_classroom())
        self.app.replace_education_workspace(
            workspace,
            expected_revision=self.app.education_revision,
        )
        lesson = LessonSession(
            "session-group-drift",
            "lesson-1",
            TeachingPositionSource(PositionSourceKind.START),
            self.plan.steps,
            ("student-1", "student-2", "student-3", "student-4"),
            None,
        )
        self.app.start_teaching_session(lesson)
        plan = build_rotation_plan(
            lesson,
            rotation_id="rotation-group-drift",
            rounds=(
                RotationRound(
                    "pair",
                    RotationActivity.PAIR_PLAY,
                    "Pair group 1",
                    5,
                    RotationTarget.GROUP,
                    ("group-1",),
                ),
            ),
        )
        state = start_rotation(plan)
        self.store.save(plan, state, expected_revision=None)
        self.app.begin_or_resume_default_group_rotation("rotation-group-drift")
        durable_before = self.store.path.read_bytes()

        students = self._two_group_classroom().students
        replacement = ClassroomSnapshot(
            students=students,
            classes=(ClassroomClass("class-1", "Class", ("group-2",)),),
            groups=(Group("group-2", "class-1", "Group 2"),),
            courses=(Course("course-1", "Course", ("lesson-1",)),),
            cohorts=(
                Cohort(
                    "cohort-2",
                    "course-1",
                    tuple(student.student_id for student in students),
                    "group-2",
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
        self.app.replace_education_workspace(
            EducationWorkspace.empty(replacement),
            expected_revision=self.app.education_revision,
        )

        with self.assertRaisesRegex(RuntimeError, "requires recovery"):
            self.app.advance_group_rotation(
                expected_rotation_revision=state.revision
            )
        self.assertTrue(
            self.app.snapshot()["product_status"]["group_rotation_recovery_required"]
        )
        self.assertEqual(durable_before, self.store.path.read_bytes())
        self.assertEqual(state, self.app._rotation_state)

        status = self.app._rotation_keyboard_result()

        self.assertTrue(status["recovery_required"])
        spoken = status["announcement"].casefold()
        self.assertTrue("recovery" in spoken or "віднов" in spoken)
        self.assertEqual(durable_before, self.store.path.read_bytes())
        self.assertEqual(state, self.app._rotation_state)

    def test_workspace_replacement_cannot_change_active_group_membership(self) -> None:
        self.app.stop_teaching_session()
        workspace = EducationWorkspace.empty(self._two_group_classroom())
        self.app.replace_education_workspace(
            workspace,
            expected_revision=self.app.education_revision,
        )
        lesson = LessonSession(
            "session-membership-stable",
            "lesson-1",
            TeachingPositionSource(PositionSourceKind.START),
            self.plan.steps,
            ("student-1", "student-2", "student-3", "student-4"),
            None,
        )
        self.app.start_teaching_session(lesson)
        plan = build_rotation_plan(
            lesson,
            rotation_id="rotation-membership-stable",
            rounds=(
                RotationRound(
                    "pair",
                    RotationActivity.PAIR_PLAY,
                    "Pair group 1",
                    5,
                    RotationTarget.GROUP,
                    ("group-1",),
                ),
            ),
        )
        state = start_rotation(plan)
        self.store.save(plan, state, expected_revision=None)
        self.app.begin_or_resume_default_group_rotation(
            "rotation-membership-stable"
        )
        durable_before = self.store.path.read_bytes()
        education_revision_before = self.app.education_revision

        students = self._two_group_classroom().students
        changed = ClassroomSnapshot(
            students=students,
            classes=(
                ClassroomClass(
                    "class-1",
                    "Class",
                    ("group-1", "group-2"),
                ),
            ),
            groups=(
                Group("group-1", "class-1", "Group 1"),
                Group("group-2", "class-1", "Group 2"),
            ),
            courses=(Course("course-1", "Course", ("lesson-1",)),),
            cohorts=(
                Cohort(
                    "cohort-1",
                    "course-1",
                    ("student-1",),
                    "group-1",
                ),
                Cohort(
                    "cohort-2",
                    "course-1",
                    ("student-2", "student-3", "student-4"),
                    "group-2",
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
        with self.assertRaisesRegex(
            RuntimeError,
            "change active group rotation membership",
        ):
            self.app.replace_education_workspace(
                EducationWorkspace.empty(changed),
                expected_revision=education_revision_before,
            )

        self.assertEqual(education_revision_before, self.app.education_revision)
        self.assertEqual(durable_before, self.store.path.read_bytes())
        status = self.app._rotation_keyboard_result()
        self.assertFalse(status["recovery_required"])
        self.assertEqual(state.revision, status["revision"])

    def test_completed_group_rotation_survives_later_group_membership_change(self) -> None:
        self.app.stop_teaching_session()
        workspace = EducationWorkspace.empty(self._two_group_classroom())
        self.app.replace_education_workspace(
            workspace,
            expected_revision=self.app.education_revision,
        )
        lesson = LessonSession(
            "session-completed-group",
            "lesson-1",
            TeachingPositionSource(PositionSourceKind.START),
            self.plan.steps,
            ("student-1", "student-2", "student-3", "student-4"),
            None,
        )
        self.app.start_teaching_session(lesson)
        plan = build_rotation_plan(
            lesson,
            rotation_id="rotation-completed-group",
            rounds=(
                RotationRound(
                    "pair",
                    RotationActivity.PAIR_PLAY,
                    "Pair group 1",
                    5,
                    RotationTarget.GROUP,
                    ("group-1",),
                ),
            ),
        )
        state = start_rotation(plan)
        self.store.save(plan, state, expected_revision=None)
        self.app.begin_or_resume_default_group_rotation(
            "rotation-completed-group"
        )
        self.app.plan_classroom_pairings(
            batch_id="completed-group-pair",
            game_session_ids=("completed-game",),
            student_ids=("student-1", "student-2"),
            base_seconds=300,
            increment_seconds=2,
        )
        bound = self.app.bind_current_pairing_to_group_rotation(
            expected_rotation_revision=state.revision
        )
        completed = self.app.advance_group_rotation(
            expected_rotation_revision=bound.revision
        )
        self.assertEqual("completed", completed.phase.value)
        durable_before = self.store.path.read_bytes()

        students = self._two_group_classroom().students
        changed = ClassroomSnapshot(
            students=students,
            classes=(
                ClassroomClass(
                    "class-1",
                    "Class",
                    ("group-1", "group-2"),
                ),
            ),
            groups=(
                Group("group-1", "class-1", "Group 1"),
                Group("group-2", "class-1", "Group 2"),
            ),
            courses=(Course("course-1", "Course", ("lesson-1",)),),
            cohorts=(
                Cohort(
                    "cohort-1",
                    "course-1",
                    ("student-1",),
                    "group-1",
                ),
                Cohort(
                    "cohort-2",
                    "course-1",
                    ("student-2", "student-3", "student-4"),
                    "group-2",
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
        self.app.replace_education_workspace(
            EducationWorkspace.empty(changed),
            expected_revision=self.app.education_revision,
        )

        status = self.app._rotation_keyboard_result()

        self.assertFalse(status["recovery_required"])
        self.assertEqual("completed", status["phase"])
        self.assertEqual(completed.revision, status["revision"])
        self.assertEqual(durable_before, self.store.path.read_bytes())
        resumed = self.app.begin_or_resume_default_group_rotation(
            "rotation-completed-group"
        )
        self.assertEqual(completed, resumed)

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

    def test_bind_outside_pair_round_preserves_domain_error_precedence(self) -> None:
        state = self.app.begin_or_resume_default_group_rotation("rotation-1")
        before = self.store.path.read_bytes()
        self.app.plan_classroom_pairings(
            batch_id="premature-subset",
            game_session_ids=("game-1",),
            student_ids=("student-1", "student-2"),
            base_seconds=300,
            increment_seconds=2,
        )

        with self.assertRaisesRegex(
            ValueError,
            "only bind during pair-play rotation",
        ):
            self.app.bind_current_pairing_to_group_rotation(
                expected_rotation_revision=state.revision
            )

        self.assertEqual(before, self.store.path.read_bytes())
        self.assertEqual(state, self.app._rotation_state)
        self.assertFalse(
            self.app.snapshot()["product_status"]["group_rotation_recovery_required"]
        )

    def test_pair_round_rejects_subset_batch_for_all_students_target(self) -> None:
        state = self._reach_pair_round()
        before = self.store.path.read_bytes()
        subset = self.app.plan_classroom_pairings(
            batch_id="pair-round-subset",
            game_session_ids=("game-1",),
            student_ids=("student-1", "student-2"),
            base_seconds=300,
            increment_seconds=2,
        )
        self.assertEqual(1, len(subset.pairings))

        with self.assertRaisesRegex(
            RuntimeError,
            "does not match current rotation target",
        ):
            self.app.bind_current_pairing_to_group_rotation(
                expected_rotation_revision=state.revision
            )

        self.assertEqual(before, self.store.path.read_bytes())
        self.assertEqual(state, self.app._rotation_state)
        self.assertFalse(
            self.app.snapshot()["product_status"]["group_rotation_recovery_required"]
        )

        self.app.plan_classroom_pairings(
            batch_id="pair-round-all",
            game_session_ids=("game-1", "game-2"),
            base_seconds=300,
            increment_seconds=2,
        )
        bound = self.app.bind_current_pairing_to_group_rotation(
            expected_rotation_revision=state.revision
        )
        self.assertEqual("pair-round-all", bound.pair_play_batch_ref)

    def test_keyboard_status_fences_noncanonical_durable_rotation_bytes(self) -> None:
        state = self.app.begin_or_resume_default_group_rotation("rotation-1")
        canonical = self.store.path.read_bytes()
        payload = json.loads(canonical.decode("utf-8"))
        noncanonical = json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=False,
            indent=2,
        ).encode("utf-8")
        self.assertNotEqual(canonical, noncanonical)
        self.store.path.write_bytes(noncanonical)

        keyboard = self.app._rotation_keyboard_result()

        self.assertTrue(keyboard["recovery_required"])
        spoken = keyboard["announcement"].casefold()
        self.assertTrue("recovery" in spoken or "віднов" in spoken)
        self.assertEqual(state, self.app._rotation_state)
        self.assertEqual(noncanonical, self.store.path.read_bytes())
        with self.assertRaisesRegex(RuntimeError, "requires recovery"):
            self.app.advance_group_rotation(
                expected_rotation_revision=state.revision
            )

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
        self.assertTrue(
            self.app.snapshot()["product_status"]["group_rotation_recovery_required"]
        )
        keyboard = self.app._rotation_keyboard_result()
        self.assertTrue(keyboard["recovery_required"])
        spoken = keyboard["announcement"].casefold()
        self.assertTrue("recovery" in spoken or "віднов" in spoken)

    def test_durable_rotation_for_different_lesson_fails_closed(self) -> None:
        self.app.begin_or_resume_default_group_rotation("rotation-1")
        before = self.store.path.read_bytes()
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
        self.assertTrue(
            self.app.snapshot()["product_status"]["group_rotation_recovery_required"]
        )
        with self.assertRaisesRegex(RuntimeError, "different teaching session"):
            self.app.begin_or_resume_default_group_rotation("rotation-1")
        self.assertTrue(
            self.app.snapshot()["product_status"]["group_rotation_recovery_required"]
        )
        self.assertEqual(before, self.store.path.read_bytes())

    def test_completed_prior_lesson_rolls_over_global_store_atomically(self) -> None:
        state = self.app.begin_or_resume_default_group_rotation("rotation-1")
        state = self.app.advance_group_rotation(
            expected_rotation_revision=state.revision
        )
        state = self.app.advance_group_rotation(
            expected_rotation_revision=state.revision
        )
        self.app.plan_classroom_pairings(
            batch_id="completed-old-lesson-pairing",
            game_session_ids=("game-1", "game-2"),
            base_seconds=300,
            increment_seconds=2,
        )
        state = self.app.bind_current_pairing_to_group_rotation(
            expected_rotation_revision=state.revision
        )
        state = self.app.advance_group_rotation(
            expected_rotation_revision=state.revision
        )
        state = self.app.advance_group_rotation(
            expected_rotation_revision=state.revision
        )
        self.assertEqual("completed", state.phase.value)
        old_bytes = self.store.path.read_bytes()

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
        self.assertFalse(
            self.app.snapshot()["product_status"]["group_rotation_recovery_required"]
        )

        started = self.app.begin_or_resume_default_group_rotation("rotation-2")

        self.assertEqual("active", started.phase.value)
        self.assertEqual(1, started.revision)
        self.assertFalse(
            self.app.snapshot()["product_status"]["group_rotation_recovery_required"]
        )
        loaded = self.store.load()
        self.assertIsNotNone(loaded)
        assert loaded is not None
        self.assertEqual("session-2", loaded.plan.lesson_session_id)
        self.assertEqual("rotation-2", loaded.plan.rotation_id)
        self.assertEqual(started, loaded.state)
        self.assertNotEqual(old_bytes, self.store.path.read_bytes())

    def test_completed_prior_lesson_rollover_conflict_preserves_concurrent_writer(self) -> None:
        state = self.app.begin_or_resume_default_group_rotation("rotation-1")
        state = self.app.advance_group_rotation(
            expected_rotation_revision=state.revision
        )
        state = self.app.advance_group_rotation(
            expected_rotation_revision=state.revision
        )
        self.app.plan_classroom_pairings(
            batch_id="completed-race-pairing",
            game_session_ids=("game-1", "game-2"),
            base_seconds=300,
            increment_seconds=2,
        )
        state = self.app.bind_current_pairing_to_group_rotation(
            expected_rotation_revision=state.revision
        )
        state = self.app.advance_group_rotation(
            expected_rotation_revision=state.revision
        )
        state = self.app.advance_group_rotation(
            expected_rotation_revision=state.revision
        )
        self.assertEqual("completed", state.phase.value)

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
        real_save = self.store.save
        foreign = b'{"external":"newer-completed-owner"}'

        def concurrent_writer(plan, next_state, *, expected_revision):
            self.store.path.write_bytes(foreign)
            return real_save(
                plan,
                next_state,
                expected_revision=expected_revision,
            )

        with mock.patch.object(self.store, "save", side_effect=concurrent_writer):
            with self.assertRaises(ChildCoachingRotationStoreConflictError):
                self.app.begin_or_resume_default_group_rotation("rotation-2")

        self.assertEqual(foreign, self.store.path.read_bytes())
        self.assertIsNone(self.app._rotation_state)
        self.assertTrue(
            self.app.snapshot()["product_status"]["group_rotation_recovery_required"]
        )

    def test_completed_prior_lesson_post_publication_failure_recovers_exact_new_state(self) -> None:
        state = self.app.begin_or_resume_default_group_rotation("rotation-1")
        state = self.app.advance_group_rotation(
            expected_rotation_revision=state.revision
        )
        state = self.app.advance_group_rotation(
            expected_rotation_revision=state.revision
        )
        self.app.plan_classroom_pairings(
            batch_id="completed-postpublish-pairing",
            game_session_ids=("game-1", "game-2"),
            base_seconds=300,
            increment_seconds=2,
        )
        state = self.app.bind_current_pairing_to_group_rotation(
            expected_rotation_revision=state.revision
        )
        state = self.app.advance_group_rotation(
            expected_rotation_revision=state.revision
        )
        state = self.app.advance_group_rotation(
            expected_rotation_revision=state.revision
        )
        self.assertEqual("completed", state.phase.value)

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
        real_save = self.store.save

        def publish_then_fail(plan, next_state, *, expected_revision):
            real_save(
                plan,
                next_state,
                expected_revision=expected_revision,
            )
            raise OSError("simulated rollover failure after durable publication")

        with mock.patch.object(self.store, "save", side_effect=publish_then_fail):
            with self.assertRaisesRegex(OSError, "after durable publication"):
                self.app.begin_or_resume_default_group_rotation("rotation-2")

        self.assertIsNone(self.app._rotation_state)
        self.assertTrue(
            self.app.snapshot()["product_status"]["group_rotation_recovery_required"]
        )
        durable = self.store.load()
        self.assertIsNotNone(durable)
        assert durable is not None
        self.assertEqual("session-2", durable.plan.lesson_session_id)
        self.assertEqual("rotation-2", durable.plan.rotation_id)
        self.assertEqual("active", durable.state.phase.value)
        self.assertEqual(1, durable.state.revision)

        recovered = self.app.begin_or_resume_default_group_rotation("rotation-2")
        self.assertEqual(durable.state, recovered)
        self.assertEqual(durable.revision, self.app._rotation_store_revision)
        self.assertFalse(
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
        with self.assertRaisesRegex(RuntimeError, "requires recovery"):
            self.app.advance_group_rotation(
                expected_rotation_revision=state.revision
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
        with self.assertRaisesRegex(RuntimeError, "requires recovery"):
            self.app.bind_current_pairing_to_group_rotation(
                expected_rotation_revision=state.revision
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

        # Rebinding the same readable store is only an integrity probe. It must
        # not clear the recovery fence while application memory is still stale.
        self.app.bind_child_coaching_rotation_store(self.store)
        self.assertTrue(
            self.app.snapshot()["product_status"]["group_rotation_recovery_required"]
        )
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
