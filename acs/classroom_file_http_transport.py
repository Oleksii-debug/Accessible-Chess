from __future__ import annotations

"""Authenticated binary HTTP transport for canonical classroom file RPC.

The RPC contract remains authoritative for request semantics. This module owns
only deployment authentication and bounded HTTP framing. Upload bytes stay
opaque: the wire frame is a four-byte big-endian JSON-header length, followed by
strict UTF-8 JSON without a content field, followed by raw upload bytes.
"""

from collections.abc import Awaitable, Callable, Mapping
import http.client
import ipaddress
import json
import math
import re
import struct
from typing import Protocol
from urllib.parse import urlsplit

from .classroom_file_rpc import (
    MAX_RPC_UPLOAD_BYTES,
    ClassroomFileRpcError,
    ClassroomFileRpcService,
)


FILE_RPC_PATH = "/v1/classroom/files"
FILE_RPC_CONTENT_TYPE = "application/vnd.accessible-chess.classroom-file-rpc"
MAX_AUTHORIZATION_BYTES = 8192
MAX_REQUEST_HEADER_BYTES = 16 * 1024
MAX_FILE_HTTP_JSON_BYTES = 512 * 1024
MAX_FILE_HTTP_RESPONSE_BYTES = 64 * 1024 * 1024
MAX_REQUEST_BODY_EVENTS = 128 * 1024
MAX_FILE_HTTP_REQUEST_BYTES = 4 + MAX_FILE_HTTP_JSON_BYTES + MAX_RPC_UPLOAD_BYTES
_UPLOAD_SEND_CHUNK_BYTES = 1024 * 1024

_BEARER_CHALLENGE = (
    (
        b"www-authenticate",
        b'Bearer realm="accessible-chess-classroom-files"',
    ),
)
_HEADER_NAME_RE = re.compile(rb"^[!#$%&'*+.^_`|~0-9A-Za-z-]+$")
_CANONICAL_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")

Receive = Callable[[], Awaitable[dict[str, object]]]
Send = Callable[[dict[str, object]], Awaitable[None]]


class ClassroomFileHttpAuthenticatorPort(Protocol):
    """Deployment authenticator returning one canonical room/caller identity."""

    async def authenticate_bearer(self, bearer_token: str) -> tuple[str, str]:
        ...


class ClassroomFileHttpClientError(RuntimeError):
    """Safe desktop-side failure for the bounded file HTTP transport."""


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
    """Strict ASGI endpoint over one canonical ClassroomFileRpcService."""

    __slots__ = (
        "_service",
        "_authenticator",
        "_allow_insecure_loopback",
    )

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
            raise RuntimeError("classroom file endpoint supports HTTP only")

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
        _require_request_content_type(headers)
        declared_length = _required_content_length(headers)
        bearer = _bearer_token(headers)

        try:
            authenticated = await self._authenticator.authenticate_bearer(bearer)
        except Exception:
            raise _unauthorized() from None
        room_id, participant_id = _validated_authenticated_identity(authenticated)

        body = await _read_body(receive, declared_length=declared_length)
        request = _decode_request_frame(body)

        try:
            response = self._service.handle(
                request,
                authenticated_room_id=room_id,
                authenticated_participant_id=participant_id,
            )
        except ClassroomFileRpcError as error:
            raise _HttpReject(
                _service_error_status(error),
                "file_request_rejected",
            ) from None
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


