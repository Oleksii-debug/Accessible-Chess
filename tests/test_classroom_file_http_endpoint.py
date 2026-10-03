from __future__ import annotations

import asyncio
from dataclasses import replace
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from acs.classroom_collaboration import (
    AttachmentHistoryPage,
    FileTransferProgress,
    PreparedFile,
)
from acs.classroom_collaboration_storage import AttachmentMetadata
from acs.classroom_file_http_endpoint import (
    FILE_HTTP_UPLOAD_CHUNK_BYTES,
    FILE_RPC_MEDIA_TYPE,
    FILE_RPC_PATH,
    FRAME_MAGIC,
    MAX_FILE_HTTP_BODY_BYTES,
    ClassroomFileHttpCallTransport,
    ClassroomFileHttpEndpoint,
    ClassroomFileHttpPrincipal,
    encode_file_rpc_http_frame,
)
from acs.classroom_file_rpc import (
    RPC_VERSION,
    ClassroomFileRpcClient,
    ClassroomFileRpcError,
    ClassroomFileRpcService,
)
from acs.classroom_file_server import (
    ClassroomFileServerSQLiteStore,
    ClassroomFileServerService,
)


class FakeAuthenticator:
    def __init__(self):
        self.calls = []
        self.fail = False
        self.principal = ClassroomFileHttpPrincipal("room-1", "student-1")

    async def authenticate_bearer(self, bearer_token):
        self.calls.append(bearer_token)
        if self.fail or bearer_token != "good-token":
            raise RuntimeError("identity provider signing secret")
        return self.principal


class FakeBackend:
    def __init__(self):
        self.upload_calls = []
        self.history_calls = []
        self.fail = False
        self.stored = []

    def upload(self, *, trusted_caller_identity, metadata, content):
        self.upload_calls.append(
            (trusted_caller_identity, metadata, bytes(content))
        )
        if self.fail:
            raise RuntimeError("object storage supersecret")
        result = replace(
            metadata,
            sequence_no=len(self.stored),
            transfer_state="stored",
            scan_state="clean",
        )
        self.stored.append(result)
        return result

    def cancel(
        self,
        *,
        trusted_caller_identity,
        attachment_id,
        expected_room_id=None,
    ):
        if self.fail:
            raise RuntimeError("cancel supersecret")

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
            raise RuntimeError("history supersecret")
        rows = tuple(
            item
            for item in self.stored
            if item.room_id == room_id
            and (after_sequence is None or item.sequence_no > after_sequence)
        )[:limit]
        return AttachmentHistoryPage(rows, None)

    def state_updates_after(
        self,
        *,
        trusted_caller_identity,
        room_id,
        after_revision,
        limit,
    ):
        if self.fail:
            raise RuntimeError("state supersecret")
        return ()

    def issue_read_token(
        self,
        *,
        trusted_caller_identity,
        object_key,
        ttl_seconds,
        expected_room_id=None,
    ):
        if self.fail:
            raise RuntimeError("token supersecret")
        return "read-token"

    def delete_object(
        self,
        *,
        trusted_caller_identity,
        object_key,
        expected_room_id=None,
    ):
        if self.fail:
            raise RuntimeError("delete supersecret")


class StaticBearer:
    def __init__(self, token="good-token"):
        self.token = token
        self.calls = 0
        self.fail = False

    def bearer_token(self):
        self.calls += 1
        if self.fail:
            raise RuntimeError("desktop identity supersecret")
        return self.token


class FakeHttpResponse:
    def __init__(self, *, status, headers, body):
        self.status = status
        self.headers = headers
        self._body = body
        self.read_limits = []

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self, limit=-1):
        self.read_limits.append(limit)
        if limit is None or limit < 0:
            return self._body
        return self._body[:limit]


class StaticOpener:
    def __init__(self, response):
        self.response = response
        self.calls = []
        self.fail = False

    def open(self, request, *, timeout):
        self.calls.append((request, timeout))
        if self.fail:
            raise OSError("network proxy secret")
        return self.response


