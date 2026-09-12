from __future__ import annotations

import unittest
from types import SimpleNamespace

from acs import classroom_domain as cd
from acs.education_workspace import EducationWorkspace
from acs.full_product_ui_shell import UILanguage
from acs.version2_education_mutation_application import (
    MutableEducationWebViewProjection,
    Version2EducationMutationApplication,
)
from acs.version2_final_product_profile import build_final_product_action_registry


class EducationOpenSelectedProjectionTests(unittest.TestCase):
    def test_open_selected_revalidates_trusted_identity_and_returns_bounded_detail(self) -> None:
        workspace = EducationWorkspace.empty(
            cd.ClassroomSnapshot(classes=(cd.ClassroomClass("class-alpha", "Клас Альфа"),))
        )
        calls: list[tuple[str, dict[str, object]]] = []

        def dispatch(action_id: str, payload: dict[str, object]) -> object:
            calls.append((action_id, dict(payload)))
            return {"validated": True, "kind": "class"}

        projection = MutableEducationWebViewProjection(
            lambda: workspace,
            dispatch,
            language=UILanguage.UA,
        )
        snapshot = projection.snapshot()
        self.assertTrue(snapshot["sections"][0]["items"][0]["selected"])

        event = projection.open_selected("class")
        self.assertEqual(calls, [("classes.open", {"record_id": "class-alpha"})])
        self.assertEqual(event.kind, "delegated")
        self.assertEqual(event.payload["detail"]["kind"], "class")
        self.assertEqual(event.payload["detail"]["heading"], "Клас Альфа")
        self.assertNotIn("record_id", event.payload["detail"])
        self.assertNotIn("class-alpha", repr(event.payload))
        self.assertEqual(event.payload["focus_target"], "education-detail-heading")
        self.assertEqual(event.payload["announcement"], "Відкрито: Клас Альфа")

    def test_open_selected_fails_closed_if_selection_becomes_stale(self) -> None:
        state = {
            "workspace": EducationWorkspace.empty(
                cd.ClassroomSnapshot(classes=(cd.ClassroomClass("class-alpha", "Клас Альфа"),))
            )
        }
        calls: list[tuple[str, dict[str, object]]] = []
        projection = MutableEducationWebViewProjection(
            lambda: state["workspace"],
            lambda action_id, payload: calls.append((action_id, dict(payload))),
            language=UILanguage.UA,
        )
        projection.snapshot()
        state["workspace"] = EducationWorkspace.empty(cd.ClassroomSnapshot())

        event = projection.open_selected("class")
        self.assertEqual(event.kind, "error")
        self.assertEqual(calls, [])


class EducationReadOpenDispatchTests(unittest.TestCase):
    @staticmethod
    def _application_with_records() -> Version2EducationMutationApplication:
        application = object.__new__(Version2EducationMutationApplication)
        classroom = SimpleNamespace(
            classes=(SimpleNamespace(class_id="class-1"),),
            students=(SimpleNamespace(student_id="student-1"),),
            lessons=(SimpleNamespace(lesson_id="lesson-1"),),
            assignments=(SimpleNamespace(assignment_id="assignment-1"),),
        )
        application._education_provider = lambda: SimpleNamespace(classroom=classroom)
        return application

    def test_all_open_actions_revalidate_current_canonical_record(self) -> None:
        application = self._application_with_records()
        cases = {
            "classes.open": ("class-1", "class"),
            "classes.student_open": ("student-1", "student"),
            "classes.lesson_open": ("lesson-1", "lesson"),
            "classes.assignment_open": ("assignment-1", "assignment"),
        }
        for action_id, (record_id, kind) in cases.items():
            with self.subTest(action_id=action_id):
                result = application._education_dispatch(
                    action_id,
                    {"record_id": record_id},
                )
                self.assertEqual(result, {"validated": True, "kind": kind})
                self.assertNotIn(record_id, repr(result))

    def test_open_action_rejects_missing_stale_or_extra_authority_fields(self) -> None:
        application = self._application_with_records()
        for payload in (
            {},
            {"record_id": "missing"},
            {"record_id": "class-1", "revision": "browser-controlled"},
        ):
            with self.subTest(payload=payload):
                with self.assertRaises((LookupError, ValueError)):
                    application._education_dispatch("classes.open", payload)

    def test_final_registry_exposes_only_safe_read_open_actions(self) -> None:
        ids = {
            definition.action_id
            for definition in build_final_product_action_registry().definitions()
        }
        self.assertTrue(
            {
                "classes.open",
                "classes.student_open",
                "classes.lesson_open",
                "classes.assignment_open",
            }.issubset(ids)
        )
        self.assertNotIn("classes.new", ids)
        self.assertFalse(any(action_id.startswith("remote.") for action_id in ids))


if __name__ == "__main__":
    unittest.main()