class ClassroomFileHttpRpcCall:
    """Desktop implementation of ClassroomFileRpcCallPort over bounded HTTP."""

    __slots__ = (
        "_scheme",
        "_host",
        "_port",
        "_bearer_token_provider",
        "_timeout_seconds",
    )

    def __init__(
        self,
        *,
        endpoint_url: str,
        bearer_token_provider: Callable[[], str],
        timeout_seconds: float = 30.0,
        allow_insecure_loopback: bool = False,
    ) -> None:
        if not callable(bearer_token_provider):
            raise TypeError("file HTTP bearer token provider must be callable")
        if type(allow_insecure_loopback) is not bool:
            raise TypeError("allow_insecure_loopback must be bool")
        if (
            type(timeout_seconds) not in {int, float}
            or not math.isfinite(float(timeout_seconds))
            or not 0 < float(timeout_seconds) <= 120
        ):
            raise ValueError("file HTTP timeout must be from 0 to 120 seconds")
        scheme, host, port = _validated_client_endpoint(
            endpoint_url,
            allow_insecure_loopback=allow_insecure_loopback,
        )
        self._scheme = scheme
        self._host = host
        self._port = port
        self._bearer_token_provider = bearer_token_provider
        self._timeout_seconds = float(timeout_seconds)

    def __repr__(self) -> str:
        return (
            "ClassroomFileHttpRpcCall("
            f"scheme={self._scheme!r}, host={self._host!r}, port={self._port!r}, "
            "bearer_token_provider=<bound>)"
        )

    def call(
        self,
        request: Mapping[str, object],
        *,
        on_upload_progress: Callable[[int], None] | None = None,
    ) -> Mapping[str, object]:
        if on_upload_progress is not None and not callable(on_upload_progress):
            raise ClassroomFileHttpClientError(
                "file HTTP upload progress consumer must be callable"
            )
        if type(request) is not dict:
            raise ClassroomFileHttpClientError(
                "classroom file HTTP request must be a canonical object"
            )
        header_bytes, content = _encode_request_frame_parts(request)
        total_length = 4 + len(header_bytes) + len(content)
        if total_length > MAX_FILE_HTTP_REQUEST_BYTES:
            raise ClassroomFileHttpClientError(
                "classroom file HTTP request exceeds transport limit"
            )

        try:
            token = self._bearer_token_provider()
        except Exception:
            raise ClassroomFileHttpClientError(
                "classroom file credential is unavailable"
            ) from None
        token = _validated_bearer_token_text(token)

        connection_type = (
            http.client.HTTPSConnection
            if self._scheme == "https"
            else http.client.HTTPConnection
        )
        connection = connection_type(
            self._host,
            self._port,
            timeout=self._timeout_seconds,
        )
        prefix = struct.pack("!I", len(header_bytes))
        try:
            connection.putrequest(
                "POST",
                FILE_RPC_PATH,
                skip_accept_encoding=True,
            )
            connection.putheader("Authorization", f"Bearer {token}")
            connection.putheader("Content-Type", FILE_RPC_CONTENT_TYPE)
            connection.putheader("Accept", "application/json")
            connection.putheader("Content-Length", str(total_length))
            connection.endheaders()
            connection.send(prefix)
            connection.send(header_bytes)
            if content:
                if on_upload_progress is not None:
                    on_upload_progress(0)
                view = memoryview(content)
                transferred = 0
                while transferred < len(content):
                    next_offset = min(
                        transferred + _UPLOAD_SEND_CHUNK_BYTES,
                        len(content),
                    )
                    connection.send(view[transferred:next_offset])
                    transferred = next_offset
                    if on_upload_progress is not None:
                        on_upload_progress(transferred)
            elif request.get("op") == "upload" and on_upload_progress is not None:
                on_upload_progress(0)
            response = connection.getresponse()
            return _read_client_response(response)
        except ClassroomFileHttpClientError:
            raise
        except ClassroomFileRpcError:
            raise
        except Exception:
            raise ClassroomFileHttpClientError(
                "classroom file HTTP transport failed"
            ) from None
        finally:
            try:
                connection.close()
            except Exception:
                pass


def _encode_request_frame_parts(
    request: dict[str, object],
) -> tuple[bytes, bytes]:
    envelope = dict(request)
    op = envelope.get("op")
    if op == "upload":
        content = envelope.pop("content", None)
        if type(content) is not bytes:
            raise ClassroomFileHttpClientError(
                "file upload requires opaque byte content"
            )
        if len(content) > MAX_RPC_UPLOAD_BYTES:
            raise ClassroomFileHttpClientError(
                "file upload exceeds transport limit"
            )
    else:
        if "content" in envelope:
            raise ClassroomFileHttpClientError(
                "non-upload file request cannot contain opaque content"
            )
        content = b""

    try:
        header = json.dumps(
            envelope,
            ensure_ascii=False,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError, UnicodeEncodeError, RecursionError):
        raise ClassroomFileHttpClientError(
            "classroom file HTTP request header is not serializable"
        ) from None
    if not header or len(header) > MAX_FILE_HTTP_JSON_BYTES:
        raise ClassroomFileHttpClientError(
            "classroom file HTTP request header exceeds transport limit"
        )
    return header, content