class AsgiOpener:
    """In-memory urllib-compatible bridge proving desktop -> ASGI composition."""

    def __init__(self, endpoint, *, before_endpoint=None):
        self.endpoint = endpoint
        self.before_endpoint = before_endpoint
        self.calls = []
        self.request_bodies = []

    def open(self, request, *, timeout):
        self.calls.append((request, timeout))
        raw_headers = [
            (
                name.lower().encode("ascii"),
                value.encode("ascii"),
            )
            for name, value in request.header_items()
        ]
        raw_data = request.data or b""
        body = (
            raw_data
            if type(raw_data) is bytes
            else b"".join(raw_data)
        )
        self.request_bodies.append(body)
        if self.before_endpoint is not None:
            self.before_endpoint()
        scope = {
            "type": "http",
            "scheme": "https",
            "http_version": "1.1",
            "method": request.get_method(),
            "path": FILE_RPC_PATH,
            "raw_path": FILE_RPC_PATH.encode("ascii"),
            "query_string": b"",
            "headers": raw_headers,
            "server": ("127.0.0.1", 443),
            "client": ("127.0.0.1", 45000),
        }
        events = [
            {
                "type": "http.request",
                "body": body,
                "more_body": False,
            }
        ]
        sent = []

        async def receive():
            return events.pop(0)

        async def send(event):
            sent.append(event)

        asyncio.run(self.endpoint(scope, receive, send))
        status, raw_response_headers, response_body = response(sent)
        headers = {
            key.decode("ascii").lower(): value.decode("ascii")
            for key, value in raw_response_headers.items()
        }
        return FakeHttpResponse(
            status=status,
            headers=headers,
            body=response_body,
        )


class PartialSendFailureOpener:
    """Consume enough iterable body to prove partial progress, then fail."""

    def __init__(self):
        self.calls = []

    def open(self, request, *, timeout):
        self.calls.append((request, timeout))
        data = request.data
        if type(data) is bytes:
            raise AssertionError("tracked upload must use iterable HTTP body")
        iterator = iter(data)
        # Prefix reports zero; first content chunk is then consumed. Advancing
        # once more records that first chunk before the simulated socket fault.
        next(iterator)
        next(iterator)
        next(iterator)
        raise OSError("network failed after partial upload")


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


def metadata_for(content=b"\x00\xffopaque", *, room_id="room-1"):
    digest = hashlib.sha256(content).hexdigest()
    return AttachmentMetadata(
        attachment_id="att-1",
        room_id=room_id,
        sender_id="student-1",
        sequence_no=0,
        display_name="sample.bin",
        mime_type="application/octet-stream",
        size_bytes=len(content),
        sha256=digest,
        object_key=f"rooms/{room_id}/att-1",
        transfer_state="pending",
        retention="session",
        scan_state="pending",
    )


def wire(metadata):
    return {
        "attachment_id": metadata.attachment_id,
        "room_id": metadata.room_id,
        "sender_id": metadata.sender_id,
        "sequence_no": metadata.sequence_no,
        "display_name": metadata.display_name,
        "mime_type": metadata.mime_type,
        "size_bytes": metadata.size_bytes,
        "sha256": metadata.sha256,
        "object_key": metadata.object_key,
        "transfer_state": metadata.transfer_state,
        "retention": metadata.retention,
        "scan_state": metadata.scan_state,
    }


def upload_request(content=b"\x00\xffopaque", *, room_id="room-1"):
    metadata = metadata_for(content, room_id=room_id)
    return {
        "v": RPC_VERSION,
        "op": "upload",
        "room_id": room_id,
        "participant_id": "student-1",
        "metadata": wire(metadata),
        "content": content,
    }


