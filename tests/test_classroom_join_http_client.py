from __future__ import annotations

import json
import unittest
from unittest import mock

from acs.classroom_join_http_client import (
    ClassroomJoinHttpClient,
    ClassroomJoinHttpClientError,
)
from acs.classroom_join_http_endpoint import JOIN_CREDENTIAL_PATH
from acs.classroom_realtime_media import JoinCredential


def response_body(
    *,
    room_id: str = "room-1",
    participant_id: str = "student-1",
    token: str = "provider-token-1",
    issued_at: str = "2026-10-03T00:30:00Z",
    expires_at: str = "2026-10-03T00:31:00Z",
) -> bytes:
    return json.dumps(
        {
            "version": 1,
            "room_id": room_id,
            "participant_id": participant_id,
            "token": token,
            "issued_at": issued_at,
            "expires_at": expires_at,
        },
        separators=(",", ":"),
    ).encode("utf-8")


class FakeResponse:
    def __init__(
        self,
        body: bytes,
        *,
        status: int = 200,
        headers: list[tuple[str, str]] | None = None,
    ) -> None:
        self.status = status
        self.body = body
        self.headers = headers or [
            ("Content-Type", "application/json; charset=utf-8"),
            ("Content-Length", str(len(body))),
            ("Cache-Control", "no-store"),
            ("Pragma", "no-cache"),
            ("X-Content-Type-Options", "nosniff"),
        ]

    def getheaders(self):
        return list(self.headers)

    def read(self, limit: int):
        return self.body[:limit]


class FakeConnection:
    responses: list[FakeResponse] = []
    instances: list["FakeConnection"] = []

    def __init__(self, host: str, port: int, timeout: float) -> None:
        self.host = host
        self.port = port
        self.timeout = timeout
        self.request = None
        self.headers: list[tuple[str, str]] = []
        self.parts: list[bytes] = []
        self.closed = False
        type(self).instances.append(self)

    def putrequest(self, method: str, target: str, **kwargs) -> None:
        self.request = (method, target, kwargs)

    def putheader(self, name: str, value: str) -> None:
        self.headers.append((name, value))

    def endheaders(self) -> None:
        return None

    def send(self, data) -> None:
        self.parts.append(bytes(data))

    def getresponse(self):
        if not type(self).responses:
            raise AssertionError("no fake join response configured")
        return type(self).responses.pop(0)

    def close(self) -> None:
        self.closed = True


