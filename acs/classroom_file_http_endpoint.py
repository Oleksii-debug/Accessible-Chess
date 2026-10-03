from __future__ import annotations

"""HTTPS ASGI transport for the canonical authenticated classroom file RPC.

The HTTP layer owns framing, bearer authentication and transport safety only.
Room/file authorization, quota, scanning, persistence, object storage and file
semantics remain in ClassroomFileRpcService and its trusted backend.

Upload bytes are carried after a bounded JSON frame rather than base64-encoded,
so arbitrary binary content stays opaque and does not incur JSON/base64 expansion.
"""

from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
import ipaddress
import json
import re
from typing import Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

from .classroom_file_rpc import (
    MAX_RPC_UPLOAD_BYTES,
    ClassroomFileRpcError,
    ClassroomFileRpcService,
    _opaque_id,
)


FILE_RPC_PATH = "/v1/classroom/file-rpc"
FILE_RPC_MEDIA_TYPE = "application/vnd.accessible-chess.classroom-file-rpc"
FRAME_MAGIC = b"ACFRPC1\n"
MAX_FRAME_JSON_BYTES = 64 * 1024
MAX_AUTHORIZATION_BYTES = 8192
MAX_REQUEST_HEADER_BYTES = 16 * 1024
MAX_FILE_HTTP_BODY_BYTES = (
    len(FRAME_MAGIC) + 4 + MAX_FRAME_JSON_BYTES + MAX_RPC_UPLOAD_BYTES
)
MAX_FILE_HTTP_RESPONSE_BYTES = 32 * 1024 * 1024
FILE_HTTP_UPLOAD_CHUNK_BYTES = 64 * 1024
_BEARER_CHALLENGE = (
    (b"www-authenticate", b'Bearer realm="accessible-chess-classroom"'),
)
_HEADER_NAME_RE = re.compile(rb"^[!#$%&'*+.^_`|~0-9A-Za-z-]+$")

Receive = Callable[[], Awaitable[dict[str, object]]]
Send = Callable[[dict[str, object]], Awaitable[None]]


@dataclass(frozen=True, slots=True)
class ClassroomFileHttpPrincipal:
    """Canonical room + participant identity proven by deployment authentication."""

    room_id: str
    participant_id: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "room_id", _opaque_id(self.room_id, "room id"))
        object.__setattr__(
            self,
            "participant_id",
            _opaque_id(self.participant_id, "participant id"),
        )


class ClassroomFileHttpAuthenticatorPort(Protocol):
    """Trusted deployment bearer verifier; no credential storage is owned here."""

    async def authenticate_bearer(
        self,
        bearer_token: str,
    ) -> ClassroomFileHttpPrincipal:
        ...


class ClassroomFileHttpBearerPort(Protocol):
    """Desktop credential supplier; tokens are requested per call and never stored."""

    def bearer_token(self) -> str:
        ...


class ClassroomFileHttpOpenPort(Protocol):
    """Small urllib-compatible seam used for deterministic transport tests."""

    def open(self, request: Request, *, timeout: float):
        ...