async def invoke(
    endpoint,
    body,
    *,
    token="good-token",
    scheme="https",
    path=FILE_RPC_PATH,
    raw_path=None,
    method="POST",
    query=b"",
    content_type=FILE_RPC_MEDIA_TYPE,
    declared_length=True,
    extra_headers=(),
    chunks=None,
):
    headers = []
    if content_type is not None:
        headers.append((b"content-type", content_type.encode("ascii")))
    if token is not None:
        headers.append((b"authorization", f"Bearer {token}".encode("ascii")))
    if declared_length is True:
        headers.append((b"content-length", str(len(body)).encode("ascii")))
    elif type(declared_length) is bytes:
        headers.append((b"content-length", declared_length))
    headers.extend(extra_headers)
    scope = {
        "type": "http",
        "scheme": scheme,
        "http_version": "1.1",
        "method": method,
        "path": path,
        "raw_path": (
            path.encode("ascii") if raw_path is None else raw_path
        ),
        "query_string": query,
        "headers": headers,
        "server": ("127.0.0.1", 443 if scheme == "https" else 8080),
        "client": ("127.0.0.1", 45000),
    }
    events = []
    if chunks is None:
        events.append(
            {"type": "http.request", "body": body, "more_body": False}
        )
    else:
        for index, chunk in enumerate(chunks):
            events.append(
                {
                    "type": "http.request",
                    "body": chunk,
                    "more_body": index + 1 < len(chunks),
                }
            )
    sent = []

    async def receive():
        if not events:
            raise AssertionError("endpoint read beyond request")
        return events.pop(0)

    async def send(event):
        sent.append(event)

    await endpoint(scope, receive, send)
    return sent, events


def run(*args, **kwargs):
    return asyncio.run(invoke(*args, **kwargs))


def response(sent):
    starts = [event for event in sent if event["type"] == "http.response.start"]
    bodies = [event for event in sent if event["type"] == "http.response.body"]
    if not starts:
        return None, {}, b""
    headers = dict(starts[0]["headers"])
    return starts[0]["status"], headers, b"".join(
        event.get("body", b"") for event in bodies
    )


