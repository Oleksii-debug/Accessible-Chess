from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from pathlib import Path
from urllib.parse import urlsplit
import json
import math

from .subscription_plans import SubscriptionActionKind
from .web_client_gateway import WebPrincipal


_MAX_BODY = 32_768
_MAX_EVENTS = 16
_MAX_TEXT = 16_384
_JSON_TYPE = b"application/json; charset=utf-8"
_HTML_TYPE = b"text/html; charset=utf-8"
_JS_TYPE = b"text/javascript; charset=utf-8"


class SubscriptionWebError(ValueError):
    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.message = message


def _principal(scope: Mapping[str, object]) -> WebPrincipal | None:
    state = scope.get("state")
    if not isinstance(state, Mapping):
        return None
    value = state.get("accessible_chess_principal")
    if value is None:
        return None
    if type(value) is not WebPrincipal:
        raise SubscriptionWebError(401, "Authentication required.")
    return value


def _safe_value(value: object, *, depth: int = 0) -> object:
    if depth > 8:
        raise SubscriptionWebError(400, "Response is too deeply nested.")
    if value is None or type(value) in {bool, int}:
        return value
    if type(value) is float:
        if not math.isfinite(value):
            raise SubscriptionWebError(400, "Invalid numeric value.")
        return value
    if type(value) is str:
        if len(value) > _MAX_TEXT or "\x00" in value:
            raise SubscriptionWebError(400, "Invalid text value.")
        return value
    if type(value) in {list, tuple}:
        if len(value) > 256:
            raise SubscriptionWebError(400, "Too many values.")
        return [_safe_value(item, depth=depth + 1) for item in value]
    if type(value) is dict:
        if len(value) > 64:
            raise SubscriptionWebError(400, "Too many fields.")
        result: dict[str, object] = {}
        for key, item in value.items():
            if type(key) is not str or not key or len(key) > 96:
                raise SubscriptionWebError(400, "Invalid field.")
            result[key] = _safe_value(item, depth=depth + 1)
        return result
    raise SubscriptionWebError(400, "Unsupported value.")


def _safe_navigation_url(value: object) -> str:
    if type(value) is not str or not value or len(value) > 4096:
        raise SubscriptionWebError(400, "Invalid navigation target.")
    if any(ord(ch) < 32 or ch == "\\" for ch in value):
        raise SubscriptionWebError(400, "Invalid navigation target.")
    if value.startswith("/") and not value.startswith("//"):
        return value
    parsed = urlsplit(value)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.fragment
    ):
        raise SubscriptionWebError(400, "Invalid navigation target.")
    try:
        _ = parsed.port
    except ValueError:
        raise SubscriptionWebError(400, "Invalid navigation target.") from None
    return value


class SubscriptionWebGateway:
    """Provider-neutral subscription browser boundary.

    The gateway validates browser envelopes only. Account registration, payment,
    entitlement issuance and cancellation authority remain server-side callbacks.
    """

    def __init__(
        self,
        *,
        snapshot: Callable[[WebPrincipal | None], Mapping[str, object]],
        command: Callable[
            [WebPrincipal | None, SubscriptionActionKind, Mapping[str, object]],
            Mapping[str, object],
        ],
    ) -> None:
        if not callable(snapshot) or not callable(command):
            raise TypeError("snapshot and command must be callable")
        self._snapshot = snapshot
        self._command = command

    def snapshot(self, principal: WebPrincipal | None) -> dict[str, object]:
        if principal is not None and type(principal) is not WebPrincipal:
            raise TypeError("principal must be WebPrincipal or None")
        value = self._snapshot(principal)
        if not isinstance(value, Mapping):
            raise SubscriptionWebError(500, "Subscription state is unavailable.")
        safe = _safe_value(dict(value))
        if type(safe) is not dict:
            raise SubscriptionWebError(500, "Subscription state is unavailable.")
        return {
            "ok": True,
            "signed_in": principal is not None,
            "context": {} if principal is None else dict(principal.public_context()),
            "subscription": safe,
        }

    def command(
        self,
        principal: WebPrincipal | None,
        *,
        action: object,
        payload: object,
    ) -> dict[str, object]:
        try:
            kind = SubscriptionActionKind(str(action))
        except ValueError as exc:
            raise SubscriptionWebError(400, "Unsupported subscription action.") from exc
        if type(payload) is not dict:
            raise SubscriptionWebError(400, "Action payload must be an object.")
        if kind in {
            SubscriptionActionKind.BEGIN_CHECKOUT,
            SubscriptionActionKind.REFRESH_CONFIRMATION,
            SubscriptionActionKind.OPEN_MANAGE,
            SubscriptionActionKind.CANCEL,
        } and principal is None:
            raise SubscriptionWebError(401, "Authentication required.")
        safe_payload = _safe_value(payload)
        if type(safe_payload) is not dict:
            raise SubscriptionWebError(400, "Action payload is invalid.")
        value = self._command(principal, kind, safe_payload)
        if not isinstance(value, Mapping):
            raise SubscriptionWebError(500, "Subscription action failed.")
        safe = _safe_value(dict(value))
        if type(safe) is not dict:
            raise SubscriptionWebError(500, "Subscription action failed.")
        if "navigation_url" in safe:
            safe["navigation_url"] = _safe_navigation_url(safe["navigation_url"])
        return {"ok": True, "result": safe}


