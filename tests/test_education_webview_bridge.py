import unittest

from acs.education_webview_bridge import EducationWebViewBridge
from acs.education_webview_projection import EducationWebViewProjection
from acs.education_workspace import EducationWorkspace
from acs.full_product_ui_shell import UILanguage
from tests.test_education_webview_projection import classroom


class EducationWebViewBridgeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.workspace = EducationWorkspace.empty(classroom(class_count=3))
        self.calls: list[tuple[str, dict[str, object]]] = []
        projection = EducationWebViewProjection(
            lambda: self.workspace,
            lambda action, payload: self.calls.append((action, dict(payload))),
            language=UILanguage.EN,
            page_size=2,
        )
        self.bridge = EducationWebViewBridge(projection)

    @staticmethod
    def class_section(event):
        return next(
            item for item in event.payload["snapshot"]["sections"]
            if item["kind"] == "class"
        )

    def test_snapshot_select_page_open_and_new_class_use_small_exact_commands(self) -> None:
        rendered = self.bridge.dispatch("education.snapshot", {})
        self.assertEqual("render", rendered.kind)
        classes = self.class_section(rendered)
        second_key = classes["items"][1]["item_key"]
        selected = self.bridge.dispatch(
            "education.select",
            {"kind": "class", "item_key": second_key},
        )
        self.assertEqual("selection", selected.kind)
        self.assertTrue(selected.payload["focus_target"])
        self.assertEqual(
            "delegated",
            self.bridge.dispatch("education.open", {"kind": "class"}).kind,
        )
        self.assertEqual(
            ("classes.open", {"record_id": "private-class-2"}),
            self.calls[-1],
        )
        page = self.bridge.dispatch(
            "education.page", {"kind": "class", "direction": 1}
        )
        self.assertEqual(2, page.payload["snapshot"]["page"])
        self.assertEqual(
            "delegated", self.bridge.dispatch("education.new_class", {}).kind
        )
        self.assertEqual(("classes.new", {}), self.calls[-1])

    def test_browser_cannot_supply_workspace_identity_chess_or_mutation_authority(self) -> None:
        attacks = (
            ("education.snapshot", {"path": "C:/Users/private/workspace.json"}),
            ("education.select", {"kind": "student", "item_key": "private-student-1"}),
            ("education.open", {"kind": "student", "student_id": "private-student-1"}),
            ("education.page", {"kind": "class", "direction": True}),
            ("education.move", {"kind": "class", "direction": 0}),
            ("education.submit", {"fen": "private-fen", "revision": 7}),
            ("education.homework.update", {"response_ref": "private-response-ref"}),
            ("student.move", {"raw_text": "e4"}),
        )
        for command, payload in attacks:
            with self.subTest(command=command, payload=payload):
                event = self.bridge.dispatch(command, payload)
                self.assertEqual("error", event.kind)
                rendered = repr(event)
                for secret in (
                    "C:/Users/private",
                    "private-student-1",
                    "private-fen",
                    "private-response-ref",
                ):
                    self.assertNotIn(secret, rendered)
        self.assertEqual([], self.calls)

    def test_scalar_payload_and_provider_failure_are_sanitized(self) -> None:
        self.assertEqual(
            "error", self.bridge.dispatch("education.snapshot", "bad").kind
        )
        broken = EducationWebViewBridge(
            EducationWebViewProjection(
                lambda: (_ for _ in ()).throw(RuntimeError("C:/private/provider")),
                lambda _action, _payload: None,
                language=UILanguage.EN,
            )
        )
        event = broken.dispatch("education.snapshot", {})
        self.assertEqual("error", event.kind)
        self.assertNotIn("private", repr(event).lower())


if __name__ == "__main__":
    unittest.main()
