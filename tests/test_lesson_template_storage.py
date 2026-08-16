from __future__ import annotations

import sqlite3
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from acs.child_coaching_ui import (
    PRESCHOOL_TEMPLATE,
    LessonTemplate,
    LessonTemplateBlock,
)
from acs.lesson_plan import LessonItemKind
from acs.lesson_storage import LessonSQLiteStore
from acs.lesson_template_storage import (
    TEMPLATE_SCHEMA_VERSION,
    LessonTemplateConflictError,
    LessonTemplatePreset,
    LessonTemplateSQLiteStore,
    LessonTemplateStorageError,
    RotationRoundRecord,
    RotationRoundState,
)


class LessonTemplateSQLiteStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "teaching.sqlite3"
        self.store = LessonTemplateSQLiteStore(self.path)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_schema_reopen_is_idempotent_and_coexists_with_lesson_schema_v2(self) -> None:
        LessonSQLiteStore(self.path, fen_validator=lambda fen: None)
        reopened = LessonTemplateSQLiteStore(self.path)
        reopened_again = LessonTemplateSQLiteStore(self.path)
        with sqlite3.connect(self.path) as db:
            template_version = db.execute(
                "SELECT value FROM lesson_template_schema_meta WHERE key='schema_version'"
            ).fetchone()[0]
            lesson_version = db.execute(
                "SELECT value FROM schema_meta WHERE key='schema_version'"
            ).fetchone()[0]
            integrity = db.execute("PRAGMA integrity_check").fetchone()[0]
        self.assertEqual(TEMPLATE_SCHEMA_VERSION, template_version)
        self.assertEqual(2, lesson_version)
        self.assertEqual("ok", integrity)
        self.assertIsInstance(reopened, LessonTemplateSQLiteStore)
        self.assertIsInstance(reopened_again, LessonTemplateSQLiteStore)

    def test_editable_preset_round_trip_preserves_order_and_no_notation_metadata(self) -> None:
        custom = LessonTemplate(
            "custom-preschool",
            "Мій дошкільний урок",
            "4-6",
            (
                LessonTemplateBlock("find", LessonItemKind.EXERCISE, "Знайди поле", 4, False),
                LessonTemplateBlock("move", LessonItemKind.MINI_GAME, "Зроби хід", 6, True),
            ),
        )
        revision = self.store.save_new_template(LessonTemplatePreset(custom, "absolute-beginner"))
        loaded, loaded_revision = self.store.load_template("custom-preschool")
        self.assertEqual(1, revision.revision)
        self.assertEqual(revision, loaded_revision)
        self.assertEqual(custom, loaded.template)
        self.assertEqual("absolute-beginner", loaded.level)
        self.assertEqual((False, True), tuple(block.notation_required for block in loaded.template.blocks))

    def test_ensure_presets_never_silently_overwrites_teacher_edit(self) -> None:
        preset = LessonTemplatePreset(PRESCHOOL_TEMPLATE, "beginner", True)
        self.store.ensure_presets((preset,))
        loaded, revision = self.store.load_template("preschool")
        edited_block = replace(loaded.template.blocks[0], title="Моє привітання", duration_minutes=5)
        edited_template = replace(loaded.template, blocks=(edited_block, *loaded.template.blocks[1:]))
        updated = self.store.update_template(
            LessonTemplatePreset(edited_template, loaded.level, loaded.is_preset),
            expected_revision=revision.revision,
        )

        self.store.ensure_presets((preset,))
        after, after_revision = self.store.load_template("preschool")
        self.assertEqual(updated, after_revision)
        self.assertEqual("Моє привітання", after.template.blocks[0].title)
        self.assertEqual(5, after.template.blocks[0].duration_minutes)

    def test_template_update_requires_exact_revision(self) -> None:
        preset = LessonTemplatePreset(PRESCHOOL_TEMPLATE, "beginner", True)
        self.store.save_new_template(preset)
        self.store.update_template(preset, expected_revision=1)
        with self.assertRaises(LessonTemplateConflictError):
            self.store.update_template(preset, expected_revision=1)

    def test_rotation_rounds_persist_order_and_stable_references(self) -> None:
        first = RotationRoundRecord(
            "round-1",
            "class-1",
            1,
            "Демонстрація",
            RotationRoundState.PLANNED,
            ("pair-1", "pair-2"),
            ("batch-a",),
        )
        second = RotationRoundRecord(
            "round-2",
            "class-1",
            2,
            "Парна гра",
            RotationRoundState.PLANNED,
            ("pair-3", "pair-4"),
            ("batch-b", "batch-c"),
        )
        self.store.save_new_rotation(second)
        first_revision = self.store.save_new_rotation(first)
        loaded, loaded_revision = self.store.load_rotation("round-1")
        self.assertEqual(first, loaded)
        self.assertEqual(first_revision, loaded_revision)
        self.assertEqual((first, second), self.store.list_rotations("class-1"))

    def test_rotation_state_update_is_optimistic_and_identity_order_is_immutable(self) -> None:
        planned = RotationRoundRecord("round-1", "class-1", 1, "Раунд", pairing_ids=("pair-1",))
        self.store.save_new_rotation(planned)
        active = replace(planned, state=RotationRoundState.ACTIVE, label="Раунд триває")
        revision = self.store.update_rotation(active, expected_revision=1)
        loaded, loaded_revision = self.store.load_rotation("round-1")
        self.assertEqual(2, revision.revision)
        self.assertEqual(revision, loaded_revision)
        self.assertEqual(RotationRoundState.ACTIVE, loaded.state)
        self.assertEqual("Раунд триває", loaded.label)
        with self.assertRaises(LessonTemplateConflictError):
            self.store.update_rotation(active, expected_revision=1)
        with self.assertRaises(LessonTemplateConflictError):
            self.store.update_rotation(replace(active, round_number=2), expected_revision=2)

    def test_rotation_round_number_conflict_is_atomic(self) -> None:
        first = RotationRoundRecord("round-1", "class-1", 1, "Перший")
        collision = RotationRoundRecord("round-other", "class-1", 1, "Колізія")
        self.store.save_new_rotation(first)
        with self.assertRaises(LessonTemplateConflictError):
            self.store.save_new_rotation(collision)
        self.assertEqual((first,), self.store.list_rotations("class-1"))

    def test_future_template_schema_fails_closed_without_rewriting_database(self) -> None:
        with sqlite3.connect(self.path) as db:
            db.execute(
                "UPDATE lesson_template_schema_meta SET value=? WHERE key='schema_version'",
                (TEMPLATE_SCHEMA_VERSION + 1,),
            )
        before = self.path.read_bytes()
        with self.assertRaises(LessonTemplateStorageError):
            LessonTemplateSQLiteStore(self.path)
        self.assertEqual(before, self.path.read_bytes())


if __name__ == "__main__":
    unittest.main()