class _NoRedirectHandler(HTTPRedirectHandler):
    """Never forward Authorization through an HTTP redirect."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class ClassroomFileHttpCallTransport:
    """Concrete synchronous HTTP call port for ClassroomFileRpcClient."""

    __slots__ = (
        "_endpoint_url",
        "_bearer",
        "_timeout_seconds",
        "_opener",
        "_allow_insecure_loopback",
    )

    def __init__(
        self,
        *,
        endpoint_url: str,
        bearer: ClassroomFileHttpBearerPort,
        timeout_seconds: float = 30.0,
        allow_insecure_loopback: bool = False,
        opener: ClassroomFileHttpOpenPort | None = None,
    ) -> None:
        if type(allow_insecure_loopback) is not bool:
            raise TypeError("allow_insecure_loopback must be bool")
        self._endpoint_url = _validated_endpoint_url(
            endpoint_url,
            allow_insecure_loopback=allow_insecure_loopback,
        )
        if bearer is None or not callable(getattr(bearer, "bearer_token", None)):
            raise TypeError("file HTTP transport requires a bearer supplier")
        if (
            type(timeout_seconds) not in {int, float}
            or isinstance(timeout_seconds, bool)
            or not 0 < float(timeout_seconds) <= 120.0
        ):
            raise ValueError("file HTTP timeout must be from 0 to 120 seconds")
        if opener is None:
            opener = build_opener(_NoRedirectHandler())
        if not callable(getattr(opener, "open", None)):
            raise TypeError("file HTTP transport opener is invalid")
        self._bearer = bearer
        self._timeout_seconds = float(timeout_seconds)
        self._opener = opener
        self._allow_insecure_loopback = allow_insecure_loopback

    def __repr__(self) -> str:
        return (
            "ClassroomFileHttpCallTransport("
            f"endpoint_url={self._endpoint_url!r}, bearer=<bound>, "
            f"timeout_seconds={self._timeout_seconds!r}, "
            f"allow_insecure_loopback={self._allow_insecure_loopback!r})"
        )

class _ProgressHttpBody:
    """Fixed-length iterable that reports opaque upload bytes as they are sent."""

    __slots__ = ("_prefix", "_content", "_consumer")

    def __init__(
        self,
        prefix: bytes,
        content: bytes,
        consumer: Callable[[int], None],
    ) -> None:
        self._prefix = prefix
        self._content = content
        self._consumer = consumer

    def __iter__(self):
        # The framing prefix is transport overhead, not file progress.
        self._consumer(0)
        if self._prefix:
            yield self._prefix
        transferred = 0
        for start in range(0, len(self._content), FILE_HTTP_UPLOAD_CHUNK_BYTES):
            chunk = self._content[start:start + FILE_HTTP_UPLOAD_CHUNK_BYTES]
            yield chunk
            transferred += len(chunk)
            # Iteration resumes only after http.client consumed the yielded
            # chunk, so this sample tracks bytes handed to the socket layer,
            # not a synthetic post-response completion marker.
            self._consumer(transferred)


    def call(
        self,
        request: Mapping[str, object],
        *,
        on_upload_progress: Callable[[int], None] | None = None,
    ) -> Mapping[str, object]:
        if on_upload_progress is not None and not callable(on_upload_progress):
            raise ClassroomFileRpcError(
                "file HTTP upload progress consumer must be callable"
            )
        is_upload = type(request) is dict and request.get("op") == "upload"
        if on_upload_progress is not None and not is_upload:
            raise ClassroomFileRpcError(
                "file HTTP upload progress is valid for upload only"
            )
        upload_size = 0
        if is_upload:
            content = request.get("content")
            if type(content) is not bytes:
                raise ClassroomFileRpcError(
                    "file upload content must be opaque bytes"
                )
            upload_size = len(content)
        try:
            token = self._bearer.bearer_token()
        except Exception:
            raise ClassroomFileRpcError(
                "classroom file HTTP authentication unavailable"
            ) from None
        bearer = _client_bearer_token(token)
        prefix, content = _encode_file_rpc_http_parts(request)
        body_length = len(prefix) + len(content)
        body: object
        if is_upload and on_upload_progress is not None:
            body = _ProgressHttpBody(prefix, content, on_upload_progress)
        else:
            body = prefix + content
        http_request = Request(
            self._endpoint_url,
            data=body,
            method="POST",
            headers={
                "Content-Type": FILE_RPC_MEDIA_TYPE,
                "Authorization": f"Bearer {bearer}",
                "Content-Length": str(body_length),
                "Accept": "application/json",
            },
        )
        try:
            response = self._opener.open(
                http_request,
                timeout=self._timeout_seconds,
            )
            with response:
                status = getattr(response, "status", None)
                if type(status) is not int or status != 200:
                    raise ClassroomFileRpcError(
                        "classroom file HTTP request failed"
                    )
                headers = getattr(response, "headers", None)
                _validate_http_response_headers(headers)
                body = response.read(MAX_FILE_HTTP_RESPONSE_BYTES + 1)
                if type(body) is not bytes or len(body) > MAX_FILE_HTTP_RESPONSE_BYTES:
                    raise ClassroomFileRpcError(
                        "classroom file HTTP response is invalid"
                    )
                _validate_response_content_length(headers, len(body))
        except ClassroomFileRpcError:
            raise
        except (HTTPError, URLError, OSError, TimeoutError):
            raise ClassroomFileRpcError(
                "classroom file HTTP request failed"
            ) from None
        except Exception:
            raise ClassroomFileRpcError(
                "classroom file HTTP request failed"
            ) from None
        return _decode_http_response(body)


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


class ClassroomFileHttpEndpoint:
    """Minimal authenticated ASGI endpoint for one binary-capable file RPC route."""

    __slots__ = ("_service", "_authenticator", "_allow_insecure_loopback")

    def __init__(
        self,
        *,
        service: ClassroomFileRpcService,
        authenticator: ClassroomFileHttpAuthenticatorPort,
        allow_insecure_loopback: bool = False,
    ) -> None:
        if not isinstance(service, ClassroomFileRpcService):
            raise TypeError("file HTTP endpoint requires ClassroomFileRpcService")
        if authenticator is None or not callable(
            getattr(authenticator, "authenticate_bearer", None)
        ):
            raise TypeError("file HTTP endpoint requires an authenticator")
        if type(allow_insecure_loopback) is not bool:
            raise TypeError("allow_insecure_loopback must be bool")
        self._service = service
        self._authenticator = authenticator
        self._allow_insecure_loopback = allow_insecure_loopback

    def __repr__(self) -> str:
        return (
            "ClassroomFileHttpEndpoint("
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
            raise RuntimeError("file RPC endpoint supports HTTP only")
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
        _require_file_rpc_content_type(headers)
        declared_length = _content_length(headers)
        bearer = _bearer_token(headers)
        try:
            principal = await self._authenticator.authenticate_bearer(bearer)
        except Exception:
            raise _unauthorized() from None
        if type(principal) is not ClassroomFileHttpPrincipal:
            raise _unauthorized()

        body = await _read_body(receive, declared_length=declared_length)
        request = _decode_file_rpc_http_frame(body)
        _require_frame_identity(request, principal)
        try:
            response = self._service.handle(
                request,
                authenticated_room_id=principal.room_id,
                authenticated_participant_id=principal.participant_id,
            )
        except ClassroomFileRpcError as error:
            if str(error) in {
                "classroom file backend failed",
                "classroom file service unavailable",
            }:
                raise _HttpReject(503, "file_service_unavailable") from None
            raise _HttpReject(400, "file_request_rejected") from None
        except Exception:
            raise _HttpReject(503, "file_service_unavailable") from None

        response_bytes = _encode_response(response)
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


def _encode_file_rpc_http_parts(
    request: Mapping[str, object],
) -> tuple[bytes, bytes]:
    """Encode bounded structured metadata separately from opaque upload bytes."""
    if type(request) is not dict:
        raise ClassroomFileRpcError("file HTTP request must be an object")
    header = dict(request)
    content = header.pop("content", b"")
    op = header.get("op")
    if op == "upload":
        if type(content) is not bytes:
            raise ClassroomFileRpcError("file upload content must be opaque bytes")
        if len(content) > MAX_RPC_UPLOAD_BYTES:
            raise ClassroomFileRpcError("file exceeds HTTP upload limit")
    elif content != b"":
        raise ClassroomFileRpcError(
            "non-upload file RPC cannot carry opaque content"
        )
    try:
        json_bytes = json.dumps(
            header,
            ensure_ascii=True,
            allow_nan=False,
            separators=(",", ":"),
        ).encode("ascii")
    except (TypeError, ValueError, UnicodeEncodeError):
        raise ClassroomFileRpcError(
            "file HTTP request metadata is not JSON-safe"
        ) from None
    if not json_bytes or len(json_bytes) > MAX_FRAME_JSON_BYTES:
        raise ClassroomFileRpcError("file HTTP request metadata is too large")
    prefix = (
        FRAME_MAGIC
        + len(json_bytes).to_bytes(4, "big")
        + json_bytes
    )
    return prefix, content


def encode_file_rpc_http_frame(request: Mapping[str, object]) -> bytes:
    """Encode one RPC request without base64-expanding an upload body."""
    prefix, content = _encode_file_rpc_http_parts(request)
    return prefix + content


def _decode_file_rpc_http_frame(body: bytes) -> dict[str, object]:
    prefix = len(FRAME_MAGIC) + 4
    if type(body) is not bytes or len(body) < prefix:
        raise _HttpReject(400, "invalid_file_rpc_frame")
    if body[: len(FRAME_MAGIC)] != FRAME_MAGIC:
        raise _HttpReject(400, "invalid_file_rpc_frame")
    json_length = int.from_bytes(
        body[len(FRAME_MAGIC):prefix],
        "big",
        signed=False,
    )
    if not 1 <= json_length <= MAX_FRAME_JSON_BYTES:
        raise _HttpReject(400, "invalid_file_rpc_frame")
    end = prefix + json_length
    if end > len(body):
        raise _HttpReject(400, "invalid_file_rpc_frame")
    try:
        header_text = body[prefix:end].decode("ascii")
        request = json.loads(
            header_text,
            object_pairs_hook=_closed_json_object,
            parse_constant=_reject_json_constant,
        )
    except (UnicodeDecodeError, ValueError, TypeError):
        raise _HttpReject(400, "invalid_file_rpc_frame") from None
    if type(request) is not dict or "content" in request:
        raise _HttpReject(400, "invalid_file_rpc_frame")
    opaque = body[end:]
    if request.get("op") == "upload":
        raw_metadata = request.get("metadata")
        if type(raw_metadata) is not dict:
            raise _HttpReject(400, "invalid_file_rpc_frame")
        size = raw_metadata.get("size_bytes")
        if (
            type(size) is not int
            or not 0 <= size <= MAX_RPC_UPLOAD_BYTES
            or len(opaque) != size
        ):
            raise _HttpReject(400, "invalid_file_rpc_frame")
        request["content"] = opaque
    elif opaque:
        raise _HttpReject(400, "invalid_file_rpc_frame")
    return request


def _closed_json_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def _reject_json_constant(value: str) -> object:
    raise ValueError(f"non-finite JSON number: {value}")


def _require_frame_identity(
    request: Mapping[str, object],
    principal: ClassroomFileHttpPrincipal,
) -> None:
    if (
        request.get("room_id") != principal.room_id
        or request.get("participant_id") != principal.participant_id
    ):
        raise _HttpReject(403, "authenticated_identity_mismatch")


def _encode_response(response: Mapping[str, object]) -> bytes:
    if type(response) is not dict:
        raise _HttpReject(503, "file_service_unavailable")
    try:
        payload = json.dumps(
            response,
            ensure_ascii=True,
            allow_nan=False,
            separators=(",", ":"),
        ).encode("ascii")
    except (TypeError, ValueError, UnicodeEncodeError):
        raise _HttpReject(503, "file_service_unavailable") from None
    if not payload or len(payload) > MAX_FILE_HTTP_RESPONSE_BYTES:
        raise _HttpReject(503, "file_service_unavailable")
    return payload


def _validated_endpoint_url(
    value: object,
    *,
    allow_insecure_loopback: bool,
) -> str:
    if type(value) is not str or not value or len(value) > 4096:
        raise ValueError("file HTTP endpoint URL is invalid")
    try:
        parsed = urlsplit(value)
    except ValueError:
        raise ValueError("file HTTP endpoint URL is invalid") from None
    if (
        parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
        or not parsed.hostname
        or parsed.path != FILE_RPC_PATH
    ):
        raise ValueError("file HTTP endpoint URL is invalid")
    if parsed.scheme == "https":
        pass
    elif (
        parsed.scheme == "http"
        and allow_insecure_loopback
        and _host_is_loopback(parsed.hostname)
    ):
        pass
    else:
        raise ValueError("file HTTP endpoint URL requires HTTPS")
    try:
        parsed.port
    except ValueError:
        raise ValueError("file HTTP endpoint URL is invalid") from None
    return value


def _host_is_loopback(host: str) -> bool:
    try:
        return ipaddress.ip_address(host.strip("[]")).is_loopback
    except ValueError:
        return False


def _client_bearer_token(value: object) -> str:
    if (
        type(value) is not str
        or not value
        or len(value.encode("utf-8")) > MAX_AUTHORIZATION_BYTES - 7
        or value != value.strip()
        or any(ord(ch) <= 32 or ord(ch) == 127 for ch in value)
        or any(ord(ch) > 127 for ch in value)
    ):
        raise ClassroomFileRpcError(
            "classroom file HTTP bearer token is invalid"
        )
    return value


def _header_value(headers: object, name: str) -> str | None:
    if headers is None:
        return None
    getter = getattr(headers, "get", None)
    if not callable(getter):
        return None
    value = getter(name)
    if value is None:
        value = getter(name.lower())
    if value is None:
        return None
    if type(value) is not str:
        return str(value)
    return value


def _validate_http_response_headers(headers: object) -> None:
    content_type = _header_value(headers, "Content-Type")
    if content_type is None:
        raise ClassroomFileRpcError(
            "classroom file HTTP response is invalid"
        )
    normalized = [part.strip().lower() for part in content_type.split(";")]
    if not normalized or normalized[0] != "application/json":
        raise ClassroomFileRpcError(
            "classroom file HTTP response is invalid"
        )
    if len(normalized) > 2 or (
        len(normalized) == 2 and normalized[1] != "charset=utf-8"
    ):
        raise ClassroomFileRpcError(
            "classroom file HTTP response is invalid"
        )
    if _header_value(headers, "Content-Encoding") is not None:
        raise ClassroomFileRpcError(
            "classroom file HTTP response is invalid"
        )
    cache_control = _header_value(headers, "Cache-Control")
    if cache_control is None or "no-store" not in {
        item.strip().lower() for item in cache_control.split(",")
    }:
        raise ClassroomFileRpcError(
            "classroom file HTTP response is not privacy-safe"
        )


def _validate_response_content_length(headers: object, actual: int) -> None:
    raw = _header_value(headers, "Content-Length")
    if raw is None or not raw.isdigit():
        raise ClassroomFileRpcError(
            "classroom file HTTP response length is invalid"
        )
    if len(raw) > len(str(MAX_FILE_HTTP_RESPONSE_BYTES)):
        raise ClassroomFileRpcError(
            "classroom file HTTP response length is invalid"
        )
    declared = int(raw, 10)
    if declared != actual or declared > MAX_FILE_HTTP_RESPONSE_BYTES:
        raise ClassroomFileRpcError(
            "classroom file HTTP response length is invalid"
        )


def _decode_http_response(body: bytes) -> dict[str, object]:
    try:
        text = body.decode("utf-8")
        value = json.loads(
            text,
            object_pairs_hook=_closed_json_object,
            parse_constant=_reject_json_constant,
        )
    except (UnicodeDecodeError, ValueError, TypeError):
        raise ClassroomFileRpcError(
            "classroom file HTTP response is invalid"
        ) from None
    if type(value) is not dict:
        raise ClassroomFileRpcError(
            "classroom file HTTP response is invalid"
        )
    return value


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
    if scope.get("path") != FILE_RPC_PATH:
        raise _HttpReject(404, "not_found")
    raw_path = scope.get("raw_path")
    if raw_path is not None and raw_path != FILE_RPC_PATH.encode("ascii"):
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


def _require_file_rpc_content_type(
    headers: Mapping[bytes, tuple[bytes, ...]],
) -> None:
    raw = _single_header(headers, b"content-type", required=True)
    assert raw is not None
    try:
        media_type = raw.decode("ascii").strip().lower()
    except UnicodeDecodeError:
        raise _HttpReject(415, "unsupported_media_type") from None
    if media_type != FILE_RPC_MEDIA_TYPE:
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
    if len(text) > len(str(MAX_FILE_HTTP_BODY_BYTES)):
        raise _HttpReject(413, "request_too_large")
    value = int(text, 10)
    if value > MAX_FILE_HTTP_BODY_BYTES:
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
        if len(chunk) > MAX_FILE_HTTP_BODY_BYTES - len(body):
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
            "file RPC response delivery failed"
        ) from None


__all__ = [
    "ClassroomFileHttpAuthenticatorPort",
    "ClassroomFileHttpBearerPort",
    "ClassroomFileHttpCallTransport",
    "ClassroomFileHttpEndpoint",
    "ClassroomFileHttpOpenPort",
    "ClassroomFileHttpPrincipal",
    "FILE_HTTP_UPLOAD_CHUNK_BYTES",
    "FILE_RPC_MEDIA_TYPE",
    "FILE_RPC_PATH",
    "FRAME_MAGIC",
    "MAX_AUTHORIZATION_BYTES",
    "MAX_FILE_HTTP_BODY_BYTES",
    "MAX_FILE_HTTP_RESPONSE_BYTES",
    "MAX_FRAME_JSON_BYTES",
    "MAX_REQUEST_HEADER_BYTES",
    "encode_file_rpc_http_frame",
]
