from __future__ import annotations

from dataclasses import replace
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

from acs.child_coaching import (
    AgeBand,
    ChildCoachingError,
    LessonBlock,
    LessonBlockKind,
    LessonLevel,
    LessonTemplate,
    compile_lesson_session,
    copy_as_custom,
    ensure_preset_templates,
    preset_templates,
)
from acs.child_coaching_store import (
    ChildCoachingStoreBusyError,
    ChildCoachingStoreConflictError,
    ChildCoachingStoreError,
    ChildCoachingTemplateStore,
    _exclusive_store_lock,
)
from acs.interaction_contracts import BoardPermissionState, EngineVisibilityPolicy
from acs.teaching_session import (
    PositionSourceKind,
    TeachingActivity,
    TeachingPositionSource,
    TeachingSessionPhase,
    advance_step,
    start_session,
    submit_selection,
)


class ChildCoachingDomainTests(unittest.TestCase):
    def test_presets_cover_requested_age_bands_and_default_durations(self) -> None:
        presets = {item.age_band: item for item in preset_templates()}
        self.assertEqual(
            set(presets),
            {
                AgeBand.PRESCHOOL_4_6,
                AgeBand.YOUNG_BEGINNER_7_8,
                AgeBand.SCHOOL_AGE_9_10,
                AgeBand.STRONG_CHILD,
            },
        )
        self.assertTrue(25 <= presets[AgeBand.PRESCHOOL_4_6].total_minutes <= 35)
        self.assertTrue(40 <= presets[AgeBand.YOUNG_BEGINNER_7_8].total_minutes <= 60)
        self.assertTrue(45 <= presets[AgeBand.SCHOOL_AGE_9_10].total_minutes <= 65)
        self.assertTrue(60 <= presets[AgeBand.STRONG_CHILD].total_minutes <= 90)
        self.assertTrue(all(item.no_notation_required for item in presets.values()))
        self.assertTrue(
            all(
                not block.student_engine_visible
                for template in presets.values()
                for block in template.blocks
            )
        )

    def test_preschool_materializes_without_typed_notation_or_second_chess_core(self) -> None:
        template = preset_templates()[0]
        session = compile_lesson_session(
            template,
            session_id="session-child-1",
            lesson_id="lesson-child-1",
            source=TeachingPositionSource(PositionSourceKind.START),
            student_ids=("student-1",),
            cohort_id="cohort-1",
            require_no_notation=True,
        )
        self.assertEqual(len(session.steps), len(template.blocks))
        self.assertEqual(session.source.fen, TeachingPositionSource(PositionSourceKind.START).fen)
        self.assertTrue(
            all(step.policy.engine_visibility is EngineVisibilityPolicy.HIDDEN for step in session.steps)
        )
        self.assertTrue(
            all(step.policy.board_permission is not BoardPermissionState.MOVE_ALLOWED for step in session.steps)
        )

    def test_school_age_move_block_uses_canonical_move_policy(self) -> None:
        template = next(
            item for item in preset_templates()
            if item.age_band is AgeBand.SCHOOL_AGE_9_10
        )
        session = compile_lesson_session(
            template,
            session_id="session-school",
            lesson_id="lesson-school",
            source=TeachingPositionSource(PositionSourceKind.START),
        )
        move_step = next(
            step for step in session.steps
            if step.activity is TeachingActivity.MAKE_MOVE
        )
        self.assertEqual(move_step.policy.board_permission, BoardPermissionState.MOVE_ALLOWED)
        self.assertEqual(move_step.policy.engine_visibility, EngineVisibilityPolicy.HIDDEN)

    def test_teacher_only_notes_never_cross_into_student_session(self) -> None:
        block = LessonBlock(
            "explain",
            LessonBlockKind.CONCEPT,
            "Concept",
            5,
            TeachingActivity.TEACHER_EXPLAINS,
            "Student prompt",
            teacher_note="Private teacher observation",
        )
        template = LessonTemplate(
            "custom-private",
            "Private note test",
            AgeBand.YOUNG_BEGINNER_7_8,
            LessonLevel.BEGINNER,
            (block,),
            custom=True,
        )
        session = compile_lesson_session(
            template,
            session_id="session-private",
            lesson_id="lesson-private",
            source=TeachingPositionSource(PositionSourceKind.START),
        )
        self.assertEqual(session.steps[0].prompt, "Student prompt")
        self.assertNotIn("Private teacher observation", session.to_json())

    def test_activity_target_shape_delegates_to_canonical_teaching_step(self) -> None:
        with self.assertRaises(ChildCoachingError):
            LessonBlock(
                "bad-square",
                LessonBlockKind.POINTER_TASK,
                "Find square",
                5,
                TeachingActivity.SHOW_SQUARE,
                "Find e4",
            )
        valid = LessonBlock(
            "square",
            LessonBlockKind.POINTER_TASK,
            "Find square",
            5,
            TeachingActivity.SHOW_SQUARE,
            "Find e4",
            target_square="e4",
        )
        self.assertEqual(valid.to_teaching_step().target_square, "e4")

    def test_template_round_trip_is_closed_world_and_tamper_evident(self) -> None:
        template = preset_templates()[1]
        restored = LessonTemplate.from_json(template.to_json())
        self.assertEqual(restored, template)
        self.assertEqual(restored.to_json(), template.to_json())

        record = template.to_record()
        record["title"] = "Tampered"
        with self.assertRaises(ChildCoachingError):
            LessonTemplate.from_record(record)

        record = template.to_record()
        record["unexpected"] = True
        with self.assertRaises(ChildCoachingError):
            LessonTemplate.from_record(record)

        duplicate = template.to_json()[:-1] + ',"version":1}'
        with self.assertRaises(ChildCoachingError):
            LessonTemplate.from_json(duplicate)

    def test_editing_is_functional_and_preserves_stable_block_identity(self) -> None:
        base = preset_templates()[0]
        custom = copy_as_custom(
            base,
            template_id="custom-preschool",
            title="My preschool",
        )
        original = custom.blocks[0]
        changed = replace(
            original,
            minutes=4,
            teacher_note="Keep this block short.",
        )
        edited = custom.replace_block(original.block_id, changed)
        self.assertEqual(base.blocks[0].minutes, 3)
        self.assertEqual(edited.blocks[0].minutes, 4)
        self.assertTrue(edited.custom)
        with self.assertRaises(ChildCoachingError):
            custom.replace_block(
                original.block_id,
                replace(original, block_id="different"),
            )

    def test_require_no_notation_fails_closed_for_notation_template(self) -> None:
        block = LessonBlock(
            "notation",
            LessonBlockKind.EXERCISE,
            "Notation exercise",
            5,
            TeachingActivity.STUDENT_RESPONDS,
            "Type the requested notation.",
            notation_required=True,
        )
        template = LessonTemplate(
            "custom-notation",
            "Notation lesson",
            AgeBand.SCHOOL_AGE_9_10,
            LessonLevel.DEVELOPING,
            (block,),
            custom=True,
        )
        with self.assertRaises(ChildCoachingError):
            compile_lesson_session(
                template,
                session_id="session-notation",
                lesson_id="lesson-notation",
                source=TeachingPositionSource(PositionSourceKind.START),
                require_no_notation=True,
            )

    def test_preset_seeding_never_overwrites_existing_teacher_edits(self) -> None:
        preset = preset_templates()[0]
        edited = replace(preset, title="Teacher edited preset", custom=True)
        seeded = ensure_preset_templates((edited,))
        retained = next(
            item for item in seeded
            if item.template_id == preset.template_id
        )
        self.assertEqual(retained.title, "Teacher edited preset")
        self.assertEqual(len(seeded), len(preset_templates()))


    def test_preschool_pointer_only_lesson_completes_without_move_input_or_board_mutation(self) -> None:
        template = preset_templates()[0]
        session = compile_lesson_session(
            template,
            session_id="pointer-only-session",
            lesson_id="pointer-only-lesson",
            source=TeachingPositionSource(PositionSourceKind.START),
            student_ids=("student-1",),
            require_no_notation=True,
        )
        state = start_session(session)
        initial_fen = state.position_fen

        for index, block in enumerate(template.blocks):
            if block.activity is TeachingActivity.STUDENT_RESPONDS:
                state = submit_selection(
                    session,
                    state,
                    "student-1",
                    "e4",
                    state.revision,
                )
                self.assertEqual(state.position_fen, initial_fen)
            self.assertNotEqual(
                state.presentation.board_permission,
                BoardPermissionState.MOVE_ALLOWED,
            )
            state = advance_step(session, state, state.revision)
            if index + 1 < len(template.blocks):
                self.assertEqual(state.position_fen, initial_fen)

        self.assertEqual(state.phase, TeachingSessionPhase.COMPLETED)
        self.assertEqual(state.position_fen, initial_fen)


