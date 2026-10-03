from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import patch

from acs import classroom_domain as cd
from acs import education_workspace as ew
from acs import education_workspace_store as ews
from acs.full_product_ui_shell import UILanguage
from acs.version2_final_product_application import Version2FinalProductApplication


def _changed_workspace() -> ew.EducationWorkspace:
    student = cd.Student(
        "student-1",
        "Knight-17",
        cd.ConsentState.GRANTED,
    )
    return ew.EducationWorkspace.empty(
        cd.ClassroomSnapshot(students=(student,))
    )


def _application(path: Path):
    store = ews.EducationWorkspaceStore(path)
    initial = ew.EducationWorkspace.empty(cd.ClassroomSnapshot())
    revision = store.save(initial, expected_revision=None)

    application = object.__new__(Version2FinalProductApplication)
    application.shell = SimpleNamespace(language=UILanguage.EN)
    application.education_store = store
    application._education_workspace = None
    application._education_revision = None
    application._education_load_error = False
    application.education = None
    application._assert_thread = lambda: None
    application._load_education(UILanguage.EN)
    return application, store, initial, revision


class D10WorkspaceApplicationRecoveryTests(unittest.TestCase):
    def test_ambiguous_publication_reloads_visible_durable_workspace_before_error_escapes(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "education-workspace.json"
            application, store, _initial, revision = _application(path)
            changed = _changed_workspace()

            with patch(
                "acs.education_workspace_store._sync_published_path",
                side_effect=OSError("durability barrier failed"),
            ):
                with self.assertRaisesRegex(
                    ews.EducationWorkspaceDurabilityError,
                    "reload before retrying",
                ):
                    application.replace_education_workspace(
                        changed,
                        expected_revision=revision,
                    )

            durable = store.load()
            self.assertIsNotNone(durable)
            self.assertEqual(durable.workspace, changed)
            self.assertEqual(application._education_provider(), changed)
            self.assertEqual(application.education_revision, durable.revision)
            self.assertNotEqual(application.education_revision, revision)
            self.assertFalse(application._education_load_error)
            self.assertIsNotNone(application.education)

            with self.assertRaises(ews.EducationWorkspaceConflictError):
                application.replace_education_workspace(
                    changed,
                    expected_revision=revision,
                )

    def test_ambiguous_publication_with_reload_failure_disables_stale_education_surface(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "education-workspace.json"
            application, store, _initial, revision = _application(path)
            changed = _changed_workspace()

            with (
                patch(
                    "acs.education_workspace_store._sync_published_path",
                    side_effect=OSError("durability barrier failed"),
                ),
                patch.object(
                    store,
                    "load",
                    side_effect=OSError("reload unavailable"),
                ),
            ):
                with self.assertRaises(ews.EducationWorkspaceDurabilityError):
                    application.replace_education_workspace(
                        changed,
                        expected_revision=revision,
                    )

            self.assertTrue(application._education_load_error)
            self.assertIsNone(application._education_workspace)
            self.assertIsNone(application.education_revision)
            self.assertIsNone(application.education)
            with self.assertRaisesRegex(
                RuntimeError,
                "Education workspace is unavailable",
            ):
                application._education_provider()

            durable = ews.EducationWorkspaceStore(path).load()
            self.assertIsNotNone(durable)
            self.assertEqual(durable.workspace, changed)

    def test_pre_replace_failure_preserves_last_known_in_memory_workspace(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "education-workspace.json"
            application, store, initial, revision = _application(path)
            changed = _changed_workspace()

            with patch(
                "acs.education_workspace_store.os.replace",
                side_effect=OSError("replace failed"),
            ):
                with self.assertRaisesRegex(OSError, "replace failed"):
                    application.replace_education_workspace(
                        changed,
                        expected_revision=revision,
                    )

            self.assertEqual(application._education_provider(), initial)
            self.assertEqual(application.education_revision, revision)
            self.assertFalse(application._education_load_error)
            self.assertIsNotNone(application.education)
            durable = store.load()
            self.assertIsNotNone(durable)
            self.assertEqual(durable.workspace, initial)
            self.assertEqual(durable.revision, revision)


if __name__ == "__main__":
    unittest.main()
