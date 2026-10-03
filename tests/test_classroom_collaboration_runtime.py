from __future__ import annotations

from pathlib import Path
import asyncio
import hashlib
import json
import struct
from types import SimpleNamespace
import tempfile
import unittest
from unittest import mock

from acs.classroom_chat_http_endpoint import ClassroomChatHttpEndpoint
from acs.classroom_chat_rpc import ClassroomChatRpcService
from acs.classroom_collaboration_chat_server import (
    ClassroomChatServerSQLiteStore,
    ClassroomChatServerService,
)
from acs.classroom_collaboration import CollaborationError, FileQuotaPolicy
from acs.classroom_collaboration_runtime import (
    ClassroomCollaborationRuntime,
    build_classroom_collaboration_http_runtime,
)
from acs.classroom_collaboration_storage import ChatMessageMetadata
from acs.classroom_file_http_transport import ClassroomFileHttpEndpoint
from acs.classroom_file_rpc import ClassroomFileRpcService
from acs.classroom_file_server import (
    ClassroomFileServerSQLiteStore,
    ClassroomFileServerService,
)
from acs.classroom_file_rpc import MAX_RPC_UPLOAD_BYTES
from acs.full_product_ui_shell import UILanguage
from acs.version2_application import Version2Application
from acs.version2_final_product_application import Version2FinalProductApplication
from tests.test_classroom_collaboration import FakeRoster


