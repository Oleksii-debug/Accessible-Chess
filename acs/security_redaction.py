"""Deterministic redaction for logs, diagnostics, and crash payloads.

This module is deliberately dependency-free and presentation-neutral.  It must
be safe to call before untrusted diagnostic text reaches a log file, support
bundle, issue attachment, or crash reporter.  It is not a credential store and
must never be used as a substitute for DPAPI/OS-backed secret storage.
"""
from __future__ import annotations

from collections.abc import Mapping, Sequence
import re
from typing import Any


REDACTED = "[REDACTED]"

# Keys are normalized before comparison so token/access_token/access-token and
# case variants follow one policy.  Keep this conservative: false positives in
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
        "api_key",
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
_JWT_RE = re.compile(r"(?<![A-Za-z0-9_-])eyJ[A-Za-z0-9_-]{6,}\.[A-Za-z0-9_-]{6,}\.[A-Za-z0-9_-]{6,}(?![A-Za-z0-9_-])")
_URL_SECRET_RE = re.compile(
    r"(?i)([?&](?:access_token|refresh_token|id_token|token|api_key|license_key)=)([^&#\s]+)"
)
_ASSIGNMENT_RE = re.compile(
    r"(?i)(\b(?:access[_-]?token|refresh[_-]?token|id[_-]?token|api[_-]?key|client[_-]?secret|license[_-]?key|activation[_-]?key|password|passwd)\b\s*[:=]\s*)([^\s,;]+)"
)


def _normalize_key(value: Any) -> str:
    return re.sub(r"[^a-z0-9_]", "", str(value).casefold())


def is_sensitive_key(key: Any) -> bool:
    normalized = _normalize_key(key)
    return normalized in _SENSITIVE_KEYS or normalized.endswith("token") or normalized.endswith("secret")


def redact_text(value: Any) -> str:
    """Return text with common credential forms removed.

    The function intentionally preserves prefixes such as ``Bearer`` and query
    parameter names because those are useful in diagnostics while the secret
    value itself is not.
    """

    text = str(value)
    text = _BEARER_RE.sub(lambda match: match.group(1) + REDACTED, text)
    text = _BASIC_RE.sub(lambda match: match.group(1) + REDACTED, text)
    text = _JWT_RE.sub(REDACTED, text)
    text = _URL_SECRET_RE.sub(lambda match: match.group(1) + REDACTED, text)
    text = _ASSIGNMENT_RE.sub(lambda match: match.group(1) + REDACTED, text)
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
