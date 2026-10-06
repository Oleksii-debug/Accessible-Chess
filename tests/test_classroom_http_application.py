from __future__ import annotations

import asyncio
import json
import struct
import unittest

from acs.classroom_chat_http_endpoint import CHAT_RPC_PATH
from acs.classroom_chat_rpc import ClassroomChatRpcService
from acs.classroom_collaboration import AttachmentHistoryPage
from acs.classroom_file_http_transport import FILE_RPC_CONTENT_TYPE, FILE_RPC_PATH
from acs.classroom_file_rpc import ClassroomFileRpcService
from acs.classroom_http_application import ClassroomCollaborationHttpApplication


class ChatBackend:
    def __init__(self) -> None:
        self.history_calls = []

    def send_message(self, **_kwargs):
        raise AssertionError("send is not expected")

    def history_after(self, **kwargs):
        self.history_calls.append(kwargs)
        return ()

    def state_updates_after(self, **_kwargs):
        return ()

    def apply_moderation(self, **_kwargs):
        raise AssertionError("moderation is not expected")


class FileBackend:
    def __init__(self) -> None:
        self.history_calls = []

    def upload(self, **_kwargs):
        raise AssertionError("upload is not expected")

    def cancel(self, **_kwargs):
        raise AssertionError("cancel is not expected")

    def history_after(self, **kwargs):
        self.history_calls.append(kwargs)
        return AttachmentHistoryPage((), None)

    def state_updates_after(self, **_kwargs):
        return ()

    def issue_read_token(self, **_kwargs):
        raise AssertionError("read token is not expected")

    def delete_object(self, **_kwargs):
        raise AssertionError("delete is not expected")


class SharedAuthenticator:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.calls = []

    async def authenticate_bearer(self, bearer_token: str):
        self.calls.append(bearer_token)
        if self.fail:
            raise RuntimeError("credential rejected")
        return ("room-1", "student-1")


def chat_history_body() -> bytes:
    return json.dumps(
        {
            "v": 1,
            "op": "history",
            "room_id": "room-1",
            "participant_id": "student-1",
            "after_sequence": None,
            "limit": 10,
        },
        separators=(",", ":"),
    ).encode("utf-8")


def file_history_body() -> bytes:
    header = json.dumps(
        {
            "v": 1,
            "op": "history",
            "room_id": "room-1",
            "participant_id": "student-1",
            "after_sequence": None,
            "limit": 10,
        },
        separators=(",", ":"),
    ).encode("utf-8")
    return struct.pack("!I", len(header)) + header


def http_scope(
    path: str,
    *,
    body: bytes,
    bearer: str,
    content_type: str,
    scheme: str = "https",
):
    return {
        "type": "http",
        "http_version": "1.1",
        "scheme": scheme,
        "method": "POST",
        "path": path,
        "raw_path": path.encode("ascii"),
        "query_string": b"",
        "server": ("127.0.0.1", 443 if scheme == "https" else 80),
        "client": ("127.0.0.1", 50000),
        "headers": [
            (b"authorization", f"Bearer {bearer}".encode("ascii")),
            (b"content-type", content_type.encode("ascii")),
            (b"content-length", str(len(body)).encode("ascii")),
        ],
    }


async def invoke(app, scope, body: bytes):
    incoming = [{"type": "http.request", "body": body, "more_body": False}]
    sent = []

    async def receive():
        if not incoming:
            raise AssertionError("unexpected extra receive")
        return incoming.pop(0)

    async def send(event):
        sent.append(event)

    await app(scope, receive, send)
    return sent


def response_status(events) -> int:
    return next(event["status"] for event in events if event["type"] == "http.response.start")


def response_headers(events) -> dict[bytes, bytes]:
    start = next(event for event in events if event["type"] == "http.response.start")
    return dict(start["headers"])


def response_json(events):
    body = next(event["body"] for event in events if event["type"] == "http.response.body")
    return json.loads(body.decode("utf-8"))


class ClassroomHttpApplicationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.chat_backend = ChatBackend()
        self.file_backend = FileBackend()
        self.chat_service = ClassroomChatRpcService(backend=self.chat_backend)
        self.file_service = ClassroomFileRpcService(backend=self.file_backend)
        self.auth = SharedAuthenticator()
        self.app = ClassroomCollaborationHttpApplication(
            chat_service=self.chat_service,
            file_service=self.file_service,
            authenticator=self.auth,
        )

    def test_one_authenticator_routes_chat_and_file_to_canonical_services(self) -> None:
        chat_body = chat_history_body()
        chat_events = asyncio.run(
            invoke(
                self.app,
                http_scope(
                    CHAT_RPC_PATH,
                    body=chat_body,
                    bearer="chat-token",
                    content_type="application/json",
                ),
                chat_body,
            )
        )
        self.assertEqual(response_status(chat_events), 200)
        self.assertTrue(response_json(chat_events)["ok"])

        file_body = file_history_body()
        file_events = asyncio.run(
            invoke(
                self.app,
                http_scope(
                    FILE_RPC_PATH,
                    body=file_body,
                    bearer="file-token",
                    content_type=FILE_RPC_CONTENT_TYPE,
                ),
                file_body,
            )
        )
        self.assertEqual(response_status(file_events), 200)
        self.assertTrue(response_json(file_events)["ok"])

        self.assertEqual(self.auth.calls, ["chat-token", "file-token"])
        self.assertEqual(
            self.chat_backend.history_calls,
            [{
                "trusted_caller_identity": "student-1",
                "room_id": "room-1",
                "after_sequence": None,
                "limit": 10,
            }],
        )
        self.assertEqual(
            self.file_backend.history_calls,
            [{
                "trusted_caller_identity": "student-1",
                "room_id": "room-1",
                "after_sequence": None,
                "limit": 10,
            }],
        )
        self.assertIs(self.app._chat._authenticator, self.auth)
        self.assertIs(self.app._files._authenticator, self.auth)
        self.assertEqual(repr(self.app), "ClassroomCollaborationHttpApplication(<bound>)")
        self.assertNotIn("chat-token", repr(self.app))

    def test_unknown_route_is_privacy_safe_and_never_authenticates(self) -> None:
        events = asyncio.run(
            invoke(
                self.app,
                {
                    "type": "http",
                    "http_version": "1.1",
                    "scheme": "https",
                    "method": "GET",
                    "path": "/not-classroom",
                    "raw_path": b"/not-classroom",
                    "query_string": b"",
                    "headers": [],
                },
                b"",
            )
        )
        self.assertEqual(response_status(events), 404)
        self.assertEqual(response_json(events), {"error": "not_found"})
        headers = response_headers(events)
        self.assertEqual(headers[b"cache-control"], b"no-store")
        self.assertEqual(headers[b"pragma"], b"no-cache")
        self.assertEqual(headers[b"x-content-type-options"], b"nosniff")
        self.assertEqual(self.auth.calls, [])
        self.assertEqual(self.chat_backend.history_calls, [])
        self.assertEqual(self.file_backend.history_calls, [])

    def test_shared_auth_failure_keeps_route_specific_bearer_challenge(self) -> None:
        auth = SharedAuthenticator(fail=True)
        app = ClassroomCollaborationHttpApplication(
            chat_service=self.chat_service,
            file_service=self.file_service,
            authenticator=auth,
        )

        chat_body = chat_history_body()
        chat_events = asyncio.run(
            invoke(
                app,
                http_scope(
                    CHAT_RPC_PATH,
                    body=chat_body,
                    bearer="bad-chat",
                    content_type="application/json",
                ),
                chat_body,
            )
        )
        self.assertEqual(response_status(chat_events), 401)
        self.assertIn(
            b"accessible-chess-classroom-chat",
            response_headers(chat_events)[b"www-authenticate"],
        )

        file_body = file_history_body()
        file_events = asyncio.run(
            invoke(
                app,
                http_scope(
                    FILE_RPC_PATH,
                    body=file_body,
                    bearer="bad-file",
                    content_type=FILE_RPC_CONTENT_TYPE,
                ),
                file_body,
            )
        )
        self.assertEqual(response_status(file_events), 401)
        self.assertIn(
            b"accessible-chess-classroom-files",
            response_headers(file_events)[b"www-authenticate"],
        )
        self.assertEqual(auth.calls, ["bad-chat", "bad-file"])

    def test_insecure_loopback_opt_in_is_shared_by_both_routes(self) -> None:
        app = ClassroomCollaborationHttpApplication(
            chat_service=self.chat_service,
            file_service=self.file_service,
            authenticator=self.auth,
            allow_insecure_loopback=True,
        )

        chat_body = chat_history_body()
        chat_events = asyncio.run(
            invoke(
                app,
                http_scope(
                    CHAT_RPC_PATH,
                    body=chat_body,
                    bearer="loop-chat",
                    content_type="application/json",
                    scheme="http",
                ),
                chat_body,
            )
        )
        self.assertEqual(response_status(chat_events), 200)

        file_body = file_history_body()
        file_events = asyncio.run(
            invoke(
                app,
                http_scope(
                    FILE_RPC_PATH,
                    body=file_body,
                    bearer="loop-file",
                    content_type=FILE_RPC_CONTENT_TYPE,
                    scheme="http",
                ),
                file_body,
            )
        )
        self.assertEqual(response_status(file_events), 200)

    def test_lifespan_is_owned_once_by_combined_application(self) -> None:
        async def run():
            incoming = [
                {"type": "lifespan.startup"},
                {"type": "lifespan.shutdown"},
            ]
            sent = []

            async def receive():
                return incoming.pop(0)

            async def send(event):
                sent.append(event)

            await self.app({"type": "lifespan"}, receive, send)
            return sent

        self.assertEqual(
            asyncio.run(run()),
            [
                {"type": "lifespan.startup.complete"},
                {"type": "lifespan.shutdown.complete"},
            ],
        )
        self.assertEqual(self.auth.calls, [])

    def test_constructor_and_scope_validation_fail_closed(self) -> None:
        with self.assertRaises(TypeError):
            ClassroomCollaborationHttpApplication(
                chat_service=object(),
                file_service=self.file_service,
                authenticator=self.auth,
            )
        with self.assertRaises(TypeError):
            ClassroomCollaborationHttpApplication(
                chat_service=self.chat_service,
                file_service=object(),
                authenticator=self.auth,
            )
        with self.assertRaises(TypeError):
            ClassroomCollaborationHttpApplication(
                chat_service=self.chat_service,
                file_service=self.file_service,
                authenticator=object(),
            )
        with self.assertRaises(TypeError):
            ClassroomCollaborationHttpApplication(
                chat_service=self.chat_service,
                file_service=self.file_service,
                authenticator=self.auth,
                allow_insecure_loopback=1,
            )

        async def no_receive():
            raise AssertionError("receive must not be called")

        async def no_send(_event):
            raise AssertionError("send must not be called")

        with self.assertRaises(RuntimeError):
            asyncio.run(self.app({"type": "websocket"}, no_receive, no_send))
        with self.assertRaises(TypeError):
            asyncio.run(self.app(None, no_receive, no_send))


if __name__ == "__main__":
    unittest.main()
