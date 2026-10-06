from __future__ import annotations

from dataclasses import replace
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from acs.child_coaching import LessonBlock, LessonBlockKind, copy_as_custom, preset_templates
from acs.child_coaching_application import (
    ChildCoachingApplication,
    ChildCoachingApplicationError,
)
from acs.child_coaching_store import (
    ChildCoachingStoreConflictError,
    ChildCoachingTemplateStore,
    _exclusive_store_lock,
)
from acs.teaching_session import PositionSourceKind, TeachingActivity, TeachingPositionSource


class ChildCoachingApplicationTests(unittest.TestCase):
    def make_app(self, temp: str) -> ChildCoachingApplication:
        return ChildCoachingApplication(
            ChildCoachingTemplateStore(Path(temp) / "child-coaching.json")
        )

    def test_first_open_seeds_presets_once_and_exposes_concise_accessible_summaries(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            app = self.make_app(temp)
            first = app.open_catalog()
            second = app.open_catalog()
            self.assertEqual(first.revision, second.revision)
            self.assertEqual(len(first.templates), len(preset_templates()))
            self.assertTrue(
                all(summary.accessible_text for summary in first.templates)
            )
            preschool = first.summary("preset-preschool-4-6")
            self.assertIn("30 minutes", preschool.accessible_text)
            self.assertIn("no notation required", preschool.accessible_text)
            self.assertIn("preset", preschool.accessible_text)

    def test_copy_edit_rename_reopen_and_delete_custom_template(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            app = self.make_app(temp)
            catalog = app.open_catalog()
            catalog = app.copy_template(
                "preset-preschool-4-6",
                template_id="teacher-preschool",
                title="My preschool group",
                expected_revision=catalog.revision,
            )
            copied = catalog.summary("teacher-preschool")
            self.assertTrue(copied.custom)

            template, revision = app.get_template("teacher-preschool")
            first_block = template.blocks[0]
            replacement = replace(
                first_block,
                minutes=4,
                teacher_note="Slow down if attention drops.",
            )
            catalog = app.replace_block(
                "teacher-preschool",
                first_block.block_id,
                replacement,
                expected_revision=revision,
            )
            changed, revision = app.get_template("teacher-preschool")
            self.assertEqual(changed.blocks[0].minutes, 4)
            self.assertEqual(
                changed.blocks[0].teacher_note,
                "Slow down if attention drops.",
            )

            catalog = app.rename_template(
                "teacher-preschool",
                "Saturday preschool group",
                expected_revision=revision,
            )
            reopened = self.make_app(temp).open_catalog()
            self.assertEqual(
                reopened.summary("teacher-preschool").title,
                "Saturday preschool group",
            )
            deleted = app.delete_custom_template(
                "teacher-preschool",
                expected_revision=reopened.revision,
            )
            with self.assertRaises(ChildCoachingApplicationError):
                deleted.summary("teacher-preschool")

    def test_store_contention_is_reduced_to_stable_application_error(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "child-coaching.json"
            store = ChildCoachingTemplateStore(path)
            app = ChildCoachingApplication(store)
            lock_path = path.with_name(f".{path.name}.lock")

            with _exclusive_store_lock(lock_path):
                with self.assertRaisesRegex(
                    ChildCoachingApplicationError,
                    "catalog is busy; retry",
                ):
                    app.open_catalog()

            catalog = app.open_catalog()
            with _exclusive_store_lock(lock_path):
                with self.assertRaisesRegex(
                    ChildCoachingApplicationError,
                    "catalog is busy; retry",
                ):
                    app.copy_template(
                        "preset-preschool-4-6",
                        template_id="busy-copy",
                        title="Busy copy",
                        expected_revision=catalog.revision,
                    )

    def test_open_catalog_retries_seed_after_concurrent_partial_catalog_write(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            store = ChildCoachingTemplateStore(Path(temp) / "child-coaching.json")
            presets = preset_templates()
            initial_revision = store.save((presets[0],), expected_revision=None)
            original_save = store.save
            injected = {"done": False}

            def conflict_once(templates, *, expected_revision):
                if not injected["done"]:
                    injected["done"] = True
                    self.assertEqual(expected_revision, initial_revision)
                    original_save((presets[1],), expected_revision=expected_revision)
                    raise ChildCoachingStoreConflictError("concurrent partial write")
                return original_save(
                    templates,
                    expected_revision=expected_revision,
                )

            app = ChildCoachingApplication(store)
            with mock.patch.object(store, "save", side_effect=conflict_once):
                catalog = app.open_catalog()

            self.assertTrue(injected["done"])
            self.assertEqual(
                {item.template_id for item in catalog.templates},
                {item.template_id for item in presets},
            )
            reopened = ChildCoachingApplication(store).open_catalog()
            self.assertEqual(
                {item.template_id for item in reopened.templates},
                {item.template_id for item in presets},
            )

    def test_direct_access_canonicalizes_partial_legacy_store_without_catalog_call(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "child-coaching.json"
            presets = preset_templates()
            path.write_text(
                json.dumps(
                    {"templates": [presets[0].to_record()]},
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            app = ChildCoachingApplication(ChildCoachingTemplateStore(path))

            template, revision = app.get_template(presets[1].template_id)
            self.assertEqual(template, presets[1])
            self.assertEqual(len(revision), 64)

            durable = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(durable["schema_version"], 1)
            self.assertEqual(
                {item["template_id"] for item in durable["templates"]},
                {item.template_id for item in presets},
            )

    def test_direct_access_repairs_valid_backup_after_corrupt_primary(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "child-coaching.json"
            store = ChildCoachingTemplateStore(path)
            presets = preset_templates()
            first_revision = store.save(presets, expected_revision=None)
            # Advance once with a valid distinct catalog so the original complete
            # preset set is retained as the known-valid backup.
            copied = copy_as_custom(
                presets[0],
                template_id="backup-custom",
                title="Backup custom",
            )
            store.save(
                presets + (copied,),
                expected_revision=first_revision,
            )
            path.write_text("{corrupt", encoding="utf-8")

            app = ChildCoachingApplication(store)
            template, _ = app.get_template("preset-preschool-4-6")
            self.assertEqual(template.template_id, "preset-preschool-4-6")

            repaired = store.load()
            self.assertIsNotNone(repaired)
            assert repaired is not None
            self.assertFalse(repaired.recovered_from_backup)
            self.assertEqual(
                {item.template_id for item in repaired.templates},
                {item.template_id for item in presets},
            )

    def test_stale_writer_is_rejected_before_silent_overwrite(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            app_a = self.make_app(temp)
            app_b = self.make_app(temp)
            first = app_a.open_catalog()
            same = app_b.open_catalog()
            self.assertEqual(first.revision, same.revision)

            newer = app_a.copy_template(
                "preset-young-beginner-7-8",
                template_id="newer-copy",
                title="Newer copy",
                expected_revision=first.revision,
            )
            self.assertNotEqual(newer.revision, same.revision)
            with self.assertRaisesRegex(
                ChildCoachingApplicationError,
                "changed; reopen",
            ):
                app_b.copy_template(
                    "preset-school-age-9-10",
                    template_id="stale-copy",
                    title="Stale copy",
                    expected_revision=same.revision,
                )
            reopened = app_b.open_catalog()
            self.assertIsNotNone(reopened.summary("newer-copy"))
            with self.assertRaises(ChildCoachingApplicationError):
                reopened.summary("stale-copy")



    def test_custom_template_can_append_and_remove_reusable_blocks(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            app = self.make_app(temp)
            catalog = app.open_catalog()
            catalog = app.copy_template(
                "preset-preschool-4-6",
                template_id="editable-blocks",
                title="Editable blocks",
                expected_revision=catalog.revision,
            )
            before, revision = app.get_template("editable-blocks")
            extra = LessonBlock(
                "homework",
                LessonBlockKind.HOMEWORK,
                "Home practice",
                5,
                TeachingActivity.TEACHER_EXPLAINS,
                "Review today's idea once at home.",
                teacher_note="Send this only after the lesson.",
            )
            catalog = app.append_block(
                "editable-blocks",
                extra,
                expected_revision=revision,
            )
            appended, revision = app.get_template("editable-blocks")
            self.assertEqual(len(appended.blocks), len(before.blocks) + 1)
            self.assertEqual(appended.blocks[-1], extra)

            catalog = app.remove_block(
                "editable-blocks",
                "homework",
                expected_revision=revision,
            )
            restored, _ = app.get_template("editable-blocks")
            self.assertEqual(len(restored.blocks), len(before.blocks))
            self.assertTrue(restored.custom)


    def test_session_start_can_require_exact_reviewed_template_revision(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            app_a = self.make_app(temp)
            app_b = self.make_app(temp)
            reviewed = app_a.open_catalog()
            app_b.copy_template(
                "preset-preschool-4-6",
                template_id="concurrent-template",
                title="Concurrent template",
                expected_revision=reviewed.revision,
            )
            with self.assertRaisesRegex(
                ChildCoachingApplicationError,
                "changed; reopen",
            ):
                app_a.compile_session(
                    "preset-preschool-4-6",
                    session_id="stale-start",
                    lesson_id="lesson-1",
                    source=TeachingPositionSource(PositionSourceKind.START),
                    expected_revision=reviewed.revision,
                )

            current = app_a.open_catalog()
            session = app_a.compile_session(
                "preset-preschool-4-6",
                session_id="current-start",
                lesson_id="lesson-1",
                source=TeachingPositionSource(PositionSourceKind.START),
                expected_revision=current.revision,
            )
            self.assertEqual(session.session_id, "current-start")


    def test_builtin_preset_cannot_be_deleted_but_can_be_edited_and_is_not_reseeded_over(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            app = self.make_app(temp)
            catalog = app.open_catalog()
            with self.assertRaisesRegex(
                ChildCoachingApplicationError,
                "preset cannot be deleted",
            ):
                app.delete_custom_template(
                    "preset-preschool-4-6",
                    expected_revision=catalog.revision,
                )

            template, revision = app.get_template("preset-preschool-4-6")
            block = template.blocks[0]
            changed = replace(block, minutes=4)
            app.replace_block(
                template.template_id,
                block.block_id,
                changed,
                expected_revision=revision,
            )
            reopened_template, _ = app.get_template("preset-preschool-4-6")
            self.assertEqual(reopened_template.blocks[0].minutes, 4)
            self.assertTrue(reopened_template.custom)
            edited_catalog = app.open_catalog()
            self.assertEqual(
                edited_catalog.summary("preset-preschool-4-6").total_minutes,
                31,
            )
            with self.assertRaisesRegex(
                ChildCoachingApplicationError,
                "preset cannot be deleted",
            ):
                app.delete_custom_template(
                    "preset-preschool-4-6",
                    expected_revision=edited_catalog.revision,
                )
            still_edited, _ = app.get_template("preset-preschool-4-6")
            self.assertEqual(still_edited.blocks[0].minutes, 4)
            self.assertTrue(still_edited.custom)

    def test_compilation_uses_persisted_template_and_redacts_teacher_note(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            app = self.make_app(temp)
            catalog = app.open_catalog()
            app.copy_template(
                "preset-young-beginner-7-8",
                template_id="session-template",
                title="Session template",
                expected_revision=catalog.revision,
            )
            template, revision = app.get_template("session-template")
            block = template.blocks[0]
            app.replace_block(
                template.template_id,
                block.block_id,
                replace(block, teacher_note="Private teacher-only plan"),
                expected_revision=revision,
            )
            session = app.compile_session(
                "session-template",
                session_id="session-1",
                lesson_id="lesson-1",
                source=TeachingPositionSource(PositionSourceKind.START),
                student_ids=("student-1",),
                require_no_notation=True,
            )
            self.assertNotIn("Private teacher-only plan", session.to_json())
            self.assertEqual(
                len(session.steps),
                len(app.get_template("session-template")[0].blocks),
            )

    def test_invalid_replacement_is_reduced_to_stable_application_error(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            app = self.make_app(temp)
            catalog = app.open_catalog()
            template, _ = app.get_template("preset-preschool-4-6")
            wrong = LessonBlock(
                "different-id",
                template.blocks[0].kind,
                template.blocks[0].title,
                template.blocks[0].minutes,
                template.blocks[0].activity,
                template.blocks[0].prompt,
            )
            with self.assertRaisesRegex(
                ChildCoachingApplicationError,
                "block update was rejected",
            ):
                app.replace_block(
                    template.template_id,
                    template.blocks[0].block_id,
                    wrong,
                    expected_revision=catalog.revision,
                )


if __name__ == "__main__":
    unittest.main()
