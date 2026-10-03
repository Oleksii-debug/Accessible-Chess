from __future__ import annotations

"""Authenticated ASGI transport for the canonical classroom room-chat RPC.

This module owns only HTTP framing and deployment authentication. Canonical
request semantics remain in ClassroomChatRpcService; membership, roles,
authorization, durable chat state, files, chess state, provider credentials and
analytics remain outside this boundary.
"""

from collections.abc import Awaitable, Callable, Mapping
import ipaddress
import json
import re
from typing import Protocol

from .classroom_chat_rpc import (
    ClassroomChatRpcError,
    ClassroomChatRpcService,
)


CHAT_RPC_PATH = "/v1/classroom/chat"
MAX_AUTHORIZATION_BYTES = 8192
MAX_REQUEST_HEADER_BYTES = 16 * 1024
# A full 5,000-command moderation batch with canonical 128-character opaque IDs
# fits comfortably while attacker-controlled bodies remain explicitly bounded.
MAX_CHAT_HTTP_REQUEST_BYTES = 4 * 1024 * 1024
# MAX_SYNC_MESSAGES is 10,000 and each chat body is at most 4,000 Unicode
# characters. UTF-8 JSON can therefore legitimately be large; keep the transport
# bounded without introducing a smaller semantic history page than the RPC.
MAX_CHAT_HTTP_RESPONSE_BYTES = 192 * 1024 * 1024

_BEARER_CHALLENGE = (
    (
        b"www-authenticate",
        b'Bearer realm="accessible-chess-classroom-chat"',
    ),
)
_HEADER_NAME_RE = re.compile(rb"^[!#$%&'*+.^_`|~0-9A-Za-z-]+$")

Receive = Callable[[], Awaitable[dict[str, object]]]
Send = Callable[[dict[str, object]], Awaitable[None]]


class ClassroomChatHttpAuthenticatorPort(Protocol):
    """Trusted deployment authentication boundary for room chat.

    Implementations validate the transport credential and return the exact
    canonical (room_id, participant_id) identity bound to that credential.
    """

    async def authenticate_bearer(self, bearer_token: str) -> tuple[str, str]:
        """Return (room_id, participant_id) or raise when authentication fails."""


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


class ClassroomChatHttpEndpoint:
    """Minimal production ASGI boundary for canonical room-chat RPC."""

    __slots__ = (
        "_service",
        "_authenticator",
        "_allow_insecure_loopback",
    )

    def __init__(
        self,
        *,
        service: ClassroomChatRpcService,
        authenticator: ClassroomChatHttpAuthenticatorPort,
        allow_insecure_loopback: bool = False,
    ) -> None:
        if not isinstance(service, ClassroomChatRpcService):
            raise TypeError("chat HTTP endpoint requires ClassroomChatRpcService")
        if authenticator is None or not callable(
            getattr(authenticator, "authenticate_bearer", None)
        ):
            raise TypeError("chat HTTP endpoint requires an authenticator")
        if type(allow_insecure_loopback) is not bool:
            raise TypeError("allow_insecure_loopback must be bool")
        self._service = service
        self._authenticator = authenticator
        self._allow_insecure_loopback = allow_insecure_loopback

    def __repr__(self) -> str:
        return (
            "ClassroomChatHttpEndpoint("
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
            raise RuntimeError("classroom chat endpoint supports HTTP only")

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
            authenticated = await self._authenticator.authenticate_bearer(bearer)
        except Exception:
            raise _unauthorized() from None
        if (
            type(authenticated) is not tuple
            or len(authenticated) != 2
            or type(authenticated[0]) is not str
            or type(authenticated[1]) is not str
        ):
            raise _unauthorized()
        authenticated_room_id, authenticated_participant_id = authenticated

        body = await _read_body(receive, declared_length=declared_length)
        payload = _decode_request_json(body)

        try:
            response = self._service.handle(
                payload,
                authenticated_room_id=authenticated_room_id,
                authenticated_participant_id=authenticated_participant_id,
            )
        except ClassroomChatRpcError as error:
            status = _service_error_status(error)
            raise _HttpReject(status, "chat_request_rejected") from None
        except Exception:
            raise _HttpReject(503, "chat_service_unavailable") from None

        if type(response) is not dict:
            raise _HttpReject(503, "chat_service_unavailable")
        try:
            response_bytes = json.dumps(
                response,
                ensure_ascii=False,
                separators=(",", ":"),
                allow_nan=False,
            ).encode("utf-8")
        except (TypeError, ValueError, UnicodeEncodeError, RecursionError):
            raise _HttpReject(503, "chat_service_unavailable") from None
        if not response_bytes or len(response_bytes) > MAX_CHAT_HTTP_RESPONSE_BYTES:
            raise _HttpReject(503, "chat_service_unavailable")

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
    try:
        address = ipaddress.ip_address(value[0].strip("[]"))
    except ValueError:
        return False
    return address.is_loopback


def _require_route(scope: Mapping[str, object]) -> None:
    if scope.get("http_version") not in {"1.1", "2"}:
        raise _HttpReject(400, "unsupported_http_version")
    if scope.get("path") != CHAT_RPC_PATH:
        raise _HttpReject(404, "not_found")
    raw_path = scope.get("raw_path")
    if raw_path is not None and raw_path != CHAT_RPC_PATH.encode("ascii"):
        raise _HttpReject(404, "not_found")
    if scope.get("query_string", b"") != b"":
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
    try:
        parts = [
            part.strip().lower()
            for part in values[0].decode("ascii").split(";")
        ]
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
    max_digits = len(str(MAX_CHAT_HTTP_REQUEST_BYTES))
    if len(text) > max_digits:
        raise _HttpReject(413, "request_too_large")
    value = int(text, 10)
    if value > MAX_CHAT_HTTP_REQUEST_BYTES:
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
    while True:
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
        if len(chunk) > MAX_CHAT_HTTP_REQUEST_BYTES - len(body):
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


def _decode_request_json(body: bytes) -> dict[str, object]:
    try:
        text = body.decode("utf-8")
    except UnicodeDecodeError:
        raise _HttpReject(400, "invalid_request") from None

    def no_duplicates(
        pairs: list[tuple[str, object]],
    ) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate JSON member")
            result[key] = value
        return result

    def reject_constant(_value: str) -> object:
        raise ValueError("non-finite JSON number")

    try:
        value = json.loads(
            text,
            object_pairs_hook=no_duplicates,
            parse_constant=reject_constant,
        )
    except (ValueError, TypeError, RecursionError):
        raise _HttpReject(400, "invalid_request") from None
    if type(value) is not dict:
        raise _HttpReject(400, "invalid_request")
    return value


def _service_error_status(error: ClassroomChatRpcError) -> int:
    message = str(error)
    if message == "chat request identity does not match authenticated transport":
        return 403
    if message == "classroom chat backend failed":
        return 503
    return 400


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
            "classroom chat response delivery failed"
        ) from None


__all__ = [
    "CHAT_RPC_PATH",
    "ClassroomChatHttpAuthenticatorPort",
    "ClassroomChatHttpEndpoint",
    "MAX_AUTHORIZATION_BYTES",
    "MAX_CHAT_HTTP_REQUEST_BYTES",
    "MAX_CHAT_HTTP_RESPONSE_BYTES",
    "MAX_REQUEST_HEADER_BYTES",
]