class ClassroomFileHttpEndpointTests(unittest.TestCase):
    def setUp(self):
        self.backend = FakeBackend()
        self.rpc = ClassroomFileRpcService(backend=self.backend)
        self.auth = FakeAuthenticator()
        self.endpoint = ClassroomFileHttpEndpoint(
            service=self.rpc,
            authenticator=self.auth,
        )

    def test_concrete_desktop_http_transport_composes_with_rpc_client_and_endpoint(self):
        bearer = StaticBearer()
        samples = []
        content = b"\x00\xffdesktop to HTTPS to RPC"

        def assert_progress_precedes_server_response():
            self.assertEqual(
                samples,
                [
                    FileTransferProgress("att-1", 0, len(content)),
                    FileTransferProgress(
                        "att-1",
                        len(content),
                        len(content),
                    ),
                ],
            )
            self.assertTrue(all(not sample.complete for sample in samples))
            self.assertEqual(self.backend.upload_calls, [])

        opener = AsgiOpener(
            self.endpoint,
            before_endpoint=assert_progress_precedes_server_response,
        )
        transport = ClassroomFileHttpCallTransport(
            endpoint_url="https://127.0.0.1/v1/classroom/file-rpc",
            bearer=bearer,
            opener=opener,
        )
        client = ClassroomFileRpcClient(
            room_id="room-1",
            participant_id="student-1",
            transport=transport,
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "opaque.bin"
            path.write_bytes(content)
            metadata = metadata_for(content)
            prepared = PreparedFile(path, metadata)
            stored = client.upload(prepared, on_progress=samples.append)

        self.assertEqual(stored.transfer_state, "stored")
        self.assertEqual(self.backend.upload_calls[-1][2], content)
        self.assertEqual(
            samples,
            [
                FileTransferProgress("att-1", 0, len(content)),
                FileTransferProgress(
                    "att-1",
                    len(content),
                    len(content),
                ),
            ],
        )
        self.assertEqual(bearer.calls, 1)
        request, timeout = opener.calls[0]
        self.assertEqual(timeout, 30.0)
        self.assertEqual(
            request.get_header("Authorization"),
            "Bearer good-token",
        )
        self.assertEqual(request.get_method(), "POST")
        self.assertTrue(opener.request_bodies[0].startswith(FRAME_MAGIC))
        self.assertTrue(opener.request_bodies[0].endswith(content))
        self.assertNotIn("Transfer-encoding", dict(request.header_items()))
        self.assertEqual(
            int(request.get_header("Content-length")),
            len(opener.request_bodies[0]),
        )
        self.assertNotIn("good-token", repr(transport))

    def test_desktop_http_progress_tracks_multiple_file_chunks_before_response(self):
        total = FILE_HTTP_UPLOAD_CHUNK_BYTES * 2 + 17
        content = bytes((index % 251 for index in range(total)))
        samples = []

        def assert_progress_precedes_server_response():
            self.assertEqual(
                [sample.transferred_bytes for sample in samples],
                [
                    0,
                    FILE_HTTP_UPLOAD_CHUNK_BYTES,
                    FILE_HTTP_UPLOAD_CHUNK_BYTES * 2,
                    total,
                ],
            )
            self.assertEqual(self.backend.upload_calls, [])

        opener = AsgiOpener(
            self.endpoint,
            before_endpoint=assert_progress_precedes_server_response,
        )
        client = ClassroomFileRpcClient(
            room_id="room-1",
            participant_id="student-1",
            transport=ClassroomFileHttpCallTransport(
                endpoint_url="https://127.0.0.1/v1/classroom/file-rpc",
                bearer=StaticBearer(),
                opener=opener,
            ),
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "large.bin"
            path.write_bytes(content)
            prepared = PreparedFile(path, metadata_for(content))
            stored = client.upload(prepared, on_progress=samples.append)

        self.assertEqual(stored.transfer_state, "stored")
        self.assertEqual(self.backend.upload_calls[-1][2], content)
        self.assertEqual(
            [sample.transferred_bytes for sample in samples],
            [
                0,
                FILE_HTTP_UPLOAD_CHUNK_BYTES,
                FILE_HTTP_UPLOAD_CHUNK_BYTES * 2,
                total,
            ],
        )
        self.assertTrue(all(not sample.complete for sample in samples))

    def test_partial_http_send_reports_partial_progress_then_fails_safely(self):
        total = FILE_HTTP_UPLOAD_CHUNK_BYTES * 2 + 17
        content = b"x" * total
        samples = []
        client = ClassroomFileRpcClient(
            room_id="room-1",
            participant_id="student-1",
            transport=ClassroomFileHttpCallTransport(
                endpoint_url="https://127.0.0.1/v1/classroom/file-rpc",
                bearer=StaticBearer(),
                opener=PartialSendFailureOpener(),
            ),
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "partial.bin"
            path.write_bytes(content)
            prepared = PreparedFile(path, metadata_for(content))
            with self.assertRaisesRegex(
                ClassroomFileRpcError,
                "HTTP request failed",
            ):
                client.upload(prepared, on_progress=samples.append)

        self.assertEqual(
            [sample.transferred_bytes for sample in samples],
            [0, FILE_HTTP_UPLOAD_CHUNK_BYTES],
        )
        self.assertTrue(all(not sample.complete for sample in samples))
        self.assertEqual(self.backend.upload_calls, [])

    def test_desktop_transport_url_policy_rejects_credentials_queries_and_remote_http(self):
        bearer = StaticBearer()
        safe_response = FakeHttpResponse(
            status=200,
            headers={
                "content-type": "application/json; charset=utf-8",
                "content-length": "19",
                "cache-control": "no-store",
            },
            body=b'{"v":1,"ok":true}',
        )
        opener = StaticOpener(safe_response)
        invalid = (
            "http://example.com/v1/classroom/file-rpc",
            "https://user:pass@example.com/v1/classroom/file-rpc",
            "https://example.com/v1/classroom/file-rpc?token=x",
            "https://example.com/v1/classroom/file-rpc#fragment",
            "https://example.com/wrong",
        )
        for url in invalid:
            with self.subTest(url=url):
                with self.assertRaises(ValueError):
                    ClassroomFileHttpCallTransport(
                        endpoint_url=url,
                        bearer=bearer,
                        opener=opener,
                    )

        local = ClassroomFileHttpCallTransport(
            endpoint_url="http://127.0.0.1/v1/classroom/file-rpc",
            bearer=bearer,
            opener=opener,
            allow_insecure_loopback=True,
        )
        self.assertIn("127.0.0.1", repr(local))

    def test_desktop_transport_rejects_bad_or_unavailable_bearer_before_network(self):
        response_ok = FakeHttpResponse(
            status=200,
            headers={
                "content-type": "application/json",
                "content-length": "19",
                "cache-control": "no-store",
            },
            body=b'{"v":1,"ok":true}',
        )
        opener = StaticOpener(response_ok)
        for token in ("", "has space", "line\nbreak", "ümlaut"):
            bearer = StaticBearer(token)
            transport = ClassroomFileHttpCallTransport(
                endpoint_url="https://example.com/v1/classroom/file-rpc",
                bearer=bearer,
                opener=opener,
            )
            with self.subTest(token=token):
                with self.assertRaises(ClassroomFileRpcError):
                    transport.call(
                        {
                            "v": 1,
                            "op": "cancel",
                            "room_id": "room-1",
                            "participant_id": "student-1",
                            "attachment_id": "att-1",
                        }
                    )
        failing = StaticBearer()
        failing.fail = True
        transport = ClassroomFileHttpCallTransport(
            endpoint_url="https://example.com/v1/classroom/file-rpc",
            bearer=failing,
            opener=opener,
        )
        with self.assertRaisesRegex(
            ClassroomFileRpcError,
            "authentication unavailable",
        ):
            transport.call(
                {
                    "v": 1,
                    "op": "cancel",
                    "room_id": "room-1",
                    "participant_id": "student-1",
                    "attachment_id": "att-1",
                }
            )
        self.assertEqual(opener.calls, [])

    def test_desktop_transport_validates_privacy_headers_length_status_and_json(self):
        bearer = StaticBearer()
        request = {
            "v": 1,
            "op": "cancel",
            "room_id": "room-1",
            "participant_id": "student-1",
            "attachment_id": "att-1",
        }
        cases = (
            FakeHttpResponse(
                status=302,
                headers={
                    "content-type": "application/json",
                    "content-length": "2",
                    "cache-control": "no-store",
                },
                body=b"{}",
            ),
            FakeHttpResponse(
                status=200,
                headers={
                    "content-type": "text/plain",
                    "content-length": "2",
                    "cache-control": "no-store",
                },
                body=b"{}",
            ),
            FakeHttpResponse(
                status=200,
                headers={
                    "content-type": "application/json",
                    "content-length": "2",
                    "cache-control": "private",
                },
                body=b"{}",
            ),
            FakeHttpResponse(
                status=200,
                headers={
                    "content-type": "application/json",
                    "content-length": "3",
                    "cache-control": "no-store",
                },
                body=b"{}",
            ),
            FakeHttpResponse(
                status=200,
                headers={
                    "content-type": "application/json",
                    "content-length": "7",
                    "cache-control": "no-store",
                },
                body=b'{"a":1,',
            ),
        )
        for response_value in cases:
            transport = ClassroomFileHttpCallTransport(
                endpoint_url="https://example.com/v1/classroom/file-rpc",
                bearer=bearer,
                opener=StaticOpener(response_value),
            )
            with self.subTest(status=response_value.status, headers=response_value.headers):
                with self.assertRaises(ClassroomFileRpcError):
                    transport.call(request)

    def test_desktop_transport_network_failure_is_sanitized(self):
        bearer = StaticBearer()
        opener = StaticOpener(
            FakeHttpResponse(
                status=200,
                headers={},
                body=b"",
            )
        )
        opener.fail = True
        transport = ClassroomFileHttpCallTransport(
            endpoint_url="https://example.com/v1/classroom/file-rpc",
            bearer=bearer,
            opener=opener,
        )
        with self.assertRaises(ClassroomFileRpcError) as caught:
            transport.call(
                {
                    "v": 1,
                    "op": "cancel",
                    "room_id": "room-1",
                    "participant_id": "student-1",
                    "attachment_id": "att-1",
                }
            )
        self.assertNotIn("proxy secret", str(caught.exception))
        self.assertIsNone(caught.exception.__cause__)

    def test_secure_upload_authenticates_and_preserves_arbitrary_binary(self):
        content = b"\x00\x01\xfe\xff\nopaque binary"
        frame = encode_file_rpc_http_frame(upload_request(content))
        self.assertTrue(frame.startswith(FRAME_MAGIC))
        self.assertTrue(frame.endswith(content))
        self.assertNotIn(content.hex().encode("ascii"), frame)

        sent, _ = run(self.endpoint, frame)
        status, headers, body = response(sent)
        self.assertEqual(status, 200)
        self.assertEqual(self.auth.calls, ["good-token"])
        self.assertEqual(self.backend.upload_calls[0][2], content)
        payload = json.loads(body)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["attachment"]["transfer_state"], "stored")
        self.assertEqual(headers[b"cache-control"], b"no-store")
        self.assertEqual(headers[b"x-content-type-options"], b"nosniff")

    def test_chunked_asgi_delivery_reassembles_exact_frame_without_transfer_encoding(self):
        content = b"abcdef" * 100
        frame = encode_file_rpc_http_frame(upload_request(content))
        chunks = [frame[:3], frame[3:19], frame[19:70], frame[70:]]
        sent, _ = run(self.endpoint, frame, chunks=chunks)
        status, _, _ = response(sent)
        self.assertEqual(status, 200)
        self.assertEqual(self.backend.upload_calls[0][2], content)

    def test_authentication_failure_happens_before_body_read_or_rpc_effect(self):
        frame = encode_file_rpc_http_frame(upload_request())
        self.auth.fail = True
        sent, unread = run(self.endpoint, frame)
        status, headers, body = response(sent)
        self.assertEqual(status, 401)
        self.assertIn(b"www-authenticate", headers)
        self.assertEqual(json.loads(body), {"error": "unauthorized"})
        self.assertEqual(len(unread), 1)
        self.assertEqual(self.backend.upload_calls, [])
        self.assertNotIn(b"supersecret", body)

    def test_authenticated_principal_is_independent_of_payload_identity(self):
        frame = encode_file_rpc_http_frame(upload_request(room_id="room-2"))
        sent, _ = run(self.endpoint, frame)
        status, _, body = response(sent)
        self.assertEqual(status, 403)
        self.assertEqual(
            json.loads(body),
            {"error": "authenticated_identity_mismatch"},
        )
        self.assertEqual(self.backend.upload_calls, [])

    def test_remote_plain_http_is_rejected_and_explicit_loopback_mode_is_narrow(self):
        frame = encode_file_rpc_http_frame(upload_request())
        sent, unread = run(self.endpoint, frame, scheme="http")
        self.assertEqual(response(sent)[0], 400)
        self.assertEqual(len(unread), 1)

        dev = ClassroomFileHttpEndpoint(
            service=self.rpc,
            authenticator=self.auth,
            allow_insecure_loopback=True,
        )
        sent, _ = run(dev, frame, scheme="http")
        self.assertEqual(response(sent)[0], 200)

    def test_route_method_query_and_content_type_fail_before_authentication(self):
        frame = encode_file_rpc_http_frame(upload_request())
        cases = (
            {"path": "/v1/other"},
            {"raw_path": b"/v1/classroom/file-rpc%2f"},
            {"method": "GET"},
            {"query": b"token=secret"},
            {"content_type": "application/json"},
        )
        for options in cases:
            self.auth.calls.clear()
            with self.subTest(options=options):
                sent, _ = run(self.endpoint, frame, **options)
                self.assertIn(response(sent)[0], {400, 404, 405, 415})
                self.assertEqual(self.auth.calls, [])

    def test_duplicate_authorization_and_transport_encoding_are_rejected(self):
        frame = encode_file_rpc_http_frame(upload_request())
        cases = (
            ((b"authorization", b"Bearer second"),),
            ((b"content-encoding", b"gzip"),),
            ((b"transfer-encoding", b"chunked"),),
        )
        for extra in cases:
            self.auth.calls.clear()
            with self.subTest(extra=extra):
                sent, _ = run(self.endpoint, frame, extra_headers=extra)
                self.assertIn(response(sent)[0], {400, 415})
                self.assertEqual(self.auth.calls, [])

    def test_declared_length_mismatch_is_generic_and_has_no_backend_effect(self):
        frame = encode_file_rpc_http_frame(upload_request())
        sent, _ = run(
            self.endpoint,
            frame,
            declared_length=str(len(frame) + 1).encode("ascii"),
        )
        status, _, body = response(sent)
        self.assertEqual(status, 400)
        self.assertEqual(json.loads(body), {"error": "content_length_mismatch"})
        self.assertEqual(self.backend.upload_calls, [])

    def test_attacker_sized_content_length_is_rejected_before_authentication(self):
        frame = encode_file_rpc_http_frame(upload_request())
        self.auth.calls.clear()
        sent, unread = run(
            self.endpoint,
            frame,
            declared_length=str(MAX_FILE_HTTP_BODY_BYTES + 1).encode("ascii"),
        )
        self.assertEqual(response(sent)[0], 413)
        self.assertEqual(self.auth.calls, [])
        self.assertEqual(len(unread), 1)

    def test_frame_rejects_bad_magic_truncation_duplicate_keys_and_binary_on_nonupload(self):
        good = encode_file_rpc_http_frame(upload_request())
        duplicate_json = (
            b'{"v":1,"v":1,"op":"history","room_id":"room-1",'
            b'"participant_id":"student-1","after_sequence":null,"limit":1}'
        )
        duplicate = (
            FRAME_MAGIC
            + len(duplicate_json).to_bytes(4, "big")
            + duplicate_json
        )
        nonupload_json = (
            b'{"v":1,"op":"history","room_id":"room-1",'
            b'"participant_id":"student-1","after_sequence":null,"limit":1}'
        )
        nonupload_binary = (
            FRAME_MAGIC
            + len(nonupload_json).to_bytes(4, "big")
            + nonupload_json
            + b"x"
        )
        for frame in (
            b"BADMAGIC" + good[8:],
            good[:10],
            duplicate,
            nonupload_binary,
        ):
            with self.subTest(frame=frame[:30]):
                sent, _ = run(self.endpoint, frame)
                self.assertEqual(response(sent)[0], 400)
        self.assertEqual(self.backend.upload_calls, [])

    def test_upload_frame_requires_binary_length_to_match_metadata(self):
        request = upload_request(b"abcdef")
        frame = encode_file_rpc_http_frame(request)
        for malformed in (frame[:-1], frame + b"x"):
            with self.subTest(length=len(malformed)):
                sent, _ = run(self.endpoint, malformed)
                self.assertEqual(response(sent)[0], 400)
        self.assertEqual(self.backend.upload_calls, [])

    def test_nonupload_history_round_trip_has_no_binary_body(self):
        self.backend.stored.append(
            replace(
                metadata_for(b"abc"),
                transfer_state="stored",
                scan_state="clean",
            )
        )
        request = {
            "v": RPC_VERSION,
            "op": "history",
            "room_id": "room-1",
            "participant_id": "student-1",
            "after_sequence": None,
            "limit": 10,
        }
        frame = encode_file_rpc_http_frame(request)
        sent, _ = run(self.endpoint, frame)
        status, _, body = response(sent)
        self.assertEqual(status, 200)
        payload = json.loads(body)
        self.assertEqual(len(payload["attachments"]), 1)
        self.assertIsNone(payload["snapshot_state_revision"])

    def test_rpc_backend_failure_maps_to_retryable_generic_503_without_secret(self):
        self.backend.fail = True
        frame = encode_file_rpc_http_frame(upload_request())
        sent, _ = run(self.endpoint, frame)
        status, _, body = response(sent)
        self.assertEqual(status, 503)
        self.assertEqual(
            json.loads(body),
            {"error": "file_service_unavailable"},
        )
        self.assertNotIn(b"supersecret", body)

    def test_malformed_authenticated_rpc_maps_to_generic_400(self):
        request = {
            "v": RPC_VERSION,
            "op": "history",
            "room_id": "room-1",
            "participant_id": "student-1",
            "after_sequence": True,
            "limit": 1,
        }
        sent, _ = run(
            self.endpoint,
            encode_file_rpc_http_frame(request),
        )
        status, _, body = response(sent)
        self.assertEqual(status, 400)
        self.assertEqual(json.loads(body), {"error": "file_request_rejected"})

    def test_disconnect_emits_no_partial_response(self):
        frame = encode_file_rpc_http_frame(upload_request())
        scope = {
            "type": "http",
            "scheme": "https",
            "http_version": "1.1",
            "method": "POST",
            "path": FILE_RPC_PATH,
            "raw_path": FILE_RPC_PATH.encode("ascii"),
            "query_string": b"",
            "headers": [
                (b"content-type", FILE_RPC_MEDIA_TYPE.encode("ascii")),
                (b"authorization", b"Bearer good-token"),
            ],
            "server": ("127.0.0.1", 443),
            "client": ("127.0.0.1", 45000),
        }
        events = [{"type": "http.disconnect"}]
        sent = []

        async def receive():
            return events.pop(0)

        async def send(event):
            sent.append(event)

        asyncio.run(self.endpoint(scope, receive, send))
        self.assertEqual(sent, [])
        self.assertEqual(self.backend.upload_calls, [])
        self.assertEqual(frame[:8], FRAME_MAGIC)

    def test_lifespan_does_not_open_auth_or_file_authority(self):
        events = [
            {"type": "lifespan.startup"},
            {"type": "lifespan.shutdown"},
        ]
        sent = []

        async def receive():
            return events.pop(0)

        async def send(event):
            sent.append(event)

        asyncio.run(
            self.endpoint(
                {"type": "lifespan"},
                receive,
                send,
            )
        )
        self.assertEqual(
            sent,
            [
                {"type": "lifespan.startup.complete"},
                {"type": "lifespan.shutdown.complete"},
            ],
        )
        self.assertEqual(self.auth.calls, [])
        self.assertEqual(self.backend.upload_calls, [])

    def test_full_https_to_rpc_to_trusted_sqlite_object_store_round_trip(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            objects = MemoryObjectStore()
            server = ClassroomFileServerService(
                store=ClassroomFileServerSQLiteStore(
                    str(Path(temp_dir) / "files.sqlite3")
                ),
                authorization=AllowMembers({("student-1", "room-1")}),
                scanner=CleanScanner(),
                object_store=objects,
            )
            endpoint = ClassroomFileHttpEndpoint(
                service=ClassroomFileRpcService(backend=server),
                authenticator=self.auth,
            )
            content = b"\x00\xfffull stack arbitrary bytes"
            upload = upload_request(content)
            sent, _ = run(
                endpoint,
                encode_file_rpc_http_frame(upload),
            )
            status, _, body = response(sent)
            self.assertEqual(status, 200)
            stored = json.loads(body)["attachment"]
            self.assertEqual(stored["transfer_state"], "stored")
            self.assertEqual(objects.objects[stored["object_key"]], content)

            history = {
                "v": RPC_VERSION,
                "op": "history",
                "room_id": "room-1",
                "participant_id": "student-1",
                "after_sequence": None,
                "limit": 10,
            }
            sent, _ = run(
                endpoint,
                encode_file_rpc_http_frame(history),
            )
            payload = json.loads(response(sent)[2])
            self.assertEqual(payload["attachments"], [stored])

    def test_repr_and_errors_never_render_credentials(self):
        value = repr(self.endpoint)
        self.assertNotIn("good-token", value)
        self.assertNotIn("supersecret", value)
        self.assertIn("service=<bound>", value)
        frame = encode_file_rpc_http_frame(upload_request())
        sent, _ = run(self.endpoint, frame, token="wrong-secret-token")
        self.assertNotIn(b"wrong-secret-token", response(sent)[2])

    def test_constructor_and_principal_are_strict(self):
        with self.assertRaises(TypeError):
            ClassroomFileHttpEndpoint(
                service=object(),
                authenticator=self.auth,
            )
        with self.assertRaises(TypeError):
            ClassroomFileHttpEndpoint(
                service=self.rpc,
                authenticator=object(),
            )
        with self.assertRaises(TypeError):
            ClassroomFileHttpEndpoint(
                service=self.rpc,
                authenticator=self.auth,
                allow_insecure_loopback=1,
            )
        with self.assertRaises(Exception):
            ClassroomFileHttpPrincipal("../room", "student-1")


if __name__ == "__main__":
    unittest.main()
