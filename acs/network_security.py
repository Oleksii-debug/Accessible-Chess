from __future__ import annotations

"""Section 29 network/privacy security contract.

This module is deliberately domain-neutral. It does not own chess, classroom,
media, Agent, Web, authentication, or storage state. It defines the production
security gate those networked surfaces must satisfy before they may be exposed.
"""

from dataclasses import dataclass
from enum import Enum
import hashlib
import json
import re
from types import MappingProxyType
from typing import Mapping, Protocol


_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_OPERATION_RE = re.compile(r"^[a-z][a-z0-9_.:-]{0,127}$")
_MAX_RETENTION_DAYS = 3650
_MAX_RATE_LIMIT = 100_000
_MAX_RATE_WINDOW = 86_400


class SecurityContractError(ValueError):
    """A request or policy violates the Section 29 production security contract."""


class NetworkSurface(str, Enum):
    SERVER = "server"
    CLASSROOM = "classroom"
    WEB = "web"
    AGENT = "agent"
    MEDIA = "media"
    FILE_UPLOAD = "file_upload"


class DataClass(str, Enum):
    PROFILE = "profile"
    CHILD = "child"
    CLASSROOM_STATE = "classroom_state"
    CHESS_CONTENT = "chess_content"
    BOOK_CONTENT = "book_content"
    CHAT = "chat"
    FILE = "file"
    AUDIO_VIDEO = "audio_video"
    CLIPBOARD = "clipboard"
    AGGREGATE_USAGE = "aggregate_usage"


_FORBIDDEN_ORDINARY_ANALYTICS = frozenset({
    DataClass.CHESS_CONTENT, DataClass.BOOK_CONTENT, DataClass.CHAT,
    DataClass.FILE, DataClass.AUDIO_VIDEO, DataClass.CLIPBOARD,
})
_SENSITIVE_RETENTION = frozenset({
    DataClass.PROFILE, DataClass.CHILD, DataClass.CLASSROOM_STATE,
    DataClass.CHAT, DataClass.FILE, DataClass.AUDIO_VIDEO,
})
_SECRET_FIELD_FRAGMENTS = (
    "authorization", "cookie", "credential", "password", "secret",
    "session_token", "access_token", "refresh_token", "join_token",
    "api_key", "private_key",
)
_RAW_CONTENT_FIELDS = frozenset({
    "pgn", "fen_library", "book_text", "chat_body", "file_bytes",
    "audio_bytes", "video_bytes", "clipboard",
})


@dataclass(frozen=True, slots=True)
class ThreatModelEntry:
    surface: NetworkSurface
    threats: tuple[str, ...]
    controls: tuple[str, ...]

    def __post_init__(self) -> None:
        if type(self.surface) is not NetworkSurface:
            raise SecurityContractError("threat-model surface must be canonical")
        if (type(self.threats) is not tuple or not self.threats
                or type(self.controls) is not tuple or not self.controls):
            raise SecurityContractError("threat-model entry must name threats and controls")
        for value in (*self.threats, *self.controls):
            if type(value) is not str or not value.strip() or len(value) > 240:
                raise SecurityContractError("invalid threat-model text")


@dataclass(frozen=True, slots=True)
class RetentionRule:
    data_class: DataClass
    max_days: int
    deletion_supported: bool = True
    export_supported: bool = True

    def __post_init__(self) -> None:
        if type(self.data_class) is not DataClass:
            raise SecurityContractError("retention data class must be canonical")
        if type(self.max_days) is not int or not (1 <= self.max_days <= _MAX_RETENTION_DAYS):
            raise SecurityContractError("retention days are outside the bounded policy")
        if type(self.deletion_supported) is not bool or type(self.export_supported) is not bool:
            raise SecurityContractError("retention hooks must be boolean")


@dataclass(frozen=True, slots=True)
class RateLimitRule:
    operation_prefix: str
    limit: int
    window_seconds: int

    def __post_init__(self) -> None:
        object.__setattr__(self, "operation_prefix", _operation(self.operation_prefix))
        if type(self.limit) is not int or not (1 <= self.limit <= _MAX_RATE_LIMIT):
            raise SecurityContractError("rate-limit count is outside the bounded policy")
        if type(self.window_seconds) is not int or not (1 <= self.window_seconds <= _MAX_RATE_WINDOW):
            raise SecurityContractError("rate-limit window is outside the bounded policy")