def _asset(name: str) -> bytes:
    return (Path(__file__).resolve().parent.parent / "web" / name).read_bytes()


async def _read_body(receive: Callable[[], Awaitable[Mapping[str, object]]]) -> bytes:
    body = bytearray()
    for _ in range(_MAX_EVENTS):
        event = await receive()
        if event.get("type") != "http.request":
            raise SubscriptionWebError(400, "Invalid request.")
        chunk = event.get("body", b"")
        if type(chunk) is not bytes:
            raise SubscriptionWebError(400, "Invalid request.")
        body.extend(chunk)
        if len(body) > _MAX_BODY:
            raise SubscriptionWebError(413, "Request is too large.")
        if not event.get("more_body", False):
            return bytes(body)
    raise SubscriptionWebError(400, "Invalid request.")


def _strict_json(data: bytes) -> dict[str, object]:
    def pairs(items: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in items:
            if key in result:
                raise ValueError("duplicate field")
            result[key] = value
        return result

    try:
        value = json.loads(
            data.decode("utf-8", errors="strict"),
            object_pairs_hook=pairs,
            parse_constant=lambda _value: (_ for _ in ()).throw(ValueError()),
        )
    except (UnicodeDecodeError, ValueError, TypeError):
        raise SubscriptionWebError(400, "Invalid JSON request.") from None
    if type(value) is not dict:
        raise SubscriptionWebError(400, "JSON request must be an object.")
    return value


async def _respond(send, status: int, body: bytes, content_type: bytes) -> None:
    await send({
        "type": "http.response.start",
        "status": status,
        "headers": [
            (b"content-type", content_type),
            (b"content-length", str(len(body)).encode("ascii")),
            (b"cache-control", b"no-store"),
            (b"x-content-type-options", b"nosniff"),
            (b"referrer-policy", b"no-referrer"),
        ],
    })
    await send({"type": "http.response.body", "body": body})


def _json(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode("utf-8")


class AccessibleChessSubscriptionAsgi:
    def __init__(
        self,
        gateway: SubscriptionWebGateway,
        *,
        html: bytes | None = None,
        javascript: bytes | None = None,
    ) -> None:
        if not isinstance(gateway, SubscriptionWebGateway):
            raise TypeError("gateway must be SubscriptionWebGateway")
        self._gateway = gateway
        self._html = html if html is not None else _asset("accessible_chess_subscription.html")
        self._javascript = javascript if javascript is not None else _asset("accessible_chess_subscription.js")

    async def __call__(self, scope, receive, send) -> None:
        if scope.get("type") != "http":
            return
        try:
            if scope.get("query_string", b"") not in {b"", None}:
                raise SubscriptionWebError(400, "Query strings are not supported.")
            method = scope.get("method")
            path = scope.get("path")
            principal = _principal(scope)
            if method == "GET" and path == "/subscription":
                await _respond(send, 200, self._html, _HTML_TYPE)
                return
            if method == "GET" and path == "/assets/accessible_chess_subscription.js":
                await _respond(send, 200, self._javascript, _JS_TYPE)
                return
            if method == "GET" and path == "/v1/subscription/snapshot":
                await _respond(send, 200, _json(self._gateway.snapshot(principal)), _JSON_TYPE)
                return
            if method == "POST" and path == "/v1/subscription/command":
                headers = {item[0].lower(): item[1] for item in scope.get("headers", ()) if isinstance(item, (list, tuple)) and len(item) == 2}
                if headers.get(b"content-type", b"").split(b";", 1)[0].strip().lower() != b"application/json":
                    raise SubscriptionWebError(415, "JSON content type is required.")
                body = _strict_json(await _read_body(receive))
                if set(body) != {"action", "payload"}:
                    raise SubscriptionWebError(400, "Invalid subscription envelope.")
                result = self._gateway.command(principal, action=body["action"], payload=body["payload"])
                await _respond(send, 200, _json(result), _JSON_TYPE)
                return
            raise SubscriptionWebError(404, "Not found.")
        except SubscriptionWebError as error:
            await _respond(send, error.status, _json({"ok": False, "error": error.message}), _JSON_TYPE)
        except Exception:
            await _respond(send, 500, _json({"ok": False, "error": "The action could not be completed."}), _JSON_TYPE)