class ClassroomJoinHttpClientTests(unittest.TestCase):
    def setUp(self) -> None:
        FakeConnection.responses = []
        FakeConnection.instances = []
        self.token_calls = 0

    def bearer(self) -> str:
        self.token_calls += 1
        return f"account-bearer-{self.token_calls}"

    def client(self, **overrides) -> ClassroomJoinHttpClient:
        values = {
            "endpoint_url": "https://classroom.example/v1/classroom/join-credential",
            "bearer_token_provider": self.bearer,
        }
        values.update(overrides)
        return ClassroomJoinHttpClient(**values)

    def issue(self, client: ClassroomJoinHttpClient | None = None) -> JoinCredential:
        target = client or self.client()
        with mock.patch(
            "acs.classroom_join_http_client.http.client.HTTPSConnection",
            FakeConnection,
        ):
            return target.issue(room_id="room-1", participant_id="student-1")

    def test_success_sends_exact_request_and_returns_canonical_credential(self) -> None:
        FakeConnection.responses.append(FakeResponse(response_body()))
        client = self.client()

        credential = self.issue(client)

        self.assertIsInstance(credential, JoinCredential)
        self.assertEqual(credential.room_id, "room-1")
        self.assertEqual(credential.participant_id, "student-1")
        self.assertEqual(credential.token, "provider-token-1")
        self.assertEqual(self.token_calls, 1)
        self.assertEqual(len(FakeConnection.instances), 1)

        connection = FakeConnection.instances[0]
        self.assertEqual(connection.host, "classroom.example")
        self.assertEqual(connection.port, 443)
        self.assertEqual(connection.timeout, 15.0)
        self.assertEqual(
            connection.request,
            ("POST", JOIN_CREDENTIAL_PATH, {"skip_accept_encoding": True}),
        )
        headers = dict(connection.headers)
        self.assertEqual(headers["Authorization"], "Bearer account-bearer-1")
        self.assertEqual(headers["Content-Type"], "application/json; charset=utf-8")
        self.assertEqual(headers["Accept"], "application/json")
        self.assertTrue(connection.closed)

        wire = b"".join(connection.parts)
        payload = json.loads(wire.decode("utf-8"))
        self.assertEqual(
            payload,
            {
                "version": 1,
                "room_id": "room-1",
                "participant_id": "student-1",
            },
        )
        self.assertNotIn(b"account-bearer", wire)
        self.assertNotIn(b"provider-token", wire)
        rendered = repr(client)
        self.assertNotIn("account-bearer", rendered)
        self.assertEqual(
            rendered,
            "ClassroomJoinHttpClient("
            "scheme='https', host='classroom.example', port=443, "
            "bearer_token_provider=<bound>)",
        )

    def test_bearer_is_fetched_fresh_for_each_join_request(self) -> None:
        FakeConnection.responses.extend(
            [
                FakeResponse(response_body(token="provider-token-1")),
                FakeResponse(response_body(token="provider-token-2")),
            ]
        )
        client = self.client()
        with mock.patch(
            "acs.classroom_join_http_client.http.client.HTTPSConnection",
            FakeConnection,
        ):
            first = client.issue(room_id="room-1", participant_id="student-1")
            second = client.issue(room_id="room-1", participant_id="student-1")

        self.assertEqual(first.token, "provider-token-1")
        self.assertEqual(second.token, "provider-token-2")
        self.assertEqual(self.token_calls, 2)
        self.assertEqual(
            [dict(item.headers)["Authorization"] for item in FakeConnection.instances],
            ["Bearer account-bearer-1", "Bearer account-bearer-2"],
        )
        self.assertTrue(all(item.closed for item in FakeConnection.instances))

    def test_invalid_request_identity_is_rejected_before_bearer_or_connection(self) -> None:
        client = self.client()
        invalid = (
            ("bad room", "student-1"),
            ("/room", "student-1"),
            ("room-1", "bad participant"),
            ("room-1", ""),
            ("room-1", 7),
        )
        with mock.patch(
            "acs.classroom_join_http_client.http.client.HTTPSConnection",
            FakeConnection,
        ):
            for room_id, participant_id in invalid:
                with self.subTest(room_id=room_id, participant_id=participant_id):
                    with self.assertRaisesRegex(
                        ClassroomJoinHttpClientError,
                        "^join credential request (room|participant) id is invalid$",
                    ):
                        client.issue(
                            room_id=room_id,
                            participant_id=participant_id,
                        )
        self.assertEqual(self.token_calls, 0)
        self.assertEqual(FakeConnection.instances, [])

    def test_remote_plain_http_is_rejected_before_bearer_or_connection(self) -> None:
        with self.assertRaisesRegex(ValueError, "must use HTTPS"):
            self.client(
                endpoint_url="http://classroom.example/v1/classroom/join-credential",
                allow_insecure_loopback=True,
            )
        self.assertEqual(self.token_calls, 0)
        self.assertEqual(FakeConnection.instances, [])

    def test_explicit_literal_loopback_http_uses_http_connection(self) -> None:
        FakeConnection.responses.append(FakeResponse(response_body()))
        client = self.client(
            endpoint_url="http://127.0.0.1/v1/classroom/join-credential",
            allow_insecure_loopback=True,
        )
        with mock.patch(
            "acs.classroom_join_http_client.http.client.HTTPConnection",
            FakeConnection,
        ):
            credential = client.issue(room_id="room-1", participant_id="student-1")
        self.assertEqual(credential.room_id, "room-1")
        self.assertEqual(FakeConnection.instances[0].host, "127.0.0.1")
        self.assertEqual(FakeConnection.instances[0].port, 80)
        self.assertTrue(FakeConnection.instances[0].closed)

    def test_endpoint_rejects_userinfo_query_fragment_and_hostname_loopback(self) -> None:
        values = (
            "https://user@classroom.example/v1/classroom/join-credential",
            "https://classroom.example/v1/classroom/join-credential?token=x",
            "https://classroom.example/v1/classroom/join-credential#x",
            "https://classroom.example/wrong",
            "http://localhost/v1/classroom/join-credential",
        )
        for value in values:
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    self.client(
                        endpoint_url=value,
                        allow_insecure_loopback=True,
                    )
        self.assertEqual(self.token_calls, 0)

    def test_bearer_provider_failure_and_invalid_token_are_sanitized(self) -> None:
        def broken():
            raise RuntimeError("private token secret=do-not-leak")

        client = self.client(bearer_token_provider=broken)
        with self.assertRaisesRegex(
            ClassroomJoinHttpClientError,
            "^join authentication credential is unavailable$",
        ) as raised:
            self.issue(client)
        self.assertIsNone(raised.exception.__cause__)
        self.assertNotIn("do-not-leak", str(raised.exception))

        for value in ("", " token", "token ", "token with space", "токен"):
            with self.subTest(value=value):
                client = self.client(bearer_token_provider=lambda v=value: v)
                with self.assertRaisesRegex(
                    ClassroomJoinHttpClientError,
                    "^join authentication credential is invalid$",
                ):
                    self.issue(client)

    def test_response_identity_mismatch_is_rejected_after_connection_close(self) -> None:
        FakeConnection.responses.append(
            FakeResponse(response_body(room_id="other-room"))
        )
        with self.assertRaisesRegex(
            ClassroomJoinHttpClientError,
            "identity does not match request",
        ):
            self.issue()
        self.assertTrue(FakeConnection.instances[0].closed)

    def test_response_requires_privacy_and_framing_headers(self) -> None:
        base_body = response_body()
        bad_headers = (
            [
                ("Content-Type", "application/json; charset=utf-8"),
                ("Content-Length", str(len(base_body))),
                ("Pragma", "no-cache"),
                ("X-Content-Type-Options", "nosniff"),
            ],
            [
                ("Content-Type", "application/json; charset=utf-8"),
                ("Content-Length", str(len(base_body))),
                ("Cache-Control", "no-store"),
                ("Pragma", "no-cache"),
                ("X-Content-Type-Options", "nosniff"),
                ("Content-Encoding", "gzip"),
            ],
            [
                ("Content-Type", "text/plain"),
                ("Content-Length", str(len(base_body))),
                ("Cache-Control", "no-store"),
                ("Pragma", "no-cache"),
                ("X-Content-Type-Options", "nosniff"),
            ],
        )
        for headers in bad_headers:
            with self.subTest(headers=headers):
                FakeConnection.responses.append(
                    FakeResponse(base_body, headers=headers)
                )
                with self.assertRaises(ClassroomJoinHttpClientError):
                    self.issue()
        self.assertTrue(all(item.closed for item in FakeConnection.instances))

    def test_non_200_and_body_length_mismatch_fail_closed(self) -> None:
        body = response_body()
        FakeConnection.responses.append(FakeResponse(body, status=401))
        with self.assertRaisesRegex(
            ClassroomJoinHttpClientError,
            "request was rejected",
        ):
            self.issue()

        headers = [
            ("Content-Type", "application/json; charset=utf-8"),
            ("Content-Length", str(len(body) + 1)),
            ("Cache-Control", "no-store"),
            ("Pragma", "no-cache"),
            ("X-Content-Type-Options", "nosniff"),
        ]
        FakeConnection.responses.append(FakeResponse(body, headers=headers))
        with self.assertRaisesRegex(
            ClassroomJoinHttpClientError,
            "response body is invalid",
        ):
            self.issue()

    def test_duplicate_json_and_noncanonical_timestamp_fail_closed(self) -> None:
        duplicate = (
            b'{"version":1,"room_id":"room-1","room_id":"room-1",'
            b'"participant_id":"student-1","token":"provider-token-1",'
            b'"issued_at":"2026-10-03T00:30:00Z",'
            b'"expires_at":"2026-10-03T00:31:00Z"}'
        )
        FakeConnection.responses.append(FakeResponse(duplicate))
        with self.assertRaisesRegex(
            ClassroomJoinHttpClientError,
            "response JSON is invalid",
        ):
            self.issue()

        FakeConnection.responses.append(
            FakeResponse(
                response_body(issued_at="2026-10-03T00:30:00+00:00")
            )
        )
        with self.assertRaisesRegex(
            ClassroomJoinHttpClientError,
            "issued_at is invalid",
        ):
            self.issue()

    def test_invalid_credential_ttl_is_rejected_without_token_leak(self) -> None:
        secret = "provider-super-secret"
        FakeConnection.responses.append(
            FakeResponse(
                response_body(
                    token=secret,
                    expires_at="2026-10-03T01:00:01Z",
                )
            )
        )
        with self.assertRaisesRegex(
            ClassroomJoinHttpClientError,
            "^join credential response is invalid$",
        ) as raised:
            self.issue()
        self.assertNotIn(secret, str(raised.exception))
        self.assertIsNone(raised.exception.__cause__)


if __name__ == "__main__":
    unittest.main()
