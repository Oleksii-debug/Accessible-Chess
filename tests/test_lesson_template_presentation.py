from __future__ import annotations

import unittest

from acs.child_coaching_ui import PRESCHOOL_TEMPLATE
from acs.lesson_template_presentation import LessonTemplatePresentation
from acs.lesson_template_storage import LessonTemplatePreset, TemplateRevision


class FakeLessonApplication:
    def __init__(self) -> None:
        self.rows = {
            PRESCHOOL_TEMPLATE.template_id: (
                LessonTemplatePreset(PRESCHOOL_TEMPLATE, level="beginner", is_preset=True),
                TemplateRevision(PRESCHOOL_TEMPLATE.template_id, 1),
            )
        }
        self.saved_expected_revision = None
        self.fail = False

    def ensure_default_templates(self):
        if self.fail:
            raise RuntimeError("private sqlite path /tmp/secret.db")
        return tuple(revision for _, revision in self.rows.values())

    def save_new_template(self, template, *, level, is_preset=False):
        if self.fail:
            raise RuntimeError("private sqlite path /tmp/secret.db")
        revision = TemplateRevision(template.template_id, 1)
        self.rows[template.template_id] = (
            LessonTemplatePreset(template, level=level, is_preset=is_preset),
            revision,
        )
        return revision

    def update_template(self, template, *, level, expected_revision, is_preset=False):
        if self.fail:
            raise RuntimeError("private sqlite path /tmp/secret.db")
        self.saved_expected_revision = expected_revision
        current = self.rows[template.template_id][1]
        if expected_revision != current.revision:
            raise RuntimeError("revision conflict internal detail")
        revision = TemplateRevision(template.template_id, current.revision + 1)
        self.rows[template.template_id] = (
            LessonTemplatePreset(template, level=level, is_preset=is_preset),
            revision,
        )
        return revision

    def load_template(self, template_id):
        if self.fail:
            raise RuntimeError("private sqlite path /tmp/secret.db")
        return self.rows[template_id]


class LessonTemplatePresentationTests(unittest.TestCase):
    def test_preset_can_be_opened_as_accessible_readable_state(self) -> None:
        app = FakeLessonApplication()
        ui = LessonTemplatePresentation(app)
        result = ui.open_template("preschool")
        self.assertTrue(result["ok"])
        self.assertTrue(result["open"])
        self.assertEqual(result["template"]["revision"], 1)
        self.assertTrue(result["template"]["isPreset"])
        self.assertIn("Відкрито шаблон", result["accessibleText"])

    def test_copy_edit_save_reopen_preserves_custom_template(self) -> None:
        app = FakeLessonApplication()
        ui = LessonTemplatePresentation(app)
        started = ui.begin_copy(
            PRESCHOOL_TEMPLATE,
            template_id="oleksii-preschool",
            title="Мій урок",
        )
        self.assertFalse(started["template"]["persisted"])
        edited = ui.edit_block("movement", title="Кінь шукає поле", duration_minutes=9)
        self.assertTrue(edited["ok"])
        saved = ui.save()
        self.assertTrue(saved["ok"])
        self.assertEqual(saved["template"]["revision"], 1)
        self.assertFalse(saved["template"]["isPreset"])

        reopened = LessonTemplatePresentation(app)
        state = reopened.open_template("oleksii-preschool")
        movement = next(
            block for block in state["template"]["blocks"] if block["blockId"] == "movement"
        )
        self.assertEqual(movement["title"], "Кінь шукає поле")
        self.assertEqual(movement["durationMinutes"], 9)

    def test_second_save_uses_current_revision_and_never_overwrites_silently(self) -> None:
        app = FakeLessonApplication()
        ui = LessonTemplatePresentation(app)
        ui.begin_copy(PRESCHOOL_TEMPLATE, template_id="custom", title="Custom")
        ui.save()
        ui.edit_block("hello", duration_minutes=4)
        saved = ui.save()
        self.assertTrue(saved["ok"])
        self.assertEqual(app.saved_expected_revision, 1)
        self.assertEqual(saved["template"]["revision"], 2)

    def test_invalid_edit_is_concise_and_does_not_leak_python_error(self) -> None:
        app = FakeLessonApplication()
        ui = LessonTemplatePresentation(app)
        ui.begin_copy(PRESCHOOL_TEMPLATE, template_id="custom", title="Custom")
        result = ui.edit_block("hello", duration_minutes=0)
        self.assertFalse(result["ok"])
        self.assertNotIn("ValueError", result["accessibleText"])

    def test_storage_failure_is_redacted(self) -> None:
        app = FakeLessonApplication()
        ui = LessonTemplatePresentation(app)
        ui.begin_copy(PRESCHOOL_TEMPLATE, template_id="custom", title="Custom")
        app.fail = True
        result = ui.save()
        self.assertFalse(result["ok"])
        self.assertNotIn("RuntimeError", result["accessibleText"])
        self.assertNotIn("/tmp/secret.db", result["accessibleText"])

    def test_default_template_setup_reports_one_concise_result(self) -> None:
        app = FakeLessonApplication()
        ui = LessonTemplatePresentation(app)
        result = ui.ensure_presets()
        self.assertTrue(result["ok"])
        self.assertGreaterEqual(result["count"], 1)
        self.assertEqual(result["accessibleText"], "Стандартні шаблони уроків готові.")


if __name__ == "__main__":
    unittest.main()
