from __future__ import annotations

"""Provider-neutral secret redaction for diagnostics and log output.

This module is deliberately independent from authentication and token storage.
Callers sanitize diagnostic structures before persistence/upload and may use
``RedactingFormatter`` as the final formatter for Python logging handlers.
"""

from collections.abc import Mapping
import json
import logging
import re
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit


REDACTED = "[REDACTED]"

# Keys are normalized by dropping separators so variants such as
# ``access-token``, ``access_token`` and ``AccessToken`` share one contract.
_SECRET_KEYS = frozenset(
    {
        "authorization",
        "proxyauthorization",
        "accesstoken",
        "refreshtoken",
        "idtoken",
        "clientsecret",
        "apisecret",
        "apikey",
        "licensekey",
        "password",
        "passwd",
        "sessiontoken",
        "bearertoken",
        "cookie",
        "setcookie",
    }
)
_URL_SECRET_KEYS = _SECRET_KEYS | frozenset({"code", "state"})
_KEY_NORMALIZER = re.compile(r"[^a-z0-9]")

# Text patterns intentionally require a sensitive label or an Authorization /
# Bearer shape. They do not redact ordinary chess words, PGN tags, SAN or FEN.
_HEADER_RE = re.compile(
    r"(?im)(\b(?:authorization|proxy-authorization)\s*:\s*)(?:bearer\s+|basic\s+)?[^\s,;]+"
)
# Cookie headers can carry several credentials separated by semicolons and
# Set-Cookie attributes on the same line. Redact the complete header value so a
# second cookie/attribute cannot survive after only the first token is hidden.
_COOKIE_HEADER_RE = re.compile(r"(?im)(\b(?:cookie|set-cookie)\s*:\s*)[^\r\n]*")
_BEARER_RE = re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+\-/]+=*")
_QUOTED_ASSIGNMENT_RE = re.compile(
    r"(?i)(\b(?:access[_-]?token|refresh[_-]?token|id[_-]?token|client[_-]?secret|"
    r"api[_-]?key|api[_-]?secret|license[_-]?key|session[_-]?token|password|passwd)"
    r"\s*[=:]\s*)(?P<quote>[\"'])(?:\\.|(?!(?P=quote)).)*(?P=quote)"
)
_ASSIGNMENT_RE = re.compile(
    r"(?i)(\b(?:access[_-]?token|refresh[_-]?token|id[_-]?token|client[_-]?secret|"
    r"api[_-]?key|api[_-]?secret|license[_-]?key|session[_-]?token|password|passwd)"
    r"\s*[=:]\s*)([^\s&,;]+)"
)
_JSONISH_RE = re.compile(
    r"(?i)([\"'](?:access[_-]?token|refresh[_-]?token|id[_-]?token|client[_-]?secret|"
    r"api[_-]?key|api[_-]?secret|license[_-]?key|session[_-]?token|password|passwd|"
    r"authorization|cookie|set[_-]?cookie)[\"']\s*:\s*)"
    r"(?P<json_quote>[\"'])(?:\\.|(?!(?P=json_quote)).)*(?P=json_quote)"
)
_URL_RE = re.compile(r"https?://[^\s<>'\"]+")


class SecretRedactionError(ValueError):
    """Raised when a diagnostic object cannot be safely sanitized."""


def _normalize_key(value: str) -> str:
    # Never coerce arbitrary objects here. Mapping-key inspection is part of the
    # security boundary, and attacker-controlled __str__ may itself expose data
    # or perform side effects before redaction has a chance to run.
    if type(value) is not str:
        return ""
    return _KEY_NORMALIZER.sub("", value.strip().casefold())


def is_secret_key(value: object) -> bool:
    """Return whether a textual mapping/header key identifies secret material."""

    return type(value) is str and _normalize_key(value) in _SECRET_KEYS


def redact_text(value: str) -> str:
    """Redact recognizable secret material from already-rendered diagnostic text."""

    if type(value) is not str:
        raise SecretRedactionError("diagnostic text must be plain text")
    text = value
    text = _COOKIE_HEADER_RE.sub(lambda match: match.group(1) + REDACTED, text)
    text = _HEADER_RE.sub(lambda match: match.group(1) + REDACTED, text)
    text = _BEARER_RE.sub("Bearer " + REDACTED, text)
    text = _QUOTED_ASSIGNMENT_RE.sub(
        lambda match: match.group(1) + match.group("quote") + REDACTED + match.group("quote"),
        text,
    )
    text = _ASSIGNMENT_RE.sub(lambda match: match.group(1) + REDACTED, text)
    text = _JSONISH_RE.sub(
        lambda match: (
            match.group(1)
            + match.group("json_quote")
            + REDACTED
            + match.group("json_quote")
        ),
        text,
    )
    return _URL_RE.sub(lambda match: _redact_url(match.group(0)), text)


