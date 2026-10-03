from __future__ import annotations

"""Authenticated ASGI endpoint for canonical classroom join credentials.

This module owns only the HTTP transport boundary. Authentication, classroom
membership/media policy, provider token minting, and chess state remain in their
existing injected authorities. The endpoint never reads ambient credentials and
never places bearer/provider tokens in URLs, headers, diagnostics, or repr output.
"""

from collections.abc import Awaitable, Callable, Mapping
import ipaddress
import json
import re
from typing import Protocol

from .classroom_join_credentials import (
    ClassroomJoinCredentialError,
    ClassroomJoinCredentialService,
    MAX_JOIN_REQUEST_BYTES,
    MAX_JOIN_RESPONSE_BYTES,
)


JOIN_CREDENTIAL_PATH = "/v1/classroom/join-credential"
MAX_AUTHORIZATION_BYTES = 8192
MAX_REQUEST_HEADER_BYTES = 16 * 1024
# A maximally fragmented valid request can use one event per body byte plus
# one final empty event carrying more_body=False. Anything beyond that cannot
# encode additional valid request bytes and only burns event-loop turns.
MAX_REQUEST_BODY_EVENTS = MAX_JOIN_REQUEST_BYTES + 1
_BEARER_CHALLENGE = (
    (
        b"www-authenticate",
        b'Bearer realm="accessible-chess-classroom"',
    ),
)
_HEADER_NAME_RE = re.compile(rb"^[!#$%&'*+.^_`|~0-9A-Za-z-]+$")

Receive = Callable[[], Awaitable[dict[str, object]]]
Send = Callable[[dict[str, object]], Awaitable[None]]


class ClassroomJoinHttpAuthenticatorPort(Protocol):
    """Trusted deployment authentication boundary.

    The bearer value is transport credential material only. Implementations return
    the canonical authenticated caller identity consumed by the join service.
    """

    async def authenticate_bearer(self, bearer_token: str) -> str:
        """Return the trusted caller identity or raise when authentication fails."""


class _HttpReject(Exception):
    __slots__ = ("status", "code", "extra_headers")

    def __init__(
        self,
        status: int,
        code: str,
        *,
        extra_headers: tuple[tuple[bytes, bytes], ...] = (),
    ) -> None:
        super().__init__(code)
        self.status = status
        self.code = code
        self.extra_headers = extra_headers


class _ClientDisconnected(Exception):
    pass


class _ResponseDeliveryFailure(RuntimeError):
    pass


