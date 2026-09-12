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


STAMP = "2026-08-25T08:00:00Z"


def education_workspace(*, class_title: str = "Клас Альфа") -> EducationWorkspace:
    classroom = cd.ClassroomSnapshot(
        students=(cd.Student("student-1", "Учень 1", cd.ConsentState.GRANTED),),
        classes=(cd.ClassroomClass("class-alpha", class_title),),
        courses=(cd.Course("course-1", "Тактика", ("lesson-1",)),),
        cohorts=(cd.Cohort("cohort-1", "course-1", ("student-1",)),),
        lessons=(cd.Lesson("lesson-1", "course-1", "Вилки", (), STAMP),),
        assignments=(
            cd.Assignment(
                "assignment-1",
                "lesson-1",
                "cohort-1",
                "Домашня робота",
                STAMP,
            ),
        ),
    )
    return EducationWorkspace.empty(classroom)


class EducationOpenSelectedProjectionTests(unittest.TestCase):
    def test_open_selected_revalidates_trusted_identity_and_returns_bounded_detail(self) -> None:
        workspace = education_workspace()
        calls: list[tuple[str, dict[str, object]]] = []

        def dispatch(action_id: str, payload: dict[str, object]) -> object:
            calls.append((action_id, dict(payload)))
            return {
                "validated": True,
                "detail": {
                    "kind": "class",
                    "heading": "Клас Альфа",
                    "secondary": "",
                    "status": "0 груп",
                },
            }

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
        state = {"workspace": education_workspace()}
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

    def test_open_selected_publishes_fresh_same_id_detail_from_trusted_host(self) -> None:
        state = {"workspace": education_workspace(class_title="Старе значення")}
        application = object.__new__(Version2EducationMutationApplication)
        application._education_provider = lambda: state["workspace"]
        application.shell = SimpleNamespace(language=UILanguage.UA)

        def dispatch(action_id: str, payload: dict[str, object]) -> object:
            state["workspace"] = education_workspace(class_title="Нове значення")
            return application._education_dispatch(action_id, payload)

        projection = MutableEducationWebViewProjection(
            lambda: state["workspace"],
            dispatch,
            language=UILanguage.UA,
        )
        projection.snapshot()

        event = projection.open_selected("class")
        self.assertEqual(event.kind, "delegated")
        self.assertEqual(event.payload["detail"]["heading"], "Нове значення")
        self.assertNotEqual(event.payload["detail"]["heading"], "Старе значення")
        self.assertNotIn("class-alpha", repr(event.payload))
        self.assertNotIn("revision", repr(event.payload).lower())


class EducationReadOpenDispatchTests(unittest.TestCase):
    @staticmethod
    def _application_with_records() -> Version2EducationMutationApplication:
        application = object.__new__(Version2EducationMutationApplication)
        workspace = education_workspace()
        application._education_provider = lambda: workspace
        application.shell = SimpleNamespace(language=UILanguage.UA)
        return application

    def test_all_open_actions_revalidate_current_canonical_record(self) -> None:
        application = self._application_with_records()
        cases = {
            "classes.open": ("class-alpha", "class", "Клас Альфа"),
            "classes.student_open": ("student-1", "student", "Учень 1"),
            "classes.lesson_open": ("lesson-1", "lesson", "Вилки"),
            "classes.assignment_open": ("assignment-1", "assignment", "Домашня робота"),
        }
        for action_id, (record_id, kind, heading) in cases.items():
            with self.subTest(action_id=action_id):
                result = application._education_dispatch(
                    action_id,
                    {"record_id": record_id},
                )
                self.assertTrue(result["validated"])
                self.assertEqual(result["detail"]["kind"], kind)
                self.assertEqual(result["detail"]["heading"], heading)
                self.assertNotIn(record_id, repr(result))
                self.assertNotIn("revision", repr(result).lower())

    def test_open_action_rejects_missing_stale_or_extra_authority_fields(self) -> None:
        application = self._application_with_records()
        for payload in (
            {},
            {"record_id": "missing"},
            {"record_id": "class-alpha", "revision": "browser-controlled"},
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
