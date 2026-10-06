from __future__ import annotations

from pathlib import Path
import tempfile
import unittest
from unittest import mock

from acs.acsdb import AcsDatabase
from acs.analysis_service import AnalysisService
from acs.book_progress_store import BookProgressStore
from acs.child_coaching_application import ChildCoachingApplication
from acs.child_coaching_rotation_store import ChildCoachingRotationStore
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
from acs.full_product_actions import build_full_product_action_registry
from acs.keybindings import ActionRegistry, BindingContext
from acs.teaching_session import (
    PositionSourceKind,
    TeachingPositionSource,
)
from acs.version2_final_product_application import Version2FinalProductApplication


ACTION_BINDINGS = {
    "teacher.prepared_previous": "Ctrl+Alt+PageUp",
    "teacher.prepared_next": "Ctrl+Alt+PageDown",
    "teacher.rotation_start_or_resume": "Ctrl+Alt+R",
    "teacher.rotation_advance": "Ctrl+Alt+N",
    "teacher.rotation_bind_pairing": "Ctrl+Alt+B",
    "teacher.rotation_status": "Ctrl+Alt+S",
}


class ChildCoachingKeyboardActionTests(unittest.TestCase):
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
            position_id="prep-a",
            source=TeachingPositionSource(PositionSourceKind.START),
            expected_position_revision=0,
        )
        workspace = save_prepared_position(
            workspace,
            position_id="prep-b",
            source=TeachingPositionSource(
                PositionSourceKind.FEN,
                fen="8/8/8/8/8/8/2K5/6k1 w - - 0 1",
            ),
            expected_position_revision=0,
        )
        self.app.replace_education_workspace(workspace, expected_revision=None)
        self.app.bind_child_coaching_application(
            ChildCoachingApplication(
                ChildCoachingTemplateStore(self.root / "child-coaching.json")
            )
        )
        self.app.bind_child_coaching_rotation_store(
            ChildCoachingRotationStore(
                self.root / "child-coaching-rotation.json"
            )
        )
        catalog = self.app.open_child_coaching_catalog()
        selected = self.app.prepared_position_snapshot()
        selected_summary = next(item for item in selected.positions if item.selected)
        self.app.start_prepared_child_lesson(
            "preset-preschool-4-6",
            session_id="session-1",
            lesson_id="lesson-1",
            student_ids=("student-1", "student-2", "student-3", "student-4"),
            cohort_id="cohort-1",
            require_no_notation=True,
            expected_template_revision=catalog.revision,
            expected_position_revision=selected_summary.revision,
        )
        route = self.app.router.dispatch("screen.teacher")
        self.assertEqual("teacher", route.route_id)
        self.assertEqual("teacher-pointer-input", route.focus_target)

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

    def _dispatch_chord(self, chord: str):
        resolved = self.app.adapter.registry.resolve_binding(
            BindingContext.DOCUMENT,
            chord,
        )
        self.assertIsNotNone(resolved, chord)
        assert resolved is not None
        return self.app.router.dispatch(resolved.action_id)

    def test_defaults_are_central_remappable_and_conflict_free(self) -> None:
        registry = build_full_product_action_registry()
        for action_id, binding in ACTION_BINDINGS.items():
            with self.subTest(action_id=action_id):
                definition = registry.definition(action_id)
                self.assertIs(definition.context, BindingContext.DOCUMENT)
                self.assertEqual(binding, registry.get_binding(action_id))
                self.assertEqual(
                    action_id,
                    registry.resolve_binding(
                        BindingContext.DOCUMENT,
                        binding,
                    ).action_id,
                )
                self.assertEqual((), registry.binding_conflicts(action_id, binding))

        registry.set_binding("teacher.prepared_next", "Ctrl+Alt+J")
        self.assertIsNone(
            registry.resolve_binding(
                BindingContext.DOCUMENT,
                "Ctrl+Alt+PageDown",
            )
        )
        self.assertEqual(
            "teacher.prepared_next",
            registry.resolve_binding(
                BindingContext.DOCUMENT,
                "Ctrl+Alt+J",
            ).action_id,
        )
        restored = ActionRegistry.import_json(
            registry.export_json(),
            registry.definitions(),
        )
        self.assertEqual(
            "teacher.prepared_next",
            restored.resolve_binding(
                BindingContext.DOCUMENT,
                "Ctrl+Alt+J",
            ).action_id,
        )

    def test_keyboard_prepared_navigation_keeps_teacher_focus_and_d10_bytes(self) -> None:
        before = self.app._education_provider().to_json()
        result = self._dispatch_chord("Ctrl+Alt+PageDown")
        self.assertFalse(result.handled_by_shell)
        self.assertEqual("prepared-position", result.value["kind"])
        self.assertEqual(1, result.value["selected_index"])
        self.assertEqual(2, result.value["count"])
        self.assertEqual("teacher", self.app.shell.current_route.route_id)
        self.assertEqual(
            "teacher-pointer-input",
            self.app.shell.restore_focus_target(),
        )
        self.assertEqual(before, self.app._education_provider().to_json())

        result = self._dispatch_chord("Ctrl+Alt+PageUp")
        self.assertEqual(0, result.value["selected_index"])
        events = self.app.drain_events()
        announcements = [
            item["payload"]["announcement"]
            for item in events
            if item.get("kind") == "status"
        ]
        self.assertTrue(any("позиція" in item.lower() for item in announcements))

    def test_keyboard_rotation_status_before_start_is_spoken_without_mutation(self) -> None:
        store = self.app._rotation_store
        self.assertIsNotNone(store)
        assert store is not None
        self.assertIsNone(self.app._rotation_state)
        self.assertIsNone(store.load())

        status = self._dispatch_chord("Ctrl+Alt+S").value

        self.assertEqual("group-rotation", status["kind"])
        self.assertFalse(status["recovery_required"])
        self.assertNotIn("revision", status)
        spoken = status["announcement"].casefold()
        self.assertTrue("не розпоч" in spoken or "not started" in spoken)
        self.assertIsNone(self.app._rotation_state)
        self.assertIsNone(store.load())
        self.assertEqual(
            "teacher-pointer-input",
            self.app.shell.restore_focus_target(),
        )

    def test_keyboard_rotation_pairing_flow_is_semantic_and_cas_backed(self) -> None:
        started = self._dispatch_chord("Ctrl+Alt+R").value
        self.assertEqual("demonstration", started["activity"])
        task = self._dispatch_chord("Ctrl+Alt+N").value
        self.assertEqual("task_work", task["activity"])
        pair = self._dispatch_chord("Ctrl+Alt+N").value
        self.assertEqual("pair_play", pair["activity"])
        self.assertFalse(pair["pair_play_bound"])
        pair_spoken = pair["announcement"].casefold()
        self.assertTrue("не прив" in pair_spoken or "not bound" in pair_spoken)

        batch = self.app.plan_classroom_pairings(
            batch_id="keyboard-round-1",
            game_session_ids=("game-1", "game-2"),
            base_seconds=300,
            increment_seconds=2,
        )
        first = batch.pairings[0]
        self.app.override_classroom_pairing(
            pairing_id=first.pairing_id,
            white_student_id=first.black_student_id,
            black_student_id=first.white_student_id,
            base_seconds=600,
            increment_seconds=5,
        )

        bound = self._dispatch_chord("Ctrl+Alt+B").value
        self.assertTrue(bound["pair_play_bound"])
        bound_spoken = bound["announcement"].casefold()
        self.assertTrue("прив’язано" in bound_spoken or "pairing bound" in bound_spoken)
        review = self._dispatch_chord("Ctrl+Alt+N").value
        self.assertEqual("review", review["activity"])
        status = self._dispatch_chord("Ctrl+Alt+S").value
        self.assertEqual("review", status["activity"])
        self.assertEqual("teacher", self.app.shell.current_route.route_id)

        loaded = self.app._rotation_store.load()
        self.assertIsNotNone(loaded)
        assert loaded is not None
        self.assertEqual(
            self.app._rotation_state,
            loaded.state,
        )
        self.assertNotIn("white_student_id", status)
        self.assertNotIn("black_student_id", status)
        self.assertNotIn("fen", status)

    def test_keyboard_rotation_recovery_is_spoken_and_blocks_stale_advance(self) -> None:
        started = self._dispatch_chord("Ctrl+Alt+R").value
        self.assertFalse(started["recovery_required"])
        store = self.app._rotation_store
        self.assertIsNotNone(store)
        assert store is not None
        real_save = store.save

        def publish_then_fail(plan, next_state, *, expected_revision):
            real_save(
                plan,
                next_state,
                expected_revision=expected_revision,
            )
            raise OSError("simulated keyboard post-publication failure")

        with mock.patch.object(store, "save", side_effect=publish_then_fail):
            with self.assertRaisesRegex(OSError, "post-publication failure"):
                self._dispatch_chord("Ctrl+Alt+N")

        status = self._dispatch_chord("Ctrl+Alt+S").value
        self.assertTrue(status["recovery_required"])
        spoken = status["announcement"].casefold()
        self.assertTrue("віднов" in spoken or "recovery" in spoken)

        with self.assertRaisesRegex(RuntimeError, "requires recovery"):
            self._dispatch_chord("Ctrl+Alt+N")

        resumed = self._dispatch_chord("Ctrl+Alt+R").value
        self.assertFalse(resumed["recovery_required"])
        self.assertEqual(started["revision"] + 1, resumed["revision"])
        self.assertEqual("teacher", self.app.shell.current_route.route_id)
        self.assertEqual(
            "teacher-pointer-input",
            self.app.shell.restore_focus_target(),
        )

    def test_keyboard_status_speaks_recovery_when_durable_rotation_is_corrupt(self) -> None:
        store = self.app._rotation_store
        self.assertIsNotNone(store)
        assert store is not None
        store.path.write_bytes(b"{not-valid-json")

        # A read-only rebind probes durable integrity without adopting stale
        # lesson state, so accessibility truth is available before Start/Resume.
        self.app.bind_child_coaching_rotation_store(store)
        self.assertTrue(
            self.app.snapshot()["product_status"]["group_rotation_recovery_required"]
        )

        status = self._dispatch_chord("Ctrl+Alt+S").value
        self.assertEqual("group-rotation", status["kind"])
        self.assertTrue(status["recovery_required"])
        self.assertNotIn("revision", status)
        spoken = status["announcement"].casefold()
        self.assertTrue("віднов" in spoken or "recovery" in spoken)
        self.assertEqual(
            "teacher-pointer-input",
            self.app.shell.restore_focus_target(),
        )

    def test_hidden_route_and_modal_reject_teacher_keyboard_actions_without_mutation(self) -> None:
        selected_before = self.app.prepared_position_snapshot()
        self.app.router.dispatch("screen.books")
        with self.assertRaisesRegex(ValueError, "visible Teacher workspace"):
            self.app.router.dispatch("teacher.prepared_next")
        self.assertEqual(selected_before, self.app.prepared_position_snapshot())

        self.app.router.dispatch("screen.teacher")
        self.app.shell.open_dialog(
            "teacher-dialog",
            opener_focus_id="teacher-pointer-input",
            initial_focus_id="teacher-dialog-close",
        )
        with self.assertRaisesRegex(ValueError, "Close the active dialog"):
            self.app.router.dispatch("teacher.rotation_start_or_resume")
        self.assertIsNone(self.app._rotation_state)
        self.app.shell.close_dialog("teacher-dialog")

    def test_payload_injection_is_rejected_before_any_teacher_state_change(self) -> None:
        before = self.app.prepared_position_snapshot()
        with self.assertRaisesRegex(ValueError, "accepts no payload"):
            self.app.router.dispatch(
                "teacher.prepared_next",
                {"student_id": "student-1"},
            )
        self.assertEqual(before, self.app.prepared_position_snapshot())


if __name__ == "__main__":
    unittest.main()