class ClassroomJoinHttpEndpoint:
    """Minimal production ASGI boundary for one credential-minting route."""

    __slots__ = (
        "_service",
        "_authenticator",
        "_allow_insecure_loopback",
    )

    def __init__(
        self,
        *,
        service: ClassroomJoinCredentialService,
        authenticator: ClassroomJoinHttpAuthenticatorPort,
        allow_insecure_loopback: bool = False,
    ) -> None:
        if not isinstance(service, ClassroomJoinCredentialService):
            raise TypeError("join HTTP endpoint requires ClassroomJoinCredentialService")
        if authenticator is None or not callable(
            getattr(authenticator, "authenticate_bearer", None)
        ):
            raise TypeError("join HTTP endpoint requires an authenticator")
        if type(allow_insecure_loopback) is not bool:
            raise TypeError("allow_insecure_loopback must be bool")
        self._service = service
        self._authenticator = authenticator
        self._allow_insecure_loopback = allow_insecure_loopback

    def __repr__(self) -> str:
        return (
            "ClassroomJoinHttpEndpoint("
            "service=<bound>, authenticator=<bound>, "
            f"allow_insecure_loopback={self._allow_insecure_loopback!r})"
        )

    async def __call__(
        self,
        scope: Mapping[str, object],
        receive: Receive,
        send: Send,
    ) -> None:
        if not isinstance(scope, Mapping):
            raise TypeError("ASGI scope must be a mapping")
        scope_type = scope.get("type")
        if scope_type == "lifespan":
            await self._lifespan(receive, send)
            return
        if scope_type != "http":
            raise RuntimeError("join credential endpoint supports HTTP only")

        try:
            await self._handle_http(scope, receive, send)
        except _ClientDisconnected:
            return
        except _ResponseDeliveryFailure:
            raise
        except _HttpReject as rejected:
            await _send_error(
                send,
                rejected.status,
                rejected.code,
                extra_headers=rejected.extra_headers,
            )
        except Exception:
            await _send_error(send, 500, "internal_error")

    async def _handle_http(
        self,
        scope: Mapping[str, object],
        receive: Receive,
        send: Send,
    ) -> None:
        _require_secure_transport(
            scope,
            allow_insecure_loopback=self._allow_insecure_loopback,
        )
        _require_route(scope)
        headers = _validated_headers(scope)
        _require_json_content_type(headers)
        declared_length = _content_length(headers)
        bearer = _bearer_token(headers)

        try:
            trusted_caller_identity = await self._authenticator.authenticate_bearer(
                bearer
            )
        except Exception:
            raise _unauthorized() from None

        body = await _read_body(receive, declared_length=declared_length)
        try:
            payload = body.decode("utf-8")
        except UnicodeDecodeError:
            raise _HttpReject(400, "invalid_request") from None

        try:
            response = await self._service.issue(
                trusted_caller_identity=trusted_caller_identity,
                payload=payload,
            )
        except ClassroomJoinCredentialError as error:
            status = _service_error_status(error)
            raise _HttpReject(
                status,
                "join_request_rejected",
                extra_headers=_BEARER_CHALLENGE if status == 401 else (),
            ) from None
        except Exception:
            raise _HttpReject(503, "join_service_unavailable") from None

        if type(response) is not str:
            raise _HttpReject(503, "join_service_unavailable")
        try:
            response_bytes = response.encode("utf-8")
        except UnicodeEncodeError:
            raise _HttpReject(503, "join_service_unavailable") from None
        if not response_bytes or len(response_bytes) > MAX_JOIN_RESPONSE_BYTES:
            raise _HttpReject(503, "join_service_unavailable")

        await _send_response(send, 200, response_bytes)

    async def _lifespan(self, receive: Receive, send: Send) -> None:
        while True:
            event = await receive()
            if type(event) is not dict:
                raise RuntimeError("invalid ASGI lifespan event")
            event_type = event.get("type")
            if event_type == "lifespan.startup":
                await send({"type": "lifespan.startup.complete"})
            elif event_type == "lifespan.shutdown":
                await send({"type": "lifespan.shutdown.complete"})
                return
            else:
                raise RuntimeError("unsupported ASGI lifespan event")


def _require_secure_transport(
    scope: Mapping[str, object],
    *,
    allow_insecure_loopback: bool,
) -> None:
    scheme = scope.get("scheme")
    if scheme == "https":
        return
    if (
        scheme == "http"
        and allow_insecure_loopback
        and _network_endpoint_is_loopback(scope.get("server"))
        and _network_endpoint_is_loopback(scope.get("client"))
    ):
        return
    raise _HttpReject(400, "secure_transport_required")


def _network_endpoint_is_loopback(value: object) -> bool:
    if (
        type(value) not in {tuple, list}
        or len(value) != 2
        or type(value[0]) is not str
        or type(value[1]) is not int
    ):
        return False
    host = value[0]
    try:
        address = ipaddress.ip_address(host.strip("[]"))
    except ValueError:
        return False
    return address.is_loopback


def _require_route(scope: Mapping[str, object]) -> None:
    if scope.get("http_version") not in {"1.1", "2"}:
        raise _HttpReject(400, "unsupported_http_version")
    if scope.get("path") != JOIN_CREDENTIAL_PATH:
        raise _HttpReject(404, "not_found")
    raw_path = scope.get("raw_path")
    if raw_path is not None and raw_path != JOIN_CREDENTIAL_PATH.encode("ascii"):
        raise _HttpReject(404, "not_found")
    query = scope.get("query_string", b"")
    if query != b"":
        raise _HttpReject(400, "query_not_allowed")
    if scope.get("method") != "POST":
        raise _HttpReject(
            405,
            "method_not_allowed",
            extra_headers=((b"allow", b"POST"),),
        )


