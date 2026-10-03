from __future__ import annotations

from dataclasses import replace
import hashlib
import json
from pathlib import Path
import struct
import tempfile
import unittest
from unittest.mock import patch

from acs.classroom_collaboration import (
    AttachmentHistoryPage,
    PreparedFile,
)
from acs.classroom_collaboration_storage import AttachmentMetadata
from acs.classroom_file_http_transport import (
    FILE_RPC_CONTENT_TYPE,
    FILE_RPC_PATH,
    MAX_FILE_HTTP_REQUEST_BYTES,
    ClassroomFileHttpClientError,
    ClassroomFileHttpEndpoint,
    ClassroomFileHttpRpcCall,
)
from acs.classroom_file_rpc import (
    ClassroomFileRpcClient,
    ClassroomFileRpcService,
)
from acs.classroom_file_server import (
    ClassroomFileServerSQLiteStore,
    ClassroomFileServerService,
)


ROOM = "room-1"
STUDENT = "student-1"


class Authenticator:
    def __init__(self) -> None:
        self.calls = []
        self.identity = (ROOM, STUDENT)
        self.fail = False

    async def authenticate_bearer(self, token):
        self.calls.append(token)
        if self.fail:
            raise RuntimeError("secret auth detail")
        return self.identity


class Backend:
    def __init__(self) -> None:
        self.upload_calls = []
        self.cancel_calls = []
        self.history_calls = []
        self.state_calls = []
        self.token_calls = []
        self.delete_calls = []
        self.fail = False

    def upload(self, *, trusted_caller_identity, metadata, content):
        self.upload_calls.append(
            (trusted_caller_identity, metadata, bytes(content))
        )
        if self.fail:
            raise RuntimeError("secret backend detail")
        return replace(
            metadata,
            sequence_no=0,
            transfer_state="stored",
            scan_state="clean",
        )

    def cancel(
        self,
        *,
        trusted_caller_identity,
        attachment_id,
        expected_room_id=None,
    ):
        self.cancel_calls.append(
            (trusted_caller_identity, attachment_id, expected_room_id)
        )
        if self.fail:
            raise RuntimeError("secret cancel detail")

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
            raise RuntimeError("secret history detail")
        return AttachmentHistoryPage((), None)

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
            raise RuntimeError("secret state detail")
        return ()

    def issue_read_token(
        self,
        *,
        trusted_caller_identity,
        object_key,
        ttl_seconds,
        expected_room_id=None,
    ):
        self.token_calls.append(
            (
                trusted_caller_identity,
                object_key,
                ttl_seconds,
                expected_room_id,
            )
        )
        if self.fail:
            raise RuntimeError("secret token detail")
        return "read-token"

    def delete_object(
        self,
        *,
        trusted_caller_identity,
        object_key,
        expected_room_id=None,
    ):
        self.delete_calls.append(
            (trusted_caller_identity, object_key, expected_room_id)
        )
        if self.fail:
            raise RuntimeError("secret delete detail")


class AllowMembers:
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


class MemoryObjectStore:
    def __init__(self):
        self.objects = {}

    def stored_sha256(self, *, object_key):
        content = self.objects.get(object_key)
        if content is None:
            return None
        return hashlib.sha256(content).hexdigest()

    def put(self, *, object_key, content, expected_sha256):
        if hashlib.sha256(content).hexdigest() != expected_sha256:
            raise RuntimeError("hash mismatch")
        self.objects[object_key] = bytes(content)

    def issue_read_token(self, *, object_key, participant_id, ttl_seconds):
        if object_key not in self.objects:
            raise RuntimeError("missing object")
        return f"token-{participant_id}-{ttl_seconds}"

    def delete(self, *, object_key):
        self.objects.pop(object_key, None)


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
    fail_send_at = None
    instances = []

    def __init__(self, host, port, timeout):
        self.host = host
        self.port = port
        self.timeout = timeout
        self.request_line = None
        self.headers = []
        self.sent_parts = []
        self.closed = False
        type(self).instances.append(self)

    def putrequest(self, method, target, **kwargs):
        self.request_line = (method, target, dict(kwargs))

    def putheader(self, name, value):
        self.headers.append((name, value))

    def endheaders(self):
        pass

    def send(self, data):
        if (
            type(self).fail_send_at is not None
            and len(self.sent_parts) == type(self).fail_send_at
        ):
            raise RuntimeError("socket supersecret")
        self.sent_parts.append(bytes(data))

    def getresponse(self):
        return type(self).response

    def close(self):
        self.closed = True


