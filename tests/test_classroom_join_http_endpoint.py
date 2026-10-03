from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import json
import unittest

from acs.classroom_join_credentials import (
    ClassroomJoinCredentialService,
    ClassroomJoinGrant,
    MAX_JOIN_REQUEST_BYTES,
)
from acs.classroom_join_http_endpoint import (
    ClassroomJoinHttpEndpoint,
    JOIN_CREDENTIAL_PATH,
    MAX_AUTHORIZATION_BYTES,
    MAX_REQUEST_BODY_EVENTS,
    MAX_REQUEST_HEADER_BYTES,
)
from acs.classroom_realtime_media import MediaSource


NOW = datetime(2026, 10, 3, 0, 30, tzinfo=timezone.utc)


class FakeAuthenticator:
    def __init__(self) -> None:
        self.calls: list[str] = []
        self.error: Exception | None = None
        self.identity: object = "account-17"

    async def authenticate_bearer(self, bearer_token: str) -> str:
        self.calls.append(bearer_token)
        if self.error is not None:
            raise self.error
        return self.identity  # type: ignore[return-value]


class FakeAuthorization:
    def __init__(self) -> None:
        self.calls: list[dict[str, str]] = []
        self.error: Exception | None = None
        self.grant: ClassroomJoinGrant | None = None

    def authorize_join(
        self,
        *,
        room_id: str,
        trusted_caller_identity: str,
        requested_participant_id: str,
    ) -> ClassroomJoinGrant:
        self.calls.append(
            {
                "room_id": room_id,
                "trusted_caller_identity": trusted_caller_identity,
                "requested_participant_id": requested_participant_id,
            }
        )
        if self.error is not None:
            raise self.error
        return self.grant or ClassroomJoinGrant(
            room_id=room_id,
            participant_id=requested_participant_id,
            publish_sources=(MediaSource.MICROPHONE,),
        )


class FakeIssuer:
    def __init__(self) -> None:
        self.calls = []
        self.error: Exception | None = None
        self.token: object = "provider-token-1"

    async def issue_join_token(self, *, grant, issued_at, expires_at):
        self.calls.append((grant, issued_at, expires_at))
        if self.error is not None:
            raise self.error
        return self.token


class BrokenService(ClassroomJoinCredentialService):
    async def issue(self, *, trusted_caller_identity: str, payload: object) -> str:
        raise RuntimeError("private service traceback /srv/secrets/join")


