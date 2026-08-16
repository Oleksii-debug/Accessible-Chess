from __future__ import annotations

import unittest
from pathlib import Path

from acs.child_coaching_ui import PRESCHOOL_TEMPLATE
from acs.lesson_template_presentation import LessonTemplatePresentation
from acs.lesson_template_storage import LessonTemplatePreset, TemplateRevision
from acs.teaching_webapp import TeachingAccessibleChessAPI


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

    def test_open_copy_current_edit_save_is_complete_ui_journey(self) -> None:
        app = FakeLessonApplication()
        ui = LessonTemplatePresentation(app)
        self.assertTrue(ui.open_template("preschool")["ok"])
        copied = ui.begin_copy_current(
            template_id="group-a-lesson",
            title="Урок групи А",
            level="absolute_beginner",
        )
        self.assertTrue(copied["ok"])
        self.assertFalse(copied["template"]["persisted"])
        changed = ui.edit_block("recognition", title="Знайди коня", duration_minutes=7)
        self.assertTrue(changed["ok"])
        saved = ui.save()
        self.assertTrue(saved["ok"])
        self.assertEqual(saved["template"]["templateId"], "group-a-lesson")
        self.assertEqual(saved["template"]["level"], "absolute_beginner")
        self.assertEqual(saved["template"]["revision"], 1)

    def test_standard_preset_is_read_only_until_explicit_copy(self) -> None:
        app = FakeLessonApplication()
        ui = LessonTemplatePresentation(app)
        ui.open_template("preschool")
        result = ui.save()
        self.assertFalse(result["ok"])
        self.assertIn("власну копію", result["accessibleText"])
        self.assertEqual(app.rows["preschool"][1].revision, 1)

    def test_actions_without_open_template_fail_concisely(self) -> None:
        ui = LessonTemplatePresentation(FakeLessonApplication())
        for result in (
            ui.begin_copy_current(template_id="x", title="X"),
            ui.edit_block("hello", title="X"),
            ui.save(),
        ):
            self.assertFalse(result["ok"])
            self.assertEqual(result["accessibleText"], "Спочатку відкрийте шаблон уроку.")
            self.assertNotIn("ValueError", result["accessibleText"])

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


class LessonTemplateWebApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.application = FakeLessonApplication()
        self.presentation = LessonTemplatePresentation(self.application)
        self.api = TeachingAccessibleChessAPI(lesson_templates=self.presentation)

    def test_api_exposes_persisted_template_copy_edit_save_without_storage_details(self) -> None:
        self.assertTrue(self.api.coaching_template_prepare()["ok"])
        self.assertTrue(self.api.coaching_template_open("preschool")["ok"])
        copied = self.api.coaching_template_begin_copy("coach-copy", "Мій шаблон", "beginner")
        self.assertTrue(copied["ok"])
        edited = self.api.coaching_template_edit_block("hello", "Старт", 4)
        self.assertTrue(edited["ok"])
        saved = self.api.coaching_template_save()
        self.assertTrue(saved["ok"])
        self.assertEqual(saved["template"]["revision"], 1)

    def test_api_without_persistence_provider_fails_closed(self) -> None:
        api = TeachingAccessibleChessAPI()
        result = api.coaching_template_open("preschool")
        self.assertFalse(result["ok"])
        self.assertEqual(result["accessibleText"], "Збережені шаблони уроків недоступні.")

    def test_child_coaching_page_has_semantic_persisted_editor_and_one_live_region(self) -> None:
        html = (Path(__file__).resolve().parents[1] / "web" / "child_coaching.html").read_text(
            encoding="utf-8"
        )
        for control_id in (
            'id="persisted-template-select"',
            'id="open-persisted-template"',
            'id="copy-template-id"',
            'id="copy-template-title"',
            'id="copy-persisted-template"',
            'id="save-persisted-template"',
            'id="persisted-template-blocks"',
        ):
            self.assertIn(control_id, html)
        self.assertEqual(html.count('aria-live="polite"'), 1)
        self.assertNotIn("document.addEventListener('keydown'", html)
        self.assertNotIn('document.addEventListener("keydown"', html)
        self.assertIn("coaching_template_begin_copy", html)
        self.assertIn("coaching_template_save", html)


if __name__ == "__main__":
    unittest.main()
