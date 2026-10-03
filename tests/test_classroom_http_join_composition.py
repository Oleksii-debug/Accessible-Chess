from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest

from acs.classroom_chat_rpc import ClassroomChatRpcService
from acs.classroom_collaboration import AttachmentHistoryPage, FileQuotaPolicy
from acs.classroom_file_rpc import ClassroomFileRpcService
from acs.classroom_http_application import ClassroomCollaborationHttpApplication
from acs.classroom_http_server_runtime import build_classroom_collaboration_http_server_runtime
from acs.classroom_join_credentials import (
    ClassroomJoinCredentialService,
    ClassroomJoinGrant,
)
from acs.classroom_join_http_endpoint import JOIN_CREDENTIAL_PATH
from tests.test_classroom_collaboration_chat_server import FakeAuthorization
from tests.test_classroom_file_server import AllowMembers, FakeObjectStore, FakeScanner


NOW = datetime(2026, 10, 3, 4, 15, tzinfo=timezone.utc)


class ChatBackend:
    def history_after(self, **_kwargs):
        return ()

    def state_updates_after(self, **_kwargs):
        return ()


class FileBackend:
    def history_after(self, **_kwargs):
        return AttachmentHistoryPage((), None)

    def state_updates_after(self, **_kwargs):
        return ()


class CollaborationAuthenticator:
    def __init__(self):
        self.calls = []

    async def authenticate_bearer(self, bearer_token: str):
        self.calls.append(bearer_token)
        return ("room-1", "student-1")


class JoinAuthenticator:
    def __init__(self):
        self.calls = []

    async def authenticate_bearer(self, bearer_token: str):
        self.calls.append(bearer_token)
        return "account-17"


class JoinAuthorization:
    def __init__(self):
        self.calls = []

    def authorize_join(
        self,
        *,
        room_id: str,
        trusted_caller_identity: str,
        requested_participant_id: str,
    ):
        self.calls.append(
            (room_id, trusted_caller_identity, requested_participant_id)
        )
        if trusted_caller_identity != "account-17":
            raise RuntimeError("caller rejected")
        return ClassroomJoinGrant(
            room_id=room_id,
            participant_id=requested_participant_id,
            publish_sources=(),
        )


class JoinIssuer:
    async def issue_join_token(self, *, grant, issued_at, expires_at):
        return "provider-short-lived-token"


def join_service():
    authorization = JoinAuthorization()
    service = ClassroomJoinCredentialService(
        authorization=authorization,
        token_issuer=JoinIssuer(),
        now=lambda: NOW,
    )
    return service, authorization


def scope(body: bytes, bearer: str = "account-bearer"):
    return {
        "type": "http",
        "http_version": "1.1",
        "scheme": "https",
        "method": "POST",
        "path": JOIN_CREDENTIAL_PATH,
        "raw_path": JOIN_CREDENTIAL_PATH.encode("ascii"),
        "query_string": b"",
        "server": ("127.0.0.1", 443),
        "client": ("127.0.0.1", 50000),
        "headers": [
            (b"authorization", f"Bearer {bearer}".encode("ascii")),
            (b"content-type", b"application/json; charset=utf-8"),
            (b"content-length", str(len(body)).encode("ascii")),
        ],
    }


async def invoke(app, request_scope, body):
    incoming = [{"type": "http.request", "body": body, "more_body": False}]
    sent = []

    async def receive():
        if not incoming:
            raise AssertionError("unexpected extra receive")
        return incoming.pop(0)

    async def send(event):
        sent.append(event)

    await app(request_scope, receive, send)
    return sent


def status(events):
    return next(
        item["status"]
        for item in events
        if item["type"] == "http.response.start"
    )


def response(events):
    raw = next(
        item["body"]
        for item in events
        if item["type"] == "http.response.body"
    )
    return json.loads(raw.decode("utf-8"))


