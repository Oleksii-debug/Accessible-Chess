from __future__ import annotations

from pathlib import Path
import json
import struct
from types import SimpleNamespace
import tempfile
import unittest
from unittest import mock

from acs.classroom_collaboration import CollaborationError, FileQuotaPolicy
from acs.classroom_collaboration_runtime import (
    ClassroomCollaborationRuntime,
    build_classroom_collaboration_http_runtime,
)
from acs.classroom_collaboration_storage import ChatMessageMetadata
from acs.classroom_file_rpc import MAX_RPC_UPLOAD_BYTES
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

    def test_smaller_local_file_quota_is_shared_by_controller_and_rpc_client(self) -> None:
        quota = FileQuotaPolicy(max_file_bytes=3, max_room_bytes=10)
        runtime = self.build(local_quota=quota)

        self.assertIs(runtime.controller._quota, quota)
        self.assertEqual(runtime.file_client._max_upload_bytes, 3)
        selected = self.root / "too-large-for-room.bin"
        selected.write_bytes(b"four")
        with self.assertRaises(CollaborationError):
            runtime.controller.prepare_file(
                attachment_id="quota-test",
                local_path=selected,
                sequence_no=0,
            )
        self.assertEqual(self.chat_token_calls, 0)
        self.assertEqual(self.file_token_calls, 0)

    def test_local_file_quota_cannot_exceed_authenticated_rpc_limit(self) -> None:
        path = self.root / "quota-mismatch-must-not-exist.sqlite3"
        quota = FileQuotaPolicy(max_file_bytes=MAX_RPC_UPLOAD_BYTES + 1)
        with self.assertRaisesRegex(ValueError, "RPC upload limit"):
            self.build(
                store_path=path,
                local_quota=quota,
            )
        self.assertFalse(path.exists())
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

    def test_final_app_chat_send_reaches_authenticated_http_wire(self) -> None:
        wire: list[dict[str, object]] = []

        class Response:
            status = 200

            def __init__(self, payload: dict[str, object]) -> None:
                self.body = json.dumps(
                    payload,
                    ensure_ascii=False,
                    separators=(",", ":"),
                ).encode("utf-8")

            def getheaders(self):
                return [
                    ("Content-Type", "application/json; charset=utf-8"),
                    ("Content-Length", str(len(self.body))),
                ]

            def read(self, limit):
                return self.body[:limit]

        class Connection:
            instances = []

            def __init__(self, host, port, timeout):
                self.host = host
                self.port = port
                self.timeout = timeout
                self.closed = False
                type(self).instances.append(self)

            def request(self, method, target, body, headers):
                self.request_data = (method, target, bytes(body), dict(headers))

            def getresponse(self):
                method, target, body, headers = self.request_data
                request = json.loads(body.decode("utf-8"))
                message = dict(request["message"])
                wire.append(
                    {
                        "method": method,
                        "target": target,
                        "headers": headers,
                        "request": request,
                    }
                )
                return Response(
                    {
                        "v": 1,
                        "ok": True,
                        "message": {
                            "message_id": message["message_id"],
                            "room_id": request["room_id"],
                            "sender_id": request["participant_id"],
                            "sequence_no": 0,
                            "body": message["body"],
                            "retention": message["retention"],
                            "hidden": False,
                            "sent_at_unix_ms": 1700000000000,
                        },
                    }
                )

            def close(self):
                self.closed = True

        app = self.bare_app()
        with (
            mock.patch.object(Version2FinalProductApplication, "_assert_thread"),
            mock.patch(
                "acs.classroom_chat_http_endpoint.http.client.HTTPSConnection",
                Connection,
            ),
        ):
            runtime = self.configure(
                app,
                chat_endpoint_url="https://chat.example.test/v1/classroom/chat",
            )
            result = app.browser_command(
                "classes",
                "collaboration.chat.send",
                {"body": "Network hello"},
            )
            app.unbind_classroom_collaboration()

        self.assertEqual("collaboration.chat.sent", result["kind"])
        self.assertEqual(self.chat_token_calls, 1)
        self.assertEqual(self.file_token_calls, 0)
        self.assertEqual(1, len(wire))
        self.assertEqual("POST", wire[0]["method"])
        self.assertEqual("/v1/classroom/chat", wire[0]["target"])
        self.assertEqual("send", wire[0]["request"]["op"])
        self.assertEqual("room-1", wire[0]["request"]["room_id"])
        self.assertEqual("student-1", wire[0]["request"]["participant_id"])
        self.assertEqual("Network hello", wire[0]["request"]["message"]["body"])
        self.assertEqual(
            ("Network hello",),
            tuple(
                message.body
                for message in runtime.store.room_messages("room-1")
            ),
        )
        self.assertTrue(Connection.instances[0].closed)
        exposed = repr(result)
        self.assertNotIn("chat-final-secret", exposed)
        self.assertNotIn("Authorization", exposed)

    def test_final_app_file_upload_reaches_authenticated_http_wire(self) -> None:
        selected = self.root / "runtime-http-upload.bin"
        selected.write_bytes(b"abcdef")
        progress_events: list[dict[str, object]] = []
        wire: list[dict[str, object]] = []

        class Response:
            status = 200

            def __init__(self, payload: dict[str, object]) -> None:
                self.body = json.dumps(
                    payload,
                    ensure_ascii=False,
                    separators=(",", ":"),
                ).encode("utf-8")

            def getheaders(self):
                return [
                    ("Content-Type", "application/json; charset=utf-8"),
                    ("Content-Length", str(len(self.body))),
                ]

            def read(self, limit):
                return self.body[:limit]

        class Connection:
            instances = []

            def __init__(self, host, port, timeout):
                self.host = host
                self.port = port
                self.timeout = timeout
                self.headers = []
                self.sent_parts = []
                self.closed = False
                type(self).instances.append(self)

            def putrequest(self, method, target, **kwargs):
                self.request = (method, target, kwargs)

            def putheader(self, name, value):
                self.headers.append((name, value))

            def endheaders(self):
                return None

            def send(self, data):
                self.sent_parts.append(bytes(data))

            def getresponse(self):
                if len(self.sent_parts) < 2:
                    raise AssertionError("file HTTP request frame is incomplete")
                (header_size,) = struct.unpack("!I", self.sent_parts[0])
                if header_size != len(self.sent_parts[1]):
                    raise AssertionError("file HTTP JSON frame length mismatch")
                envelope = json.loads(self.sent_parts[1].decode("utf-8"))
                content = b"".join(self.sent_parts[2:])
                metadata = dict(envelope["metadata"])
                metadata["sequence_no"] = 0
                metadata["transfer_state"] = "stored"
                metadata["scan_state"] = "clean"
                wire.append(
                    {
                        "request": self.request,
                        "headers": tuple(self.headers),
                        "envelope": envelope,
                        "content": content,
                    }
                )
                return Response(
                    {
                        "v": 1,
                        "ok": True,
                        "attachment": metadata,
                    }
                )

            def close(self):
                self.closed = True

        app = self.bare_app()
        with (
            mock.patch.object(Version2FinalProductApplication, "_assert_thread"),
            mock.patch(
                "acs.classroom_file_http_transport.http.client.HTTPSConnection",
                Connection,
            ),
        ):
            self.configure(
                app,
                file_endpoint_url="https://files.example.test/v1/classroom/files",
                file_picker=lambda: selected,
                file_progress_event_sink=progress_events.append,
            )
            result = app.browser_command(
                "classes",
                "collaboration.file.choose_upload",
                {},
            )
            app.unbind_classroom_collaboration()

        self.assertEqual("collaboration.file.sent", result["kind"])
        self.assertEqual(self.chat_token_calls, 0)
        self.assertEqual(self.file_token_calls, 1)
        self.assertEqual(1, len(wire))
        self.assertEqual(b"abcdef", wire[0]["content"])
        self.assertNotIn("content", wire[0]["envelope"])
        self.assertEqual(
            [0, 6, 6],
            [
                event["payload"]["file_progress"]["transferred_bytes"]
                for event in progress_events
            ],
        )
        self.assertEqual(
            [False, False, True],
            [
                event["payload"]["file_progress"]["complete"]
                for event in progress_events
            ],
        )
        self.assertTrue(Connection.instances[0].closed)
        exposed = repr((result, progress_events))
        self.assertNotIn("file-final-secret", exposed)
        self.assertNotIn(str(selected), exposed)
        self.assertNotIn("rooms/room-1", exposed)
        self.assertNotIn("sha256", exposed.lower())

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

    def test_final_app_forwards_bounded_file_quota_to_runtime(self) -> None:
        app = self.bare_app()
        quota = FileQuotaPolicy(max_file_bytes=7, max_room_bytes=20)
        with mock.patch.object(Version2FinalProductApplication, "_assert_thread"):
            runtime = self.configure(app, local_quota=quota)

        self.assertIs(runtime.controller._quota, quota)
        self.assertEqual(runtime.file_client._max_upload_bytes, 7)
        self.assertEqual(self.chat_token_calls, 0)
        self.assertEqual(self.file_token_calls, 0)

    def test_final_app_rebind_reopens_durable_collaboration_without_credentials(self) -> None:
        store_path = self.root / "restart-collaboration.sqlite3"
        first = self.bare_app()
        with mock.patch.object(Version2FinalProductApplication, "_assert_thread"):
            runtime = self.configure(
                first,
                collaboration_store_path=store_path,
            )
            runtime.store.append_message(
                ChatMessageMetadata(
                    "restart-message",
                    "room-1",
                    "student-1",
                    0,
                    "Persist across rebind",
                    sent_at_unix_ms=1700000000000,
                )
            )
            first.unbind_classroom_collaboration()

            second = self.bare_app()
            reopened = self.configure(
                second,
                collaboration_store_path=store_path,
            )
            snapshot = reopened.webview.safe_snapshot()

        self.assertEqual(
            ("Persist across rebind",),
            tuple(item["body"] for item in snapshot["chat"]["messages"]),
        )
        self.assertEqual(self.chat_token_calls, 0)
        self.assertEqual(self.file_token_calls, 0)

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