class MemorySecretStore:
    def __init__(self) -> None:
        self.values: dict[str, bytes] = {}

    def write(self, name: str, value: bytes) -> None:
        self.values[name] = bytes(value)

    def read(self, name: str) -> bytes | None:
        value = self.values.get(name)
        return None if value is None else bytes(value)

    def delete(self, name: str) -> bool:
        return self.values.pop(name, None) is not None


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


    def test_invalid_host_adapters_and_retention_fail_before_local_store_creation(self) -> None:
        cases = (
            ("file_picker", object(), TypeError),
            ("file_saver", object(), TypeError),
            ("file_opener", object(), TypeError),
            ("file_progress_event_sink", object(), TypeError),
            ("moderation_allowed", object(), TypeError),
            ("participant_moderation", object(), TypeError),
            ("chat_retention", "forever", ValueError),
            ("file_retention", "", ValueError),
        )
        for index, (name, value, error_type) in enumerate(cases):
            with self.subTest(name=name):
                path = self.root / f"invalid-host-{index}.sqlite3"
                with self.assertRaises(error_type):
                    self.build(
                        store_path=path,
                        **{name: value},
                    )
                self.assertFalse(path.exists())
                self.assertEqual(self.chat_token_calls, 0)
                self.assertEqual(self.file_token_calls, 0)



    def test_runtime_secure_outbox_reuses_message_identity_after_full_rebuild(self) -> None:
        secure = MemorySecretStore()
        first = self.build(chat_secret_store=secure)
        first_calls: list[str] = []

        def ambiguous_send(*, message_id: str, body: str, retention: str = "session"):
            first_calls.append(message_id)
            raise RuntimeError("acknowledgement unavailable")

        with mock.patch.object(
            first.controller,
            "send_chat",
            side_effect=ambiguous_send,
        ):
            failed = first.webview.dispatch(
                "collaboration.chat.send",
                {"body": "Durable runtime draft"},
            )
        self.assertEqual("error", failed.kind)
        self.assertEqual(len(first_calls), 1)
        self.assertTrue(first_calls[0].startswith("message-"))
        self.assertIsNotNone(first.chat_outbox)
        assert first.chat_outbox is not None
        pending_id = first.chat_outbox.entries()[0].message_id

        second = self.build(chat_secret_store=secure)
        second_calls: list[str] = []

        def confirmed_send(*, message_id: str, body: str, retention: str = "session"):
            second_calls.append(message_id)
            return None

        with mock.patch.object(
            second.controller,
            "send_chat",
            side_effect=confirmed_send,
        ):
            sent = second.webview.dispatch(
                "collaboration.chat.send",
                {"body": "Durable runtime draft"},
            )

        self.assertEqual("collaboration.chat.sent", sent.kind)
        self.assertEqual(second_calls, [pending_id])
        assert second.chat_outbox is not None
        self.assertEqual(second.chat_outbox.entries(), ())

    def test_invalid_secure_outbox_fails_before_collaboration_sqlite_or_network(self) -> None:
        class FailingSecretStore(MemorySecretStore):
            def read(self, name: str) -> bytes | None:
                raise RuntimeError("unavailable secret backend")

        target = self.root / "outbox-preflight.sqlite3"
        with self.assertRaisesRegex(RuntimeError, "chat outbox"):
            self.build(
                store_path=target,
                chat_secret_store=FailingSecretStore(),
            )
        self.assertFalse(target.exists())
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

    def test_final_app_ambiguous_chat_ack_retries_same_logical_message(self) -> None:
        attempts: list[dict[str, object]] = []
        committed: dict[str, object] | None = None

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
            def __init__(self, host, port, timeout):
                self.request_data = None

            def request(self, method, target, body, headers):
                self.request_data = (method, target, bytes(body), dict(headers))

            def getresponse(self):
                nonlocal committed
                if self.request_data is None:
                    raise AssertionError("chat HTTP request was not sent")
                method, target, body, headers = self.request_data
                request = json.loads(body.decode("utf-8"))
                message = dict(request["message"])
                attempts.append(
                    {
                        "message_id": message["message_id"],
                        "body": message["body"],
                        "retention": message["retention"],
                        "room_id": request["room_id"],
                        "participant_id": request["participant_id"],
                    }
                )
                authoritative = {
                    "message_id": message["message_id"],
                    "room_id": request["room_id"],
                    "sender_id": request["participant_id"],
                    "sequence_no": 0,
                    "body": message["body"],
                    "retention": message["retention"],
                    "hidden": False,
                    "sent_at_unix_ms": 1700000000000,
                }
                if committed is None:
                    committed = authoritative
                    raise OSError("chat acknowledgement lost after commit")
                if authoritative != committed:
                    raise AssertionError("retry changed committed chat identity")
                return Response({"v": 1, "ok": True, "message": committed})

            def close(self):
                return None

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
                {"body": "Exactly once chat"},
            )

        self.assertEqual("collaboration.chat.sent", result["kind"])
        self.assertEqual(self.chat_token_calls, 2)
        self.assertEqual(self.file_token_calls, 0)
        self.assertEqual(len(attempts), 2)
        self.assertEqual(attempts[0], attempts[1])
        messages = runtime.store.room_messages("room-1")
        self.assertEqual(len(messages), 1)
        self.assertEqual(messages[0].message_id, attempts[0]["message_id"])
        self.assertEqual(messages[0].body, "Exactly once chat")

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

    def test_final_app_ambiguous_file_ack_retries_same_logical_attachment(self) -> None:
        selected = self.root / "ambiguous-runtime-upload.bin"
        selected.write_bytes(b"same logical payload")
        attempts: list[dict[str, object]] = []
        committed: dict[str, object] | None = None

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
            def __init__(self, host, port, timeout):
                self.headers = []
                self.sent_parts = []

            def putrequest(self, method, target, **kwargs):
                self.request = (method, target, kwargs)

            def putheader(self, name, value):
                self.headers.append((name, value))

            def endheaders(self):
                return None

            def send(self, data):
                self.sent_parts.append(bytes(data))

            def getresponse(self):
                nonlocal committed
                (header_size,) = struct.unpack("!I", self.sent_parts[0])
                envelope = json.loads(self.sent_parts[1].decode("utf-8"))
                self.assert_frame(header_size, envelope)
                content = b"".join(self.sent_parts[2:])
                metadata = dict(envelope["metadata"])
                attempts.append(
                    {
                        "attachment_id": metadata["attachment_id"],
                        "object_key": metadata["object_key"],
                        "sha256": metadata["sha256"],
                        "content": content,
                    }
                )
                authoritative = dict(metadata)
                authoritative["sequence_no"] = 0
                authoritative["transfer_state"] = "stored"
                authoritative["scan_state"] = "clean"
                if committed is None:
                    committed = authoritative
                    raise OSError("response acknowledgement lost after commit")
                if authoritative != committed:
                    raise AssertionError("retry changed committed attachment identity")
                return Response({"v": 1, "ok": True, "attachment": committed})

            @staticmethod
            def assert_frame(header_size, envelope):
                if header_size <= 0 or not isinstance(envelope, dict):
                    raise AssertionError("invalid file HTTP frame")

            def close(self):
                return None

        app = self.bare_app()
        with (
            mock.patch.object(Version2FinalProductApplication, "_assert_thread"),
            mock.patch(
                "acs.classroom_file_http_transport.http.client.HTTPSConnection",
                Connection,
            ),
        ):
            runtime = self.configure(
                app,
                file_endpoint_url="https://files.example.test/v1/classroom/files",
                file_picker=lambda: selected,
            )
            failed = app.browser_command(
                "classes",
                "collaboration.file.choose_upload",
                {},
            )
            self.assertEqual("error", failed["kind"])
            retry_item = runtime.webview.safe_snapshot()["files"]["items"][0]
            self.assertTrue(retry_item["can_retry"])
            retried = app.browser_command(
                "classes",
                "collaboration.file.retry",
                {"file_key": retry_item["file_key"]},
            )

        self.assertEqual("collaboration.file.retried", retried["kind"])
        self.assertEqual(self.file_token_calls, 2)
        self.assertEqual(len(attempts), 2)
        self.assertEqual(
            attempts[0]["attachment_id"],
            attempts[1]["attachment_id"],
        )
        self.assertEqual(attempts[0]["object_key"], attempts[1]["object_key"])
        self.assertEqual(attempts[0]["sha256"], attempts[1]["sha256"])
        self.assertEqual(attempts[0]["content"], attempts[1]["content"])
        attachments = runtime.store.room_attachments("room-1")
        self.assertEqual(len(attachments), 1)
        self.assertEqual(attachments[0].transfer_state, "stored")
        self.assertEqual(attachments[0].scan_state, "clean")
        self.assertEqual(attachments[0].sequence_no, 0)

    def test_two_final_apps_share_chat_and_files_through_production_http_authorities(self) -> None:
        room = "room-1"
        selected = self.root / "two-client-shared.pgn"
        selected.write_bytes(b"1. e4 e5 *")
        saved: list[tuple[str, str]] = []

        class ChatAuthorization:
            def __init__(self, members):
                self.members = set(members)

            def _require(self, room_id, participant_id):
                if (participant_id, room_id) not in self.members:
                    raise RuntimeError("not a room member")

            def authorize_chat_send(self, *, room_id, caller_identity, sender_id):
                self._require(room_id, caller_identity)
                if sender_id != caller_identity:
                    raise RuntimeError("sender mismatch")
                return None

            def authorize_chat_history(self, *, room_id, caller_identity):
                self._require(room_id, caller_identity)
                return None

            def authorize_chat_moderation(self, *, room_id, caller_identity, commands):
                self._require(room_id, caller_identity)
                return None

        class FileAuthorization:
            def __init__(self, members):
                self.members = set(members)

            def authorize_file_action(
                self,
                *,
                trusted_caller_identity,
                room_id,
                action,
                attachment_id,
                retention,
            ):
                return (trusted_caller_identity, room_id) in self.members

        class CleanScanner:
            def scan(self, **kwargs):
                return "clean"

        class ObjectStore:
            def __init__(self):
                self.objects = {}

            def stored_sha256(self, *, object_key):
                content = self.objects.get(object_key)
                return (
                    None
                    if content is None
                    else hashlib.sha256(content).hexdigest()
                )

            def put(self, *, object_key, content, expected_sha256):
                if hashlib.sha256(content).hexdigest() != expected_sha256:
                    raise RuntimeError("hash mismatch")
                self.objects[object_key] = bytes(content)

            def issue_read_token(self, *, object_key, participant_id, ttl_seconds):
                if object_key not in self.objects:
                    raise RuntimeError("missing object")
                return f"read-{participant_id}-{ttl_seconds}"

            def delete(self, *, object_key):
                self.objects.pop(object_key, None)

        class BearerAuthenticator:
            def __init__(self, identities):
                self.identities = dict(identities)
                self.calls = []

            async def authenticate_bearer(self, bearer_token):
                self.calls.append(bearer_token)
                try:
                    return self.identities[bearer_token]
                except KeyError:
                    raise RuntimeError("invalid token") from None

        class AsgiResponse:
            def __init__(self, sent):
                if len(sent) != 2:
                    raise AssertionError("ASGI response must contain start and body")
                start, body = sent
                self.status = start["status"]
                self._body = body["body"]
                self._headers = [
                    (
                        name.decode("ascii"),
                        value.decode("ascii"),
                    )
                    for name, value in start["headers"]
                ]

            def getheaders(self):
                return list(self._headers)

            def read(self, limit):
                return self._body[:limit]

        def invoke_asgi(endpoint, *, target, body, headers):
            scope = {
                "type": "http",
                "scheme": "https",
                "http_version": "1.1",
                "method": "POST",
                "path": target,
                "raw_path": target.encode("ascii"),
                "query_string": b"",
                "headers": [
                    (
                        str(name).lower().encode("ascii"),
                        str(value).encode("ascii"),
                    )
                    for name, value in headers
                ],
                "server": ("203.0.113.10", 443),
                "client": ("198.51.100.20", 41000),
            }
            events = [
                {
                    "type": "http.request",
                    "body": bytes(body),
                    "more_body": False,
                }
            ]
            sent = []

            async def receive():
                if events:
                    return events.pop(0)
                return {"type": "http.disconnect"}

            async def send(event):
                sent.append(event)

            asyncio.run(endpoint(scope, receive, send))
            return AsgiResponse(sent)

        members = {
            ("student-1", room),
            ("student-2", room),
        }
        chat_server = ClassroomChatServerService(
            store=ClassroomChatServerSQLiteStore(
                self.root / "two-client-chat-server.sqlite3"
            ),
            authorization=ChatAuthorization(members),
            clock_unix_ms=lambda: 1700000000000,
        )
        chat_auth = BearerAuthenticator(
            {
                "chat-student-1": (room, "student-1"),
                "chat-student-2": (room, "student-2"),
            }
        )
        chat_endpoint = ClassroomChatHttpEndpoint(
            service=ClassroomChatRpcService(backend=chat_server),
            authenticator=chat_auth,
        )
        object_store = ObjectStore()
        file_server = ClassroomFileServerService(
            store=ClassroomFileServerSQLiteStore(
                str(self.root / "two-client-file-server.sqlite3")
            ),
            authorization=FileAuthorization(members),
            scanner=CleanScanner(),
            object_store=object_store,
        )
        file_auth = BearerAuthenticator(
            {
                "file-student-1": (room, "student-1"),
                "file-student-2": (room, "student-2"),
            }
        )
        file_endpoint = ClassroomFileHttpEndpoint(
            service=ClassroomFileRpcService(backend=file_server),
            authenticator=file_auth,
        )

        class ChatConnection:
            endpoint = chat_endpoint

            def __init__(self, host, port, timeout):
                self.closed = False
                self.request_data = None

            def request(self, method, target, *, body, headers):
                self.request_data = (method, target, bytes(body), dict(headers))

            def getresponse(self):
                if self.request_data is None:
                    raise AssertionError("chat request was not sent")
                method, target, body, headers = self.request_data
                if method != "POST":
                    raise AssertionError("unexpected chat method")
                return invoke_asgi(
                    self.endpoint,
                    target=target,
                    body=body,
                    headers=headers.items(),
                )

            def close(self):
                self.closed = True

        class FileConnection:
            endpoint = file_endpoint

            def __init__(self, host, port, timeout):
                self.closed = False
                self.request_line = None
                self.headers = []
                self.parts = []

            def putrequest(self, method, target, **kwargs):
                self.request_line = (method, target)

            def putheader(self, name, value):
                self.headers.append((name, value))

            def endheaders(self):
                return None

            def send(self, data):
                self.parts.append(bytes(data))

            def getresponse(self):
                if self.request_line is None:
                    raise AssertionError("file request was not started")
                method, target = self.request_line
                if method != "POST":
                    raise AssertionError("unexpected file method")
                return invoke_asgi(
                    self.endpoint,
                    target=target,
                    body=b"".join(self.parts),
                    headers=self.headers,
                )

            def close(self):
                self.closed = True

        first = self.bare_app()
        second = self.bare_app()
        with (
            mock.patch.object(Version2FinalProductApplication, "_assert_thread"),
            mock.patch(
                "acs.classroom_chat_http_endpoint.http.client.HTTPSConnection",
                ChatConnection,
            ),
            mock.patch(
                "acs.classroom_file_http_transport.http.client.HTTPSConnection",
                FileConnection,
            ),
        ):
            first_runtime = self.configure(
                first,
                participant_id="student-1",
                collaboration_store_path=self.root / "client-one.sqlite3",
                chat_endpoint_url="https://chat.example.test/v1/classroom/chat",
                file_endpoint_url="https://files.example.test/v1/classroom/files",
                chat_bearer_token_provider=lambda: "chat-student-1",
                file_bearer_token_provider=lambda: "file-student-1",
                file_picker=lambda: selected,
                allow_insecure_loopback=False,
            )
            second_runtime = self.configure(
                second,
                participant_id="student-2",
                collaboration_store_path=self.root / "client-two.sqlite3",
                chat_endpoint_url="https://chat.example.test/v1/classroom/chat",
                file_endpoint_url="https://files.example.test/v1/classroom/files",
                chat_bearer_token_provider=lambda: "chat-student-2",
                file_bearer_token_provider=lambda: "file-student-2",
                file_saver=lambda token, name: saved.append((token, name)),
                allow_insecure_loopback=False,
            )

            sent = first.browser_command(
                "classes",
                "collaboration.chat.send",
                {"body": "Shared over production HTTP"},
            )
            self.assertEqual("collaboration.chat.sent", sent["kind"])
            second.refresh_classroom_chat()

            uploaded = first.browser_command(
                "classes",
                "collaboration.file.choose_upload",
                {},
            )
            self.assertEqual("collaboration.file.sent", uploaded["kind"])
            second.refresh_classroom_files()
            second_file = second_runtime.webview.safe_snapshot()["files"]["items"][0]
            self.assertTrue(second_file["can_save"])
            saved_result = second.browser_command(
                "classes",
                "collaboration.file.save",
                {"file_key": second_file["file_key"]},
            )

            first.unbind_classroom_collaboration()
            second.unbind_classroom_collaboration()

        self.assertEqual(
            ("Shared over production HTTP",),
            tuple(
                item.body
                for item in second_runtime.store.room_messages(room)
            ),
        )
        remote_files = second_runtime.store.room_attachments(room)
        self.assertEqual(1, len(remote_files))
        self.assertEqual("two-client-shared.pgn", remote_files[0].display_name)
        self.assertEqual("stored", remote_files[0].transfer_state)
        self.assertEqual("clean", remote_files[0].scan_state)
        self.assertEqual(b"1. e4 e5 *", object_store.objects[remote_files[0].object_key])
        self.assertEqual("collaboration.file.saved", saved_result["kind"])
        self.assertEqual(
            [("read-student-2-300", "two-client-shared.pgn")],
            saved,
        )
        self.assertNotIn("read-student-2-300", repr(saved_result))
        self.assertNotIn(remote_files[0].object_key, repr(saved_result))
        self.assertIn("chat-student-1", chat_auth.calls)
        self.assertIn("chat-student-2", chat_auth.calls)
        self.assertIn("file-student-1", file_auth.calls)
        self.assertIn("file-student-2", file_auth.calls)
        self.assertNotEqual(
            first_runtime.store.path,
            second_runtime.store.path,
        )

    def test_process_restart_recovers_ambiguous_file_from_authoritative_history(self) -> None:
        store_path = self.root / "ambiguous-restart.sqlite3"
        selected = self.root / "ambiguous-restart.bin"
        selected.write_bytes(b"recover without local path")
        committed: dict[str, object] | None = None
        operations: list[str] = []

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
            def __init__(self, host, port, timeout):
                self.sent_parts = []

            def putrequest(self, method, target, **kwargs):
                return None

            def putheader(self, name, value):
                return None

            def endheaders(self):
                return None

            def send(self, data):
                self.sent_parts.append(bytes(data))

            def getresponse(self):
                nonlocal committed
                (header_size,) = struct.unpack("!I", self.sent_parts[0])
                if header_size != len(self.sent_parts[1]):
                    raise AssertionError("file HTTP JSON frame length mismatch")
                request = json.loads(self.sent_parts[1].decode("utf-8"))
                operation = request["op"]
                operations.append(operation)
                if operation == "upload":
                    metadata = dict(request["metadata"])
                    authoritative = dict(metadata)
                    authoritative["sequence_no"] = 0
                    authoritative["transfer_state"] = "stored"
                    authoritative["scan_state"] = "clean"
                    committed = authoritative
                    raise OSError("upload committed but acknowledgement was lost")
                if operation == "history":
                    if committed is None:
                        raise AssertionError("history requested before committed upload")
                    return Response(
                        {
                            "v": 1,
                            "ok": True,
                            "attachments": [committed],
                            "snapshot_state_revision": None,
                        }
                    )
                if operation == "state":
                    return Response({"v": 1, "ok": True, "updates": []})
                raise AssertionError(f"unexpected file operation: {operation}")

            def close(self):
                return None

        with (
            mock.patch.object(Version2FinalProductApplication, "_assert_thread"),
            mock.patch(
                "acs.classroom_file_http_transport.http.client.HTTPSConnection",
                Connection,
            ),
        ):
            first = self.bare_app()
            first_runtime = self.configure(
                first,
                collaboration_store_path=store_path,
                file_endpoint_url="https://files.example.test/v1/classroom/files",
                file_picker=lambda: selected,
            )
            failed = first.browser_command(
                "classes",
                "collaboration.file.choose_upload",
                {},
            )
            self.assertEqual("error", failed["kind"])
            failed_rows = first_runtime.store.room_attachments("room-1")
            self.assertEqual(len(failed_rows), 1)
            self.assertEqual(failed_rows[0].transfer_state, "failed")
            first.unbind_classroom_collaboration()

            second = self.bare_app()
            second_runtime = self.configure(
                second,
                collaboration_store_path=store_path,
                file_endpoint_url="https://files.example.test/v1/classroom/files",
            )
            before_sync = second_runtime.webview.safe_snapshot()["files"]["items"][0]
            self.assertFalse(before_sync["can_retry"])
            synced = second.refresh_classroom_files()

        self.assertEqual("collaboration.files.synced", synced["kind"])
        self.assertEqual(operations, ["upload", "history", "state"])
        self.assertEqual(self.file_token_calls, 3)
        recovered = second_runtime.store.room_attachments("room-1")
        self.assertEqual(len(recovered), 1)
        self.assertEqual(recovered[0].transfer_state, "stored")
        self.assertEqual(recovered[0].scan_state, "clean")
        self.assertEqual(recovered[0].sequence_no, 0)
        self.assertEqual(
            recovered[0].attachment_id,
            failed_rows[0].attachment_id,
        )

    def test_collaboration_remains_visible_when_education_workspace_is_unavailable(self) -> None:
        app = self.bare_app()
        with (
            mock.patch.object(Version2FinalProductApplication, "_assert_thread"),
            mock.patch.object(Version2Application, "snapshot", return_value={}),
        ):
            runtime = self.configure(app)
            snapshot = app.snapshot()

        self.assertIsNone(app.education)
        self.assertFalse(snapshot["product_status"]["education_available"])
        self.assertTrue(snapshot["product_status"]["collaboration_available"])
        education = snapshot["education"]
        self.assertIsInstance(education, dict)
        self.assertEqual("en", education["document"]["lang"])
        self.assertEqual("Classes and students", education["document"]["heading"])
        self.assertEqual((), education["sections"])
        self.assertIsNone(education["detail"])
        self.assertEqual(
            runtime.webview.safe_snapshot()["session_key"],
            education["collaboration"]["session_key"],
        )
        self.assertTrue(education["collaboration"]["available"])

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

    def test_final_app_rejects_quota_above_rpc_limit_before_store_creation(self) -> None:
        app = self.bare_app()
        target = self.root / "invalid-quota.sqlite3"
        oversized = FileQuotaPolicy(max_file_bytes=MAX_RPC_UPLOAD_BYTES + 1)
        with mock.patch.object(Version2FinalProductApplication, "_assert_thread"):
            with self.assertRaisesRegex(ValueError, "RPC upload limit"):
                self.configure(
                    app,
                    collaboration_store_path=target,
                    local_quota=oversized,
                )

        self.assertFalse(target.exists())
        self.assertIsNone(app.collaboration)
        self.assertIsNone(app._collaboration_runtime)
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


    def test_windows_final_product_defaults_chat_outbox_to_dpapi_state_root(self) -> None:
        app = self.bare_app()
        secure = MemorySecretStore()
        with (
            mock.patch.object(Version2FinalProductApplication, "_assert_thread"),
            mock.patch(
                "acs.version2_final_product_application.sys.platform",
                "win32",
            ),
            mock.patch(
                "acs.version2_final_product_application.WindowsDpapiSecretStore",
                return_value=secure,
            ) as dpapi,
        ):
            runtime = self.configure(
                app,
                collaboration_store_path=self.root / "windows-runtime.sqlite3",
            )

        dpapi.assert_called_once_with(self.root / "secure")
        self.assertIsNotNone(runtime.chat_outbox)
        self.assertEqual(self.chat_token_calls, 0)
        self.assertEqual(self.file_token_calls, 0)

    def test_explicit_chat_secret_store_is_forwarded_without_windows_default(self) -> None:
        app = self.bare_app()
        secure = MemorySecretStore()
        with (
            mock.patch.object(Version2FinalProductApplication, "_assert_thread"),
            mock.patch(
                "acs.version2_final_product_application.WindowsDpapiSecretStore"
            ) as dpapi,
        ):
            runtime = self.configure(
                app,
                chat_secret_store=secure,
            )

        dpapi.assert_not_called()
        self.assertIsNotNone(runtime.chat_outbox)
        assert runtime.chat_outbox is not None
        self.assertIs(runtime.chat_outbox.secret_store, secure)


if __name__ == "__main__":
    unittest.main()
