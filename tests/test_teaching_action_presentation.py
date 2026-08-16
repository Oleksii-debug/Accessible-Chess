from __future__ import annotations

import unittest
from pathlib import Path

from acs.teaching_action_presentation import TeachingActionPresentation
from acs.teaching_ui import TeachingUiState


ROOT = Path(__file__).resolve().parents[1]
HTML = ROOT / "web" / "teaching_actions.html"


class TeachingActionPresentationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.state = TeachingUiState()
        self.actions = TeachingActionPresentation(self.state)

    def test_snapshot_exposes_pointer_and_annotation_actions_from_central_registry(self) -> None:
        rows = {row["actionId"]: row for row in self.actions.snapshot()["actions"]}
        self.assertEqual(
            set(rows),
            {
                "teaching.pointer_input",
                "teaching.annotation.square",
                "teaching.annotation.arrow",
            },
        )
        self.assertIsNone(rows["teaching.pointer_input"]["binding"])

    def test_pointer_action_can_be_remapped_and_dispatched_by_binding(self) -> None:
        saved = self.actions.set_binding("teaching.pointer_input", "Ctrl+Alt+P")
        self.assertTrue(saved["ok"])
        self.assertEqual(saved["binding"], "Ctrl+Alt+P")
        result = self.actions.dispatch_binding("ctrl-alt-p", {"value": "f3"})
        self.assertTrue(result["ok"])
        self.assertEqual(result["square"], "f3")
        self.assertTrue(result["clearInput"])
        self.assertTrue(result["keepFocus"])
        self.assertEqual(self.state.snapshot()["pointer"]["square"], "f3")

    def test_annotation_actions_delegate_to_existing_overlay_state(self) -> None:
        square = self.actions.dispatch(
            "teaching.annotation.square",
            {"annotationId": "sq-1", "square": "c7"},
        )
        arrow = self.actions.dispatch(
            "teaching.annotation.arrow",
            {"annotationId": "ar-1", "source": "f3", "target": "c6"},
        )
        self.assertTrue(square["ok"])
        self.assertTrue(arrow["ok"])
        rows = self.state.snapshot()["annotations"]
        self.assertEqual(rows[0]["source"], "c7")
        self.assertEqual(rows[1]["source"], "f3")
        self.assertEqual(rows[1]["target"], "c6")

    def test_invalid_binding_or_payload_fails_concisely_without_exception_text(self) -> None:
        bad_binding = self.actions.set_binding("teaching.pointer_input", "Shift+Shift")
        self.assertFalse(bad_binding["ok"])
        self.assertNotIn("ValueError", bad_binding["accessibleText"])
        bad_payload = self.actions.dispatch("teaching.pointer_input", {"value": "f9"})
        self.assertFalse(bad_payload["ok"])
        self.assertNotIn("ValueError", bad_payload["accessibleText"])
        unknown = self.actions.dispatch_binding("Ctrl+Alt+Q", {"value": "f3"})
        self.assertFalse(unknown["ok"])


class TeachingActionSemanticTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.html = HTML.read_text(encoding="utf-8")

    def test_settings_surface_has_one_action_live_region_and_native_text_inputs(self) -> None:
        self.assertEqual(self.html.count('role="status"'), 1)
        self.assertIn('id="action-list"', self.html)
        self.assertIn('id="pointer-test"', self.html)
        self.assertNotIn("document.addEventListener('keydown'", self.html)
        self.assertNotIn('document.addEventListener("keydown"', self.html)

    def test_surface_uses_central_action_api_and_preserves_focus_after_pointer_test(self) -> None:
        self.assertIn("teaching_action_set_binding", self.html)
        self.assertIn("teaching_action_dispatch", self.html)
        self.assertIn("input.value=''", self.html)
        self.assertIn("input.focus()", self.html)


if __name__ == "__main__":
    unittest.main()
