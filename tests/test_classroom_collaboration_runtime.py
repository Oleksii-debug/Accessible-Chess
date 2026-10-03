from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest import mock

from acs.classroom_collaboration_runtime import (
    ClassroomCollaborationRuntime,
    build_classroom_collaboration_http_runtime,
)
from acs.full_product_ui_shell import UILanguage
from acs.version2_application import Version2Application
from acs.version2_final_product_application import Version2FinalProductApplication
from tests.test_classroom_collaboration import FakeRoster


CHAT_URL = "http://127.0.0.1/v1/classroom/chat"
FILE_URL = "http://127.0.0.1/v1/classroom/files"


class ClassroomCollaborationRuntimeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.roster = FakeRoster()
        self.chat_token_calls = 0
        self.file_token_calls = 0

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def chat_token(self) -> str:
        self.chat_token_calls += 1
        return "chat-secret-token"

    def file_token(self) -> str:
        self.file_token_calls += 1
        return "file-secret-token"

    def build(self, **overrides) -> ClassroomCollaborationRuntime:
        arguments = {
            "room_id": "room-1",
            "participant_id": "student-1",
            "roster": self.roster,
            "store_path": self.root / "collaboration.sqlite3",
            "chat_endpoint_url": CHAT_URL,
            "file_endpoint_url": FILE_URL,
            "chat_bearer_token_provider": self.chat_token,
            "file_bearer_token_provider": self.file_token,
            "participant_label": lambda participant_id: participant_id,
            "language": UILanguage.EN,
            "allow_insecure_loopback": True,
        }
        arguments.update(overrides)
        return build_classroom_collaboration_http_runtime(**arguments)

    def test_runtime_composes_existing_authorities_without_network_or_credentials(self) -> None:
        runtime = self.build()

        self.assertEqual(self.chat_token_calls, 0)
        self.assertEqual(self.file_token_calls, 0)
        self.assertIs(runtime.controller._chat, runtime.chat_client)
        self.assertIs(runtime.controller._files, runtime.file_client)
        self.assertIs(runtime.controller._file_store, runtime.file_client)
        self.assertIs(runtime.webview._controller, runtime.controller)
        self.assertIs(runtime.webview._store, runtime.store)
        self.assertEqual(runtime.controller.room_id, "room-1")
        self.assertEqual(runtime.controller.local_participant_id, "student-1")
        self.assertEqual(runtime.webview.language, UILanguage.EN)
        self.assertTrue((self.root / "collaboration.sqlite3").exists())

        snapshot = runtime.webview.safe_snapshot()
        self.assertTrue(snapshot["available"])
        self.assertEqual(snapshot["chat"]["messages"], ())
        self.assertEqual(snapshot["files"]["items"], ())

        rendered = repr(runtime)
        self.assertEqual(rendered, "ClassroomCollaborationRuntime(<bound>)")
        self.assertNotIn("chat-secret-token", rendered)
        self.assertNotIn("file-secret-token", rendered)

    def test_remote_plain_http_is_rejected_before_local_store_creation(self) -> None:
        path = self.root / "must-not-exist.sqlite3"
        with self.assertRaises(ValueError):
            self.build(
                store_path=path,
                chat_endpoint_url="http://example.com/v1/classroom/chat",
                allow_insecure_loopback=True,
            )
        self.assertFalse(path.exists())
        self.assertEqual(self.chat_token_calls, 0)
        self.assertEqual(self.file_token_calls, 0)

    def test_file_endpoint_is_validated_before_local_store_creation(self) -> None:
        path = self.root / "must-not-exist-file.sqlite3"
        with self.assertRaises(ValueError):
            self.build(
                store_path=path,
                file_endpoint_url="http://example.com/v1/classroom/files",
                allow_insecure_loopback=True,
            )
        self.assertFalse(path.exists())

    def test_bearer_suppliers_must_be_explicit_callables(self) -> None:
        path = self.root / "no-provider.sqlite3"
        with self.assertRaises(TypeError):
            self.build(
                store_path=path,
                chat_bearer_token_provider="static-secret",
            )
        self.assertFalse(path.exists())

        with self.assertRaises(TypeError):
            self.build(
                store_path=path,
                file_bearer_token_provider=None,
            )
        self.assertFalse(path.exists())

    def test_https_endpoints_do_not_need_insecure_loopback_opt_in(self) -> None:
        runtime = self.build(
            chat_endpoint_url="https://classroom.example/v1/classroom/chat",
            file_endpoint_url="https://classroom.example/v1/classroom/files",
            allow_insecure_loopback=False,
        )
        self.assertIsInstance(runtime, ClassroomCollaborationRuntime)
        self.assertEqual(self.chat_token_calls, 0)
        self.assertEqual(self.file_token_calls, 0)


class ClassroomCollaborationFinalCompositionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.roster = FakeRoster()
        self.chat_token_calls = 0
        self.file_token_calls = 0

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def chat_token(self) -> str:
        self.chat_token_calls += 1
        return "chat-final-secret"

    def file_token(self) -> str:
        self.file_token_calls += 1
        return "file-final-secret"

    def bare_app(self) -> Version2FinalProductApplication:
        app = object.__new__(Version2FinalProductApplication)
        app.collaboration = None
        app._collaboration_runtime = None
        app.education = None
        app.teacher = None
        app._teacher_state_provider = None
        app._teacher_dispatch = None
        app._education_load_error = False
        app.shell = SimpleNamespace(language=UILanguage.EN)
        app.progress_store = SimpleNamespace(path=self.root / "progress.json")
        return app

    def configure(self, app: Version2FinalProductApplication, **overrides):
        arguments = {
            "room_id": "room-1",
            "participant_id": "student-1",
            "roster": self.roster,
            "chat_endpoint_url": CHAT_URL,
            "file_endpoint_url": FILE_URL,
            "chat_bearer_token_provider": self.chat_token,
            "file_bearer_token_provider": self.file_token,
            "participant_label": lambda participant_id: participant_id,
            "allow_insecure_loopback": True,
        }
        arguments.update(overrides)
        return app.configure_classroom_collaboration_http(**arguments)

    def test_final_app_configures_and_retires_owned_http_runtime(self) -> None:
        app = self.bare_app()
        with mock.patch.object(Version2FinalProductApplication, "_assert_thread"):
            runtime = self.configure(app)
            self.assertIs(app._collaboration_runtime, runtime)
            self.assertIs(app.collaboration, runtime.webview)
            self.assertEqual(self.chat_token_calls, 0)
            self.assertEqual(self.file_token_calls, 0)
            self.assertTrue(
                (self.root / "classroom-collaboration.sqlite3").exists()
            )
            with self.assertRaises(RuntimeError):
                self.configure(app)
            app.unbind_classroom_collaboration()

        self.assertIsNone(app.collaboration)
        self.assertIsNone(app._collaboration_runtime)

    def test_product_status_reports_http_only_for_owned_http_composition(self) -> None:
        app = self.bare_app()
        with (
            mock.patch.object(Version2FinalProductApplication, "_assert_thread"),
            mock.patch.object(Version2Application, "snapshot", return_value={}),
        ):
            unconfigured = app.snapshot()
            self.assertEqual(
                unconfigured["product_status"]["remote_transport"],
                "not_approved",
            )

            self.configure(app)
            configured = app.snapshot()
            self.assertEqual(
                configured["product_status"]["remote_transport"],
                "classroom_collaboration_http",
            )

            app.unbind_classroom_collaboration()
            retired = app.snapshot()
            self.assertEqual(
                retired["product_status"]["remote_transport"],
                "not_approved",
            )

    def test_custom_store_path_and_language_are_bound_without_fetching_tokens(self) -> None:
        app = self.bare_app()
        custom = self.root / "custom" / "room.sqlite3"
        custom.parent.mkdir()
        with mock.patch.object(Version2FinalProductApplication, "_assert_thread"):
            runtime = self.configure(
                app,
                collaboration_store_path=custom,
            )
        self.assertTrue(custom.exists())
        self.assertEqual(runtime.webview.language, UILanguage.EN)
        self.assertEqual(self.chat_token_calls, 0)
        self.assertEqual(self.file_token_calls, 0)

    def test_invalid_progress_sink_fails_before_store_or_network_composition(self) -> None:
        app = self.bare_app()
        target = self.root / "explicit.sqlite3"
        with mock.patch.object(Version2FinalProductApplication, "_assert_thread"):
            with self.assertRaises(TypeError):
                self.configure(
                    app,
                    collaboration_store_path=target,
                    file_progress_event_sink=object(),
                )
        self.assertFalse(target.exists())
        self.assertIsNone(app.collaboration)
        self.assertIsNone(app._collaboration_runtime)
        self.assertEqual(self.chat_token_calls, 0)
        self.assertEqual(self.file_token_calls, 0)


if __name__ == "__main__":
    unittest.main()
