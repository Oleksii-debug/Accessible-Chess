from __future__ import annotations

"""Strict ASGI transport for the Accessible Chess browser client."""

from collections.abc import Awaitable, Callable, Mapping
from pathlib import Path
import json

from .web_client_gateway import (
    CanonicalWebGateway,
    WebClientContractError,
    WebPrincipal,
)


_MAX_BODY = 65_536
_MAX_EVENTS = 32
_JSON_TYPE = b"application/json; charset=utf-8"
_HTML_TYPE = b"text/html; charset=utf-8"
_JS_TYPE = b"text/javascript; charset=utf-8"
_NO_STORE = (b"cache-control", b"no-store")
_NOSNIFF = (b"x-content-type-options", b"nosniff")
_REFERRER = (b"referrer-policy", b"no-referrer")


class WebClientHttpError(ValueError):
    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.message = message


def _asset_bytes(name: str) -> bytes:
    root = Path(__file__).resolve().parent.parent / "web"
    return (root / name).read_bytes()


def _trusted_principal(scope: Mapping[str, object]) -> WebPrincipal:
    state = scope.get("state")
    if not isinstance(state, Mapping):
        raise WebClientHttpError(401, "Authentication required.")
    value = state.get("accessible_chess_principal")
    if type(value) is WebPrincipal:
        return value
    raise WebClientHttpError(401, "Authentication required.")


def _headers(scope: Mapping[str, object]) -> dict[bytes, bytes]:
    values: dict[bytes, bytes] = {}
    raw = scope.get("headers", ())
    if not isinstance(raw, (list, tuple)):
        raise WebClientHttpError(400, "Invalid request.")
    for item in raw:
        if (
            not isinstance(item, (list, tuple))
            or len(item) != 2
            or type(item[0]) is not bytes
            or type(item[1]) is not bytes
        ):
            raise WebClientHttpError(400, "Invalid request.")
        name = item[0].lower()
        if name in values:
            raise WebClientHttpError(400, "Duplicate request header.")
        values[name] = item[1]
    return values


async def _read_body(receive: Callable[[], Awaitable[Mapping[str, object]]]) -> bytes:
    body = bytearray()
    events = 0
    while True:
        event = await receive()
        events += 1
        if events > _MAX_EVENTS or event.get("type") != "http.request":
            raise WebClientHttpError(400, "Invalid request.")
        chunk = event.get("body", b"")
        if type(chunk) is not bytes:
            raise WebClientHttpError(400, "Invalid request.")
        body.extend(chunk)
        if len(body) > _MAX_BODY:
            raise WebClientHttpError(413, "Request is too large.")
        if not event.get("more_body", False):
            return bytes(body)


def _strict_json(data: bytes) -> dict[str, object]:
    try:
        text = data.decode("utf-8", errors="strict")
        value = json.loads(
            text,
            object_pairs_hook=lambda pairs: _pairs(pairs),
            parse_constant=lambda _value: (_ for _ in ()).throw(ValueError()),
        )
    except (UnicodeDecodeError, ValueError, TypeError):
        raise WebClientHttpError(400, "Invalid JSON request.") from None
    if type(value) is not dict:
        raise WebClientHttpError(400, "JSON request must be an object.")
    return value


def _pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON field")
        result[key] = value
    return result


async def _respond(send, status: int, body: bytes, content_type: bytes) -> None:
    await send(
        {
            "type": "http.response.start",
            "status": status,
            "headers": [
                (b"content-type", content_type),
                (b"content-length", str(len(body)).encode("ascii")),
                _NO_STORE,
                _NOSNIFF,
                _REFERRER,
            ],
        }
    )
    await send({"type": "http.response.body", "body": body})


def _json_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


class AccessibleChessWebAsgi:
    """Browser transport over CanonicalWebGateway.

    Authentication is deliberately external. Deployment middleware must verify
    the account/session and place a WebPrincipal in ASGI scope state under
    accessible_chess_principal. Browser-supplied user/workspace identifiers are
    never accepted as authority.
    """

    def __init__(
        self,
        gateway: CanonicalWebGateway,
        *,
        html: bytes | None = None,
        javascript: bytes | None = None,
    ) -> None:
        if not isinstance(gateway, CanonicalWebGateway):
            raise TypeError("gateway must be CanonicalWebGateway")
        self._gateway = gateway
        self._html = html if html is not None else _asset_bytes("accessible_chess_web.html")
        self._javascript = (
            javascript
            if javascript is not None
            else _asset_bytes("accessible_chess_web.js")
        )

    async def __call__(self, scope, receive, send) -> None:
        if scope.get("type") != "http":
            return
        try:
            if scope.get("query_string", b"") not in {b"", None}:
                raise WebClientHttpError(400, "Query strings are not supported.")
            method = scope.get("method")
            path = scope.get("path")
            headers = _headers(scope)

            if method == "GET" and path == "/":
                _trusted_principal(scope)
                await _respond(send, 200, self._html, _HTML_TYPE)
                return
            if method == "GET" and path == "/assets/accessible_chess_web.js":
                _trusted_principal(scope)
                await _respond(send, 200, self._javascript, _JS_TYPE)
                return
            if method == "GET" and path == "/v1/snapshot":
                principal = _trusted_principal(scope)
                await _respond(
                    send, 200, _json_bytes(self._gateway.snapshot(principal)), _JSON_TYPE
                )
                return
            if method == "POST" and path == "/v1/command":
                principal = _trusted_principal(scope)
                if headers.get(b"content-type", b"").split(b";", 1)[0].strip().lower() != b"application/json":
                    raise WebClientHttpError(415, "JSON content type is required.")
                body = _strict_json(await _read_body(receive))
                if set(body) != {"area", "command", "payload"}:
                    raise WebClientHttpError(400, "Invalid command envelope.")
                result = self._gateway.command(
                    principal,
                    area=body["area"],
                    command=body["command"],
                    payload=body["payload"],
                )
                await _respond(send, 200, _json_bytes(result), _JSON_TYPE)
                return
            raise WebClientHttpError(404, "Not found.")
        except WebClientContractError:
            await _respond(
                send,
                400,
                _json_bytes({"ok": False, "error": "Invalid browser request."}),
                _JSON_TYPE,
            )
        except WebClientHttpError as error:
            await _respond(
                send,
                error.status,
                _json_bytes({"ok": False, "error": error.message}),
                _JSON_TYPE,
            )
        except Exception:
            await _respond(
                send,
                500,
                _json_bytes({"ok": False, "error": "The action could not be completed."}),
                _JSON_TYPE,
            )