def _validated_headers(
    scope: Mapping[str, object],
) -> dict[bytes, tuple[bytes, ...]]:
    raw_headers = scope.get("headers")
    if type(raw_headers) not in {list, tuple}:
        raise _HttpReject(400, "invalid_headers")
    total = 0
    grouped: dict[bytes, list[bytes]] = {}
    for entry in raw_headers:
        if (
            type(entry) not in {list, tuple}
            or len(entry) != 2
            or type(entry[0]) is not bytes
            or type(entry[1]) is not bytes
        ):
            raise _HttpReject(400, "invalid_headers")
        name, value = entry
        total += len(name) + len(value)
        if total > MAX_REQUEST_HEADER_BYTES:
            raise _HttpReject(431, "headers_too_large")
        lowered = name.lower()
        if _HEADER_NAME_RE.fullmatch(lowered) is None:
            raise _HttpReject(400, "invalid_headers")
        if any(byte < 32 or byte == 127 for byte in value):
            # Authorization credential syntax is an authentication failure, not
            # a generic request-shape oracle. Keep the same Bearer challenge for
            # every malformed credential while retaining 400 for other headers.
            if lowered == b"authorization":
                raise _unauthorized()
            raise _HttpReject(400, "invalid_headers")
        grouped.setdefault(lowered, []).append(value)

    if b"content-encoding" in grouped:
        raise _HttpReject(415, "content_encoding_not_allowed")
    if b"transfer-encoding" in grouped:
        raise _HttpReject(400, "transfer_encoding_not_allowed")
    return {name: tuple(values) for name, values in grouped.items()}


def _single_header(
    headers: Mapping[bytes, tuple[bytes, ...]],
    name: bytes,
    *,
    required: bool,
) -> bytes | None:
    values = headers.get(name, ())
    if not values:
        if required:
            raise _HttpReject(400, "required_header_missing")
        return None
    if len(values) != 1:
        raise _HttpReject(400, "duplicate_header")
    return values[0]


def _require_json_content_type(
    headers: Mapping[bytes, tuple[bytes, ...]],
) -> None:
    values = headers.get(b"content-type", ())
    if not values:
        raise _HttpReject(415, "unsupported_media_type")
    if len(values) != 1:
        raise _HttpReject(400, "duplicate_header")
    raw = values[0]
    try:
        parts = [part.strip().lower() for part in raw.decode("ascii").split(";")]
    except UnicodeDecodeError:
        raise _HttpReject(415, "unsupported_media_type") from None
    if not parts or parts[0] != "application/json":
        raise _HttpReject(415, "unsupported_media_type")
    parameters = parts[1:]
    if len(parameters) > 1:
        raise _HttpReject(415, "unsupported_media_type")
    if parameters and parameters[0] != "charset=utf-8":
        raise _HttpReject(415, "unsupported_media_type")


def _content_length(
    headers: Mapping[bytes, tuple[bytes, ...]],
) -> int | None:
    raw = _single_header(headers, b"content-length", required=False)
    if raw is None:
        return None
    try:
        text = raw.decode("ascii")
    except UnicodeDecodeError:
        raise _HttpReject(400, "invalid_content_length") from None
    if not text or not text.isdigit():
        raise _HttpReject(400, "invalid_content_length")
    # Do not feed attacker-sized digit strings into int(); Python itself places
    # a conversion limit on huge decimal strings, and this endpoint must map the
    # request deterministically instead of surfacing that implementation detail.
    max_digits = len(str(MAX_JOIN_REQUEST_BYTES))
    if len(text) > max_digits:
        raise _HttpReject(413, "request_too_large")
    value = int(text, 10)
    if value > MAX_JOIN_REQUEST_BYTES:
        raise _HttpReject(413, "request_too_large")
    return value


