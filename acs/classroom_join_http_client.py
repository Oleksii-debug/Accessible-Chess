from __future__ import annotations

"""Desktop HTTPS client for canonical classroom join credentials.

This module owns only bounded HTTP request/response handling. Authentication
material is supplied per request, while room membership, media policy and
provider token minting remain trusted-server responsibilities.
"""

from collections.abc import Callable
from datetime import datetime, timezone
import http.client
import ipaddress
import json
import math
import re
from urllib.parse import urlsplit

from .classroom_join_credentials import (
    JOIN_REQUEST_VERSION,
    MAX_JOIN_REQUEST_BYTES,
    MAX_JOIN_RESPONSE_BYTES,
)
from .classroom_join_http_endpoint import (
    JOIN_CREDENTIAL_PATH,
    MAX_AUTHORIZATION_BYTES,
    MAX_REQUEST_HEADER_BYTES,
)
from .classroom_realtime_media import ClassroomMediaError, JoinCredential


_HEADER_NAME_RE = re.compile(rb"^[!#$%&'*+.^_`|~0-9A-Za-z-]+$")
_IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")


class ClassroomJoinHttpClientError(RuntimeError):
    """Safe desktop-side join transport failure."""


class ClassroomJoinHttpClient:
    """Fetch one fresh server-issued JoinCredential over authenticated HTTP."""

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
        timeout_seconds: float = 15.0,
        allow_insecure_loopback: bool = False,
    ) -> None:
        if not callable(bearer_token_provider):
            raise TypeError("join HTTP bearer token provider must be callable")
        if type(allow_insecure_loopback) is not bool:
            raise TypeError("allow_insecure_loopback must be bool")
        if (
            type(timeout_seconds) not in {int, float}
            or isinstance(timeout_seconds, bool)
            or not math.isfinite(float(timeout_seconds))
            or not 0 < float(timeout_seconds) <= 60.0
        ):
            raise ValueError("join HTTP timeout must be from 0 to 60 seconds")
        scheme, host, port = _validated_endpoint(
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
            "ClassroomJoinHttpClient("
            f"scheme={self._scheme!r}, host={self._host!r}, port={self._port!r}, "
            "bearer_token_provider=<bound>)"
        )

    def issue(
        self,
        *,
        room_id: str,
        participant_id: str,
    ) -> JoinCredential:
        room = _canonical_identifier(room_id, "room id")
        participant = _canonical_identifier(participant_id, "participant id")
        request = {
            "version": JOIN_REQUEST_VERSION,
            "room_id": room,
            "participant_id": participant,
        }
        try:
            body = json.dumps(
                request,
                ensure_ascii=False,
                separators=(",", ":"),
                allow_nan=False,
            ).encode("utf-8")
        except (TypeError, ValueError, UnicodeEncodeError, RecursionError):
            raise ClassroomJoinHttpClientError(
                "join credential request is invalid"
            ) from None
        if not body or len(body) > MAX_JOIN_REQUEST_BYTES:
            raise ClassroomJoinHttpClientError(
                "join credential request exceeds transport limit"
            )

        try:
            raw_token = self._bearer_token_provider()
        except Exception:
            raise ClassroomJoinHttpClientError(
                "join authentication credential is unavailable"
            ) from None
        bearer = _validated_bearer(raw_token)

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
        try:
            connection.putrequest(
                "POST",
                JOIN_CREDENTIAL_PATH,
                skip_accept_encoding=True,
            )
            connection.putheader("Authorization", f"Bearer {bearer}")
            connection.putheader("Content-Type", "application/json; charset=utf-8")
            connection.putheader("Accept", "application/json")
            connection.putheader("Content-Length", str(len(body)))
            connection.endheaders()
            connection.send(body)
            response = connection.getresponse()
            payload = _read_response(response)
        except ClassroomJoinHttpClientError:
            raise
        except Exception:
            raise ClassroomJoinHttpClientError(
                "classroom join HTTP transport failed"
            ) from None
        finally:
            try:
                connection.close()
            except Exception:
                pass

        expected = {"version", "room_id", "participant_id", "token", "issued_at", "expires_at"}
        if set(payload) != expected:
            raise ClassroomJoinHttpClientError(
                "join credential response fields are invalid"
            )
        if type(payload["version"]) is not int or payload["version"] != JOIN_REQUEST_VERSION:
            raise ClassroomJoinHttpClientError(
                "join credential response version is invalid"
            )
        if payload["room_id"] != room or payload["participant_id"] != participant:
            raise ClassroomJoinHttpClientError(
                "join credential response identity does not match request"
            )
        token = payload["token"]
        if type(token) is not str:
            raise ClassroomJoinHttpClientError(
                "join credential response token is invalid"
            )
        issued_at = _canonical_timestamp(payload["issued_at"], "issued_at")
        expires_at = _canonical_timestamp(payload["expires_at"], "expires_at")
        try:
            return JoinCredential(
                room_id=payload["room_id"],
                participant_id=payload["participant_id"],
                token=token,
                issued_at=issued_at,
                expires_at=expires_at,
            )
        except (ClassroomMediaError, TypeError, ValueError):
            raise ClassroomJoinHttpClientError(
                "join credential response is invalid"
            ) from None


