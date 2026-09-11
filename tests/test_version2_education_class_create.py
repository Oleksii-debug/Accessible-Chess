from __future__ import annotations

import importlib
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from acs import classroom_domain as cd
from acs.education_class_management import create_class
from acs.education_workspace import EducationWorkspace, EducationWorkspaceError
from acs.education_workspace_store import EducationWorkspaceStore
from acs.full_product_ui_shell import UILanguage
from acs.version2_education_mutation_application import (
    MutableEducationWebViewProjection,
    Version2EducationMutationApplication,
)
from acs.version2_final_product_profile import build_final_product_action_registry


class EducationClassManagementTests(unittest.TestCase):
    def test_create_class_reanchors_canonical_workspace(self) -> None:
        original = EducationWorkspace.empty(cd.ClassroomSnapshot())
        updated = create_class(
            original,
            class_id="class-alpha",
            title="Клас Альфа",
            operation_id="class-create-alpha",
        )

        self.assertEqual(original.classroom.classes, ())
        self.assertEqual(len(updated.classroom.classes), 1)
        self.assertEqual(updated.classroom.classes[0].class_id, "class-alpha")
        self.assertEqual(updated.classroom.classes[0].title, "Клас Альфа")
        self.assertEqual(updated.ledger.classroom_digest, updated.classroom.digest)
        self.assertGreater(updated.ledger.revision, original.ledger.revision)

    def test_create_class_rejects_duplicate_identity_without_mutating_input(self) -> None:
        original = EducationWorkspace.empty(
            cd.ClassroomSnapshot(classes=(cd.ClassroomClass("class-alpha", "Альфа"),))
        )
        with self.assertRaises(EducationWorkspaceError):
            create_class(
                original,
                class_id="class-alpha",
                title="Інший клас",
                operation_id="class-create-duplicate",
            )
        self.assertEqual(original.classroom.classes[0].title, "Альфа")

    def test_created_class_survives_store_cas_and_fresh_reopen(self) -> None:
        original = EducationWorkspace.empty(cd.ClassroomSnapshot())
        with tempfile.TemporaryDirectory() as temp:
            store = EducationWorkspaceStore(Path(temp) / "education-workspace.json")
            first_revision = store.save(original, expected_revision=None)
            updated = create_class(
                original,
                class_id="class-persisted",
                title="Постійний клас",
                operation_id="class-create-persisted",
            )
            second_revision = store.save(updated, expected_revision=first_revision)
            self.assertNotEqual(second_revision, first_revision)

            reopened = EducationWorkspaceStore(store.path).load()
            self.assertIsNotNone(reopened)
            assert reopened is not None
            self.assertEqual(reopened.revision, second_revision)
            self.assertEqual(reopened.workspace, updated)


class EducationClassProjectionTests(unittest.TestCase):
    def test_new_class_refreshes_and_focuses_created_class(self) -> None:
        state = {
            "workspace": EducationWorkspace.empty(
                cd.ClassroomSnapshot(classes=(cd.ClassroomClass("class-existing", "Перший"),))
            )
        }

        def provider() -> EducationWorkspace:
            return state["workspace"]

        def dispatch(action_id: str, payload: dict[str, object]) -> object:
            self.assertEqual(action_id, "classes.new")
            self.assertEqual(payload, {})
            state["workspace"] = create_class(
                state["workspace"],
                class_id="class-created",
                title="Новий клас 2",
                operation_id="class-create-projection",
            )
            return {"class_id": "class-created", "revision": "test-revision"}

        projection = MutableEducationWebViewProjection(
            provider,
            dispatch,
            language=UILanguage.UA,
            page_size=1,
        )
        event = projection.new_class()

        self.assertEqual(event.kind, "selection")
        snapshot = event.payload["snapshot"]
        self.assertEqual(snapshot["kind"], "class")
        self.assertEqual(snapshot["page"], 2)
        self.assertEqual(len(snapshot["items"]), 1)
        self.assertEqual(snapshot["items"][0]["label"], "Новий клас 2")
        self.assertTrue(snapshot["items"][0]["selected"])
        self.assertEqual(event.payload["focus_target"], snapshot["items"][0]["dom_id"])
        self.assertEqual(event.payload["announcement"], "Клас створено")

    def test_new_class_failure_returns_safe_error_without_false_success(self) -> None:
        workspace = EducationWorkspace.empty(cd.ClassroomSnapshot())

        def dispatch(_action_id: str, _payload: dict[str, object]) -> object:
            raise EducationWorkspaceError("simulated CAS failure")

        projection = MutableEducationWebViewProjection(
            lambda: workspace,
            dispatch,
            language=UILanguage.UA,
        )
        event = projection.new_class()
        self.assertEqual(event.kind, "error")
        self.assertEqual(workspace.classroom.classes, ())

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


class EducationMutationReleaseBindingTests(unittest.TestCase):
    def test_import_preserves_exact_prior_release_application_owner(self) -> None:
        from acs import version2_education_mutation_release as mutation_release
        from acs import version2_release_app

        previous_owner = version2_release_app.Version2Application
        importlib.reload(mutation_release)

        self.assertIs(version2_release_app.Version2Application, previous_owner)
        self.assertIsNotNone(mutation_release.create_version2_release_application)

    def test_eager_factory_binds_child_only_during_composition(self) -> None:
        from acs import version2_education_mutation_release as mutation_release
        from acs import version2_release_app

        previous_owner = version2_release_app.Version2Application
        observed: list[object] = []
        api = SimpleNamespace()

        def fake_factory(*args: object, **kwargs: object):
            observed.append(version2_release_app.Version2Application)
            return (api, "application", "runtime", "native")

        with mock.patch.object(
            mutation_release._release_app,
            "create_version2_release_application",
            side_effect=fake_factory,
        ):
            result = mutation_release.create_version2_release_application()

        self.assertEqual(result, (api, "application", "runtime", "native"))
        self.assertEqual(observed, [Version2EducationMutationApplication])
        self.assertTrue(callable(api._sync_version2_language))
        self.assertIs(version2_release_app.Version2Application, previous_owner)

    def test_deferred_factory_rebinds_child_on_native_ui_construction(self) -> None:
        from acs import version2_education_mutation_release as mutation_release
        from acs import version2_release_app

        previous_owner = version2_release_app.Version2Application
        observed: list[object] = []
        api = SimpleNamespace()

        def fake_factory(*args: object, **kwargs: object):
            self.assertTrue(kwargs.get("defer_ui"))

            def build_application():
                observed.append(version2_release_app.Version2Application)
                return "application"

            return (api, build_application, "runtime", "native")

        with mock.patch.object(
            mutation_release._release_app,
            "create_version2_release_application",
            side_effect=fake_factory,
        ):
            returned_api, application_factory, runtime, native = (
                mutation_release.create_version2_release_application(defer_ui=True)
            )
            self.assertIs(version2_release_app.Version2Application, previous_owner)
            self.assertTrue(callable(returned_api._sync_version2_language))
            application = application_factory()

        self.assertEqual(
            (returned_api, application, runtime, native),
            (api, "application", "runtime", "native"),
        )
        self.assertEqual(observed, [Version2EducationMutationApplication])
        self.assertIs(version2_release_app.Version2Application, previous_owner)


if __name__ == "__main__":
    unittest.main()