@dataclass(frozen=True, slots=True)
class ConsentContext:
    subject_is_minor: bool
    policy_version: str
    subject_or_guardian_approved: bool
    organization_approved: bool

    def __post_init__(self) -> None:
        if type(self.subject_is_minor) is not bool:
            raise SecurityContractError("minor flag must be boolean")
        if type(self.policy_version) is not str or not self.policy_version.strip() or len(self.policy_version) > 64:
            raise SecurityContractError("consent policy version is invalid")
        if type(self.subject_or_guardian_approved) is not bool or type(self.organization_approved) is not bool:
            raise SecurityContractError("consent approvals must be boolean")

    @property
    def production_allowed(self) -> bool:
        if self.subject_is_minor:
            return self.subject_or_guardian_approved and self.organization_approved
        return self.subject_or_guardian_approved


@dataclass(frozen=True, slots=True)
class SecurityRequest:
    surface: NetworkSurface
    operation: str
    purpose: str
    actor_role: str
    required_permission: str | None
    granted_permissions: frozenset[str]
    data_classes: frozenset[DataClass] = frozenset()
    mutates: bool = False
    consent: ConsentContext | None = None
    requested_retention_days: int | None = None
    moderation: bool = False
    malware_scan_required: bool = False

    def __post_init__(self) -> None:
        if type(self.surface) is not NetworkSurface:
            raise SecurityContractError("request surface must be canonical")
        object.__setattr__(self, "operation", _operation(self.operation))
        if type(self.purpose) is not str or not self.purpose.strip() or len(self.purpose) > 64:
            raise SecurityContractError("request purpose is invalid")
        if type(self.actor_role) is not str or _ID_RE.fullmatch(self.actor_role) is None:
            raise SecurityContractError("actor role is invalid")
        if self.required_permission is not None and (
            type(self.required_permission) is not str
            or _ID_RE.fullmatch(self.required_permission) is None
        ):
            raise SecurityContractError("required permission is invalid")
        if type(self.granted_permissions) is not frozenset:
            raise SecurityContractError("granted permissions must be a frozenset")
        for permission in self.granted_permissions:
            if type(permission) is not str or _ID_RE.fullmatch(permission) is None:
                raise SecurityContractError("granted permission is invalid")
        if type(self.data_classes) is not frozenset or any(type(item) is not DataClass for item in self.data_classes):
            raise SecurityContractError("request data class is invalid")
        if type(self.mutates) is not bool or type(self.moderation) is not bool:
            raise SecurityContractError("request security flags must be boolean")
        if type(self.malware_scan_required) is not bool:
            raise SecurityContractError("malware-scan flag must be boolean")
        if self.requested_retention_days is not None and (
            type(self.requested_retention_days) is not int
            or not (1 <= self.requested_retention_days <= _MAX_RETENTION_DAYS)
        ):
            raise SecurityContractError("requested retention is invalid")


@dataclass(frozen=True, slots=True)
class SecurityGate:
    schema_version: int
    policy_revision: str
    policy_digest: str

    def __post_init__(self) -> None:
        if self.schema_version != 1:
            raise SecurityContractError("unsupported security-gate schema")
        if type(self.policy_revision) is not str or not self.policy_revision:
            raise SecurityContractError("security-gate revision is invalid")
        if (type(self.policy_digest) is not str or len(self.policy_digest) != 64
                or any(ch not in "0123456789abcdef" for ch in self.policy_digest)):
            raise SecurityContractError("security-gate digest is invalid")


class RateLimitPort(Protocol):
    def consume(self, *, key: str, limit: int, window_seconds: int) -> bool:
        ...


