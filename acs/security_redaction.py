"""Deterministic redaction for logs, diagnostics, and crash payloads.

This module is deliberately dependency-free and presentation-neutral. It must
be safe to call before untrusted diagnostic text reaches a log file, support
bundle, issue attachment, or crash reporter. It is not a credential store and
must never be used as a substitute for DPAPI/OS-backed secret storage.
"""
from __future__ import annotations

from collections.abc import Mapping, Sequence
import re
from typing import Any


REDACTED = "[REDACTED]"

# Keys are separator-insensitive so token/access_token/access-token and case
# variants follow one policy. Keep this conservative: false positives in
# diagnostics are preferable to leaking credentials.
_SENSITIVE_KEYS = frozenset(
    {
        "authorization",
        "cookie",
        "setcookie",
        "password",
        "passwd",
        "secret",
        "clientsecret",
        "apikey",
        "token",
        "accesstoken",
        "refreshtoken",
        "idtoken",
        "sessiontoken",
        "sessionid",
        "licensekey",
        "activationkey",
    }
)

_BEARER_RE = re.compile(r"(?i)(\bBearer\s+)[A-Za-z0-9._~+/=-]{8,}")
_BASIC_RE = re.compile(r"(?i)(\bBasic\s+)[A-Za-z0-9+/=]{8,}")
_JWT_RE = re.compile(
    r"(?<![A-Za-z0-9_-])eyJ[A-Za-z0-9_-]{6,}\.[A-Za-z0-9_-]{6,}\.[A-Za-z0-9_-]{6,}(?![A-Za-z0-9_-])"
)

# Query-string coverage mirrors the sensitive credential families used by the
# structured-payload policy. Values stop at URL/query delimiters or whitespace.
_URL_SECRET_RE = re.compile(
    r"(?i)([?&](?:access[_-]?token|refresh[_-]?token|id[_-]?token|session[_-]?(?:token|id)|token|api[_-]?key|client[_-]?secret|license[_-]?key|activation[_-]?key|secret)=)([^&#\s]+)"
)

# Assignment-style diagnostics are common in startup/crash logs. Keep the key
# visible for debugging but remove the value. The optional quote is consumed so
# JSON-ish text cannot leak merely because a value was quoted. Stop at '&' as
# well so chained URL query labels survive after URL-specific redaction.
_ASSIGNMENT_RE = re.compile(
    r"(?i)(\b(?:access[_-]?token|refresh[_-]?token|id[_-]?token|session[_-]?(?:token|id)|api[_-]?key|client[_-]?secret|license[_-]?key|activation[_-]?key|password|passwd|token|secret|cookie)\b\s*[:=]\s*)(?:['\"]?)([^&\s,;\"']+)(?:['\"]?)"
)

# Authorization values that are not standard Bearer/Basic schemes still must
# not reach persistent diagnostics. Standard schemes are handled above so their
# useful scheme name remains visible.
_OPAQUE_AUTH_RE = re.compile(
    r"(?i)(\bAuthorization\b\s*[:=]\s*)(?!Bearer\b|Basic\b)(?:['\"]?)([^\s,;\"']+)(?:['\"]?)"
)


def _normalize_key(value: Any) -> str:
    return re.sub(r"[^a-z0-9]", "", str(value).casefold())


def is_sensitive_key(key: Any) -> bool:
    normalized = _normalize_key(key)
    return normalized in _SENSITIVE_KEYS or normalized.endswith("token") or normalized.endswith("secret")


def redact_text(value: Any) -> str:
    """Return text with common credential forms removed.

    The function intentionally preserves diagnostic labels and standard auth
    scheme names where possible while removing the secret value itself.
    """

    text = str(value)
    text = _BEARER_RE.sub(lambda match: match.group(1) + REDACTED, text)
    text = _BASIC_RE.sub(lambda match: match.group(1) + REDACTED, text)
    text = _JWT_RE.sub(REDACTED, text)
    text = _URL_SECRET_RE.sub(lambda match: match.group(1) + REDACTED, text)
    text = _ASSIGNMENT_RE.sub(lambda match: match.group(1) + REDACTED, text)
    text = _OPAQUE_AUTH_RE.sub(lambda match: match.group(1) + REDACTED, text)
    return text


def redact_payload(value: Any) -> Any:
    """Recursively sanitize JSON-like diagnostic data without mutating input."""

    if isinstance(value, Mapping):
        result: dict[Any, Any] = {}
        for key, item in value.items():
            result[key] = REDACTED if is_sensitive_key(key) else redact_payload(item)
        return result
    if isinstance(value, tuple):
        return tuple(redact_payload(item) for item in value)
    if isinstance(value, list):
        return [redact_payload(item) for item in value]
    if isinstance(value, set):
        return {redact_payload(item) for item in value}
    if isinstance(value, str):
        return redact_text(value)
    return value


def assert_redacted(value: Any, forbidden_values: Sequence[str]) -> None:
    """Fail closed in tests/build tooling when a known secret survives sanitizing."""

    rendered = repr(redact_payload(value))
    leaked = [secret for secret in forbidden_values if secret and secret in rendered]
    if leaked:
        raise ValueError("diagnostic payload contains unredacted secret material")
