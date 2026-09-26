from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import json
import socket
import ssl
from typing import Mapping
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, HTTPSHandler, Request, build_opener


class TransportErrorCode(str, Enum):
    INVALID_REQUEST = "invalid_request"
    TIMEOUT = "timeout"
    TLS = "tls"
    NETWORK = "network"
    REDIRECT = "redirect"
    HTTP_STATUS = "http_status"
    RESPONSE_TOO_LARGE = "response_too_large"
    INVALID_CONTENT_TYPE = "invalid_content_type"
    INVALID_JSON = "invalid_json"


class SecureHttpError(RuntimeError):
    """Bounded transport error that never includes URLs, bodies, or headers."""

    def __init__(self, code: TransportErrorCode, *, status: int | None = None) -> None:
        self.code = code
        self.status = status
        suffix = f" status={status}" if status is not None else ""
        super().__init__(f"secure HTTP transport failed: {code.value}{suffix}")


@dataclass(frozen=True)
class JsonResponse:
    status: int
    value: object
    content_type: str


class _RejectRedirects(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ANN001
        raise SecureHttpError(TransportErrorCode.REDIRECT, status=int(code))


def _default_opener():
    context = ssl.create_default_context()
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    context.check_hostname = True
    context.verify_mode = ssl.CERT_REQUIRED
    return build_opener(_RejectRedirects(), HTTPSHandler(context=context))


class BoundedHttpsJsonTransport:
    """Provider-neutral HTTPS JSON transport with fail-closed resource bounds.

    The adapter deliberately owns only transport mechanics. It has no OAuth,
    entitlement, billing, provider URL, token, or identity semantics.
    """

    def __init__(
        self,
        *,
        timeout_seconds: float = 15.0,
        max_request_bytes: int = 64 * 1024,
        max_response_bytes: int = 512 * 1024,
        opener: object | None = None,
    ) -> None:
        if not (0.1 <= float(timeout_seconds) <= 120.0):
            raise ValueError("timeout_seconds out of range")
        if not (1 <= int(max_request_bytes) <= 1024 * 1024):
            raise ValueError("max_request_bytes out of range")
        if not (1 <= int(max_response_bytes) <= 8 * 1024 * 1024):
            raise ValueError("max_response_bytes out of range")
        self.timeout_seconds = float(timeout_seconds)
        self.max_request_bytes = int(max_request_bytes)
        self.max_response_bytes = int(max_response_bytes)
        self._opener = opener or _default_opener()

    def get_json(
        self,
        url: str,
        *,
        headers: Mapping[str, str] | None = None,
    ) -> JsonResponse:
        return self._request_json("GET", url, body=None, headers=headers)

    def post_json(
        self,
        url: str,
        value: object,
        *,
        headers: Mapping[str, str] | None = None,
    ) -> JsonResponse:
        try:
            body = json.dumps(
                value,
                ensure_ascii=False,
                separators=(",", ":"),
                allow_nan=False,
            ).encode("utf-8")
        except (TypeError, ValueError, UnicodeError):
            raise SecureHttpError(TransportErrorCode.INVALID_REQUEST) from None
        return self._post_bytes(
            url,
            body,
            content_type="application/json; charset=utf-8",
            headers=headers,
        )

    def post_form(
        self,
        url: str,
        encoded_form: bytes | str,
        *,
        headers: Mapping[str, str] | None = None,
    ) -> JsonResponse:
        """POST an already-canonical form body and require a bounded JSON reply.

        OAuth-specific parameter construction/validation remains outside this
        transport. This method merely carries already encoded bytes.
        """

        if isinstance(encoded_form, str):
            try:
                body = encoded_form.encode("ascii")
            except UnicodeEncodeError:
                raise SecureHttpError(TransportErrorCode.INVALID_REQUEST) from None
        elif isinstance(encoded_form, bytes):
            body = bytes(encoded_form)
        else:
            raise SecureHttpError(TransportErrorCode.INVALID_REQUEST)
        if b"\r" in body or b"\n" in body or b"\x00" in body:
            raise SecureHttpError(TransportErrorCode.INVALID_REQUEST)
        return self._post_bytes(
            url,
            body,
            content_type="application/x-www-form-urlencoded",
            headers=headers,
        )

    def _post_bytes(
        self,
        url: str,
        body: bytes,
        *,
        content_type: str,
        headers: Mapping[str, str] | None,
    ) -> JsonResponse:
        if len(body) > self.max_request_bytes:
            raise SecureHttpError(TransportErrorCode.INVALID_REQUEST)
        supplied = dict(headers or {})
        if any(str(name).strip().casefold() == "content-type" for name in supplied):
            raise SecureHttpError(TransportErrorCode.INVALID_REQUEST)
        supplied["Content-Type"] = content_type
        return self._request_json("POST", url, body=body, headers=supplied)

    def _request_json(
        self,
        method: str,
        url: str,
        *,
        body: bytes | None,
        headers: Mapping[str, str] | None,
    ) -> JsonResponse:
        target = _validated_https_url(url)
        clean_headers = _validated_headers(headers or {})
        clean_headers.setdefault("Accept", "application/json")
        request = Request(target, data=body, headers=clean_headers, method=method)

        try:
            response = self._opener.open(request, timeout=self.timeout_seconds)
            with response:
                status = int(response.getcode())
                if not 200 <= status < 300:
                    raise SecureHttpError(TransportErrorCode.HTTP_STATUS, status=status)
                content_type = _validated_json_content_type(response.headers.get("Content-Type", ""))
                payload = response.read(self.max_response_bytes + 1)
        except SecureHttpError:
            raise
        except HTTPError as exc:
            if 300 <= int(exc.code) < 400:
                raise SecureHttpError(TransportErrorCode.REDIRECT, status=int(exc.code)) from None
            raise SecureHttpError(TransportErrorCode.HTTP_STATUS, status=int(exc.code)) from None
        except (TimeoutError, socket.timeout):
            raise SecureHttpError(TransportErrorCode.TIMEOUT) from None
        except ssl.SSLError:
            raise SecureHttpError(TransportErrorCode.TLS) from None
        except URLError as exc:
            reason = getattr(exc, "reason", None)
            if isinstance(reason, (TimeoutError, socket.timeout)):
                raise SecureHttpError(TransportErrorCode.TIMEOUT) from None
            if isinstance(reason, ssl.SSLError):
                raise SecureHttpError(TransportErrorCode.TLS) from None
            raise SecureHttpError(TransportErrorCode.NETWORK) from None
        except OSError:
            raise SecureHttpError(TransportErrorCode.NETWORK) from None

        if len(payload) > self.max_response_bytes:
            raise SecureHttpError(TransportErrorCode.RESPONSE_TOO_LARGE)
        try:
            text = payload.decode("utf-8")
            value = json.loads(text, object_pairs_hook=_reject_duplicate_keys)
        except (UnicodeError, json.JSONDecodeError, ValueError):
            raise SecureHttpError(TransportErrorCode.INVALID_JSON) from None
        return JsonResponse(status=status, value=value, content_type=content_type)


def _validated_https_url(value: str) -> str:
    if not isinstance(value, str) or not value or len(value) > 4096:
        raise SecureHttpError(TransportErrorCode.INVALID_REQUEST)
    if any(ord(ch) < 0x20 or ord(ch) == 0x7F for ch in value) or "\\" in value:
        raise SecureHttpError(TransportErrorCode.INVALID_REQUEST)
    try:
        parts = urlsplit(value)
        port = parts.port
    except ValueError:
        raise SecureHttpError(TransportErrorCode.INVALID_REQUEST) from None
    if parts.scheme.lower() != "https" or not parts.hostname:
        raise SecureHttpError(TransportErrorCode.INVALID_REQUEST)
    if parts.username is not None or parts.password is not None or parts.fragment:
        raise SecureHttpError(TransportErrorCode.INVALID_REQUEST)
    if port is not None and not 1 <= port <= 65535:
        raise SecureHttpError(TransportErrorCode.INVALID_REQUEST)
    return value


def _validated_headers(headers: Mapping[str, str]) -> dict[str, str]:
    if len(headers) > 64:
        raise SecureHttpError(TransportErrorCode.INVALID_REQUEST)
    reserved = {
        "connection",
        "content-length",
        "host",
        "proxy-authenticate",
        "proxy-authorization",
        "te",
        "trailer",
        "transfer-encoding",
        "upgrade",
    }
    token_punctuation = set("!#$%&'*+-.^_`|~")
    result: dict[str, str] = {}
    seen: set[str] = set()
    for raw_name, raw_value in headers.items():
        if not isinstance(raw_name, str) or not isinstance(raw_value, str):
            raise SecureHttpError(TransportErrorCode.INVALID_REQUEST)
        name = raw_name.strip()
        value = raw_value.strip()
        folded = name.casefold()
        if not name or folded in seen or folded in reserved:
            raise SecureHttpError(TransportErrorCode.INVALID_REQUEST)
        if any(not (ch.isascii() and (ch.isalnum() or ch in token_punctuation)) for ch in name):
            raise SecureHttpError(TransportErrorCode.INVALID_REQUEST)
        if len(name) > 128 or len(value) > 8192:
            raise SecureHttpError(TransportErrorCode.INVALID_REQUEST)
        if any(ch in value for ch in ("\r", "\n", "\x00")):
            raise SecureHttpError(TransportErrorCode.INVALID_REQUEST)
        seen.add(folded)
        result[name] = value
    return result


def _validated_json_content_type(value: str) -> str:
    media_type = str(value).split(";", 1)[0].strip().lower()
    if media_type == "application/json" or media_type.endswith("+json"):
        return media_type
    raise SecureHttpError(TransportErrorCode.INVALID_CONTENT_TYPE)


def _reject_duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result
