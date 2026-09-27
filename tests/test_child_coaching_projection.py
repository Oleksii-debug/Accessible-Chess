from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import tempfile
import unittest

from acs.child_coaching import LessonBlock, LessonBlockKind
from acs.child_coaching_application import ChildCoachingApplication
from acs.child_coaching_projection import ChildCoachingProjection
from acs.child_coaching_store import ChildCoachingTemplateStore
from acs.full_product_ui_shell import UILanguage
from acs.teaching_session import TeachingActivity


class ChildCoachingProjectionTests(unittest.TestCase):
    def make_projection(
        self,
        temp: str,
        language: UILanguage = UILanguage.UA,
    ) -> tuple[ChildCoachingApplication, ChildCoachingProjection]:
        app = ChildCoachingApplication(
            ChildCoachingTemplateStore(Path(temp) / "child-coaching.json")
        )
        return app, ChildCoachingProjection(app, language=language)

    def test_snapshot_is_semantic_bounded_and_bilingual(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            _, ua = self.make_projection(temp, UILanguage.UA)
            ua_snapshot = ua.snapshot()
            self.assertEqual(ua_snapshot["document"]["lang"], "uk")
            self.assertEqual(
                ua_snapshot["document"]["heading"],
                "Шаблони занять для дітей",
            )
            self.assertGreaterEqual(len(ua_snapshot["templates"]), 4)
            preschool = next(
                item for item in ua_snapshot["templates"]
                if item["template_id"] == "preset-preschool-4-6"
            )
            self.assertIn("4–6 років", preschool["accessible_label"])
            self.assertIn("30 хвилин", preschool["accessible_label"])

            _, en = self.make_projection(temp, UILanguage.EN)
            en_snapshot = en.snapshot()
            self.assertEqual(en_snapshot["document"]["lang"], "en")
            preschool_en = next(
                item for item in en_snapshot["templates"]
                if item["template_id"] == "preset-preschool-4-6"
            )
            self.assertIn("ages 4–6", preschool_en["accessible_label"])
            self.assertIn("30 minutes", preschool_en["accessible_label"])

    def test_teacher_view_contains_private_note_but_student_preview_never_does(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            app, projection = self.make_projection(temp)
            catalog = app.open_catalog()
            catalog = app.copy_template(
                "preset-young-beginner-7-8",
                template_id="private-note-template",
                title="Private note lesson",
                expected_revision=catalog.revision,
            )
            template, revision = app.get_template("private-note-template")
            first = template.blocks[0]
            app.replace_block(
                template.template_id,
                first.block_id,
                replace(first, teacher_note="Do not show this to the student."),
                expected_revision=revision,
            )

            teacher = projection.open_teacher_template("private-note-template")
            student = projection.student_preview("private-note-template")
            teacher_block = teacher.payload["template"]["blocks"][0]
            student_block = student.payload["template"]["blocks"][0]
            self.assertEqual(
                teacher_block["teacher_note"],
                "Do not show this to the student.",
            )
            self.assertNotIn("teacher_note", student_block)
            self.assertNotIn("teacher_note_label", student_block)
            self.assertNotIn(
                "Do not show this to the student.",
                repr(student.payload),
            )


    def test_student_preview_never_leaks_solution_text_before_canonical_reveal(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            app, projection = self.make_projection(temp, UILanguage.EN)
            catalog = app.open_catalog()
            catalog = app.copy_template(
                "preset-preschool-4-6",
                template_id="solution-template",
                title="Solution template",
                expected_revision=catalog.revision,
            )
            solution = LessonBlock(
                "solution",
                LessonBlockKind.REVIEW,
                "Solution",
                3,
                TeachingActivity.SOLUTION_REVEAL,
                "Now review the solution.",
                teacher_note="Teacher may discuss alternatives.",
                solution_text="The hidden answer is e4.",
            )
            catalog = app.append_block(
                "solution-template",
                solution,
                expected_revision=catalog.revision,
            )

            teacher = projection.open_teacher_template("solution-template")
            student = projection.student_preview("solution-template")
            teacher_solution = teacher.payload["template"]["blocks"][-1]
            student_solution = student.payload["template"]["blocks"][-1]
            self.assertEqual(
                teacher_solution["solution_text"],
                "The hidden answer is e4.",
            )
            self.assertNotIn("solution_text", student_solution)
            self.assertNotIn("The hidden answer is e4.", repr(student.payload))
            self.assertNotIn("Teacher may discuss alternatives.", repr(student.payload))


    def test_student_preview_never_leaks_target_answer_fields(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            app, projection = self.make_projection(temp, UILanguage.EN)
            catalog = app.open_catalog()
            catalog = app.copy_template(
                "preset-preschool-4-6",
                template_id="target-template",
                title="Target template",
                expected_revision=catalog.revision,
            )
            target = LessonBlock(
                "find-square",
                LessonBlockKind.POINTER_TASK,
                "Find square",
                3,
                TeachingActivity.SHOW_SQUARE,
                "Find the requested square.",
                target_square="e4",
            )
            catalog = app.append_block(
                "target-template",
                target,
                expected_revision=catalog.revision,
            )

            teacher = projection.open_teacher_template("target-template")
            student = projection.student_preview("target-template")
            teacher_target = teacher.payload["template"]["blocks"][-1]
            student_target = student.payload["template"]["blocks"][-1]
            self.assertEqual(teacher_target["target_square"], "e4")
            self.assertIsNone(teacher_target["target_piece"])
            self.assertNotIn("target_square", student_target)
            self.assertNotIn("target_piece", student_target)
            self.assertNotIn('"e4"', repr(student.payload))

    def test_projection_does_not_create_move_or_board_state(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            _, projection = self.make_projection(temp)
            event = projection.student_preview("preset-school-age-9-10")
            payload = event.payload["template"]
            self.assertNotIn("fen", payload)
            self.assertNotIn("board", payload)
            self.assertNotIn("position", payload)
            move_blocks = [
                block for block in payload["blocks"]
                if block["activity"] == "make_move"
            ]
            self.assertEqual(len(move_blocks), 1)
            self.assertEqual(move_blocks[0]["prompt"], "Play the applied position using board move controls.")

    def test_invalid_template_is_reduced_to_concise_accessible_error(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            _, projection = self.make_projection(temp, UILanguage.EN)
            event = projection.safe_open_teacher_template("missing-template")
            self.assertEqual(event.kind, "error")
            self.assertEqual(
                event.payload["message"],
                "The lesson template could not be opened.",
            )
            self.assertNotIn("Traceback", repr(event.payload))
            self.assertNotIn(str(Path(temp)), repr(event.payload))

    def test_student_preview_announcement_states_duration_and_notation_mode(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            _, projection = self.make_projection(temp, UILanguage.EN)
            event = projection.student_preview("preset-preschool-4-6")
            self.assertIn("30 minutes", event.payload["announcement"])
            self.assertIn("7 blocks", event.payload["announcement"])
            self.assertIn(
                "no notation entry required",
                event.payload["announcement"],
            )


if __name__ == "__main__":
    unittest.main()