def _redact_url_parameters(value: str) -> tuple[str, bool]:
    """Redact secret key/value pairs while leaving non-parameter fragments intact."""

    if not value:
        return value, False
    try:
        pairs = parse_qsl(value, keep_blank_values=True, strict_parsing=False)
    except ValueError:
        return value, False
    changed = False
    sanitized: list[tuple[str, str]] = []
    for key, raw in pairs:
        if _normalize_key(key) in _URL_SECRET_KEYS:
            sanitized.append((key, REDACTED))
            changed = True
        else:
            sanitized.append((key, raw))
    if not changed:
        return value, False
    return urlencode(sanitized), True


def _redact_url(value: str) -> str:
    try:
        parts = urlsplit(value)
    except ValueError:
        return value
    query, query_changed = _redact_url_parameters(parts.query)
    fragment, fragment_changed = _redact_url_parameters(parts.fragment)
    if not query_changed and not fragment_changed:
        return value
    return urlunsplit((parts.scheme, parts.netloc, parts.path, query, fragment))


def redact_diagnostic(value: Any, *, max_depth: int = 32) -> Any:
    """Return a redacted, serialization-friendly copy of diagnostic data.

    Secret mapping values are replaced based on their key. Strings are scanned
    for labeled/header/query-string secrets. Bytes are never decoded into logs;
    they are represented only by length. Cycles, non-text mapping keys and
    excessive nesting fail closed rather than invoking attacker-controlled text
    conversion or risking recursive logging of unknown objects.
    """

    if type(max_depth) is not int or max_depth < 1:
        raise SecretRedactionError("max_depth must be a positive integer")
    return _redact_value(value, depth=0, max_depth=max_depth, active=set())


def _redact_value(value: Any, *, depth: int, max_depth: int, active: set[int]) -> Any:
    if depth > max_depth:
        raise SecretRedactionError("diagnostic structure exceeds redaction depth limit")
    # Exact built-in types only: subclasses can override text conversion methods
    # and therefore belong on the unknown-object path below.
    if value is None or type(value) in (bool, int, float):
        return value
    if type(value) is str:
        return redact_text(value)
    if type(value) in (bytes, bytearray, memoryview):
        return f"<binary:{len(value)} bytes>"

    marker = id(value)
    if isinstance(value, Mapping):
        if marker in active:
            raise SecretRedactionError("cyclic diagnostic mapping cannot be sanitized")
        active.add(marker)
        try:
            result: dict[str, Any] = {}
            for key, item in value.items():
                if type(key) is not str:
                    raise SecretRedactionError("diagnostic mapping keys must be plain text")
                if is_secret_key(key):
                    result[key] = REDACTED
                else:
                    result[key] = _redact_value(
                        item, depth=depth + 1, max_depth=max_depth, active=active
                    )
            return result
        finally:
            active.remove(marker)

    if isinstance(value, (list, tuple, set, frozenset)):
        if marker in active:
            raise SecretRedactionError("cyclic diagnostic sequence cannot be sanitized")
        active.add(marker)
        try:
            items = [
                _redact_value(item, depth=depth + 1, max_depth=max_depth, active=active)
                for item in value
            ]
        finally:
            active.remove(marker)
        if isinstance(value, tuple):
            return tuple(items)
        # Sets are normalized to a deterministic list because arbitrary values
        # may not remain hashable after recursive sanitization. At this point all
        # values are recursively reduced to JSON-safe built-ins, so json.dumps
        # cannot invoke an attacker-controlled __repr__ or __str__.
        if isinstance(value, (set, frozenset)):
            return sorted(
                items,
                key=lambda item: json.dumps(
                    item, ensure_ascii=True, sort_keys=True, separators=(",", ":")
                ),
            )
        return items

    # Do not call arbitrary __str__/__repr__: either can itself expose secrets or
    # have side effects. Unknown objects are reduced to their public type only.
    return f"<{type(value).__module__}.{type(value).__qualname__}>"


class RedactingFormatter(logging.Formatter):
    """Logging formatter that redacts the final emitted text.

    Redacting after ``logging.Formatter.format`` covers secrets introduced via
    message interpolation, exception text and stack text without mutating the
    shared ``LogRecord`` seen by other handlers.
    """

    def format(self, record: logging.LogRecord) -> str:
        return redact_text(super().format(record))