@dataclass(frozen=True, slots=True)
class ProductionSecurityPolicy:
    revision: str
    threats: tuple[ThreatModelEntry, ...]
    retention: tuple[RetentionRule, ...]
    rate_limits: tuple[RateLimitRule, ...]
    moderation_roles: frozenset[str] = frozenset({"teacher", "co_teacher", "admin"})
    secret_field_fragments: tuple[str, ...] = _SECRET_FIELD_FRAGMENTS

    def __post_init__(self) -> None:
        if type(self.revision) is not str or not self.revision.strip() or len(self.revision) > 64:
            raise SecurityContractError("security policy revision is invalid")
        if type(self.threats) is not tuple or any(type(x) is not ThreatModelEntry for x in self.threats):
            raise SecurityContractError("threat model is invalid")
        if type(self.retention) is not tuple or any(type(x) is not RetentionRule for x in self.retention):
            raise SecurityContractError("retention policy is invalid")
        if type(self.rate_limits) is not tuple or any(type(x) is not RateLimitRule for x in self.rate_limits):
            raise SecurityContractError("rate-limit policy is invalid")
        if type(self.moderation_roles) is not frozenset or not self.moderation_roles:
            raise SecurityContractError("moderation roles are invalid")
        if type(self.secret_field_fragments) is not tuple or not self.secret_field_fragments:
            raise SecurityContractError("log-redaction fields are invalid")
        self._validate_production_completeness()

    def _validate_production_completeness(self) -> None:
        surfaces = {entry.surface for entry in self.threats}
        if surfaces != set(NetworkSurface) or len(surfaces) != len(self.threats):
            raise SecurityContractError("threat model must cover every network surface exactly once")
        retention = {rule.data_class: rule for rule in self.retention}
        if not _SENSITIVE_RETENTION.issubset(retention):
            raise SecurityContractError("sensitive data classes require explicit retention")
        for data_class in _SENSITIVE_RETENTION:
            rule = retention[data_class]
            if not rule.deletion_supported or not rule.export_supported:
                raise SecurityContractError("sensitive data requires deletion and export hooks")
        if not self.rate_limits:
            raise SecurityContractError("networked production requires rate limits")
        prefixes = [rule.operation_prefix for rule in self.rate_limits]
        if len(prefixes) != len(set(prefixes)):
            raise SecurityContractError("duplicate rate-limit prefix")

    @property
    def retention_map(self) -> Mapping[DataClass, RetentionRule]:
        return MappingProxyType({rule.data_class: rule for rule in self.retention})

    def digest(self) -> str:
        payload = {
            "schema_version": 1,
            "revision": self.revision,
            "threats": [{
                "surface": entry.surface.value,
                "threats": list(entry.threats),
                "controls": list(entry.controls),
            } for entry in self.threats],
            "retention": [{
                "data_class": rule.data_class.value,
                "max_days": rule.max_days,
                "deletion_supported": rule.deletion_supported,
                "export_supported": rule.export_supported,
            } for rule in self.retention],
            "rate_limits": [{
                "operation_prefix": rule.operation_prefix,
                "limit": rule.limit,
                "window_seconds": rule.window_seconds,
            } for rule in self.rate_limits],
            "moderation_roles": sorted(self.moderation_roles),
            "secret_field_fragments": list(self.secret_field_fragments),
        }
        encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    def gate(self) -> SecurityGate:
        return SecurityGate(1, self.revision, self.digest())

    def verify_gate(self, gate: SecurityGate) -> None:
        if type(gate) is not SecurityGate:
            raise SecurityContractError("Section 29 security gate is required")
        if gate.policy_revision != self.revision or gate.policy_digest != self.digest():
            raise SecurityContractError("Section 29 security gate does not match policy")

    def rate_rule_for(self, operation: str) -> RateLimitRule:
        op = _operation(operation)
        matching = [rule for rule in self.rate_limits if op.startswith(rule.operation_prefix)]
        if not matching:
            raise SecurityContractError("operation has no production rate-limit policy")
        return max(matching, key=lambda rule: len(rule.operation_prefix))

    def authorize(self, request: SecurityRequest) -> None:
        if type(request) is not SecurityRequest:
            raise SecurityContractError("security request is required")
        if request.mutates:
            if not request.required_permission:
                raise SecurityContractError("state-changing request requires an explicit permission")
            if request.required_permission not in request.granted_permissions:
                raise SecurityContractError("state-changing request is not authorized")
        if request.moderation and request.actor_role not in self.moderation_roles:
            raise SecurityContractError("actor is not allowed to moderate")
        if request.purpose == "analytics" and request.data_classes.intersection(_FORBIDDEN_ORDINARY_ANALYTICS):
            raise SecurityContractError("raw product content is forbidden in ordinary analytics")
        retention = self.retention_map
        for data_class in request.data_classes.intersection(_SENSITIVE_RETENTION):
            rule = retention[data_class]
            if request.requested_retention_days is None:
                raise SecurityContractError("sensitive network data requires explicit retention")
            if request.requested_retention_days > rule.max_days:
                raise SecurityContractError("requested retention exceeds production policy")
        if DataClass.CHILD in request.data_classes or (
            request.consent is not None and request.consent.subject_is_minor
        ):
            if request.consent is None or not request.consent.production_allowed:
                raise SecurityContractError("minor/child network processing requires explicit consent")
        if request.surface is NetworkSurface.FILE_UPLOAD:
            if DataClass.FILE not in request.data_classes:
                raise SecurityContractError("file upload must be classified as file data")
            if not request.malware_scan_required:
                raise SecurityContractError("persistent file upload requires malware/content scanning")
        self.rate_rule_for(request.operation)

    def consume_rate_limit(self, limiter: RateLimitPort, *, operation: str, key: str) -> None:
        if limiter is None or not callable(getattr(limiter, "consume", None)):
            raise SecurityContractError("deployment rate limiter is required")
        if type(key) is not str or not key or len(key) > 256 or "\x00" in key:
            raise SecurityContractError("rate-limit key is invalid")
        rule = self.rate_rule_for(operation)
        try:
            allowed = limiter.consume(key=key, limit=rule.limit, window_seconds=rule.window_seconds)
        except Exception:
            raise SecurityContractError("rate limiter unavailable") from None
        if type(allowed) is not bool or not allowed:
            raise SecurityContractError("request rate limit exceeded")

    def redact_log_fields(self, values: Mapping[str, object]) -> dict[str, object]:
        if not isinstance(values, Mapping):
            raise SecurityContractError("log fields must be a mapping")
        result: dict[str, object] = {}
        for raw_key, value in values.items():
            if type(raw_key) is not str or not raw_key or len(raw_key) > 128:
                raise SecurityContractError("log field name is invalid")
            key = raw_key.lower()
            if any(fragment in key for fragment in self.secret_field_fragments) or key in _RAW_CONTENT_FIELDS:
                result[raw_key] = "[REDACTED]"
            elif isinstance(value, Mapping):
                result[raw_key] = self.redact_log_fields(value)
            elif type(value) in {str, int, float, bool} or value is None:
                result[raw_key] = value[:509] + "..." if type(value) is str and len(value) > 512 else value
            else:
                result[raw_key] = "[UNLOGGABLE]"
        return result