def _bearer_token(
    headers: Mapping[bytes, tuple[bytes, ...]],
) -> str:
    values = headers.get(b"authorization", ())
    if not values:
        raise _unauthorized()
    if len(values) != 1:
        raise _HttpReject(400, "duplicate_header")
    raw = values[0]
    if not raw or len(raw) > MAX_AUTHORIZATION_BYTES:
        raise _unauthorized()
    try:
        text = raw.decode("ascii")
    except UnicodeDecodeError:
        raise _unauthorized() from None
    if len(text) < 8 or text[:7].lower() != "bearer ":
        raise _unauthorized()
    token = text[7:]
    if (
        not token
        or token != token.strip()
        or any(ord(ch) <= 32 or ord(ch) == 127 for ch in token)
    ):
        raise _unauthorized()
    return token


def _unauthorized() -> _HttpReject:
    return _HttpReject(
        401,
        "unauthorized",
        extra_headers=_BEARER_CHALLENGE,
    )


async def _read_body(
    receive: Receive,
    *,
    declared_length: int | None,
) -> bytes:
    body = bytearray()
    event_count = 0
    while True:
        event_count += 1
        if event_count > MAX_REQUEST_BODY_EVENTS:
            raise _HttpReject(413, "request_too_fragmented")
        event = await receive()
        if type(event) is not dict:
            raise _HttpReject(400, "invalid_request")
        event_type = event.get("type")
        if event_type == "http.disconnect":
            raise _ClientDisconnected()
        if event_type != "http.request":
            raise _HttpReject(400, "invalid_request")
        chunk = event.get("body", b"")
        if type(chunk) is not bytes:
            raise _HttpReject(400, "invalid_request")
        if len(chunk) > MAX_JOIN_REQUEST_BYTES - len(body):
            raise _HttpReject(413, "request_too_large")
        body.extend(chunk)
        more = event.get("more_body", False)
        if type(more) is not bool:
            raise _HttpReject(400, "invalid_request")
        if not more:
            break

    if declared_length is not None and declared_length != len(body):
        raise _HttpReject(400, "content_length_mismatch")
    if not body:
        raise _HttpReject(400, "invalid_request")
    return bytes(body)


def _service_error_status(error: ClassroomJoinCredentialError) -> int:
    message = str(error)
    if message.startswith(
        (
            "join request payload",
            "join request fields",
            "join request version",
            "requested room id",
            "requested participant id",
        )
    ):
        return 400
    if message.startswith("trusted caller identity"):
        return 401
    if message in {
        "join request is not authorized",
        "join request is no longer authorized",
        "join authorization returned invalid grant",
        "join authorization identity does not match request",
        "join authorization changed during token issuance",
    }:
        return 403
    return 503


async def _send_error(
    send: Send,
    status: int,
    code: str,
    *,
    extra_headers: tuple[tuple[bytes, bytes], ...] = (),
) -> None:
    payload = json.dumps(
        {"error": code},
        ensure_ascii=True,
        separators=(",", ":"),
    ).encode("ascii")
    await _send_response(
        send,
        status,
        payload,
        extra_headers=extra_headers,
    )


async def _send_response(
    send: Send,
    status: int,
    body: bytes,
    *,
    extra_headers: tuple[tuple[bytes, bytes], ...] = (),
) -> None:
    headers = (
        (b"content-type", b"application/json; charset=utf-8"),
        (b"content-length", str(len(body)).encode("ascii")),
        (b"cache-control", b"no-store"),
        (b"pragma", b"no-cache"),
        (b"x-content-type-options", b"nosniff"),
        *extra_headers,
    )
    try:
        await send(
            {
                "type": "http.response.start",
                "status": status,
                "headers": list(headers),
            }
        )
        await send(
            {
                "type": "http.response.body",
                "body": body,
                "more_body": False,
            }
        )
    except Exception:
        raise _ResponseDeliveryFailure(
            "join credential response delivery failed"
        ) from None


__all__ = [
    "ClassroomJoinHttpAuthenticatorPort",
    "ClassroomJoinHttpEndpoint",
    "JOIN_CREDENTIAL_PATH",
    "MAX_AUTHORIZATION_BYTES",
    "MAX_REQUEST_BODY_EVENTS",
    "MAX_REQUEST_HEADER_BYTES",
]