class ClassroomHttpJoinCompositionTests(unittest.TestCase):
    def services(self):
        return (
            ClassroomChatRpcService(backend=ChatBackend()),
            ClassroomFileRpcService(backend=FileBackend()),
        )

    def test_join_route_keeps_authenticated_caller_distinct_from_room_participant(self):
        chat, files = self.services()
        collaboration_auth = CollaborationAuthenticator()
        join_auth = JoinAuthenticator()
        join, authorization = join_service()
        app = ClassroomCollaborationHttpApplication(
            chat_service=chat,
            file_service=files,
            authenticator=collaboration_auth,
            join_service=join,
            join_authenticator=join_auth,
        )
        body = json.dumps(
            {
                "version": 1,
                "room_id": "room-1",
                "participant_id": "student-1",
            },
            separators=(",", ":"),
        ).encode("utf-8")

        events = asyncio.run(invoke(app, scope(body), body))

        self.assertEqual(status(events), 200)
        payload = response(events)
        self.assertEqual(payload["room_id"], "room-1")
        self.assertEqual(payload["participant_id"], "student-1")
        self.assertEqual(payload["token"], "provider-short-lived-token")
        self.assertEqual(join_auth.calls, ["account-bearer"])
        self.assertEqual(collaboration_auth.calls, [])
        self.assertEqual(
            authorization.calls,
            [
                ("room-1", "account-17", "student-1"),
                ("room-1", "account-17", "student-1"),
            ],
        )
        self.assertIs(app._join._authenticator, join_auth)
        self.assertIs(app._chat._authenticator, collaboration_auth)
        self.assertIs(app._files._authenticator, collaboration_auth)
        self.assertNotIn("account-bearer", repr(app))
        self.assertNotIn("provider-short-lived-token", repr(app))

    def test_combined_join_route_malformed_bearer_uses_join_challenge_only(self):
        chat, files = self.services()
        collaboration_auth = CollaborationAuthenticator()
        join_auth = JoinAuthenticator()
        join, authorization = join_service()
        app = ClassroomCollaborationHttpApplication(
            chat_service=chat,
            file_service=files,
            authenticator=collaboration_auth,
            join_service=join,
            join_authenticator=join_auth,
        )
        body = json.dumps(
            {
                "version": 1,
                "room_id": "room-1",
                "participant_id": "student-1",
            },
            separators=(",", ":"),
        ).encode("utf-8")
        request_scope = scope(body)
        request_scope["headers"] = [
            (b"authorization", b"Bearer abc\x7fdef"),
            (b"content-type", b"application/json; charset=utf-8"),
            (b"content-length", str(len(body)).encode("ascii")),
        ]

        events = asyncio.run(invoke(app, request_scope, body))

        self.assertEqual(status(events), 401)
        start = next(
            item for item in events if item["type"] == "http.response.start"
        )
        headers = dict(start["headers"])
        self.assertEqual(
            headers[b"www-authenticate"],
            b'Bearer realm="accessible-chess-classroom"',
        )
        self.assertEqual(response(events), {"error": "unauthorized"})
        self.assertEqual(join_auth.calls, [])
        self.assertEqual(collaboration_auth.calls, [])
        self.assertEqual(authorization.calls, [])

    def test_join_route_is_absent_unless_both_join_authorities_are_bound(self):
        chat, files = self.services()
        collaboration_auth = CollaborationAuthenticator()
        join, _authorization = join_service()
        with self.assertRaisesRegex(ValueError, "configured together"):
            ClassroomCollaborationHttpApplication(
                chat_service=chat,
                file_service=files,
                authenticator=collaboration_auth,
                join_service=join,
            )
        with self.assertRaisesRegex(ValueError, "configured together"):
            ClassroomCollaborationHttpApplication(
                chat_service=chat,
                file_service=files,
                authenticator=collaboration_auth,
                join_authenticator=JoinAuthenticator(),
            )

        app = ClassroomCollaborationHttpApplication(
            chat_service=chat,
            file_service=files,
            authenticator=collaboration_auth,
        )
        body = b"{}"
        events = asyncio.run(invoke(app, scope(body), body))
        self.assertEqual(status(events), 404)
        self.assertEqual(response(events), {"error": "not_found"})
        self.assertEqual(collaboration_auth.calls, [])

    def test_server_runtime_injects_existing_join_service_without_merging_auth_semantics(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            collaboration_auth = CollaborationAuthenticator()
            join_auth = JoinAuthenticator()
            join, _authorization = join_service()
            runtime = build_classroom_collaboration_http_server_runtime(
                chat_database_path=root / "chat.sqlite3",
                file_database_path=root / "files.sqlite3",
                authenticator=collaboration_auth,
                chat_authorization=FakeAuthorization(),
                file_authorization=AllowMembers({("student-1", "room-1")}),
                file_scanner=FakeScanner(),
                file_object_store=FakeObjectStore(),
                clock_unix_ms=lambda: 1700000000000,
                file_quota=FileQuotaPolicy(
                    max_file_bytes=64,
                    max_room_bytes=256,
                ),
                join_service=join,
                join_authenticator=join_auth,
            )

            self.assertIs(runtime.join_service, join)
            self.assertIs(runtime.application._join._authenticator, join_auth)
            self.assertIs(
                runtime.application._chat._authenticator,
                collaboration_auth,
            )
            self.assertIs(
                runtime.application._files._authenticator,
                collaboration_auth,
            )

    def test_invalid_join_pair_fails_before_server_databases_are_created(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            chat_path = root / "chat.sqlite3"
            file_path = root / "files.sqlite3"
            join, _authorization = join_service()
            common = dict(
                chat_database_path=chat_path,
                file_database_path=file_path,
                authenticator=CollaborationAuthenticator(),
                chat_authorization=FakeAuthorization(),
                file_authorization=AllowMembers({("student-1", "room-1")}),
                file_scanner=FakeScanner(),
                file_object_store=FakeObjectStore(),
                clock_unix_ms=lambda: 1700000000000,
            )

            with self.assertRaisesRegex(ValueError, "configured together"):
                build_classroom_collaboration_http_server_runtime(
                    **common,
                    join_service=join,
                )
            self.assertFalse(chat_path.exists())
            self.assertFalse(file_path.exists())

            with self.assertRaisesRegex(ValueError, "configured together"):
                build_classroom_collaboration_http_server_runtime(
                    **common,
                    join_authenticator=JoinAuthenticator(),
                )
            self.assertFalse(chat_path.exists())
            self.assertFalse(file_path.exists())


if __name__ == "__main__":
    unittest.main()
