from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Mapping, Protocol
import math
import time


class IdTokenError(ValueError):
    """Bounded OIDC identity validation failure.

    Messages intentionally identify only the failed contract dimension. They do
    not include the compact token, claim values, provider responses, or keys.
    """


@dataclass(frozen=True)
class VerifiedIdTokenEnvelope:
    """Claims authenticated by an injected JWS verification authority."""

    algorithm: str
    claims: Mapping[str, object]


class IdTokenSignatureVerifier(Protocol):
    def verify(self, compact_token: str) -> VerifiedIdTokenEnvelope:
        """Cryptographically verify token/JWK policy and return authenticated claims."""


@dataclass(frozen=True)
class TrustedOidcIdentity:
    issuer: str
    subject: str = field(repr=False)
    audiences: tuple[str, ...]
    issued_at: int
    expires_at: int


Clock = Callable[[], float]
_MAX_AUTHENTICATED_CLAIMS = 128


def validate_id_token(
    compact_token: str,
    *,
    verifier: IdTokenSignatureVerifier,
    expected_issuer: str,
    client_id: str,
    expected_nonce: str,
    now: Clock = time.time,
    clock_skew_seconds: int = 60,
) -> TrustedOidcIdentity:
    """Validate authenticated OIDC ID-token claims after JWS verification."""

    _require_nonempty_string(compact_token, "token")
    issuer = _require_nonempty_string(expected_issuer, "issuer")
    audience = _require_nonempty_string(client_id, "client")
    nonce = _require_nonempty_string(expected_nonce, "nonce")
    if not isinstance(clock_skew_seconds, int) or isinstance(clock_skew_seconds, bool):
        raise IdTokenError("invalid clock skew")
    if not 0 <= clock_skew_seconds <= 300:
        raise IdTokenError("invalid clock skew")

    try:
        envelope = verifier.verify(compact_token)
    except Exception:
        raise IdTokenError("signature verification failed") from None

    if not isinstance(envelope, VerifiedIdTokenEnvelope):
        raise IdTokenError("invalid verified token envelope")
    algorithm = _require_nonempty_string(envelope.algorithm, "algorithm")
    if algorithm.casefold() == "none":
        raise IdTokenError("unsecured token algorithm rejected")
    claims = _snapshot_authenticated_claims(envelope.claims)

    token_issuer = _claim_string(claims, "iss")
    subject = _claim_string(claims, "sub")
    token_nonce = _claim_string(claims, "nonce")
    if token_issuer != issuer:
        raise IdTokenError("issuer mismatch")
    if token_nonce != nonce:
        raise IdTokenError("nonce mismatch")

    audiences = _claim_audiences(claims)
    if audience not in audiences:
        raise IdTokenError("audience mismatch")
    azp = claims.get("azp")
    if len(audiences) > 1:
        if not isinstance(azp, str) or not azp.strip():
            raise IdTokenError("authorized party required")
        if azp != audience:
            raise IdTokenError("authorized party mismatch")
    elif azp is not None:
        if not isinstance(azp, str) or azp != audience:
            raise IdTokenError("authorized party mismatch")

    issued_at = _claim_timestamp(claims, "iat")
    expires_at = _claim_timestamp(claims, "exp")
    not_before = _optional_claim_timestamp(claims, "nbf")

    try:
        current = float(now())
    except Exception:
        raise IdTokenError("clock unavailable") from None
    if not math.isfinite(current):
        raise IdTokenError("clock unavailable")

    skew = float(clock_skew_seconds)
    if expires_at <= current - skew:
        raise IdTokenError("token expired")
    if issued_at > current + skew:
        raise IdTokenError("token issued in future")
    if expires_at <= issued_at:
        raise IdTokenError("invalid token lifetime")
    if not_before is not None and not_before > current + skew:
        raise IdTokenError("token not yet valid")

    return TrustedOidcIdentity(
        issuer=token_issuer,
        subject=subject,
        audiences=audiences,
        issued_at=issued_at,
        expires_at=expires_at,
    )


def _snapshot_authenticated_claims(value: object) -> dict[str, object]:
    if not isinstance(value, Mapping):
        raise IdTokenError("invalid verified claims")
    result: dict[str, object] = {}
    try:
        for index, key in enumerate(value):
            if index >= _MAX_AUTHENTICATED_CLAIMS:
                raise IdTokenError("invalid verified claims")
            if not isinstance(key, str) or not key or key in result:
                raise IdTokenError("invalid verified claims")
            result[key] = value[key]
    except IdTokenError:
        raise
    except Exception:
        raise IdTokenError("invalid verified claims") from None
    if not result:
        raise IdTokenError("invalid verified claims")
    return result


def _require_nonempty_string(value: object, dimension: str) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > 4096:
        raise IdTokenError(f"invalid {dimension}")
    if "\x00" in value or "\r" in value or "\n" in value:
        raise IdTokenError(f"invalid {dimension}")
    return value


def _claim_string(claims: Mapping[str, object], name: str) -> str:
    value = claims.get(name)
    if not isinstance(value, str) or not value or len(value) > 4096:
        raise IdTokenError(f"invalid {name} claim")
    if "\x00" in value or "\r" in value or "\n" in value:
        raise IdTokenError(f"invalid {name} claim")
    return value


def _claim_audiences(claims: Mapping[str, object]) -> tuple[str, ...]:
    value = claims.get("aud")
    if isinstance(value, str):
        values = (value,)
    elif isinstance(value, (list, tuple)):
        values = tuple(value)
    else:
        raise IdTokenError("invalid aud claim")
    if not values or len(values) > 32:
        raise IdTokenError("invalid aud claim")
    normalized: list[str] = []
    for item in values:
        if not isinstance(item, str) or not item or len(item) > 4096:
            raise IdTokenError("invalid aud claim")
        if "\x00" in item or "\r" in item or "\n" in item:
            raise IdTokenError("invalid aud claim")
        if item in normalized:
            raise IdTokenError("invalid aud claim")
        normalized.append(item)
    return tuple(normalized)


def _claim_timestamp(claims: Mapping[str, object], name: str) -> int:
    if name not in claims:
        raise IdTokenError(f"missing {name} claim")
    return _timestamp_value(claims[name], name)


def _optional_claim_timestamp(claims: Mapping[str, object], name: str) -> int | None:
    if name not in claims:
        return None
    return _timestamp_value(claims[name], name)


def _timestamp_value(value: object, name: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise IdTokenError(f"invalid {name} claim")
    if value < 0 or value > 253402300799:
        raise IdTokenError(f"invalid {name} claim")
    return value