class ChildCoachingStoreTests(unittest.TestCase):
    def test_save_reopen_and_exact_cas_conflict(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            store = ChildCoachingTemplateStore(Path(temp) / "child-coaching.json")
            templates = preset_templates()
            revision = store.save(templates, expected_revision=None)
            loaded = store.load()
            self.assertIsNotNone(loaded)
            assert loaded is not None
            self.assertEqual(loaded.revision, revision)
            self.assertEqual(
                loaded.templates,
                tuple(sorted(templates, key=lambda item: item.template_id)),
            )
            self.assertFalse(loaded.recovered_from_backup)

            edited = copy_as_custom(templates[0], template_id="custom-one")
            new_revision = store.save(
                loaded.templates + (edited,),
                expected_revision=loaded.revision,
            )
            self.assertNotEqual(new_revision, revision)
            with self.assertRaises(ChildCoachingStoreConflictError):
                store.save(loaded.templates, expected_revision=revision)

    def test_save_rechecks_existing_target_after_temp_fsync_before_backup(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "child-coaching.json"
            store = ChildCoachingTemplateStore(path)
            templates = preset_templates()
            revision = store.save(templates, expected_revision=None)
            foreign = b'{"external":"newer-template-state"}'
            real_read = store._read_bounded
            reads = 0

            def read_with_external_change(target: Path):
                nonlocal reads
                if target == path:
                    reads += 1
                    if reads == 2:
                        path.write_bytes(foreign)
                return real_read(target)

            with mock.patch.object(
                store, "_read_bounded", side_effect=read_with_external_change
            ):
                with self.assertRaisesRegex(
                    ChildCoachingStoreConflictError,
                    "changed since the caller last observed",
                ):
                    store.save(templates, expected_revision=revision)

            self.assertGreaterEqual(reads, 2)
            self.assertEqual(path.read_bytes(), foreign)
            self.assertFalse(path.with_name(f"{path.name}.bak").exists())
            self.assertEqual(list(path.parent.glob(f".{path.name}.*.tmp")), [])

    def test_save_rechecks_absent_target_after_temp_fsync(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "child-coaching.json"
            store = ChildCoachingTemplateStore(path)
            templates = preset_templates()
            foreign = b'{"external":"created-template-state"}'
            real_read = store._read_bounded
            reads = 0

            def read_with_external_create(target: Path):
                nonlocal reads
                if target == path:
                    reads += 1
                    if reads == 2:
                        path.write_bytes(foreign)
                return real_read(target)

            with mock.patch.object(
                store, "_read_bounded", side_effect=read_with_external_create
            ):
                with self.assertRaisesRegex(
                    ChildCoachingStoreConflictError,
                    "changed since the caller last observed",
                ):
                    store.save(templates, expected_revision=None)

            self.assertGreaterEqual(reads, 2)
            self.assertEqual(path.read_bytes(), foreign)
            self.assertFalse(path.with_name(f"{path.name}.bak").exists())
            self.assertEqual(list(path.parent.glob(f".{path.name}.*.tmp")), [])

    def test_save_rechecks_target_again_after_backup_publication(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "child-coaching.json"
            store = ChildCoachingTemplateStore(path)
            initial = (preset_templates()[0],)
            revision = store.save(initial, expected_revision=None)
            initial_bytes = path.read_bytes()
            edited = initial + (
                copy_as_custom(initial[0], template_id="external-race-candidate"),
            )
            foreign = b'{"external":"changed-during-backup"}'
            real_read = store._read_bounded
            reads = 0

            def read_with_external_change_after_backup(target: Path):
                nonlocal reads
                if target == path:
                    reads += 1
                    if reads == 3:
                        path.write_bytes(foreign)
                return real_read(target)

            with mock.patch.object(
                store,
                "_read_bounded",
                side_effect=read_with_external_change_after_backup,
            ):
                with self.assertRaisesRegex(
                    ChildCoachingStoreConflictError,
                    "changed since the caller last observed",
                ):
                    store.save(edited, expected_revision=revision)

            self.assertGreaterEqual(reads, 3)
            self.assertEqual(path.read_bytes(), foreign)
            self.assertEqual(
                path.with_name(f"{path.name}.bak").read_bytes(),
                initial_bytes,
            )
            self.assertEqual(list(path.parent.glob(f".{path.name}.*.tmp")), [])

    def test_publication_lock_is_busy_while_owned_and_released_after_crash(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "child-coaching.json"
            lock_path = path.with_name(f".{path.name}.lock")
            store = ChildCoachingTemplateStore(path)
            templates = preset_templates()

            with _exclusive_store_lock(lock_path):
                with self.assertRaises(ChildCoachingStoreBusyError):
                    store.save(templates, expected_revision=None)

            script = (
                "import os,sys\n"
                "from pathlib import Path\n"
                "from acs.child_coaching_store import _exclusive_store_lock\n"
                "with _exclusive_store_lock(Path(sys.argv[1])):\n"
                "    os._exit(0)\n"
            )
            completed = subprocess.run(
                [sys.executable, "-c", script, str(lock_path)],
                cwd=Path(__file__).resolve().parents[1],
                check=False,
            )
            self.assertEqual(completed.returncode, 0)
            revision = store.save(templates, expected_revision=None)
            self.assertEqual(store.load().revision, revision)

    def test_legacy_schema_zero_loads_and_future_schema_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "child-coaching.json"
            template = preset_templates()[0]
            path.write_text(
                json.dumps(
                    {"templates": [template.to_record()]},
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            loaded = ChildCoachingTemplateStore(path).load()
            self.assertIsNotNone(loaded)
            assert loaded is not None
            self.assertEqual(loaded.migrated_from_schema, 0)
            self.assertEqual(loaded.templates, (template,))

            path.write_text(
                json.dumps({"schema_version": 99, "templates": []}),
                encoding="utf-8",
            )
            with self.assertRaises(ChildCoachingStoreError):
                ChildCoachingTemplateStore(path).load()

    def test_valid_previous_snapshot_recovers_corrupt_primary_and_repairs_by_cas(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "child-coaching.json"
            store = ChildCoachingTemplateStore(path)
            first = (preset_templates()[0],)
            first_revision = store.save(first, expected_revision=None)
            second = first + (
                copy_as_custom(first[0], template_id="custom-recovery"),
            )
            second_revision = store.save(
                second,
                expected_revision=first_revision,
            )
            self.assertNotEqual(second_revision, first_revision)

            path.write_text("{corrupt", encoding="utf-8")
            recovered = store.load()
            self.assertIsNotNone(recovered)
            assert recovered is not None
            self.assertTrue(recovered.recovered_from_backup)
            self.assertEqual(recovered.templates, first)
            corrupt_revision = recovered.revision

            repaired_revision = store.save(
                recovered.templates,
                expected_revision=corrupt_revision,
            )
            self.assertNotEqual(repaired_revision, corrupt_revision)
            repaired = store.load()
            self.assertIsNotNone(repaired)
            assert repaired is not None
            self.assertFalse(repaired.recovered_from_backup)
            self.assertEqual(repaired.templates, first)

    def test_duplicate_template_ids_and_unknown_fields_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "child-coaching.json"
            store = ChildCoachingTemplateStore(path)
            template = preset_templates()[0]
            with self.assertRaises(ChildCoachingStoreError):
                store.save((template, template), expected_revision=None)

            path.write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "templates": [],
                        "unexpected": True,
                    }
                ),
                encoding="utf-8",
            )
            with self.assertRaises(ChildCoachingStoreError):
                store.load()


if __name__ == "__main__":
    unittest.main()
