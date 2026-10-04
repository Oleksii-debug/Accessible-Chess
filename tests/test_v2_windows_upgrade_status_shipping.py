from __future__ import annotations

from collections import deque
from pathlib import Path
from types import SimpleNamespace
import tempfile
import threading
import unittest
from unittest.mock import patch

from acs import version2_release_app as _release_app
from acs import version2_upgrade_status_release as status_release
from acs.full_product_ui_shell import UILanguage
from acs.version2_upgrade import Version2UpgradeReport


class _Application:
    def __init__(self, language: UILanguage = UILanguage.UA) -> None:
        self._thread = threading.get_ident()
        self.shell = SimpleNamespace(language=language)
        self._events = deque(maxlen=64)

    def _assert_thread(self) -> None:
        if threading.get_ident() != self._thread:
            raise RuntimeError("wrong UI thread")


class Version2UpgradeStatusShippingTests(unittest.TestCase):
    def test_real_release_wrapper_runs_one_canonical_pre_writer_upgrade_and_queues_status(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "v2-user-data"
            application = _Application()
            api = object()
            runtime = object()
            native_factory = object()

            def fake_final_product_create(*args, **kwargs):
                # This is the same prepare seam the real release composition calls.
                _release_app._prepare_version2_user_data(data_root=root)
                return api, application, runtime, native_factory

            with patch.object(
                status_release._education_release,
                "create_version2_release_application",
                side_effect=fake_final_product_create,
            ):
                result = status_release.create_version2_release_application()

            self.assertEqual(result, (api, application, runtime, native_factory))
            self.assertTrue(root.is_dir())
            self.assertEqual(len(application._events), 1)
            event = application._events[0]
            self.assertEqual(event["kind"], "status")
            payload = event["payload"]
            self.assertEqual(payload["upgrade_status"], "current")
            self.assertEqual(payload["focus_target"], "app-root")
            self.assertTrue(payload["announcement"])
            self.assertIn("Version 2", payload["announcement"])
            rendered = repr(event)
            self.assertNotIn(str(root), rendered)
            self.assertNotIn(".v2-upgrade", rendered)
            self.assertNotIn("upgrade-backups", rendered)

    def test_deferred_release_publishes_only_after_application_is_built_on_owner_thread(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "v2-user-data"
            application = _Application(UILanguage.EN)
            api = object()
            runtime = object()
            native_factory = object()

            def fake_final_product_create(*args, **kwargs):
                self.assertTrue(kwargs.get("defer_ui"))
                _release_app._prepare_version2_user_data(data_root=root)
                return api, (lambda: application), runtime, native_factory

            with patch.object(
                status_release._education_release,
                "create_version2_release_application",
                side_effect=fake_final_product_create,
            ):
                composed = status_release.create_version2_release_application(defer_ui=True)

            self.assertEqual(len(application._events), 0)
            built = composed[1]()
            self.assertIs(built, application)
            self.assertEqual(len(application._events), 1)
            payload = application._events[0]["payload"]
            self.assertEqual(payload["upgrade_status"], "current")
            self.assertEqual(payload["announcement"], "Version 2 data is verified and ready.")

    def test_recovery_completion_uses_bounded_semantics_and_never_private_report_identity(self) -> None:
        application = _Application()
        report = Version2UpgradeReport(
            upgrade_id=r"C:\\Users\\Private\\upgrade-id",
            status="already_current",
            backup_name=r"D:\\secret\\backup-name",
            settings_migrated=False,
            library_migrated=False,
            preserved_files=4,
            target_settings_schema=3,
            target_acsdb_schema=6,
            recovered_interrupted_upgrade=True,
        )

        status_release._publish_canonical_upgrade_status(application, report)

        event = application._events[0]
        payload = event["payload"]
        self.assertEqual(payload["upgrade_status"], "current")
        self.assertTrue(payload["recovered_interrupted_upgrade"])
        self.assertIn("Відновлення", payload["announcement"])
        rendered = repr(event)
        self.assertNotIn(report.upgrade_id, rendered)
        self.assertNotIn(report.backup_name, rendered)
        self.assertNotIn("Users", rendered)
        self.assertNotIn("secret", rendered)


if __name__ == "__main__":
    unittest.main()