def _decode_request_frame(body: bytes) -> dict[str, object]:
    if type(body) is not bytes or len(body) < 5:
        raise _HttpReject(400, "invalid_file_frame")
    header_length = struct.unpack("!I", body[:4])[0]
    if (
        header_length < 1
        or header_length > MAX_FILE_HTTP_JSON_BYTES
        or 4 + header_length > len(body)
    ):
        raise _HttpReject(400, "invalid_file_frame")
    header = _decode_json_object(body[4 : 4 + header_length])
    if "content" in header:
        raise _HttpReject(400, "invalid_file_frame")
    content = body[4 + header_length :]
    if header.get("op") == "upload":
        if len(content) > MAX_RPC_UPLOAD_BYTES:
            raise _HttpReject(413, "request_too_large")
        header["content"] = content
    elif content:
        raise _HttpReject(400, "unexpected_binary_content")
    return header


def _decode_json_object(body: bytes) -> dict[str, object]:
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


def _encode_response(response: object) -> bytes:
    if type(response) is not dict:
        raise _HttpReject(503, "file_service_unavailable")
    try:
        payload = json.dumps(
            response,
            ensure_ascii=False,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError, UnicodeEncodeError, RecursionError):
        raise _HttpReject(503, "file_service_unavailable") from None
    if not payload or len(payload) > MAX_FILE_HTTP_RESPONSE_BYTES:
        raise _HttpReject(503, "file_service_unavailable")
    return payload


def _validated_client_endpoint(
    value: object,
    *,
    allow_insecure_loopback: bool,
) -> tuple[str, str, int]:
    if type(value) is not str or not value or len(value) > 2048:
        raise ValueError("file HTTP endpoint URL is invalid")
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except ValueError:
        raise ValueError("file HTTP endpoint URL is invalid") from None
    if (
        parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
        or parsed.path != FILE_RPC_PATH
        or parsed.hostname is None
    ):
        raise ValueError("file HTTP endpoint URL is invalid")
    scheme = parsed.scheme.lower()
    host = parsed.hostname
    try:
        host_ascii = host.encode("idna").decode("ascii")
    except UnicodeError:
        raise ValueError("file HTTP endpoint URL is invalid") from None
    if (
        not host_ascii
        or len(host_ascii) > 253
        or any(ord(ch) <= 32 or ord(ch) == 127 for ch in host_ascii)
        or (port is not None and not 1 <= port <= 65535)
    ):
        raise ValueError("file HTTP endpoint URL is invalid")
    if scheme == "https":
        return scheme, host_ascii, 443 if port is None else port
    if (
        scheme == "http"
        and allow_insecure_loopback
        and _host_is_literal_loopback(host_ascii)
    ):
        return scheme, host_ascii, 80 if port is None else port
    raise ValueError("file HTTP endpoint must use HTTPS")


def _host_is_literal_loopback(host: str) -> bool:
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def _validated_authenticated_identity(value: object) -> tuple[str, str]:
    if (
        type(value) is not tuple
        or len(value) != 2
        or type(value[0]) is not str
        or type(value[1]) is not str
        or _CANONICAL_ID_RE.fullmatch(value[0]) is None
        or _CANONICAL_ID_RE.fullmatch(value[1]) is None
    ):
        raise _unauthorized()
    return value[0], value[1]


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


def _require_request_content_type(
    headers: Mapping[bytes, tuple[bytes, ...]],
) -> None:
    raw = _single_header(headers, b"content-type", required=True)
    assert raw is not None
    try:
        value = raw.decode("ascii").strip().lower()
    except UnicodeDecodeError:
        raise _HttpReject(415, "unsupported_media_type") from None
    if value != FILE_RPC_CONTENT_TYPE:
        raise _HttpReject(415, "unsupported_media_type")