def attachment_wire(
    *,
    attachment_id="att-1",
    body=b"opaque",
    transfer_state="uploading",
    scan_state="pending",
):
    return {
        "attachment_id": attachment_id,
        "room_id": ROOM,
        "sender_id": STUDENT,
        "sequence_no": 41,
        "display_name": "lesson.bin",
        "mime_type": "application/octet-stream",
        "size_bytes": len(body),
        "sha256": hashlib.sha256(body).hexdigest(),
        "object_key": f"rooms/{ROOM}/{attachment_id}",
        "transfer_state": transfer_state,
        "retention": "persistent",
        "scan_state": scan_state,
    }


def upload_request(body=b"opaque"):
    return {
        "v": 1,
        "op": "upload",
        "room_id": ROOM,
        "participant_id": STUDENT,
        "metadata": attachment_wire(body=body),
        "content": body,
    }


def frame(request):
    request = dict(request)
    content = request.pop("content", b"")
    header = json.dumps(
        request,
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    return struct.pack("!I", len(header)) + header + content


class ClassroomFileHttpEndpointTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.backend = Backend()
        self.service = ClassroomFileRpcService(backend=self.backend)
        self.auth = Authenticator()
        self.endpoint = ClassroomFileHttpEndpoint(
            service=self.service,
            authenticator=self.auth,
        )

    async def invoke(
        self,
        *,
        request=None,
        raw_body=None,
        headers=None,
        scope_overrides=None,
        receive_events=None,
        endpoint=None,
        send_failure=None,
    ):
        if raw_body is None:
            raw_body = frame(upload_request() if request is None else request)
        if headers is None:
            headers = [
                (b"authorization", b"Bearer test-token"),
                (b"content-type", FILE_RPC_CONTENT_TYPE.encode("ascii")),
                (b"content-length", str(len(raw_body)).encode("ascii")),
            ]
        scope = {
            "type": "http",
            "scheme": "https",
            "http_version": "1.1",
            "method": "POST",
            "path": FILE_RPC_PATH,
            "raw_path": FILE_RPC_PATH.encode("ascii"),
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
        sent = []

        async def receive():
            if not events:
                return {"type": "http.disconnect"}
            return events.pop(0)

        async def send(event):
            if send_failure is not None:
                raise send_failure
            sent.append(event)

        await (endpoint or self.endpoint)(scope, receive, send)
        return sent

    @staticmethod
    def response(sent):
        start, body = sent
        headers = {
            name.decode("ascii"): value.decode("ascii")
            for name, value in start["headers"]
        }
        return (
            start["status"],
            headers,
            json.loads(body["body"].decode("utf-8")),
        )

    def test_workflow_qualifies_exact_live_stacked_file_http_scope(self):
        workflow = (
            Path(__file__).resolve().parents[1]
            / ".github"
            / "workflows"
            / "classroom-file-http-transport.yml"
        ).read_text(encoding="utf-8")
        self.assertIn(
            'test "$BASE_REF" = "feature/classroom-file-rpc-core-20261003"',
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
        self.assertIn("tests.test_classroom_file_rpc", workflow)
        self.assertIn("tests.test_classroom_file_server", workflow)

    async def test_binary_upload_preserves_opaque_bytes_and_authenticated_identity(self):
        content = b"\x00\xffopaque\nbytes"
        sent = await self.invoke(request=upload_request(content))
        status, headers, payload = self.response(sent)

        self.assertEqual(200, status)
        self.assertEqual("no-store", headers["cache-control"])
        self.assertEqual(["test-token"], self.auth.calls)
        self.assertEqual(1, len(self.backend.upload_calls))
        caller, metadata, observed = self.backend.upload_calls[0]
        self.assertEqual(STUDENT, caller)
        self.assertEqual(content, observed)
        self.assertEqual(hashlib.sha256(content).hexdigest(), metadata.sha256)
        self.assertEqual("stored", payload["attachment"]["transfer_state"])
        self.assertEqual("clean", payload["attachment"]["scan_state"])

    async def test_desktop_emitted_upload_frame_is_accepted_by_real_endpoint(self):
        content = b"\x00client-to-endpoint\xff"
        stored = attachment_wire(
            body=content,
            transfer_state="stored",
            scan_state="clean",
        )
        stored["sequence_no"] = 0
        FakeHttpConnection.instances = []
        FakeHttpConnection.response = FakeHttpResponse(
            {"v": 1, "ok": True, "attachment": stored}
        )
        transport = ClassroomFileHttpRpcCall(
            endpoint_url="https://files.example.test/v1/classroom/files",
            bearer_token_provider=lambda: "wire-token",
        )

        with patch(
            "acs.classroom_file_http_transport.http.client.HTTPSConnection",
            FakeHttpConnection,
        ):
            transport.call(upload_request(content))

        emitted = FakeHttpConnection.instances[0]
        raw_body = b"".join(emitted.sent_parts)
        request_headers = [
            (
                name.lower().encode("ascii"),
                value.encode("ascii"),
            )
            for name, value in emitted.headers
        ]
        sent = await self.invoke(
            raw_body=raw_body,
            headers=request_headers,
        )

        status, _, payload = self.response(sent)
        self.assertEqual(200, status)
        self.assertEqual("stored", payload["attachment"]["transfer_state"])
        self.assertEqual(1, len(self.backend.upload_calls))
        self.assertEqual(content, self.backend.upload_calls[0][2])
        self.assertEqual(["wire-token"], self.auth.calls)

    async def test_full_https_to_rpc_to_trusted_sqlite_object_store_round_trip(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            objects = MemoryObjectStore()
            server = ClassroomFileServerService(
                store=ClassroomFileServerSQLiteStore(
                    str(Path(temp_dir) / "files.sqlite3")
                ),
                authorization=AllowMembers({(STUDENT, ROOM)}),
                scanner=CleanScanner(),
                object_store=objects,
            )
            endpoint = ClassroomFileHttpEndpoint(
                service=ClassroomFileRpcService(backend=server),
                authenticator=self.auth,
            )
            content = b"\x00\xfffull stack arbitrary bytes"
            sent = await self.invoke(
                endpoint=endpoint,
                request=upload_request(content),
            )
            status, _, stored_payload = self.response(sent)
            self.assertEqual(200, status)
            stored = stored_payload["attachment"]
            self.assertEqual("stored", stored["transfer_state"])
            self.assertEqual("clean", stored["scan_state"])
            self.assertEqual(content, objects.objects[stored["object_key"]])

            sent = await self.invoke(
                endpoint=endpoint,
                request={
                    "v": 1,
                    "op": "history",
                    "room_id": ROOM,
                    "participant_id": STUDENT,
                    "after_sequence": None,
                    "limit": 10,
                },
            )
            status, _, history_payload = self.response(sent)
            self.assertEqual(200, status)
            self.assertEqual([stored], history_payload["attachments"])

    async def test_nonupload_request_has_no_binary_tail_and_forwards_room(self):
        request = {
            "v": 1,
            "op": "history",
            "room_id": ROOM,
            "participant_id": STUDENT,
            "after_sequence": None,
            "limit": 10,
        }
        sent = await self.invoke(request=request)
        status, _, payload = self.response(sent)
        self.assertEqual(200, status)
        self.assertEqual([], payload["attachments"])
        self.assertEqual((STUDENT, ROOM, None, 10), self.backend.history_calls[-1])

        malformed = frame(request) + b"unexpected"
        sent = await self.invoke(raw_body=malformed)
        self.assertEqual(400, self.response(sent)[0])
        self.assertEqual(1, len(self.backend.history_calls))

    async def test_frame_rejects_truncation_json_content_member_and_bad_json(self):
        valid = upload_request(b"abc")
        framed = frame(valid)
        header_length = struct.unpack("!I", framed[:4])[0]
        bad_content_member = dict(valid)
        bad_content_member["content"] = "not opaque bytes"
        bad_header = json.dumps(
            bad_content_member,
            separators=(",", ":"),
        ).encode("utf-8")
        bodies = (
            b"\x00\x00\x00\x00x",
            struct.pack("!I", header_length + 50) + framed[4:],
            struct.pack("!I", 2) + b"{}" + b"x",
            struct.pack("!I", len(bad_header)) + bad_header,
            struct.pack("!I", 7) + b'{"v":Na',
            struct.pack("!I", 13) + b'{"v":1,"v":1}',
        )
        for raw_body in bodies:
            with self.subTest(raw_body=raw_body[:40]):
                sent = await self.invoke(raw_body=raw_body)
                self.assertEqual(400, self.response(sent)[0])
        self.assertEqual([], self.backend.upload_calls)

    async def test_upload_binary_length_must_match_authenticated_metadata(self):
        framed = frame(upload_request(b"abcdef"))
        for malformed in (framed[:-1], framed + b"x"):
            with self.subTest(length=len(malformed)):
                sent = await self.invoke(raw_body=malformed)
                status, _, payload = self.response(sent)
                self.assertEqual(400, status)
                self.assertEqual({"error": "file_request_rejected"}, payload)
        self.assertEqual([], self.backend.upload_calls)

    async def test_authentication_failure_does_not_consume_request_body(self):
        raw = frame(upload_request(b"secret-body-must-not-be-read"))
        self.auth.fail = True
        receive_calls = 0
        sent = []

        async def receive():
            nonlocal receive_calls
            receive_calls += 1
            raise AssertionError("unauthenticated request body was consumed")

        async def send(event):
            sent.append(event)

        scope = {
            "type": "http",
            "scheme": "https",
            "http_version": "1.1",
            "method": "POST",
            "path": FILE_RPC_PATH,
            "raw_path": FILE_RPC_PATH.encode("ascii"),
            "query_string": b"",
            "headers": [
                (b"authorization", b"Bearer invalid-token"),
                (b"content-type", FILE_RPC_CONTENT_TYPE.encode("ascii")),
                (b"content-length", str(len(raw)).encode("ascii")),
            ],
            "server": ("203.0.113.5", 443),
            "client": ("198.51.100.7", 43120),
        }

        await self.endpoint(scope, receive, send)
        self.assertEqual(0, receive_calls)
        self.assertEqual(401, self.response(sent)[0])
        self.assertEqual([], self.backend.upload_calls)

    async def test_authentication_identity_tls_route_and_headers_fail_before_backend(self):
        self.auth.identity = ("bad room", STUDENT)
        sent = await self.invoke()
        self.assertEqual(401, self.response(sent)[0])
        self.assertEqual([], self.backend.upload_calls)

        self.auth.identity = (ROOM, STUDENT)
        cases = (
            ({"scheme": "http"}, None, 400),
            ({"method": "GET"}, None, 405),
            ({"path": "/v1/classroom/other"}, None, 404),
            ({"query_string": b"x=1"}, None, 400),
            (
                None,
                [
                    (b"authorization", b"Bearer test-token"),
                    (b"content-type", b"application/json"),
                    (b"content-length", b"5"),
                ],
                415,
            ),
            (
                None,
                [
                    (b"authorization", b"Bearer test-token"),
                    (b"content-type", FILE_RPC_CONTENT_TYPE.encode("ascii")),
                    (b"content-length", b"5"),
                    (b"transfer-encoding", b"chunked"),
                ],
                400,
            ),
        )
        for overrides, headers, expected in cases:
            with self.subTest(overrides=overrides, headers=headers):
                before = len(self.backend.upload_calls)
                sent = await self.invoke(
                    scope_overrides=overrides,
                    headers=headers,
                    raw_body=b"\x00\x00\x00\x01{}" if headers else None,
                )
                self.assertEqual(expected, self.response(sent)[0])
                self.assertEqual(before, len(self.backend.upload_calls))

    async def test_literal_loopback_http_requires_explicit_opt_in(self):
        loopback = ClassroomFileHttpEndpoint(
            service=self.service,
            authenticator=self.auth,
            allow_insecure_loopback=True,
        )
        sent = await self.invoke(
            endpoint=loopback,
            scope_overrides={
                "scheme": "http",
                "server": ("127.0.0.1", 8080),
                "client": ("::1", 55100),
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

    async def test_declared_body_and_frame_count_are_independently_bounded(self):
        raw = frame(upload_request(b"abc"))
        with patch(
            "acs.classroom_file_http_transport.MAX_REQUEST_BODY_EVENTS",
            2,
        ):
            sent = await self.invoke(
                raw_body=raw,
                receive_events=[
                    {"type": "http.request", "body": raw[:1], "more_body": True},
                    {"type": "http.request", "body": raw[1:2], "more_body": True},
                    {"type": "http.request", "body": raw[2:], "more_body": False},
                ],
            )
        self.assertEqual(413, self.response(sent)[0])
        self.assertEqual([], self.backend.upload_calls)

        sent = await self.invoke(
            raw_body=raw,
            headers=[
                (b"authorization", b"Bearer test-token"),
                (b"content-type", FILE_RPC_CONTENT_TYPE.encode("ascii")),
                (b"content-length", str(len(raw) + 1).encode("ascii")),
            ],
        )
        self.assertEqual(400, self.response(sent)[0])
        self.assertEqual([], self.backend.upload_calls)

    async def test_oversized_declared_length_fails_before_authentication(self):
        self.auth.calls.clear()
        sent = await self.invoke(
            raw_body=b"",
            headers=[
                (b"authorization", b"Bearer should-not-be-consumed"),
                (b"content-type", FILE_RPC_CONTENT_TYPE.encode("ascii")),
                (
                    b"content-length",
                    str(MAX_FILE_HTTP_REQUEST_BYTES + 1).encode("ascii"),
                ),
            ],
        )
        self.assertEqual(413, self.response(sent)[0])
        self.assertEqual([], self.auth.calls)
        self.assertEqual([], self.backend.upload_calls)

    async def test_rpc_identity_mismatch_and_backend_failure_are_sanitized(self):
        bad = upload_request()
        bad["participant_id"] = "student-2"
        sent = await self.invoke(request=bad)
        status, _, payload = self.response(sent)
        self.assertEqual(403, status)
        self.assertEqual({"error": "file_request_rejected"}, payload)
        self.assertEqual([], self.backend.upload_calls)

        self.backend.fail = True
        sent = await self.invoke()
        status, _, payload = self.response(sent)
        self.assertEqual(503, status)
        self.assertEqual({"error": "file_request_rejected"}, payload)
        self.assertNotIn("secret", repr(payload))

    async def test_disconnect_emits_no_response_or_backend_effect(self):
        raw = frame(upload_request(b"abc"))
        sent = await self.invoke(
            raw_body=raw,
            receive_events=[
                {"type": "http.request", "body": raw[:20], "more_body": True},
                {"type": "http.disconnect"},
            ],
        )
        self.assertEqual([], sent)
        self.assertEqual([], self.backend.upload_calls)

    async def test_response_delivery_failure_is_not_masked(self):
        with self.assertRaisesRegex(RuntimeError, "response delivery failed"):
            await self.invoke(send_failure=RuntimeError("socket secret"))

    async def test_lifespan_is_supported(self):
        events = [
            {"type": "lifespan.startup"},
            {"type": "lifespan.shutdown"},
        ]
        sent = []

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


class ClassroomFileHttpClientTests(unittest.TestCase):
    def setUp(self):
        FakeHttpConnection.instances = []
        FakeHttpConnection.fail_send_at = None
        FakeHttpConnection.response = FakeHttpResponse()

    def test_client_requires_exact_secure_url_and_keeps_token_out_of_repr(self):
        invalid = (
            "http://203.0.113.5/v1/classroom/files",
            "https://user:pass@example.com/v1/classroom/files",
            "https://example.com/v1/classroom/files?x=1",
            "https://example.com/v1/classroom/files#frag",
            "https://example.com/v1/classroom/files/",
            "https://example.com:0/v1/classroom/files",
            "https://bad host/v1/classroom/files",
        )
        for endpoint_url in invalid:
            with self.subTest(endpoint_url=endpoint_url):
                with self.assertRaises(ValueError):
                    ClassroomFileHttpRpcCall(
                        endpoint_url=endpoint_url,
                        bearer_token_provider=lambda: "token",
                    )

        with self.assertRaises(ValueError):
            ClassroomFileHttpRpcCall(
                endpoint_url="http://127.0.0.1:8080/v1/classroom/files",
                bearer_token_provider=lambda: "token",
            )
        transport = ClassroomFileHttpRpcCall(
            endpoint_url="http://127.0.0.1:8080/v1/classroom/files",
            bearer_token_provider=lambda: "supersecret",
            allow_insecure_loopback=True,
        )
        self.assertNotIn("supersecret", repr(transport))

    def test_client_sends_upload_as_prefix_header_and_raw_bytes_without_base64(self):
        content = b"\x00\xffopaque"
        stored = attachment_wire(
            body=content,
            transfer_state="stored",
            scan_state="clean",
        )
        stored["sequence_no"] = 0
        FakeHttpConnection.response = FakeHttpResponse(
            {"v": 1, "ok": True, "attachment": stored}
        )
        tokens = iter(("token-one", "token-two"))
        transport = ClassroomFileHttpRpcCall(
            endpoint_url="https://files.example.test/v1/classroom/files",
            bearer_token_provider=lambda: next(tokens),
            timeout_seconds=11,
        )

        with patch(
            "acs.classroom_file_http_transport.http.client.HTTPSConnection",
            FakeHttpConnection,
        ):
            first = transport.call(upload_request(content))
            second_request = {
                "v": 1,
                "op": "history",
                "room_id": ROOM,
                "participant_id": STUDENT,
                "after_sequence": None,
                "limit": 1,
            }
            FakeHttpConnection.response = FakeHttpResponse(
                {
                    "v": 1,
                    "ok": True,
                    "attachments": [],
                    "snapshot_state_revision": None,
                }
            )
            second = transport.call(second_request)

        self.assertEqual("stored", first["attachment"]["transfer_state"])
        self.assertEqual([], second["attachments"])
        upload_conn = FakeHttpConnection.instances[0]
        self.assertEqual(("POST", FILE_RPC_PATH), upload_conn.request_line[:2])
        self.assertEqual(3, len(upload_conn.sent_parts))
        prefix, header, raw = upload_conn.sent_parts
        self.assertEqual(len(header), struct.unpack("!I", prefix)[0])
        envelope = json.loads(header.decode("utf-8"))
        self.assertEqual("upload", envelope["op"])
        self.assertNotIn("content", envelope)
        self.assertEqual(content, raw)
        self.assertNotIn(
            content.hex(),
            header.decode("utf-8"),
        )
        headers = dict(upload_conn.headers)
        self.assertEqual("Bearer token-one", headers["Authorization"])
        self.assertEqual(FILE_RPC_CONTENT_TYPE, headers["Content-Type"])
        self.assertEqual(
            str(sum(len(part) for part in upload_conn.sent_parts)),
            headers["Content-Length"],
        )

        history_conn = FakeHttpConnection.instances[1]
        self.assertEqual(2, len(history_conn.sent_parts))
        self.assertEqual("Bearer token-two", dict(history_conn.headers)["Authorization"])
        self.assertTrue(upload_conn.closed)
        self.assertTrue(history_conn.closed)

    def test_client_reports_only_actual_raw_upload_bytes_monotonically(self):
        content = b"abcdefghij"
        stored = attachment_wire(
            body=content,
            transfer_state="stored",
            scan_state="clean",
        )
        stored["sequence_no"] = 0
        FakeHttpConnection.response = FakeHttpResponse(
            {"v": 1, "ok": True, "attachment": stored}
        )
        transport = ClassroomFileHttpRpcCall(
            endpoint_url="https://files.example.test/v1/classroom/files",
            bearer_token_provider=lambda: "token",
        )
        observed = []

        with (
            patch(
                "acs.classroom_file_http_transport.http.client.HTTPSConnection",
                FakeHttpConnection,
            ),
            patch(
                "acs.classroom_file_http_transport._UPLOAD_SEND_CHUNK_BYTES",
                3,
            ),
        ):
            transport.call(
                upload_request(content),
                on_upload_progress=observed.append,
            )

        self.assertEqual([0, 3, 6, 9, 10], observed)
        sent = FakeHttpConnection.instances[0].sent_parts
        self.assertEqual(6, len(sent))
        self.assertEqual(content, b"".join(sent[2:]))

    def test_client_progress_callback_failure_aborts_without_response_read(self):
        content = b"abcdef"
        transport = ClassroomFileHttpRpcCall(
            endpoint_url="https://files.example.test/v1/classroom/files",
            bearer_token_provider=lambda: "token",
        )

        def reject_progress(value):
            if value > 0:
                from acs.classroom_file_rpc import ClassroomFileRpcError
                raise ClassroomFileRpcError("progress contract rejected sample")

        with (
            patch(
                "acs.classroom_file_http_transport.http.client.HTTPSConnection",
                FakeHttpConnection,
            ),
            self.assertRaisesRegex(
                Exception,
                "progress contract rejected sample",
            ),
        ):
            transport.call(
                upload_request(content),
                on_upload_progress=reject_progress,
            )

        self.assertEqual(1, len(FakeHttpConnection.instances))
        self.assertTrue(FakeHttpConnection.instances[0].closed)

    def test_client_integrates_with_canonical_file_rpc_client(self):
        content = b"canonical HTTP file"
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "lesson.bin"
            path.write_bytes(content)
            metadata = AttachmentMetadata(
                "att-1",
                ROOM,
                STUDENT,
                77,
                path.name,
                "application/octet-stream",
                len(content),
                hashlib.sha256(content).hexdigest(),
                f"rooms/{ROOM}/att-1",
                "pending",
                "persistent",
                "pending",
            )
            prepared = PreparedFile(path, metadata)
            stored = attachment_wire(
                body=content,
                transfer_state="stored",
                scan_state="clean",
            )
            stored["sequence_no"] = 0
            FakeHttpConnection.response = FakeHttpResponse(
                {"v": 1, "ok": True, "attachment": stored}
            )
            transport = ClassroomFileHttpRpcCall(
                endpoint_url="https://files.example.test/v1/classroom/files",
                bearer_token_provider=lambda: "ephemeral-token",
            )
            client = ClassroomFileRpcClient(
                room_id=ROOM,
                participant_id=STUDENT,
                transport=transport,
            )

            with patch(
                "acs.classroom_file_http_transport.http.client.HTTPSConnection",
                FakeHttpConnection,
            ):
                delivered = client.upload(prepared)

        self.assertEqual("stored", delivered.transfer_state)
        self.assertEqual("clean", delivered.scan_state)
        envelope = json.loads(
            FakeHttpConnection.instances[0].sent_parts[1].decode("utf-8")
        )
        self.assertNotIn("content", envelope)
        self.assertNotIn("ephemeral-token", repr(envelope))

    def test_client_rejects_invalid_credentials_before_network(self):
        for token in (
            "",
            "has space",
            " trailing ",
            "nonascii-é",
            "x" * 9000,
        ):
            FakeHttpConnection.instances = []
            transport = ClassroomFileHttpRpcCall(
                endpoint_url="https://files.example.test/v1/classroom/files",
                bearer_token_provider=lambda token=token: token,
            )
            with patch(
                "acs.classroom_file_http_transport.http.client.HTTPSConnection",
                FakeHttpConnection,
            ):
                with self.assertRaises(ClassroomFileHttpClientError):
                    transport.call(
                        {
                            "v": 1,
                            "op": "history",
                            "room_id": ROOM,
                            "participant_id": STUDENT,
                            "after_sequence": None,
                            "limit": 1,
                        }
                    )
            self.assertEqual([], FakeHttpConnection.instances)

    def test_client_rejects_hostile_response_metadata_json_and_status(self):
        cases = (
            FakeHttpResponse(status=401),
            FakeHttpResponse(
                raw_body=b"{}",
                headers=[
                    ("Content-Type", "text/plain"),
                    ("Content-Length", "2"),
                ],
            ),
            FakeHttpResponse(
                raw_body=b"{}",
                headers=[
                    ("Content-Type", "application/json; charset=utf-8"),
                    ("Content-Length", "2"),
                    ("Content-Encoding", "gzip"),
                ],
            ),
            FakeHttpResponse(
                raw_body=b"{}",
                headers=[
                    ("Content-Type", "application/json; charset=utf-8"),
                    ("Content-Length", "2"),
                    ("Content-Length", "2"),
                ],
            ),
            FakeHttpResponse(
                raw_body=b"{}",
                headers=[
                    ("Bad Header", "x"),
                    ("Content-Type", "application/json; charset=utf-8"),
                    ("Content-Length", "2"),
                ],
            ),
            FakeHttpResponse(raw_body=b'{"v":1,"v":1}'),
            FakeHttpResponse(raw_body=b'{"v":NaN}'),
            FakeHttpResponse(raw_body=b"[]"),
            FakeHttpResponse(raw_body=b"\xff"),
        )
        for response in cases:
            with self.subTest(response=response):
                FakeHttpConnection.instances = []
                FakeHttpConnection.response = response
                transport = ClassroomFileHttpRpcCall(
                    endpoint_url="https://files.example.test/v1/classroom/files",
                    bearer_token_provider=lambda: "token",
                )
                with patch(
                    "acs.classroom_file_http_transport.http.client.HTTPSConnection",
                    FakeHttpConnection,
                ):
                    with self.assertRaises(ClassroomFileHttpClientError):
                        transport.call(
                            {
                                "v": 1,
                                "op": "history",
                                "room_id": ROOM,
                                "participant_id": STUDENT,
                                "after_sequence": None,
                                "limit": 1,
                            }
                        )
                self.assertEqual(1, len(FakeHttpConnection.instances))
                self.assertTrue(FakeHttpConnection.instances[0].closed)

    def test_client_partial_send_reports_only_confirmed_progress(self):
        content = b"abcdef"
        observed = []
        FakeHttpConnection.fail_send_at = 3
        transport = ClassroomFileHttpRpcCall(
            endpoint_url="https://files.example.test/v1/classroom/files",
            bearer_token_provider=lambda: "token",
        )

        with (
            patch(
                "acs.classroom_file_http_transport.http.client.HTTPSConnection",
                FakeHttpConnection,
            ),
            patch(
                "acs.classroom_file_http_transport._UPLOAD_SEND_CHUNK_BYTES",
                2,
            ),
            self.assertRaisesRegex(
                ClassroomFileHttpClientError,
                "transport failed",
            ),
        ):
            transport.call(
                upload_request(content),
                on_upload_progress=observed.append,
            )

        self.assertEqual([0, 2], observed)
        self.assertEqual(
            content[:2],
            b"".join(FakeHttpConnection.instances[0].sent_parts[2:]),
        )
        self.assertTrue(FakeHttpConnection.instances[0].closed)

    def test_client_network_failure_is_sanitized_and_connection_closes(self):
        FakeHttpConnection.fail_send_at = 1
        transport = ClassroomFileHttpRpcCall(
            endpoint_url="https://files.example.test/v1/classroom/files",
            bearer_token_provider=lambda: "token",
        )
        with patch(
            "acs.classroom_file_http_transport.http.client.HTTPSConnection",
            FakeHttpConnection,
        ):
            with self.assertRaisesRegex(
                ClassroomFileHttpClientError,
                "transport failed",
            ) as raised:
                transport.call(upload_request(b"abc"))
        self.assertIsNone(raised.exception.__cause__)
        self.assertNotIn("supersecret", str(raised.exception))
        self.assertTrue(FakeHttpConnection.instances[0].closed)


if __name__ == "__main__":
    unittest.main()