def _canonical_identifier(value: object, label: str) -> str:
    if type(value) is not str or _IDENTIFIER_RE.fullmatch(value) is None:
        raise ClassroomJoinHttpClientError(
            f"join credential request {label} is invalid"
        )
    return value


def _validated_endpoint(
    value: object,
    *,
    allow_insecure_loopback: bool,
) -> tuple[str, str, int]:
    if type(value) is not str or not value or len(value) > 2048:
        raise ValueError("join HTTP endpoint URL is invalid")
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except ValueError:
        raise ValueError("join HTTP endpoint URL is invalid") from None
    if (
        parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
        or parsed.path != JOIN_CREDENTIAL_PATH
        or parsed.hostname is None
    ):
        raise ValueError("join HTTP endpoint URL is invalid")
    scheme = parsed.scheme.lower()
    host = parsed.hostname
    try:
        host_ascii = host.encode("idna").decode("ascii")
    except UnicodeError:
        raise ValueError("join HTTP endpoint URL is invalid") from None
    if (
        not host_ascii
        or len(host_ascii) > 253
        or any(ord(ch) <= 32 or ord(ch) == 127 for ch in host_ascii)
        or (port is not None and not 1 <= port <= 65535)
    ):
        raise ValueError("join HTTP endpoint URL is invalid")
    if scheme == "https":
        return scheme, host_ascii, 443 if port is None else port
    if (
        scheme == "http"
        and allow_insecure_loopback
        and _literal_loopback(host_ascii)
    ):
        return scheme, host_ascii, 80 if port is None else port
    raise ValueError("join HTTP endpoint must use HTTPS")


def _literal_loopback(host: str) -> bool:
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def _validated_bearer(value: object) -> str:
    if type(value) is not str:
        raise ClassroomJoinHttpClientError(
            "join authentication credential is invalid"
        )
    try:
        encoded = value.encode("ascii")
    except UnicodeEncodeError:
        raise ClassroomJoinHttpClientError(
            "join authentication credential is invalid"
        ) from None
    if (
        not encoded
        or len(encoded) > MAX_AUTHORIZATION_BYTES - len(b"Bearer ")
        or value != value.strip()
        or any(ord(ch) <= 32 or ord(ch) == 127 for ch in value)
    ):
        raise ClassroomJoinHttpClientError(
            "join authentication credential is invalid"
        )
    return value


