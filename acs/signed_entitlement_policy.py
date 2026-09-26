from __future__ import annotations

"""Fail-closed authenticity boundary for remote entitlement policy.

The canonical entitlement model lives in :mod:`acs.entitlements`.  This module
only authenticates a bounded wire envelope and projects an authenticated payload
into that existing model.  It deliberately does not own transport, credentials,
billing, token persistence, signing private keys, or feature-gate semantics.
"""

from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
import base64
import binascii
import json
import re
from typing import Any, Mapping, Protocol, runtime_checkable

from .entitlements import EntitlementSnapshot, EntitlementState, ProductVersion, RemotePolicy


SIGNED_POLICY_SCHEMA = "accessible-chess-entitlement-policy-v1"
_SIGNATURE_DOMAIN = b"accessible-chess-entitlement-policy-v1\n"
_MAX_ENVELOPE_BYTES = 32 * 1024
_MAX_FEATURES = 256
_MAX_TEXT = 256
_KEY_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_POLICY_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_TOP_LEVEL_FIELDS = frozenset({"schema", "key_id", "payload", "signature"})
_PAYLOAD_FIELDS = frozenset(
    {
        "policy_id",
        "state",
        "feature_ids",
        "issued_at",
        "expires_at",
        "server_time",
        "minimum_supported_version",
        "refresh_after",
        "grace_until",
        "account_id",
        "organization_id",
    }
)


class SignedEntitlementPolicyError(ValueError):
    """Stable fail-closed error for untrusted remote entitlement material."""


@runtime_checkable
class EntitlementSignatureVerifier(Protocol):
    """Verify one asymmetric signature using a trusted public-key identity.

    Implementations belong to infrastructure and MUST NOT require a signing
    private key in the desktop client.  Returning false is an ordinary
    authentication failure; provider exceptions are sanitized by this module.
    """

    def verify(self, *, key_id: str, message: bytes, signature: bytes) -> bool:
        ...


@dataclass(frozen=True, slots=True)
class VerifiedEntitlementPolicy:
    policy_id: str
    key_id: str
    issued_at: datetime
    signed_server_time: datetime
    snapshot: EntitlementSnapshot
    message_sha256: str


@dataclass(slots=True)
class EntitlementReplayGuard:
    """In-process monotonic guard for authenticated policy observations.

    Persistence of the anchor across restarts is intentionally a separate
    infrastructure concern.  The guard is useful even without persistence: once
    a newer server-time observation has been accepted in this process, an older
    signed policy cannot roll it back.
    """

    _latest_server_time: datetime | None = None
    _latest_message_sha256: str | None = None

    def accept(self, policy: VerifiedEntitlementPolicy) -> None:
        if not isinstance(policy, VerifiedEntitlementPolicy):
            raise TypeError("policy must be VerifiedEntitlementPolicy")
        latest = self._latest_server_time
        if latest is not None:
            if policy.signed_server_time < latest:
                raise SignedEntitlementPolicyError("signed entitlement policy is older than the accepted server-time anchor")
            if (
                policy.signed_server_time == latest
                and self._latest_message_sha256 is not None
                and policy.message_sha256 != self._latest_message_sha256
            ):
                raise SignedEntitlementPolicyError("conflicting signed entitlement policies share one server-time anchor")
        self._latest_server_time = policy.signed_server_time
        self._latest_message_sha256 = policy.message_sha256