class ClassroomJoinHttpEndpointTests(unittest.TestCase):
    def setUp(self) -> None:
        self.authenticator = FakeAuthenticator()
        self.authorization = FakeAuthorization()
        self.issuer = FakeIssuer()
        self.service = ClassroomJoinCredentialService(
            authorization=self.authorization,
            token_issuer=self.issuer,
            ttl_seconds=60,
            now=lambda: NOW,
        )
        self.endpoint = ClassroomJoinHttpEndpoint(
            service=self.service,
            authenticator=self.authenticator,
        )

    @staticmethod
    def payload() -> bytes:
        return json.dumps(
            {
                "version": 1,
                "room_id": "room-1",
                "participant_id": "student-1",
            },
            separators=(",", ":"),
        ).encode("utf-8")

    @staticmethod
    def scope(
        *,
        method: str = "POST",
        path: str = JOIN_CREDENTIAL_PATH,
        raw_path: bytes | None = None,
        query_string: bytes = b"",
        scheme: str = "https",
        server: tuple[str, int] = ("203.0.113.10", 443),
        client: tuple[str, int] = ("198.51.100.7", 50000),
        http_version: str = "1.1",
        headers: list[tuple[bytes, bytes]] | None = None,
    ) -> dict[str, object]:
        if headers is None:
            headers = [
                (b"authorization", b"Bearer auth-token-1"),
                (b"content-type", b"application/json"),
            ]
        return {
            "type": "http",
            "asgi": {"version": "3.0"},
            "http_version": http_version,
            "method": method,
            "scheme": scheme,
            "path": path,
            "raw_path": raw_path if raw_path is not None else path.encode("ascii"),
            "query_string": query_string,
            "headers": headers,
            "server": server,
            "client": client,
        }

    def invoke(
        self,
        *,
        endpoint: ClassroomJoinHttpEndpoint | None = None,
        scope: dict[str, object] | None = None,
        events: list[dict[str, object]] | None = None,
    ) -> list[dict[str, object]]:
        body = self.payload()
        queue = list(
            events
            if events is not None
            else [{"type": "http.request", "body": body, "more_body": False}]
        )
        sent: list[dict[str, object]] = []

        async def receive() -> dict[str, object]:
            if not queue:
                raise AssertionError("ASGI receive called after request completed")
            return queue.pop(0)

        async def send(message: dict[str, object]) -> None:
            sent.append(message)

        asyncio.run((endpoint or self.endpoint)(scope or self.scope(), receive, send))
        return sent

    @staticmethod
    def response(sent: list[dict[str, object]]) -> tuple[int, dict[bytes, bytes], bytes]:
        assert len(sent) == 2, sent
        start, body = sent
        assert start["type"] == "http.response.start"
        assert body["type"] == "http.response.body"
        return (
            int(start["status"]),
            dict(start["headers"]),  # type: ignore[arg-type]
            body["body"],  # type: ignore[return-value]
        )

    def test_secure_post_authenticates_then_uses_canonical_join_service(self) -> None:
        body = self.payload()
        sent = self.invoke(
            scope=self.scope(
                headers=[
                    (b"authorization", b"Bearer auth-token-1"),
                    (b"content-type", b"application/json; charset=utf-8"),
                    (b"content-length", str(len(body)).encode("ascii")),
                ]
            ),
            events=[
                {"type": "http.request", "body": body[:17], "more_body": True},
                {"type": "http.request", "body": body[17:], "more_body": False},
            ],
        )
        status, headers, response_body = self.response(sent)
        payload = json.loads(response_body.decode("utf-8"))

        self.assertEqual(status, 200)
        self.assertEqual(self.authenticator.calls, ["auth-token-1"])
        expected_authorization = {
            "room_id": "room-1",
            "trusted_caller_identity": "account-17",
            "requested_participant_id": "student-1",
        }
        self.assertEqual(
            self.authorization.calls,
            [expected_authorization, expected_authorization],
        )
        self.assertEqual(len(self.issuer.calls), 1)
        self.assertEqual(payload["room_id"], "room-1")
        self.assertEqual(payload["participant_id"], "student-1")
        self.assertEqual(payload["token"], "provider-token-1")
        self.assertEqual(headers[b"cache-control"], b"no-store")
        self.assertEqual(headers[b"pragma"], b"no-cache")
        self.assertEqual(headers[b"x-content-type-options"], b"nosniff")
        self.assertEqual(
            int(headers[b"content-length"]),
            len(response_body),
        )
        self.assertNotIn(b"auth-token-1", b"\n".join(headers.values()))

    def test_bad_bearer_fails_before_body_or_join_authority(self) -> None:
        self.authenticator.error = RuntimeError(
            "private authentication backend /srv/idp token=auth-token-1"
        )
        sent = self.invoke()
        status, headers, body = self.response(sent)

        self.assertEqual(status, 401)
        self.assertIn(b"www-authenticate", headers)
        self.assertEqual(json.loads(body), {"error": "unauthorized"})
        self.assertEqual(self.authorization.calls, [])
        self.assertEqual(self.issuer.calls, [])
        self.assertNotIn(b"auth-token-1", body)
        self.assertNotIn(b"/srv/idp", body)

    def test_missing_content_type_is_unsupported_media_type(self) -> None:
        sent = self.invoke(
            scope=self.scope(
                headers=[(b"authorization", b"Bearer auth-token-1")]
            )
        )
        status, _headers, body = self.response(sent)
        self.assertEqual(status, 415)
        self.assertEqual(json.loads(body), {"error": "unsupported_media_type"})
        self.assertEqual(self.authenticator.calls, [])

    def test_missing_authorization_returns_bearer_challenge(self) -> None:
        sent = self.invoke(
            scope=self.scope(
                headers=[(b"content-type", b"application/json")]
            )
        )
        status, headers, body = self.response(sent)
        self.assertEqual(status, 401)
        self.assertEqual(json.loads(body), {"error": "unauthorized"})
        self.assertEqual(
            headers[b"www-authenticate"],
            b'Bearer realm="accessible-chess-classroom"',
        )
        self.assertEqual(self.authenticator.calls, [])
        self.assertEqual(self.authorization.calls, [])

    def test_duplicate_authorization_is_rejected_without_authentication(self) -> None:
        sent = self.invoke(
            scope=self.scope(
                headers=[
                    (b"authorization", b"Bearer one"),
                    (b"authorization", b"Bearer two"),
                    (b"content-type", b"application/json"),
                ]
            )
        )
        status, _headers, body = self.response(sent)
        self.assertEqual(status, 400)
        self.assertEqual(json.loads(body), {"error": "duplicate_header"})
        self.assertEqual(self.authenticator.calls, [])

    def test_query_string_is_rejected_before_authentication(self) -> None:
        sent = self.invoke(
            scope=self.scope(query_string=b"token=secret&room=room-1")
        )
        status, _headers, body = self.response(sent)
        self.assertEqual(status, 400)
        self.assertEqual(json.loads(body), {"error": "query_not_allowed"})
        self.assertEqual(self.authenticator.calls, [])
        self.assertNotIn(b"secret", body)

    def test_remote_plain_http_is_rejected_but_explicit_loopback_dev_mode_works(self) -> None:
        sent = self.invoke(scope=self.scope(scheme="http", server=("203.0.113.10", 8080)))
        status, _headers, _body = self.response(sent)
        self.assertEqual(status, 400)
        self.assertEqual(self.authenticator.calls, [])

        endpoint = ClassroomJoinHttpEndpoint(
            service=self.service,
            authenticator=self.authenticator,
            allow_insecure_loopback=True,
        )
        sent = self.invoke(
            endpoint=endpoint,
            scope=self.scope(
                scheme="http",
                server=("127.0.0.1", 8765),
                client=("127.0.0.1", 50000),
            ),
        )
        status, _headers, body = self.response(sent)
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)["participant_id"], "student-1")

        # A loopback listener is not sufficient: behind a local reverse proxy,
        # an external peer can still reach the backend. Never allow plaintext
        # bearer credentials unless both transport endpoints are loopback.
        self.authenticator.calls.clear()
        sent = self.invoke(
            endpoint=endpoint,
            scope=self.scope(
                scheme="http",
                server=("127.0.0.1", 8765),
                client=("198.51.100.7", 50000),
            ),
        )
        status, _headers, _body = self.response(sent)
        self.assertEqual(status, 400)
        self.assertEqual(self.authenticator.calls, [])

        sent = self.invoke(
            endpoint=endpoint,
            scope=self.scope(
                scheme="http",
                server=("192.0.2.44", 8765),
                client=("127.0.0.1", 50000),
            ),
        )
        status, _headers, _body = self.response(sent)
        self.assertEqual(status, 400)

    def test_route_method_raw_path_and_http_version_are_exact(self) -> None:
        cases = (
            (self.scope(path="/v1/classroom/other"), 404),
            (self.scope(method="GET"), 405),
            (
                self.scope(
                    raw_path=b"/v1/classroom/%6aoin-credential",
                ),
                404,
            ),
            (self.scope(http_version="1.0"), 400),
        )
        for scope, expected in cases:
            with self.subTest(scope=scope):
                self.authenticator.calls.clear()
                sent = self.invoke(scope=scope)
                status, headers, _body = self.response(sent)
                self.assertEqual(status, expected)
                self.assertEqual(self.authenticator.calls, [])
                if expected == 405:
                    self.assertEqual(headers[b"allow"], b"POST")

    def test_invalid_header_names_and_control_values_fail_before_authentication(self) -> None:
        cases = (
            [
                (b"bad header", b"x"),
                (b"authorization", b"Bearer auth-token-1"),
                (b"content-type", b"application/json"),
            ],
            [
                (b"bad:header", b"x"),
                (b"authorization", b"Bearer auth-token-1"),
                (b"content-type", b"application/json"),
            ],
            [
                (b"x-meta", b"line1\nline2"),
                (b"authorization", b"Bearer auth-token-1"),
                (b"content-type", b"application/json"),
            ],
        )
        for headers in cases:
            with self.subTest(headers=headers):
                self.authenticator.calls.clear()
                sent = self.invoke(scope=self.scope(headers=headers))
                status, _response_headers, body = self.response(sent)
                self.assertEqual(status, 400)
                self.assertEqual(json.loads(body), {"error": "invalid_headers"})
                self.assertEqual(self.authenticator.calls, [])

    def test_content_type_encoding_and_transfer_encoding_fail_closed(self) -> None:
        cases = (
            (
                [
                    (b"authorization", b"Bearer auth-token-1"),
                    (b"content-type", b"text/plain"),
                ],
                415,
            ),
            (
                [
                    (b"authorization", b"Bearer auth-token-1"),
                    (b"content-type", b"application/json; charset=latin-1"),
                ],
                415,
            ),
            (
                [
                    (b"authorization", b"Bearer auth-token-1"),
                    (b"content-type", b"application/json"),
                    (b"content-encoding", b"gzip"),
                ],
                415,
            ),
            (
                [
                    (b"authorization", b"Bearer auth-token-1"),
                    (b"content-type", b"application/json"),
                    (b"transfer-encoding", b"chunked"),
                ],
                400,
            ),
        )
        for headers, expected in cases:
            with self.subTest(headers=headers):
                self.authenticator.calls.clear()
                sent = self.invoke(scope=self.scope(headers=headers))
                status, _response_headers, _body = self.response(sent)
                self.assertEqual(status, expected)
                self.assertEqual(self.authenticator.calls, [])

    def test_body_and_declared_length_are_bounded(self) -> None:
        oversized = MAX_JOIN_REQUEST_BYTES + 1
        sent = self.invoke(
            scope=self.scope(
                headers=[
                    (b"authorization", b"Bearer auth-token-1"),
                    (b"content-type", b"application/json"),
                    (b"content-length", str(oversized).encode("ascii")),
                ]
            )
        )
        status, _headers, _body = self.response(sent)
        self.assertEqual(status, 413)
        self.assertEqual(self.authenticator.calls, [])

        self.authenticator.calls.clear()
        sent = self.invoke(
            scope=self.scope(),
            events=[
                {
                    "type": "http.request",
                    "body": b"x" * oversized,
                    "more_body": False,
                }
            ],
        )
        status, _headers, _body = self.response(sent)
        self.assertEqual(status, 413)
        self.assertEqual(self.authenticator.calls, ["auth-token-1"])
        self.assertEqual(self.authorization.calls, [])

        self.authenticator.calls.clear()
        body = self.payload()
        sent = self.invoke(
            scope=self.scope(
                headers=[
                    (b"authorization", b"Bearer auth-token-1"),
                    (b"content-type", b"application/json"),
                    (b"content-length", str(len(body) + 1).encode("ascii")),
                ]
            ),
        )
        status, _headers, response_body = self.response(sent)
        self.assertEqual(status, 400)
        self.assertEqual(
            json.loads(response_body),
            {"error": "content_length_mismatch"},
        )

    def test_every_malformed_bearer_401_includes_same_challenge(self) -> None:
        bad_values = (
            b"",
            b"Basic abc",
            b"Bearer ",
            b"Bearer abc def",
            b"Bearer abc\x7fdef",
            b"Bearer \xff",
        )
        for value in bad_values:
            with self.subTest(value=value):
                self.authenticator.calls.clear()
                sent = self.invoke(
                    scope=self.scope(
                        headers=[
                            (b"authorization", value),
                            (b"content-type", b"application/json"),
                        ]
                    )
                )
                status, headers, body = self.response(sent)
                self.assertEqual(status, 401)
                self.assertEqual(
                    headers[b"www-authenticate"],
                    b'Bearer realm="accessible-chess-classroom"',
                )
                self.assertEqual(json.loads(body), {"error": "unauthorized"})
                self.assertEqual(self.authenticator.calls, [])

    def test_attacker_sized_numeric_content_length_is_rejected_before_authentication(self) -> None:
        huge_digits = b"9" * 5000
        sent = self.invoke(
            scope=self.scope(
                headers=[
                    (b"authorization", b"Bearer auth-token-1"),
                    (b"content-type", b"application/json"),
                    (b"content-length", huge_digits),
                ]
            )
        )
        status, _headers, body = self.response(sent)
        self.assertEqual(status, 413)
        self.assertEqual(json.loads(body), {"error": "request_too_large"})
        self.assertEqual(self.authenticator.calls, [])
        self.assertEqual(self.authorization.calls, [])
        self.assertEqual(self.issuer.calls, [])

    def test_header_budget_and_bearer_bounds_fail_without_secret_reflection(self) -> None:
        huge = b"x" * (MAX_REQUEST_HEADER_BYTES + 1)
        sent = self.invoke(
            scope=self.scope(
                headers=[
                    (b"x-padding", huge),
                    (b"authorization", b"Bearer secret-token"),
                    (b"content-type", b"application/json"),
                ]
            )
        )
        status, _headers, body = self.response(sent)
        self.assertEqual(status, 431)
        self.assertEqual(self.authenticator.calls, [])
        self.assertNotIn(b"secret-token", body)

        too_long = b"Bearer " + b"a" * MAX_AUTHORIZATION_BYTES
        sent = self.invoke(
            scope=self.scope(
                headers=[
                    (b"authorization", too_long),
                    (b"content-type", b"application/json"),
                ]
            )
        )
        status, _headers, body = self.response(sent)
        self.assertEqual(status, 401)
        self.assertNotIn(b"a" * 100, body)

    def test_authenticated_malformed_join_request_is_generic_bad_request(self) -> None:
        sent = self.invoke(
            events=[
                {
                    "type": "http.request",
                    "body": b'{"version":1,"room_id":',
                    "more_body": False,
                }
            ]
        )
        status, _headers, body = self.response(sent)
        self.assertEqual(status, 400)
        self.assertEqual(json.loads(body), {"error": "join_request_rejected"})
        self.assertEqual(self.authenticator.calls, ["auth-token-1"])
        self.assertEqual(self.authorization.calls, [])

    def test_authorization_failure_is_generic_and_redacts_backend_details(self) -> None:
        self.authorization.error = RuntimeError(
            "ldap:///private/member/db account-17 room-1"
        )
        sent = self.invoke()
        status, _headers, body = self.response(sent)
        self.assertEqual(status, 403)
        self.assertEqual(json.loads(body), {"error": "join_request_rejected"})
        self.assertNotIn(b"ldap", body)
        self.assertNotIn(b"account-17", body)
        self.assertNotIn(b"room-1", body)

    def test_post_mint_authorization_revocation_is_forbidden_not_service_failure(self) -> None:
        class RevokedAuthorization:
            def __init__(self) -> None:
                self.calls = 0

            def authorize_join(
                self,
                *,
                room_id: str,
                trusted_caller_identity: str,
                requested_participant_id: str,
            ) -> ClassroomJoinGrant:
                self.calls += 1
                if self.calls == 2:
                    raise RuntimeError("membership revoked in private backend")
                return ClassroomJoinGrant(
                    room_id=room_id,
                    participant_id=requested_participant_id,
                    publish_sources=(MediaSource.MICROPHONE,),
                )

        authorization = RevokedAuthorization()
        service = ClassroomJoinCredentialService(
            authorization=authorization,
            token_issuer=self.issuer,
            ttl_seconds=60,
            now=lambda: NOW,
        )
        endpoint = ClassroomJoinHttpEndpoint(
            service=service,
            authenticator=self.authenticator,
        )
        sent = self.invoke(endpoint=endpoint)
        status, _headers, body = self.response(sent)
        self.assertEqual(status, 403)
        self.assertEqual(json.loads(body), {"error": "join_request_rejected"})
        self.assertEqual(authorization.calls, 2)
        self.assertEqual(len(self.issuer.calls), 1)
        self.assertNotIn(b"private backend", body)

    def test_post_mint_authorization_drift_is_forbidden_not_service_failure(self) -> None:
        class ChangedAuthorization:
            def __init__(self) -> None:
                self.calls = 0

            def authorize_join(
                self,
                *,
                room_id: str,
                trusted_caller_identity: str,
                requested_participant_id: str,
            ) -> ClassroomJoinGrant:
                self.calls += 1
                sources = (
                    (MediaSource.MICROPHONE,)
                    if self.calls == 1
                    else (MediaSource.MICROPHONE, MediaSource.CAMERA)
                )
                return ClassroomJoinGrant(
                    room_id=room_id,
                    participant_id=requested_participant_id,
                    publish_sources=sources,
                )

        authorization = ChangedAuthorization()
        service = ClassroomJoinCredentialService(
            authorization=authorization,
            token_issuer=self.issuer,
            ttl_seconds=60,
            now=lambda: NOW,
        )
        endpoint = ClassroomJoinHttpEndpoint(
            service=service,
            authenticator=self.authenticator,
        )
        sent = self.invoke(endpoint=endpoint)
        status, _headers, body = self.response(sent)
        self.assertEqual(status, 403)
        self.assertEqual(json.loads(body), {"error": "join_request_rejected"})
        self.assertEqual(authorization.calls, 2)
        self.assertEqual(len(self.issuer.calls), 1)

    def test_provider_issuance_failure_is_retryable_503_without_secret_leak(self) -> None:
        self.issuer.error = RuntimeError(
            "server-secret livekit provider trace /srv/provider"
        )
        sent = self.invoke()
        status, headers, body = self.response(sent)
        self.assertEqual(status, 503)
        self.assertEqual(json.loads(body), {"error": "join_request_rejected"})
        self.assertEqual(headers[b"cache-control"], b"no-store")
        self.assertNotIn(b"server-secret", body)
        self.assertNotIn(b"/srv/provider", body)

    def test_unexpected_service_failure_is_generic_500_or_503_boundary(self) -> None:
        broken = BrokenService(
            authorization=self.authorization,
            token_issuer=self.issuer,
            now=lambda: NOW,
        )
        endpoint = ClassroomJoinHttpEndpoint(
            service=broken,
            authenticator=self.authenticator,
        )
        sent = self.invoke(endpoint=endpoint)
        status, _headers, body = self.response(sent)
        self.assertEqual(status, 503)
        self.assertEqual(json.loads(body), {"error": "join_service_unavailable"})
        self.assertNotIn(b"/srv/secrets", body)

    def test_invalid_authenticator_identity_is_not_allowed_to_reach_authorization(self) -> None:
        self.authenticator.identity = "bad caller with spaces"
        sent = self.invoke()
        status, _headers, body = self.response(sent)
        self.assertEqual(status, 401)
        self.assertEqual(json.loads(body), {"error": "join_request_rejected"})
        self.assertEqual(
            _headers[b"www-authenticate"],
            b'Bearer realm="accessible-chess-classroom"',
        )
        self.assertEqual(self.authorization.calls, [])

    def test_response_body_send_failure_never_attempts_second_http_response(self) -> None:
        body = self.payload()
        events = [{"type": "http.request", "body": body, "more_body": False}]
        sent: list[dict[str, object]] = []

        async def receive() -> dict[str, object]:
            return events.pop(0)

        async def send(message: dict[str, object]) -> None:
            sent.append(message)
            if message["type"] == "http.response.body":
                raise ConnectionError("client disconnected after response start")

        with self.assertRaisesRegex(
            RuntimeError,
            "^join credential response delivery failed$",
        ):
            asyncio.run(self.endpoint(self.scope(), receive, send))

        self.assertEqual(
            [message["type"] for message in sent],
            ["http.response.start", "http.response.body"],
        )
        self.assertEqual(
            sum(message["type"] == "http.response.start" for message in sent),
            1,
        )

    def test_error_response_send_failure_is_not_retried_as_500(self) -> None:
        events = [{"type": "http.request", "body": self.payload(), "more_body": False}]
        sent: list[dict[str, object]] = []

        async def receive() -> dict[str, object]:
            return events.pop(0)

        async def send(message: dict[str, object]) -> None:
            sent.append(message)
            raise ConnectionError("client disconnected during error response")

        scope = self.scope(
            headers=[(b"content-type", b"application/json")]
        )
        with self.assertRaisesRegex(
            RuntimeError,
            "^join credential response delivery failed$",
        ):
            asyncio.run(self.endpoint(scope, receive, send))

        self.assertEqual(len(sent), 1)
        self.assertEqual(sent[0]["type"], "http.response.start")
        self.assertEqual(sent[0]["status"], 401)

    def test_request_body_event_budget_accepts_exact_boundary(self) -> None:
        body = self.payload()
        events = [
            {"type": "http.request", "body": b"", "more_body": True}
            for _ in range(MAX_REQUEST_BODY_EVENTS - 1)
        ]
        events.append(
            {"type": "http.request", "body": body, "more_body": False}
        )

        sent = self.invoke(events=events)
        status, _headers, response_body = self.response(sent)

        self.assertEqual(status, 200)
        self.assertEqual(json.loads(response_body)["room_id"], "room-1")
        self.assertEqual(self.authenticator.calls, ["auth-token-1"])
        self.assertEqual(len(self.authorization.calls), 2)
        self.assertEqual(len(self.issuer.calls), 1)

    def test_request_body_event_budget_rejects_zero_byte_fragment_dos(self) -> None:
        body = self.payload()
        events = [
            {"type": "http.request", "body": b"", "more_body": True}
            for _ in range(MAX_REQUEST_BODY_EVENTS)
        ]
        events.append(
            {"type": "http.request", "body": body, "more_body": False}
        )

        sent = self.invoke(events=events)
        status, _headers, response_body = self.response(sent)

        self.assertEqual(status, 413)
        self.assertEqual(
            json.loads(response_body),
            {"error": "request_too_fragmented"},
        )
        self.assertEqual(self.authenticator.calls, ["auth-token-1"])
        self.assertEqual(self.authorization.calls, [])
        self.assertEqual(self.issuer.calls, [])

    def test_client_disconnect_does_not_emit_partial_credential_response(self) -> None:
        sent = self.invoke(
            events=[
                {
                    "type": "http.request",
                    "body": self.payload()[:5],
                    "more_body": True,
                },
                {"type": "http.disconnect"},
            ]
        )
        self.assertEqual(sent, [])
        self.assertEqual(self.authorization.calls, [])
        self.assertEqual(self.issuer.calls, [])

    def test_lifespan_is_supported_without_opening_join_authorities(self) -> None:
        sent: list[dict[str, object]] = []
        events = [
            {"type": "lifespan.startup"},
            {"type": "lifespan.shutdown"},
        ]

        async def receive() -> dict[str, object]:
            return events.pop(0)

        async def send(message: dict[str, object]) -> None:
            sent.append(message)

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
        self.assertEqual(self.authenticator.calls, [])
        self.assertEqual(self.authorization.calls, [])

    def test_repr_contains_no_credentials_or_authority_state(self) -> None:
        rendered = repr(self.endpoint)
        self.assertEqual(
            rendered,
            "ClassroomJoinHttpEndpoint("
            "service=<bound>, authenticator=<bound>, "
            "allow_insecure_loopback=False)",
        )
        self.assertNotIn("auth-token", rendered)
        self.assertNotIn("provider-token", rendered)
        self.assertNotIn("account-17", rendered)

    def test_constructor_is_strict(self) -> None:
        with self.assertRaises(TypeError):
            ClassroomJoinHttpEndpoint(
                service=object(),  # type: ignore[arg-type]
                authenticator=self.authenticator,
            )
        with self.assertRaises(TypeError):
            ClassroomJoinHttpEndpoint(
                service=self.service,
                authenticator=object(),  # type: ignore[arg-type]
            )
        with self.assertRaises(TypeError):
            ClassroomJoinHttpEndpoint(
                service=self.service,
                authenticator=self.authenticator,
                allow_insecure_loopback=1,  # type: ignore[arg-type]
            )


if __name__ == "__main__":
    unittest.main()