def _read_response(response: object) -> dict[str, object]:
    status = getattr(response, "status", None)
    getheaders = getattr(response, "getheaders", None)
    read = getattr(response, "read", None)
    if type(status) is not int or not callable(getheaders) or not callable(read):
        raise ClassroomJoinHttpClientError(
            "join HTTP response is invalid"
        )
    try:
        raw_headers = getheaders()
    except Exception:
        raise ClassroomJoinHttpClientError(
            "join HTTP response headers are unavailable"
        ) from None
    if type(raw_headers) is not list:
        raise ClassroomJoinHttpClientError(
            "join HTTP response headers are invalid"
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
            raise ClassroomJoinHttpClientError(
                "join HTTP response headers are invalid"
            )
        name, value = entry
        try:
            name_bytes = name.encode("ascii")
            value_bytes = value.encode("latin1")
        except UnicodeEncodeError:
            raise ClassroomJoinHttpClientError(
                "join HTTP response headers are invalid"
            ) from None
        if (
            _HEADER_NAME_RE.fullmatch(name_bytes) is None
            or any(byte < 32 or byte == 127 for byte in value_bytes)
        ):
            raise ClassroomJoinHttpClientError(
                "join HTTP response headers are invalid"
            )
        header_bytes += len(name_bytes) + len(value_bytes)
        if header_bytes > MAX_REQUEST_HEADER_BYTES:
            raise ClassroomJoinHttpClientError(
                "join HTTP response headers are too large"
            )
        grouped.setdefault(name.lower(), []).append(value)

    if "content-encoding" in grouped or "transfer-encoding" in grouped:
        raise ClassroomJoinHttpClientError(
            "join HTTP response encoding is unsupported"
        )
    content_types = grouped.get("content-type", [])
    lengths = grouped.get("content-length", [])
    cache_controls = grouped.get("cache-control", [])
    pragmas = grouped.get("pragma", [])
    nosniff = grouped.get("x-content-type-options", [])
    if (
        len(content_types) != 1
        or content_types[0].strip().lower() != "application/json; charset=utf-8"
        or len(lengths) != 1
        or len(cache_controls) != 1
        or "no-store" not in {
            item.strip().lower() for item in cache_controls[0].split(",")
        }
        or len(pragmas) != 1
        or pragmas[0].strip().lower() != "no-cache"
        or len(nosniff) != 1
        or nosniff[0].strip().lower() != "nosniff"
    ):
        raise ClassroomJoinHttpClientError(
            "join HTTP response metadata is invalid"
        )
    raw_length = lengths[0].strip()
    if (
        not raw_length.isdigit()
        or len(raw_length) > len(str(MAX_JOIN_RESPONSE_BYTES))
    ):
        raise ClassroomJoinHttpClientError(
            "join HTTP response length is invalid"
        )
    expected_length = int(raw_length, 10)
    if expected_length > MAX_JOIN_RESPONSE_BYTES:
        raise ClassroomJoinHttpClientError(
            "join HTTP response exceeds transport limit"
        )
    try:
        body = read(MAX_JOIN_RESPONSE_BYTES + 1)
    except Exception:
        raise ClassroomJoinHttpClientError(
            "join HTTP response body is unavailable"
        ) from None
    if (
        type(body) is not bytes
        or not body
        or len(body) > MAX_JOIN_RESPONSE_BYTES
        or len(body) != expected_length
    ):
        raise ClassroomJoinHttpClientError(
            "join HTTP response body is invalid"
        )
    if status != 200:
        raise ClassroomJoinHttpClientError(
            "join HTTP request was rejected"
        )

    try:
        text = body.decode("utf-8")
    except UnicodeDecodeError:
        raise ClassroomJoinHttpClientError(
            "join HTTP response JSON is invalid"
        ) from None

    def no_duplicates(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, item in pairs:
            if key in result:
                raise ValueError("duplicate JSON member")
            result[key] = item
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
        raise ClassroomJoinHttpClientError(
            "join HTTP response JSON is invalid"
        ) from None
    if type(value) is not dict:
        raise ClassroomJoinHttpClientError(
            "join HTTP response JSON is invalid"
        )
    return value


def _canonical_timestamp(value: object, label: str) -> datetime:
    if type(value) is not str or not value or len(value) > 64 or not value.endswith("Z"):
        raise ClassroomJoinHttpClientError(
            f"join credential response {label} is invalid"
        )
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError:
        raise ClassroomJoinHttpClientError(
            f"join credential response {label} is invalid"
        ) from None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ClassroomJoinHttpClientError(
            f"join credential response {label} is invalid"
        )
    normalized = parsed.astimezone(timezone.utc)
    canonical = normalized.isoformat().replace("+00:00", "Z")
    if canonical != value:
        raise ClassroomJoinHttpClientError(
            f"join credential response {label} is invalid"
        )
    return normalized


__all__ = [
    "ClassroomJoinHttpClient",
    "ClassroomJoinHttpClientError",
]