def verify_signed_entitlement_policy(
    data: bytes,
    *,
    verifier: EntitlementSignatureVerifier,
    replay_guard: EntitlementReplayGuard | None = None,
) -> VerifiedEntitlementPolicy:
    """Authenticate and parse a strict signed entitlement envelope.

    No claim is projected into :class:`EntitlementSnapshot` before the signature
    succeeds.  Unknown/duplicate fields, non-canonical signature encoding,
    malformed timestamps, temporal contradictions, and provider failures all
    fail closed.
    """

    if type(data) is not bytes:
        raise SignedEntitlementPolicyError("signed entitlement envelope must be bytes")
    if not data or len(data) > _MAX_ENVELOPE_BYTES:
        raise SignedEntitlementPolicyError("signed entitlement envelope has an invalid size")
    if not isinstance(verifier, EntitlementSignatureVerifier):
        raise SignedEntitlementPolicyError("signature verifier is unavailable")

    try:
        text = data.decode("utf-8", errors="strict")
    except UnicodeDecodeError as exc:
        raise SignedEntitlementPolicyError("signed entitlement envelope is not valid UTF-8") from exc

    try:
        document = json.loads(text, object_pairs_hook=_reject_duplicate_object_pairs)
    except SignedEntitlementPolicyError:
        raise
    except (json.JSONDecodeError, UnicodeError, ValueError, TypeError, RecursionError):
        raise SignedEntitlementPolicyError("signed entitlement envelope is not valid JSON") from None

    top = _require_exact_mapping(document, _TOP_LEVEL_FIELDS, "signed entitlement envelope")
    schema = _require_text(top["schema"], "schema")
    if schema != SIGNED_POLICY_SCHEMA:
        raise SignedEntitlementPolicyError("signed entitlement policy schema is unsupported")
    key_id = _require_identifier(top["key_id"], "key_id", _KEY_ID_RE)
    payload = _require_exact_mapping(top["payload"], _PAYLOAD_FIELDS, "signed entitlement payload")
    signature = _decode_signature(top["signature"])

    message = _canonical_signature_message(schema=schema, key_id=key_id, payload=payload)
    try:
        verified = verifier.verify(key_id=key_id, message=message, signature=signature)
    except Exception:
        raise SignedEntitlementPolicyError("signed entitlement policy verification failed") from None
    if verified is not True:
        raise SignedEntitlementPolicyError("signed entitlement policy signature is invalid")

    result = _project_verified_payload(payload, key_id=key_id, message=message)
    if replay_guard is not None:
        if not isinstance(replay_guard, EntitlementReplayGuard):
            raise TypeError("replay_guard must be EntitlementReplayGuard")
        replay_guard.accept(result)
    return result


def canonical_entitlement_signature_message(*, schema: str, key_id: str, payload: Mapping[str, Any]) -> bytes:
    """Return the exact bytes an external signer/verifier must authenticate.

    This helper contains no signing operation and accepts no private key.
    """

    if schema != SIGNED_POLICY_SCHEMA:
        raise SignedEntitlementPolicyError("signed entitlement policy schema is unsupported")
    normalized_key = _require_identifier(key_id, "key_id", _KEY_ID_RE)
    bounded_payload = _require_exact_mapping(payload, _PAYLOAD_FIELDS, "signed entitlement payload")
    return _canonical_signature_message(schema=schema, key_id=normalized_key, payload=bounded_payload)


def _reject_duplicate_object_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise SignedEntitlementPolicyError("signed entitlement JSON contains a duplicate field")
        result[key] = value
    return result


def _require_exact_mapping(value: Any, fields: frozenset[str], name: str) -> dict[str, Any]:
    if type(value) is not dict:
        raise SignedEntitlementPolicyError(f"{name} must be an object")
    keys = set(value)
    if keys != fields:
        raise SignedEntitlementPolicyError(f"{name} fields are invalid")
    return dict(value)


def _require_text(value: Any, name: str, *, allow_none: bool = False) -> str | None:
    if value is None and allow_none:
        return None
    if type(value) is not str or not value or len(value) > _MAX_TEXT:
        raise SignedEntitlementPolicyError(f"{name} must be bounded non-empty text")
    if any(ord(ch) < 0x20 or ord(ch) == 0x7F for ch in value):
        raise SignedEntitlementPolicyError(f"{name} contains control characters")
    return value


def _require_identifier(value: Any, name: str, pattern: re.Pattern[str]) -> str:
    text = _require_text(value, name)
    assert isinstance(text, str)
    if pattern.fullmatch(text) is None:
        raise SignedEntitlementPolicyError(f"{name} has an invalid format")
    return text


def _decode_signature(value: Any) -> bytes:
    text = _require_text(value, "signature")
    assert isinstance(text, str)
    if "=" in text:
        raise SignedEntitlementPolicyError("signature must use unpadded base64url")
    if not re.fullmatch(r"[A-Za-z0-9_-]+", text):
        raise SignedEntitlementPolicyError("signature is not canonical base64url")
    padding = "=" * ((4 - len(text) % 4) % 4)
    try:
        decoded = base64.urlsafe_b64decode((text + padding).encode("ascii"))
    except (binascii.Error, ValueError) as exc:
        raise SignedEntitlementPolicyError("signature is not valid base64url") from exc
    if not 32 <= len(decoded) <= 1024:
        raise SignedEntitlementPolicyError("signature has an invalid size")
    canonical = base64.urlsafe_b64encode(decoded).decode("ascii").rstrip("=")
    if canonical != text:
        raise SignedEntitlementPolicyError("signature is not canonical base64url")
    return decoded