def _required_content_length(
    headers: Mapping[bytes, tuple[bytes, ...]],
) -> int:
    raw = _single_header(headers, b"content-length", required=True)
    assert raw is not None
    try:
        text = raw.decode("ascii")
    except UnicodeDecodeError:
        raise _HttpReject(400, "invalid_content_length") from None
    if not text or not text.isdigit():
        raise _HttpReject(400, "invalid_content_length")
    if len(text) > len(str(MAX_FILE_HTTP_REQUEST_BYTES)):
        raise _HttpReject(413, "request_too_large")
    value = int(text, 10)
    if value < 5:
        raise _HttpReject(400, "invalid_file_frame")
    if value > MAX_FILE_HTTP_REQUEST_BYTES:
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
    return _validated_bearer_token_text(
        text[7:],
        error_type="server",
    )


def _validated_bearer_token_text(
    value: object,
    *,
    error_type: str = "client",
) -> str:
    valid = type(value) is str
    if valid:
        try:
            encoded = value.encode("ascii")
        except UnicodeEncodeError:
            valid = False
            encoded = b""
    else:
        encoded = b""
    if (
        not valid
        or not encoded
        or len(encoded) > MAX_AUTHORIZATION_BYTES - len(b"Bearer ")
        or value != value.strip()
        or any(ord(ch) <= 32 or ord(ch) == 127 for ch in value)
    ):
        if error_type == "server":
            raise _unauthorized()
        raise ClassroomFileHttpClientError(
            "classroom file credential is invalid"
        )
    return value


def _unauthorized() -> _HttpReject:
    return _HttpReject(
        401,
        "unauthorized",
        extra_headers=_BEARER_CHALLENGE,
    )


async def _read_body(
    receive: Receive,
    *,
    declared_length: int,
) -> bytes:
    chunks: list[bytes] = []
    size = 0
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
        if len(chunk) > declared_length - size:
            raise _HttpReject(400, "content_length_mismatch")
        chunks.append(chunk)
        size += len(chunk)
        more = event.get("more_body", False)
        if type(more) is not bool:
            raise _HttpReject(400, "invalid_request")
        if not more:
            break
    if size != declared_length:
        raise _HttpReject(400, "content_length_mismatch")
    return b"".join(chunks)


def _service_error_status(error: ClassroomFileRpcError) -> int:
    message = str(error)
    if message == "file request identity does not match authenticated transport":
        return 403
    if message.startswith("classroom file backend"):
        return 503
    return 400


