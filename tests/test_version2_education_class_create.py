from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
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


class EducationMutationReleaseBindingTests(unittest.TestCase):
    def test_import_keeps_parent_final_product_application_owner(self) -> None:
        from acs import version2_education_mutation_release as mutation_release
        from acs import version2_release_app
        from acs.version2_final_product_application import Version2FinalProductApplication

        self.assertIs(
            version2_release_app.Version2Application,
            Version2FinalProductApplication,
        )
        self.assertIsNotNone(mutation_release.create_version2_release_application)

    def test_eager_factory_binds_child_only_during_composition(self) -> None:
        from acs import version2_education_mutation_release as mutation_release
        from acs import version2_release_app
        from acs.version2_final_product_application import Version2FinalProductApplication

        observed: list[object] = []

        def fake_factory(*args: object, **kwargs: object):
            observed.append(version2_release_app.Version2Application)
            return ("api", "application", "runtime", "native")

        with mock.patch.object(
            mutation_release._release_app,
            "create_version2_release_application",
            side_effect=fake_factory,
        ):
            result = mutation_release.create_version2_release_application()

        self.assertEqual(result, ("api", "application", "runtime", "native"))
        self.assertEqual(observed, [Version2EducationMutationApplication])
        self.assertIs(
            version2_release_app.Version2Application,
            Version2FinalProductApplication,
        )

    def test_deferred_factory_rebinds_child_on_native_ui_construction(self) -> None:
        from acs import version2_education_mutation_release as mutation_release
        from acs import version2_release_app
        from acs.version2_final_product_application import Version2FinalProductApplication

        observed: list[object] = []

        def fake_factory(*args: object, **kwargs: object):
            self.assertTrue(kwargs.get("defer_ui"))

            def build_application():
                observed.append(version2_release_app.Version2Application)
                return "application"

            return ("api", build_application, "runtime", "native")

        with mock.patch.object(
            mutation_release._release_app,
            "create_version2_release_application",
            side_effect=fake_factory,
        ):
            api, application_factory, runtime, native = (
                mutation_release.create_version2_release_application(defer_ui=True)
            )
            self.assertIs(
                version2_release_app.Version2Application,
                Version2FinalProductApplication,
            )
            application = application_factory()

        self.assertEqual((api, application, runtime, native), ("api", "application", "runtime", "native"))
        self.assertEqual(observed, [Version2EducationMutationApplication])
        self.assertIs(
            version2_release_app.Version2Application,
            Version2FinalProductApplication,
        )


if __name__ == "__main__":
    unittest.main()
