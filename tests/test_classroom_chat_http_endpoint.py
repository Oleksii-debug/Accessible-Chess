from __future__ import annotations

import json
from pathlib import Path
import unittest
from unittest.mock import patch

from acs.classroom_chat_http_endpoint import (
    CHAT_RPC_PATH,
    ClassroomChatHttpClientError,
    ClassroomChatHttpEndpoint,
    ClassroomChatHttpRpcCall,
)
from acs.classroom_chat_rpc import ClassroomChatRpcClient, ClassroomChatRpcService
from acs.classroom_collaboration import (
    ChatDraft,
    ChatModerationAction,
    ChatModerationCommand,
)
from acs.classroom_collaboration_storage import (
    ChatMessageMetadata,
    ChatMessageStateUpdate,
)


ROOM = "room-1"
STUDENT = "student-1"
TEACHER = "teacher-1"
CHAT_HTTP_WORKFLOW = (
    Path(__file__).resolve().parents[1]
    / ".github"
    / "workflows"
    / "classroom-chat-http-endpoint.yml"
)


class Authenticator:
    def __init__(self) -> None:
        self.calls: list[str] = []
        self.identity: object = (ROOM, STUDENT)
        self.fail = False

    async def authenticate_bearer(self, bearer_token: str):
        self.calls.append(bearer_token)
        if self.fail:
            raise RuntimeError("supersecret bearer verifier detail")
        return self.identity


class FakeHttpResponse:
    def __init__(
        self,
        payload=None,
        *,
        status=200,
        raw_body=None,
        headers=None,
    ) -> None:
        if raw_body is None:
            raw_body = json.dumps(
                {"v": 1, "ok": True} if payload is None else payload,
                ensure_ascii=False,
                separators=(",", ":"),
            ).encode("utf-8")
        self.status = status
        self.body = raw_body
        self.read_limits = []
        self.headers = (
            [
                ("Content-Type", "application/json; charset=utf-8"),
                ("Content-Length", str(len(raw_body))),
            ]
            if headers is None
            else headers
        )

    def getheaders(self):
        return list(self.headers)

    def read(self, limit):
        self.read_limits.append(limit)
        return self.body


class FakeHttpConnection:
    response = FakeHttpResponse()
    instances = []
    fail_request = None

    def __init__(self, host, port, timeout):
        self.host = host
        self.port = port
        self.timeout = timeout
        self.requests = []
        self.closed = False
        type(self).instances.append(self)

    def request(self, method, target, *, body, headers):
        if type(self).fail_request is not None:
            raise type(self).fail_request
        self.requests.append((method, target, body, dict(headers)))

    def getresponse(self):
        return type(self).response

    def close(self):
        self.closed = True


class Backend:
    def __init__(self) -> None:
        self.messages: list[ChatMessageMetadata] = []
        self.state: list[ChatMessageStateUpdate] = []
        self.send_calls: list[tuple[str, ChatDraft]] = []
        self.history_calls: list[tuple[str, str, int | None, int]] = []
        self.state_calls: list[tuple[str, str, int | None, int]] = []
        self.moderation_calls: list[
            tuple[str, tuple[ChatModerationCommand, ...]]
        ] = []
        self.fail = False
        self.invalid_send = False

    def send_message(self, *, trusted_caller_identity, draft):
        self.send_calls.append((trusted_caller_identity, draft))
        if self.fail:
            raise RuntimeError("supersecret backend detail")
        if self.invalid_send:
            return object()
        for message in self.messages:
            if message.message_id == draft.message_id:
                return message
        message = ChatMessageMetadata(
            draft.message_id,
            draft.room_id,
            draft.sender_id,
            len(self.messages),
            draft.body,
            draft.retention,
            sent_at_unix_ms=1700000000000 + len(self.messages),
        )
        self.messages.append(message)
        return message

    def history_after(
        self,
        *,
        trusted_caller_identity,
        room_id,
        after_sequence,
        limit,
    ):
        self.history_calls.append(
            (trusted_caller_identity, room_id, after_sequence, limit)
        )
        if self.fail:
            raise RuntimeError("supersecret backend detail")
        return tuple(
            message
            for message in self.messages
            if message.room_id == room_id
            and (
                after_sequence is None
                or message.sequence_no > after_sequence
            )
        )[:limit]

    def state_updates_after(
        self,
        *,
        trusted_caller_identity,
        room_id,
        after_revision,
        limit,
    ):
        self.state_calls.append(
            (trusted_caller_identity, room_id, after_revision, limit)
        )
        if self.fail:
            raise RuntimeError("supersecret backend detail")
        return tuple(
            update
            for update in self.state
            if update.room_id == room_id
            and (
                after_revision is None
                or update.revision > after_revision
            )
        )[:limit]

    def apply_moderation(
        self,
        *,
        trusted_caller_identity,
        commands,
    ):
        self.moderation_calls.append(
            (trusted_caller_identity, commands)
        )
        if self.fail:
            raise RuntimeError("supersecret backend detail")
        for command in commands:
            if command.action is not ChatModerationAction.HIDE_MESSAGE:
                continue
            for index, message in enumerate(self.messages):
                if message.message_id == command.message_id:
                    hidden = ChatMessageMetadata(
                        message.message_id,
                        message.room_id,
                        message.sender_id,
                        message.sequence_no,
                        message.body,
                        message.retention,
                        hidden=True,
                        sent_at_unix_ms=message.sent_at_unix_ms,
                    )
                    self.messages[index] = hidden
                    self.state.append(
                        ChatMessageStateUpdate(
                            room_id=message.room_id,
                            message_id=message.message_id,
                            revision=len(self.state),
                        )
                    )
                    break


class ClassroomChatHttpEndpointTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.backend = Backend()
        self.service = ClassroomChatRpcService(backend=self.backend)
        self.auth = Authenticator()
        self.endpoint = ClassroomChatHttpEndpoint(
            service=self.service,
            authenticator=self.auth,
        )

    @staticmethod
    def send_payload(
        *,
        participant: str = STUDENT,
        room: str = ROOM,
        message_id: str = "msg-1",
        body: str = "Hello",
    ) -> dict[str, object]:
        return {
            "v": 1,
            "op": "send",
            "room_id": room,
            "participant_id": participant,
            "message": {
                "message_id": message_id,
                "body": body,
                "retention": "session",
            },
        }

    async def invoke(
        self,
        *,
        payload: object | None = None,
        raw_body: bytes | None = None,
        headers: list[tuple[bytes, bytes]] | None = None,
        scope_overrides: dict[str, object] | None = None,
        receive_events: list[dict[str, object]] | None = None,
        endpoint: ClassroomChatHttpEndpoint | None = None,
        send_failure: Exception | None = None,
    ) -> list[dict[str, object]]:
        if raw_body is None:
            raw_body = json.dumps(
                self.send_payload() if payload is None else payload,
                ensure_ascii=False,
                separators=(",", ":"),
            ).encode("utf-8")
        if headers is None:
            headers = [
                (b"authorization", b"Bearer test-token"),
                (b"content-type", b"application/json; charset=utf-8"),
                (b"content-length", str(len(raw_body)).encode("ascii")),
            ]
        scope: dict[str, object] = {
            "type": "http",
            "scheme": "https",
            "http_version": "1.1",
            "method": "POST",
            "path": CHAT_RPC_PATH,
            "raw_path": CHAT_RPC_PATH.encode("ascii"),
            "query_string": b"",
            "headers": headers,
            "server": ("203.0.113.5", 443),
            "client": ("198.51.100.7", 43120),
        }
        if scope_overrides:
            scope.update(scope_overrides)
        events = list(
            receive_events
            if receive_events is not None
            else [
                {
                    "type": "http.request",
                    "body": raw_body,
                    "more_body": False,
                }
            ]
        )
        sent: list[dict[str, object]] = []

        async def receive() -> dict[str, object]:
            if not events:
                return {"type": "http.disconnect"}
            return events.pop(0)

        async def send(event: dict[str, object]) -> None:
            if send_failure is not None:
                raise send_failure
            sent.append(event)

        await (endpoint or self.endpoint)(scope, receive, send)
        return sent

    @staticmethod
    def response(sent: list[dict[str, object]]) -> tuple[int, dict[str, str], object]:
        start, body_event = sent
        headers = {
            name.decode("ascii"): value.decode("ascii")
            for name, value in start["headers"]
        }
        return (
            start["status"],
            headers,
            json.loads(body_event["body"].decode("utf-8")),
        )

    def test_workflow_qualifies_exact_live_stacked_http_scope(self) -> None:
        workflow = CHAT_HTTP_WORKFLOW.read_text(encoding="utf-8")
        self.assertIn(
            'test "$BASE_REF" = "feature/classroom-chat-rpc-core-20261002"',
            workflow,
        )
        self.assertIn(
            'test "$(git rev-parse HEAD)" = "$EXPECTED_HEAD_SHA"',
            workflow,
        )
        self.assertIn(
            'git merge-base --is-ancestor "$LIVE_BASE_SHA" HEAD',
            workflow,
        )
        self.assertIn(
            'git diff --name-only "$LIVE_BASE_SHA...HEAD"',
            workflow,
        )
        self.assertIn(
            "tests.test_classroom_chat_rpc",
            workflow,
        )
        self.assertIn(
            "tests.test_classroom_collaboration_chat_server",
            workflow,
        )

    def test_desktop_transport_requires_exact_secure_endpoint(self) -> None:
        invalid = (
            "http://203.0.113.5/v1/classroom/chat",
            "https://user:pass@example.com/v1/classroom/chat",
            "https://example.com/v1/classroom/chat?x=1",
            "https://example.com/v1/classroom/chat#frag",
            "https://example.com/v1/classroom/chat/",
            "https://example.com:0/v1/classroom/chat",
            "https://bad host/v1/classroom/chat",
            "ftp://example.com/v1/classroom/chat",
        )
        for endpoint_url in invalid:
            with self.subTest(endpoint_url=endpoint_url):
                with self.assertRaises(ValueError):
                    ClassroomChatHttpRpcCall(
                        endpoint_url=endpoint_url,
                        bearer_token_provider=lambda: "token",
                    )

        with self.assertRaises(ValueError):
            ClassroomChatHttpRpcCall(
                endpoint_url="http://127.0.0.1:8080/v1/classroom/chat",
                bearer_token_provider=lambda: "token",
            )
        with self.assertRaises(ValueError):
            ClassroomChatHttpRpcCall(
                endpoint_url="http://localhost:8080/v1/classroom/chat",
                bearer_token_provider=lambda: "token",
                allow_insecure_loopback=True,
            )
        transport = ClassroomChatHttpRpcCall(
            endpoint_url="http://127.0.0.1:8080/v1/classroom/chat",
            bearer_token_provider=lambda: "transport-secret",
            allow_insecure_loopback=True,
        )
        self.assertIn("scheme='http'", repr(transport))
        self.assertNotIn("transport-secret", repr(transport))

    def test_desktop_transport_canonicalizes_idna_host_without_credentials(self) -> None:
        transport = ClassroomChatHttpRpcCall(
            endpoint_url="https://tést.example/v1/classroom/chat",
            bearer_token_provider=lambda: "secret-token",
        )
        rendered = repr(transport)
        self.assertIn("xn--tst-bma.example", rendered)
        self.assertNotIn("secret-token", rendered)

    def test_desktop_transport_uses_fresh_bearer_and_strict_bounded_response(self) -> None:
        tokens = iter(("token-one", "token-two"))
        FakeHttpConnection.instances = []
        FakeHttpConnection.fail_request = None
        FakeHttpConnection.response = FakeHttpResponse({"v": 1, "ok": True})
        transport = ClassroomChatHttpRpcCall(
            endpoint_url="https://chat.example.test/v1/classroom/chat",
            bearer_token_provider=lambda: next(tokens),
            timeout_seconds=7,
        )

        with patch(
            "acs.classroom_chat_http_endpoint.http.client.HTTPSConnection",
            FakeHttpConnection,
        ):
            first = transport.call({"v": 1, "op": "one"})
            second = transport.call({"v": 1, "op": "two"})

        self.assertEqual({"v": 1, "ok": True}, first)
        self.assertEqual(first, second)
        self.assertEqual(2, len(FakeHttpConnection.instances))
        self.assertTrue(all(item.closed for item in FakeHttpConnection.instances))
        self.assertEqual(
            ["Bearer token-one", "Bearer token-two"],
            [
                item.requests[0][3]["Authorization"]
                for item in FakeHttpConnection.instances
            ],
        )
        self.assertEqual(
            [("chat.example.test", 443, 7.0)] * 2,
            [
                (item.host, item.port, item.timeout)
                for item in FakeHttpConnection.instances
            ],
        )
        method, target, raw_body, headers = FakeHttpConnection.instances[0].requests[0]
        self.assertEqual("POST", method)
        self.assertEqual(CHAT_RPC_PATH, target)
        self.assertEqual(
            {"v": 1, "op": "one"},
            json.loads(raw_body.decode("utf-8")),
        )
        self.assertEqual("application/json; charset=utf-8", headers["Content-Type"])
        self.assertEqual("application/json", headers["Accept"])
        self.assertEqual(str(len(raw_body)), headers["Content-Length"])
        self.assertEqual(
            [192 * 1024 * 1024 + 1, 192 * 1024 * 1024 + 1],
            FakeHttpConnection.response.read_limits,
        )

    def test_desktop_transport_integrates_with_canonical_rpc_client(self) -> None:
        delivered = {
            "v": 1,
            "ok": True,
            "message": {
                "message_id": "http-client-message",
                "room_id": ROOM,
                "sender_id": STUDENT,
                "sequence_no": 0,
                "body": "Through HTTP",
                "retention": "session",
                "hidden": False,
                "redacted": False,
                "sent_at_unix_ms": 1700000000000,
            },
        }
        FakeHttpConnection.instances = []
        FakeHttpConnection.fail_request = None
        FakeHttpConnection.response = FakeHttpResponse(delivered)
        transport = ClassroomChatHttpRpcCall(
            endpoint_url="https://chat.example.test/v1/classroom/chat",
            bearer_token_provider=lambda: "ephemeral-token",
        )
        client = ClassroomChatRpcClient(
            room_id=ROOM,
            participant_id=STUDENT,
            transport=transport,
        )

        with patch(
            "acs.classroom_chat_http_endpoint.http.client.HTTPSConnection",
            FakeHttpConnection,
        ):
            message = client.send_message(
                ChatDraft(
                    "http-client-message",
                    ROOM,
                    STUDENT,
                    "Through HTTP",
                )
            )

        self.assertEqual("http-client-message", message.message_id)
        request = json.loads(
            FakeHttpConnection.instances[0].requests[0][2].decode("utf-8")
        )
        self.assertEqual("send", request["op"])
        self.assertEqual(ROOM, request["room_id"])
        self.assertEqual(STUDENT, request["participant_id"])
        self.assertNotIn("ephemeral-token", repr(request))

    def test_desktop_transport_rejects_bad_credentials_without_network(self) -> None:
        for token in (
            "",
            "has space",
            " trailing ",
            "nonascii-\N{LATIN SMALL LETTER E WITH ACUTE}",
            "x" * 9000,
        ):
            FakeHttpConnection.instances = []
            transport = ClassroomChatHttpRpcCall(
                endpoint_url="https://chat.example.test/v1/classroom/chat",
                bearer_token_provider=lambda token=token: token,
            )
            with patch(
                "acs.classroom_chat_http_endpoint.http.client.HTTPSConnection",
                FakeHttpConnection,
            ):
                with self.assertRaises(ClassroomChatHttpClientError):
                    transport.call({"v": 1})
            self.assertEqual([], FakeHttpConnection.instances)

    def test_desktop_transport_rejects_untrusted_response_shapes_and_closes(self) -> None:
        cases = (
            FakeHttpResponse(status=401),
            FakeHttpResponse(headers=[
                ("Content-Type", "text/plain"),
                ("Content-Length", "2"),
            ], raw_body=b"{}"),
            FakeHttpResponse(headers=[
                ("Content-Type", "application/json; charset=utf-8"),
                ("Content-Length", "2"),
                ("Content-Encoding", "gzip"),
            ], raw_body=b"{}"),
            FakeHttpResponse(headers=[
                ("Content-Type", "application/json; charset=utf-8"),
                ("Content-Length", "2"),
                ("Content-Length", "2"),
            ], raw_body=b"{}"),
            FakeHttpResponse(headers=[
                ("Bad Header", "x"),
                ("Content-Type", "application/json; charset=utf-8"),
                ("Content-Length", "2"),
            ], raw_body=b"{}"),
            FakeHttpResponse(headers=[
                ("X-Test", "line\nfeed"),
                ("Content-Type", "application/json; charset=utf-8"),
                ("Content-Length", "2"),
            ], raw_body=b"{}"),
            FakeHttpResponse(
                headers=[
                    ("Content-Type", "application/json; charset=utf-8"),
                    ("Content-Length", "3"),
                ],
                raw_body=b"{}",
            ),
            FakeHttpResponse(raw_body=b'{"v":1,"v":1}'),
            FakeHttpResponse(raw_body=b"[]"),
            FakeHttpResponse(raw_body=b'{"v":NaN}'),
            FakeHttpResponse(raw_body=b"\xff"),
        )
        for response in cases:
            with self.subTest(response=response):
                FakeHttpConnection.instances = []
                FakeHttpConnection.fail_request = None
                FakeHttpConnection.response = response
                transport = ClassroomChatHttpRpcCall(
                    endpoint_url="https://chat.example.test/v1/classroom/chat",
                    bearer_token_provider=lambda: "token",
                )
                with patch(
                    "acs.classroom_chat_http_endpoint.http.client.HTTPSConnection",
                    FakeHttpConnection,
                ):
                    with self.assertRaises(ClassroomChatHttpClientError):
                        transport.call({"v": 1})
                self.assertEqual(1, len(FakeHttpConnection.instances))
                self.assertTrue(FakeHttpConnection.instances[0].closed)

    def test_desktop_transport_sanitizes_network_failure_and_closes(self) -> None:
        FakeHttpConnection.instances = []
        FakeHttpConnection.fail_request = RuntimeError("socket secret")
        transport = ClassroomChatHttpRpcCall(
            endpoint_url="https://chat.example.test/v1/classroom/chat",
            bearer_token_provider=lambda: "token",
        )
        with patch(
            "acs.classroom_chat_http_endpoint.http.client.HTTPSConnection",
            FakeHttpConnection,
        ):
            with self.assertRaisesRegex(
                ClassroomChatHttpClientError,
                "transport failed",
            ) as raised:
                transport.call({"v": 1})
        self.assertIsNone(raised.exception.__cause__)
        self.assertNotIn("socket secret", str(raised.exception))
        self.assertTrue(FakeHttpConnection.instances[0].closed)
        FakeHttpConnection.fail_request = None

    async def test_https_send_binds_bearer_identity_and_sets_private_headers(self) -> None:
        sent = await self.invoke()
        status, headers, payload = self.response(sent)

        self.assertEqual(200, status)
        self.assertEqual("no-store", headers["cache-control"])
        self.assertEqual("no-cache", headers["pragma"])
        self.assertEqual("nosniff", headers["x-content-type-options"])
        self.assertEqual("application/json; charset=utf-8", headers["content-type"])
        self.assertEqual(["test-token"], self.auth.calls)
        self.assertEqual(1, len(self.backend.send_calls))
        caller, draft = self.backend.send_calls[0]
        self.assertEqual(STUDENT, caller)
        self.assertEqual(ROOM, draft.room_id)
        self.assertEqual(STUDENT, draft.sender_id)
        self.assertEqual("msg-1", payload["message"]["message_id"])
        self.assertEqual(0, payload["message"]["sequence_no"])
        self.assertEqual(1700000000000, payload["message"]["sent_at_unix_ms"])
        self.assertFalse(payload["message"]["redacted"])

    async def test_authenticated_identity_mismatch_is_forbidden_before_backend(self) -> None:
        sent = await self.invoke(
            payload=self.send_payload(participant="student-2"),
        )
        status, _, payload = self.response(sent)
        self.assertEqual(403, status)
        self.assertEqual({"error": "chat_request_rejected"}, payload)
        self.assertEqual([], self.backend.send_calls)

    async def test_authentication_failure_and_malformed_identity_are_unauthorized(self) -> None:
        self.auth.fail = True
        sent = await self.invoke()
        status, headers, payload = self.response(sent)
        self.assertEqual(401, status)
        self.assertEqual({"error": "unauthorized"}, payload)
        self.assertIn("Bearer", headers["www-authenticate"])
        self.assertNotIn("supersecret", json.dumps(payload))
        self.assertEqual([], self.backend.send_calls)

        self.auth.fail = False
        for identity in (
            (ROOM,),
            ("bad room", STUDENT),
            (ROOM, "bad participant"),
            ("r" * 129, STUDENT),
            (ROOM, "p" * 129),
        ):
            with self.subTest(identity=identity):
                self.auth.identity = identity
                sent = await self.invoke()
                self.assertEqual(401, self.response(sent)[0])
                self.assertEqual([], self.backend.send_calls)

    async def test_backend_failure_and_contract_failure_are_sanitized_unavailable(self) -> None:
        self.backend.fail = True
        sent = await self.invoke()
        status, _, payload = self.response(sent)
        self.assertEqual(503, status)
        self.assertEqual({"error": "chat_request_rejected"}, payload)
        self.assertNotIn("supersecret", json.dumps(payload))

        self.backend.fail = False
        self.backend.invalid_send = True
        sent = await self.invoke(
            payload=self.send_payload(message_id="invalid-backend-message"),
        )
        self.assertEqual(503, self.response(sent)[0])

    async def test_http_requires_tls_except_explicit_literal_loopback(self) -> None:
        sent = await self.invoke(
            scope_overrides={
                "scheme": "http",
                "server": ("127.0.0.1", 8080),
                "client": ("127.0.0.1", 55100),
            },
        )
        self.assertEqual(400, self.response(sent)[0])
        self.assertEqual([], self.auth.calls)

        loopback = ClassroomChatHttpEndpoint(
            service=self.service,
            authenticator=self.auth,
            allow_insecure_loopback=True,
        )
        sent = await self.invoke(
            endpoint=loopback,
            scope_overrides={
                "scheme": "http",
                "server": ("::1", 8080),
                "client": ("127.0.0.1", 55100),
            },
        )
        self.assertEqual(200, self.response(sent)[0])

        sent = await self.invoke(
            endpoint=loopback,
            scope_overrides={
                "scheme": "http",
                "server": ("localhost", 8080),
                "client": ("127.0.0.1", 55100),
            },
        )
        self.assertEqual(400, self.response(sent)[0])

    async def test_route_method_query_raw_path_and_http_version_fail_closed(self) -> None:
        cases = (
            ({"method": "GET"}, 405),
            ({"path": "/v1/classroom/other"}, 404),
            ({"raw_path": b"/v1/classroom/chat%2f"}, 404),
            ({"query_string": b"x=1"}, 400),
            ({"http_version": "1.0"}, 400),
        )
        for overrides, expected in cases:
            with self.subTest(overrides=overrides):
                before = len(self.auth.calls)
                sent = await self.invoke(scope_overrides=overrides)
                self.assertEqual(expected, self.response(sent)[0])
                self.assertEqual(before, len(self.auth.calls))

    async def test_headers_are_strict_bounded_and_never_accept_encoded_body(self) -> None:
        body = json.dumps(self.send_payload()).encode("utf-8")
        cases = (
            (
                [
                    (b"authorization", b"Bearer one"),
                    (b"authorization", b"Bearer two"),
                    (b"content-type", b"application/json"),
                    (b"content-length", str(len(body)).encode("ascii")),
                ],
                400,
            ),
            (
                [
                    (b"authorization", b"Bearer one"),
                    (b"content-type", b"text/plain"),
                    (b"content-length", str(len(body)).encode("ascii")),
                ],
                415,
            ),
            (
                [
                    (b"authorization", b"Bearer one"),
                    (b"content-type", b"application/json"),
                    (b"content-encoding", b"gzip"),
                    (b"content-length", str(len(body)).encode("ascii")),
                ],
                415,
            ),
            (
                [
                    (b"authorization", b"Bearer one"),
                    (b"content-type", b"application/json"),
                    (b"transfer-encoding", b"chunked"),
                ],
                400,
            ),
            (
                [
                    (b"authorization", b"Bearer one"),
                    (b"content-type", b"application/json"),
                ],
                400,
            ),
        )
        for headers, expected in cases:
            with self.subTest(headers=headers):
                sent = await self.invoke(raw_body=body, headers=headers)
                self.assertEqual(expected, self.response(sent)[0])

    async def test_missing_content_length_fails_before_authentication_or_body_read(self) -> None:
        body = json.dumps(self.send_payload()).encode("utf-8")
        receive_calls = 0
        sent = []

        async def receive():
            nonlocal receive_calls
            receive_calls += 1
            raise AssertionError("request body must not be consumed")

        async def send(event):
            sent.append(event)

        scope = {
            "type": "http",
            "scheme": "https",
            "http_version": "1.1",
            "method": "POST",
            "path": CHAT_RPC_PATH,
            "raw_path": CHAT_RPC_PATH.encode("ascii"),
            "query_string": b"",
            "headers": [
                (b"authorization", b"Bearer test-token"),
                (b"content-type", b"application/json"),
            ],
            "server": ("203.0.113.5", 443),
            "client": ("198.51.100.7", 43120),
        }

        before = len(self.auth.calls)
        await self.endpoint(scope, receive, send)
        self.assertEqual(0, receive_calls)
        self.assertEqual(before, len(self.auth.calls))
        self.assertEqual(400, self.response(sent)[0])
        self.assertEqual([], self.backend.send_calls)
        self.assertTrue(body)

    async def test_bearer_is_single_ascii_bounded_and_not_leaked(self) -> None:
        body = json.dumps(self.send_payload()).encode("utf-8")
        for auth_value in (
            b"",
            b"Basic abc",
            b"Bearer ",
            b"Bearer has space",
            b"Bearer nonascii-\xff",
        ):
            with self.subTest(auth_value=auth_value):
                sent = await self.invoke(
                    raw_body=body,
                    headers=[
                        (b"authorization", auth_value),
                        (b"content-type", b"application/json"),
                        (b"content-length", str(len(body)).encode("ascii")),
                    ],
                )
                status, _, payload = self.response(sent)
                self.assertEqual(401, status)
                self.assertEqual({"error": "unauthorized"}, payload)
                if auth_value:
                    self.assertNotIn(
                        auth_value.decode("latin1"),
                        json.dumps(payload),
                    )

        self.assertNotIn("test-token", repr(self.endpoint))

    async def test_declared_and_streamed_body_bounds_fail_before_rpc_effect(self) -> None:
        with patch(
            "acs.classroom_chat_http_endpoint.MAX_CHAT_HTTP_REQUEST_BYTES",
            32,
        ):
            body = b"{}"
            sent = await self.invoke(
                raw_body=body,
                headers=[
                    (b"authorization", b"Bearer test-token"),
                    (b"content-type", b"application/json"),
                    (b"content-length", b"33"),
                ],
            )
            self.assertEqual(413, self.response(sent)[0])

            sent = await self.invoke(
                headers=[
                    (b"authorization", b"Bearer test-token"),
                    (b"content-type", b"application/json"),
                    (b"content-length", b"32"),
                ],
                raw_body=b"x" * 33,
            )
            self.assertEqual(413, self.response(sent)[0])

        self.assertEqual([], self.backend.send_calls)

    async def test_request_body_frame_count_is_independently_bounded(self) -> None:
        body = json.dumps(self.send_payload()).encode("utf-8")
        events = [
            {"type": "http.request", "body": body[:1], "more_body": True},
            {"type": "http.request", "body": body[1:2], "more_body": True},
            {"type": "http.request", "body": body[2:], "more_body": False},
        ]
        with patch(
            "acs.classroom_chat_http_endpoint.MAX_REQUEST_BODY_EVENTS",
            2,
        ):
            sent = await self.invoke(
                raw_body=body,
                receive_events=events,
            )

        status, _, payload = self.response(sent)
        self.assertEqual(413, status)
        self.assertEqual({"error": "request_too_fragmented"}, payload)
        self.assertEqual([], self.backend.send_calls)

    async def test_content_length_mismatch_and_invalid_body_events_fail_closed(self) -> None:
        body = json.dumps(self.send_payload()).encode("utf-8")
        sent = await self.invoke(
            raw_body=body,
            headers=[
                (b"authorization", b"Bearer test-token"),
                (b"content-type", b"application/json"),
                (b"content-length", str(len(body) + 1).encode("ascii")),
            ],
        )
        self.assertEqual(400, self.response(sent)[0])

        sent = await self.invoke(
            raw_body=body,
            receive_events=[
                {
                    "type": "http.request",
                    "body": "not-bytes",
                    "more_body": False,
                }
            ],
        )
        self.assertEqual(400, self.response(sent)[0])

    async def test_duplicate_members_nonfinite_numbers_and_nonobject_json_are_rejected(self) -> None:
        bodies = (
            b'{"v":1,"v":1}',
            b'{"v":NaN}',
            b'[]',
            b'{"v":1',
            b'\xff',
        )
        for body in bodies:
            with self.subTest(body=body):
                sent = await self.invoke(
                    raw_body=body,
                    headers=[
                        (b"authorization", b"Bearer test-token"),
                        (b"content-type", b"application/json"),
                        (b"content-length", str(len(body)).encode("ascii")),
                    ],
                )
                self.assertEqual(400, self.response(sent)[0])
        self.assertEqual([], self.backend.send_calls)

    async def test_history_state_and_moderation_delegate_only_authenticated_identity(self) -> None:
        await self.invoke()
        history = {
            "v": 1,
            "op": "history",
            "room_id": ROOM,
            "participant_id": STUDENT,
            "after_sequence": None,
            "limit": 10,
        }
        sent = await self.invoke(payload=history)
        status, _, payload = self.response(sent)
        self.assertEqual(200, status)
        self.assertEqual("msg-1", payload["messages"][0]["message_id"])
        self.assertEqual((STUDENT, ROOM, None, 10), self.backend.history_calls[-1])

        self.auth.identity = (ROOM, TEACHER)
        moderation = {
            "v": 1,
            "op": "moderate",
            "room_id": ROOM,
            "participant_id": TEACHER,
            "commands": [
                {
                    "operation_id": "hide-1",
                    "action": "hide_message",
                    "message_id": "msg-1",
                }
            ],
        }
        sent = await self.invoke(payload=moderation)
        self.assertEqual(200, self.response(sent)[0])
        caller, commands = self.backend.moderation_calls[-1]
        self.assertEqual(TEACHER, caller)
        self.assertEqual(TEACHER, commands[0].actor_id)

        self.auth.identity = (ROOM, STUDENT)
        state = {
            "v": 1,
            "op": "state",
            "room_id": ROOM,
            "participant_id": STUDENT,
            "after_revision": None,
            "limit": 10,
        }
        sent = await self.invoke(payload=state)
        status, _, payload = self.response(sent)
        self.assertEqual(200, status)
        self.assertTrue(payload["updates"][0]["hidden"])
        self.assertEqual((STUDENT, ROOM, None, 10), self.backend.state_calls[-1])

    async def test_redacted_history_and_state_survive_authenticated_http_framing(self) -> None:
        self.backend.messages = [
            ChatMessageMetadata(
                "expired-session-message",
                ROOM,
                STUDENT,
                0,
                "",
                "session",
                hidden=False,
                sent_at_unix_ms=1700000000000,
                redacted=True,
            )
        ]
        self.backend.state = [
            ChatMessageStateUpdate(
                ROOM,
                "expired-session-message",
                0,
                hidden=False,
                redacted=True,
            )
        ]

        history_request = {
            "v": 1,
            "op": "history",
            "room_id": ROOM,
            "participant_id": STUDENT,
            "after_sequence": None,
            "limit": 10,
        }
        history_sent = await self.invoke(payload=history_request)
        status, _, history_payload = self.response(history_sent)
        self.assertEqual(200, status)
        self.assertEqual(1, len(history_payload["messages"]))
        message = history_payload["messages"][0]
        self.assertEqual("expired-session-message", message["message_id"])
        self.assertEqual("", message["body"])
        self.assertFalse(message["hidden"])
        self.assertTrue(message["redacted"])
        self.assertEqual(0, message["sequence_no"])
        self.assertEqual(1700000000000, message["sent_at_unix_ms"])

        state_request = {
            "v": 1,
            "op": "state",
            "room_id": ROOM,
            "participant_id": STUDENT,
            "after_revision": None,
            "limit": 10,
        }
        state_sent = await self.invoke(payload=state_request)
        status, _, state_payload = self.response(state_sent)
        self.assertEqual(200, status)
        self.assertEqual(
            {
                "room_id": ROOM,
                "message_id": "expired-session-message",
                "revision": 0,
                "hidden": False,
                "redacted": True,
            },
            state_payload["updates"][0],
        )

    async def test_client_disconnect_before_complete_body_emits_no_response_or_rpc_effect(self) -> None:
        body = json.dumps(self.send_payload()).encode("utf-8")
        sent = await self.invoke(
            raw_body=body,
            receive_events=[
                {
                    "type": "http.request",
                    "body": body[:10],
                    "more_body": True,
                },
                {"type": "http.disconnect"},
            ],
        )
        self.assertEqual([], sent)
        self.assertEqual([], self.backend.send_calls)

    async def test_response_size_cap_fails_closed_without_leaking_rpc_payload(self) -> None:
        with patch(
            "acs.classroom_chat_http_endpoint.MAX_CHAT_HTTP_RESPONSE_BYTES",
            1,
        ):
            sent = await self.invoke()
        status, _, payload = self.response(sent)
        self.assertEqual(503, status)
        self.assertEqual({"error": "chat_service_unavailable"}, payload)

    async def test_response_delivery_failure_is_not_masked_as_second_response(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "response delivery failed"):
            await self.invoke(send_failure=RuntimeError("socket secret"))

    async def test_lifespan_startup_and_shutdown_are_supported(self) -> None:
        events = [
            {"type": "lifespan.startup"},
            {"type": "lifespan.shutdown"},
        ]
        sent: list[dict[str, object]] = []

        async def receive():
            return events.pop(0)

        async def send(event):
            sent.append(event)

        await self.endpoint({"type": "lifespan"}, receive, send)
        self.assertEqual(
            [
                {"type": "lifespan.startup.complete"},
                {"type": "lifespan.shutdown.complete"},
            ],
            sent,
        )


if __name__ == "__main__":
    unittest.main()