def _operation(value: object) -> str:
    if type(value) is not str or _OPERATION_RE.fullmatch(value) is None:
        raise SecurityContractError("operation identifier is invalid")
    return value


DEFAULT_SECTION29_POLICY = ProductionSecurityPolicy(
    revision="section29-v1",
    threats=(
        ThreatModelEntry(NetworkSurface.SERVER, ("unauthorized mutation", "request replay", "resource exhaustion"), ("authenticated principal", "permission check", "bounded DTO", "rate limit")),
        ThreatModelEntry(NetworkSurface.CLASSROOM, ("cross-room access", "abuse", "child-data overcollection"), ("room authorization", "moderation", "consent/retention")),
        ThreatModelEntry(NetworkSurface.WEB, ("browser identity spoofing", "injection", "cross-workspace access"), ("trusted middleware identity", "strict JSON", "workspace authorization")),
        ThreatModelEntry(NetworkSurface.AGENT, ("tool overreach", "secret exfiltration", "prompt-controlled authority"), ("typed tools", "least privilege", "redacted logs")),
        ThreatModelEntry(NetworkSurface.MEDIA, ("stale token", "unexpected publishing", "recording without consent"), ("short-lived server token", "safe publish defaults", "recording consent")),
        ThreatModelEntry(NetworkSurface.FILE_UPLOAD, ("path traversal", "malware", "quota abuse"), ("opaque bytes", "safe names", "scanner", "quota/rate limit")),
    ),
    retention=(
        RetentionRule(DataClass.PROFILE, 3650),
        RetentionRule(DataClass.CHILD, 365),
        RetentionRule(DataClass.CLASSROOM_STATE, 730),
        RetentionRule(DataClass.CHAT, 365),
        RetentionRule(DataClass.FILE, 90),
        RetentionRule(DataClass.AUDIO_VIDEO, 90),
    ),
    rate_limits=(
        RateLimitRule("server.", 600, 60),
        RateLimitRule("classroom.", 300, 60),
        RateLimitRule("web.", 600, 60),
        RateLimitRule("agent.", 120, 60),
        RateLimitRule("media.", 120, 60),
        RateLimitRule("file.", 60, 60),
    ),
)


__all__ = [
    "ConsentContext", "DataClass", "DEFAULT_SECTION29_POLICY", "NetworkSurface",
    "ProductionSecurityPolicy", "RateLimitPort", "RateLimitRule", "RetentionRule",
    "SecurityContractError", "SecurityGate", "SecurityRequest", "ThreatModelEntry",
]
