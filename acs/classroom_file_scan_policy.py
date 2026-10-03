from __future__ import annotations

"""Fail-closed MIME policy composition for trusted classroom file scanning.

The declared MIME type is bounded immutable attachment metadata, not proof of file
content. This adapter uses it only for administrator allow/deny policy. Every
policy-permitted payload still crosses the injected malware scanner exactly once;
MIME policy never substitutes for content scanning.
"""

from dataclasses import dataclass
import re
from typing import Protocol


_MAX_MIME_PATTERNS = 256
_MIME_TOKEN = r"[!#$%&'+.^_|~0-9A-Za-z-]+"
_MIME_RE = re.compile(rf"^({_MIME_TOKEN})/({_MIME_TOKEN})$")
_MIME_PATTERN_RE = re.compile(rf"^({_MIME_TOKEN}|\*)/({_MIME_TOKEN}|\*)$")


class ClassroomFileMalwareScannerPort(Protocol):
    """Concrete malware/content scanner invoked after MIME policy permits bytes."""

    def scan(
        self,
        *,
        room_id: str,
        sender_id: str,
        display_name: str,
        mime_type: str | None,
        sha256: str,
        content: bytes,
    ) -> str:
        """Return exactly clean, blocked or failed."""
        ...


def _canonical_mime(value: object) -> str | None:
    if value is None:
        return None
    if type(value) is not str:
        return None
    base = value.split(";", 1)[0].strip().lower()
    if not base or len(base) > 255 or _MIME_RE.fullmatch(base) is None:
        return None
    return base


def _canonical_pattern(value: object) -> str:
    if type(value) is not str:
        raise TypeError("MIME policy patterns must be strings")
    normalized = value.strip().lower()
    if (
        not normalized
        or len(normalized) > 255
        or _MIME_PATTERN_RE.fullmatch(normalized) is None
    ):
        raise ValueError("MIME policy pattern is invalid")
    major, minor = normalized.split("/", 1)
    if major == "*" and minor != "*":
        raise ValueError("MIME wildcard major type requires */*")
    return normalized


def _patterns(value: object, label: str) -> tuple[str, ...]:
    if type(value) is not tuple:
        raise TypeError(f"{label} MIME patterns must be a tuple")
    if len(value) > _MAX_MIME_PATTERNS:
        raise ValueError(f"{label} MIME policy has too many patterns")
    result: list[str] = []
    seen: set[str] = set()
    for item in value:
        normalized = _canonical_pattern(item)
        if normalized not in seen:
            seen.add(normalized)
            result.append(normalized)
    return tuple(result)


def _matches(pattern: str, mime_type: str) -> bool:
    major, minor = pattern.split("/", 1)
    mime_major, mime_minor = mime_type.split("/", 1)
    return (
        (major == "*" or major == mime_major)
        and (minor == "*" or minor == mime_minor)
    )


@dataclass(frozen=True, slots=True)
class ClassroomFileMimePolicy:
    """Administrative MIME gate evaluated before malware scanning.

    allowed=None means no allow-list restriction, preserving arbitrary opaque file
    support. allowed=() blocks every declared MIME. Deny rules always take
    precedence. Missing MIME is permitted by default only when no allow-list is
    configured; deployments can set allow_missing=False to quarantine it.
    """

    allowed: tuple[str, ...] | None = None
    denied: tuple[str, ...] = ()
    allow_missing: bool = True

    def __post_init__(self) -> None:
        if self.allowed is not None:
            object.__setattr__(
                self,
                "allowed",
                _patterns(self.allowed, "allowed"),
            )
        object.__setattr__(self, "denied", _patterns(self.denied, "denied"))
        if type(self.allow_missing) is not bool:
            raise TypeError("allow_missing must be bool")

    def allows(self, mime_type: object) -> bool:
        missing = mime_type is None or mime_type == ""
        if missing:
            return self.allowed is None and self.allow_missing
        normalized = _canonical_mime(mime_type)
        if normalized is None:
            return False
        if any(_matches(pattern, normalized) for pattern in self.denied):
            return False
        allowed = self.allowed
        if allowed is not None and not any(
            _matches(pattern, normalized) for pattern in allowed
        ):
            return False
        return True


class ClassroomFilePolicyScanner:
    """Compose MIME policy with one existing malware/content scanner."""

    __slots__ = ("_policy", "_malware_scanner")

    def __init__(
        self,
        *,
        policy: ClassroomFileMimePolicy,
        malware_scanner: ClassroomFileMalwareScannerPort,
    ) -> None:
        if type(policy) is not ClassroomFileMimePolicy:
            raise TypeError("file scan policy must be ClassroomFileMimePolicy")
        if malware_scanner is None or not callable(
            getattr(malware_scanner, "scan", None)
        ):
            raise TypeError("malware scanner must provide scan()")
        self._policy = policy
        self._malware_scanner = malware_scanner

    def __repr__(self) -> str:
        return "ClassroomFilePolicyScanner(policy=<bound>, malware_scanner=<bound>)"

    def scan(
        self,
        *,
        room_id: str,
        sender_id: str,
        display_name: str,
        mime_type: str | None,
        sha256: str,
        content: bytes,
    ) -> str:
        if not self._policy.allows(mime_type):
            return "blocked"
        try:
            state = self._malware_scanner.scan(
                room_id=room_id,
                sender_id=sender_id,
                display_name=display_name,
                mime_type=mime_type,
                sha256=sha256,
                content=content,
            )
        except Exception:
            return "failed"
        if state not in {"clean", "blocked", "failed"}:
            return "failed"
        return state


__all__ = [
    "ClassroomFileMalwareScannerPort",
    "ClassroomFileMimePolicy",
    "ClassroomFilePolicyScanner",
]