def _send_headers(
    body: bytes,
    *,
    extra_headers: tuple[tuple[bytes, bytes], ...],
) -> tuple[tuple[bytes, bytes], ...]:
    return (
        (b"content-type", b"application/json; charset=utf-8"),
        (b"content-length", str(len(body)).encode("ascii")),
        (b"cache-control", b"no-store"),
        (b"pragma", b"no-cache"),
        (b"x-content-type-options", b"nosniff"),
        *extra_headers,
    )


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
    try:
        await send(
            {
                "type": "http.response.start",
                "status": status,
                "headers": list(
                    _send_headers(body, extra_headers=extra_headers)
                ),
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
            "classroom file response delivery failed"
        ) from None


def _read_client_response(response: object) -> dict[str, object]:
    status = getattr(response, "status", None)
    getheaders = getattr(response, "getheaders", None)
    read = getattr(response, "read", None)
    if type(status) is not int or not callable(getheaders) or not callable(read):
        raise ClassroomFileHttpClientError(
            "classroom file HTTP response is invalid"
        )
    try:
        raw_headers = getheaders()
    except Exception:
        raise ClassroomFileHttpClientError(
            "classroom file HTTP response headers are unavailable"
        ) from None
    if type(raw_headers) is not list:
        raise ClassroomFileHttpClientError(
            "classroom file HTTP response headers are invalid"
        )

    grouped: dict[str, list[str]] = {}
    header_bytes = 0
    for entry in raw_headers:
        if (
            type(entry) not in {tuple, list}
            or len(entry) != 2
            or type(entry[0]) is not str
            or type(entry[1]) is not str
        ):
            raise ClassroomFileHttpClientError(
                "classroom file HTTP response headers are invalid"
            )
        name, value = entry
        try:
            name_bytes = name.encode("ascii")
            value_bytes = value.encode("latin1")
        except UnicodeEncodeError:
            raise ClassroomFileHttpClientError(
                "classroom file HTTP response headers are invalid"
            ) from None
        if (
            _HEADER_NAME_RE.fullmatch(name_bytes) is None
            or any(byte < 32 or byte == 127 for byte in value_bytes)
        ):
            raise ClassroomFileHttpClientError(
                "classroom file HTTP response headers are invalid"
            )
        header_bytes += len(name_bytes) + len(value_bytes)
        if header_bytes > MAX_REQUEST_HEADER_BYTES:
            raise ClassroomFileHttpClientError(
                "classroom file HTTP response headers are too large"
            )
        grouped.setdefault(name.lower(), []).append(value)

    if "content-encoding" in grouped or "transfer-encoding" in grouped:
        raise ClassroomFileHttpClientError(
            "classroom file HTTP response encoding is unsupported"
        )
    content_types = grouped.get("content-type", [])
    lengths = grouped.get("content-length", [])
    if (
        len(content_types) != 1
        or content_types[0].strip().lower()
        != "application/json; charset=utf-8"
        or len(lengths) != 1
    ):
        raise ClassroomFileHttpClientError(
            "classroom file HTTP response metadata is invalid"
        )
    raw_length = lengths[0].strip()
    if not raw_length.isdigit() or len(raw_length) > len(
        str(MAX_FILE_HTTP_RESPONSE_BYTES)
    ):
        raise ClassroomFileHttpClientError(
            "classroom file HTTP response length is invalid"
        )
    expected_length = int(raw_length, 10)
    if expected_length > MAX_FILE_HTTP_RESPONSE_BYTES:
        raise ClassroomFileHttpClientError(
            "classroom file HTTP response exceeds transport limit"
        )
    try:
        body = read(MAX_FILE_HTTP_RESPONSE_BYTES + 1)
    except Exception:
        raise ClassroomFileHttpClientError(
            "classroom file HTTP response body is unavailable"
        ) from None
    if (
        type(body) is not bytes
        or not body
        or len(body) > MAX_FILE_HTTP_RESPONSE_BYTES
        or len(body) != expected_length
    ):
        raise ClassroomFileHttpClientError(
            "classroom file HTTP response body is invalid"
        )
    if status != 200:
        raise ClassroomFileHttpClientError(
            "classroom file HTTP request was rejected"
        )
    try:
        return _decode_client_json(body)
    except ClassroomFileHttpClientError:
        raise


def _decode_client_json(body: bytes) -> dict[str, object]:
    try:
        text = body.decode("utf-8")
    except UnicodeDecodeError:
        raise ClassroomFileHttpClientError(
            "classroom file HTTP response JSON is invalid"
        ) from None

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
        raise ClassroomFileHttpClientError(
            "classroom file HTTP response JSON is invalid"
        ) from None
    if type(value) is not dict:
        raise ClassroomFileHttpClientError(
            "classroom file HTTP response JSON is invalid"
        )
    return value


__all__ = [
    "FILE_RPC_CONTENT_TYPE",
    "FILE_RPC_PATH",
    "ClassroomFileHttpAuthenticatorPort",
    "ClassroomFileHttpClientError",
    "ClassroomFileHttpEndpoint",
    "ClassroomFileHttpRpcCall",
    "MAX_AUTHORIZATION_BYTES",
    "MAX_FILE_HTTP_JSON_BYTES",
    "MAX_FILE_HTTP_REQUEST_BYTES",
    "MAX_FILE_HTTP_RESPONSE_BYTES",
    "MAX_REQUEST_BODY_EVENTS",
    "MAX_REQUEST_HEADER_BYTES",
]