def _canonical_signature_message(*, schema: str, key_id: str, payload: Mapping[str, Any]) -> bytes:
    signed = {"key_id": key_id, "payload": payload, "schema": schema}
    try:
        encoded = json.dumps(
            signed,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    except (TypeError, ValueError, UnicodeError, RecursionError):
        raise SignedEntitlementPolicyError("signed entitlement payload is not canonically serializable") from None
    if len(encoded) > _MAX_ENVELOPE_BYTES:
        raise SignedEntitlementPolicyError("signed entitlement payload is too large")
    return _SIGNATURE_DOMAIN + encoded


def _parse_timestamp(value: Any, name: str, *, allow_none: bool = False) -> datetime | None:
    if value is None and allow_none:
        return None
    text = _require_text(value, name)
    assert isinstance(text, str)
    if not text.endswith("Z"):
        raise SignedEntitlementPolicyError(f"{name} must be canonical UTC with Z")
    try:
        parsed = datetime.fromisoformat(text[:-1] + "+00:00")
    except ValueError as exc:
        raise SignedEntitlementPolicyError(f"{name} is not a valid UTC timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() != timezone.utc.utcoffset(parsed):
        raise SignedEntitlementPolicyError(f"{name} must be UTC")
    canonical = parsed.isoformat(timespec="seconds").replace("+00:00", "Z")
    if text != canonical:
        raise SignedEntitlementPolicyError(f"{name} is not canonical to whole seconds")
    return parsed


def _parse_optional_version(value: Any) -> ProductVersion | None:
    if value is None:
        return None
    text = _require_text(value, "minimum_supported_version")
    assert isinstance(text, str)
    try:
        version = ProductVersion.parse(text)
    except (TypeError, ValueError) as exc:
        raise SignedEntitlementPolicyError("minimum_supported_version is invalid") from exc
    if str(version) != text:
        raise SignedEntitlementPolicyError("minimum_supported_version is not canonical")
    return version


def _parse_features(value: Any) -> frozenset[str]:
    if type(value) is not list or not value or len(value) > _MAX_FEATURES:
        raise SignedEntitlementPolicyError("feature_ids must be a bounded non-empty list")
    features: list[str] = []
    for raw in value:
        text = _require_text(raw, "feature_id")
        assert isinstance(text, str)
        normalized = text.strip().lower()
        if text != normalized or any(ch.isspace() for ch in text):
            raise SignedEntitlementPolicyError("feature_id is not canonical")
        features.append(text)
    if len(set(features)) != len(features) or features != sorted(features):
        raise SignedEntitlementPolicyError("feature_ids must be unique and sorted")
    return frozenset(features)


def _project_verified_payload(
    payload: Mapping[str, Any], *, key_id: str, message: bytes
) -> VerifiedEntitlementPolicy:
    policy_id = _require_identifier(payload["policy_id"], "policy_id", _POLICY_ID_RE)
    state_text = _require_text(payload["state"], "state")
    assert isinstance(state_text, str)
    try:
        state = EntitlementState(state_text)
    except ValueError as exc:
        raise SignedEntitlementPolicyError("entitlement state is unsupported") from exc

    issued_at = _parse_timestamp(payload["issued_at"], "issued_at")
    server_time = _parse_timestamp(payload["server_time"], "server_time")
    expires_at = _parse_timestamp(payload["expires_at"], "expires_at", allow_none=True)
    refresh_after = _parse_timestamp(payload["refresh_after"], "refresh_after", allow_none=True)
    grace_until = _parse_timestamp(payload["grace_until"], "grace_until", allow_none=True)
    assert isinstance(issued_at, datetime)
    assert isinstance(server_time, datetime)

    if issued_at > server_time:
        raise SignedEntitlementPolicyError("issued_at cannot be later than signed server_time")
    if refresh_after is not None and refresh_after < issued_at:
        raise SignedEntitlementPolicyError("refresh_after cannot precede issued_at")
    if expires_at is not None and expires_at < issued_at:
        raise SignedEntitlementPolicyError("expires_at cannot precede issued_at")
    if grace_until is not None:
        floor = expires_at or issued_at
        if grace_until < floor:
            raise SignedEntitlementPolicyError("grace_until cannot precede entitlement expiry")

    account_id = _require_text(payload["account_id"], "account_id", allow_none=True)
    organization_id = _require_text(payload["organization_id"], "organization_id", allow_none=True)
    features = _parse_features(payload["feature_ids"])
    version = _parse_optional_version(payload["minimum_supported_version"])

    snapshot = EntitlementSnapshot(
        state=state,
        feature_ids=features,
        expires_at=expires_at,
        server_time=server_time,
        policy=RemotePolicy(
            minimum_supported_version=version,
            refresh_after=refresh_after,
            grace_until=grace_until,
        ),
        account_id=account_id,
        organization_id=organization_id,
        source=f"signed_remote:{key_id}",
    )
    return VerifiedEntitlementPolicy(
        policy_id=policy_id,
        key_id=key_id,
        issued_at=issued_at,
        signed_server_time=server_time,
        snapshot=snapshot,
        message_sha256=sha256(message).hexdigest(),
    )
