from __future__ import annotations

"""Provider-neutral OIDC ID-token verification for the native PKCE flow.

The network adapter owns discovery/JWKS retrieval and must provide already-decoded
JWKS JSON obtained from the configured provider over the trusted HTTPS boundary.
This module performs no I/O and supports the conservative OIDC baseline used by
Accessible Chess: compact JWS signed with RS256 and an RSA JWK selected by kid.
"""

import base64
import hashlib
import json
import secrets
import time
from dataclasses import dataclass, field
from typing import Mapping

from .oauth_pkce import OAuthContractError, _require_text


_MAX_TOKEN_LENGTH = 16384
_MAX_JSON_SEGMENT = 12288
_MAX_JWKS_KEYS = 32
_MAX_CLOCK_SKEW = 300
_SHA256_DIGEST_INFO = bytes.fromhex("3031300d060960864801650304020105000420")


class OidcIdTokenError(OAuthContractError):
    """Raised when an ID token cannot be cryptographically trusted."""


def _b64url_decode(name: str, value: object, *, limit: int = _MAX_JSON_SEGMENT) -> bytes:
    text = _require_text(name, value, max_length=limit)
    if "=" in text:
        raise OidcIdTokenError(f"{name} must use unpadded base64url")
    allowed = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_"
    if any(char not in allowed for char in text):
        raise OidcIdTokenError(f"{name} is not canonical base64url")
    try:
        return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))
    except (ValueError, TypeError) as exc:
        raise OidcIdTokenError(f"{name} is invalid base64url") from exc


def _plain_json_object(name: str, encoded: str) -> dict[str, object]:
    raw = _b64url_decode(name, encoded)
    if len(raw) > _MAX_JSON_SEGMENT:
        raise OidcIdTokenError(f"{name} is too large")

    def object_pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in pairs:
            if not isinstance(key, str) or key in result:
                raise OidcIdTokenError(f"{name} contains duplicate or invalid keys")
            result[key] = value
        return result

    try:
        value = json.loads(raw.decode("utf-8"), object_pairs_hook=object_pairs)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise OidcIdTokenError(f"{name} is not valid UTF-8 JSON") from exc
    if type(value) is not dict:
        raise OidcIdTokenError(f"{name} must be a JSON object")
    return value


def _jwk_integer(name: str, value: object) -> int:
    raw = _b64url_decode(name, value, limit=2048)
    if not raw or raw[0] == 0:
        raise OidcIdTokenError(f"{name} is not a canonical unsigned integer")
    return int.from_bytes(raw, "big")


def _select_rsa_key(jwks: Mapping[str, object], *, kid: str) -> tuple[int, int]:
    if type(jwks) is not dict:
        raise OidcIdTokenError("JWKS must be a plain JSON object")
    keys = jwks.get("keys")
    if type(keys) is not list or not 1 <= len(keys) <= _MAX_JWKS_KEYS:
        raise OidcIdTokenError("JWKS keys must be a bounded non-empty array")

    candidates: list[dict[str, object]] = []
    for raw_key in keys:
        if type(raw_key) is not dict:
            raise OidcIdTokenError("JWKS entries must be plain objects")
        if raw_key.get("kid") != kid:
            continue
        if raw_key.get("kty") != "RSA":
            continue
        if raw_key.get("alg") not in (None, "RS256"):
            continue
        if raw_key.get("use") not in (None, "sig"):
            continue
        key_ops = raw_key.get("key_ops")
        if key_ops is not None:
            if type(key_ops) is not list or "verify" not in key_ops:
                continue
            if any(not isinstance(item, str) for item in key_ops):
                raise OidcIdTokenError("JWK key_ops must contain text values")
            if len(set(key_ops)) != len(key_ops):
                raise OidcIdTokenError("JWK key_ops must not contain duplicates")
        candidates.append(raw_key)
    if len(candidates) != 1:
        raise OidcIdTokenError("JWKS must contain exactly one matching RS256 signing key")

    modulus = _jwk_integer("JWK n", candidates[0].get("n"))
    exponent = _jwk_integer("JWK e", candidates[0].get("e"))
    if not 2048 <= modulus.bit_length() <= 8192:
        raise OidcIdTokenError("RSA signing key size is outside policy bounds")
    if exponent < 3 or exponent > 0xFFFFFFFF or exponent % 2 == 0:
        raise OidcIdTokenError("RSA public exponent is invalid")
    return modulus, exponent


def _verify_rs256(signing_input: bytes, signature: bytes, *, modulus: int, exponent: int) -> None:
    width = (modulus.bit_length() + 7) // 8
    if len(signature) != width:
        raise OidcIdTokenError("ID token signature has the wrong length")
    signature_number = int.from_bytes(signature, "big")
    if signature_number >= modulus:
        raise OidcIdTokenError("ID token signature is outside the RSA modulus")
    encoded = pow(signature_number, exponent, modulus).to_bytes(width, "big")
    digest = hashlib.sha256(signing_input).digest()
    expected_tail = _SHA256_DIGEST_INFO + digest
    padding_length = width - len(expected_tail) - 3
    if padding_length < 8:
        raise OidcIdTokenError("RSA key is too small for RS256")
    expected = b"\x00\x01" + b"\xff" * padding_length + b"\x00" + expected_tail
    if not secrets.compare_digest(encoded, expected):
        raise OidcIdTokenError("ID token signature verification failed")


def _numeric_date(claims: Mapping[str, object], name: str, *, required: bool) -> int | None:
    value = claims.get(name)
    if value is None and not required:
        return None
    if type(value) is not int or value < 0:
        raise OidcIdTokenError(f"ID token {name} must be a non-negative integer")
    return value


def _audiences(value: object) -> tuple[str, ...]:
    if isinstance(value, str):
        return (_require_text("ID token aud", value, max_length=512),)
    if type(value) is list and value:
        result = tuple(_require_text("ID token aud", item, max_length=512) for item in value)
        if len(set(result)) != len(result):
            raise OidcIdTokenError("ID token aud must not contain duplicates")
        return result
    raise OidcIdTokenError("ID token aud must be text or a non-empty text array")


@dataclass(frozen=True)
class VerifiedIdToken:
    subject: str = field(repr=False)
    issuer: str
    audience: tuple[str, ...]
    issued_at: int
    expires_at: int
    claims: Mapping[str, object] = field(repr=False)


def verify_id_token(
    token: str,
    *,
    jwks: Mapping[str, object],
    expected_issuer: str,
    client_id: str,
    expected_nonce: str,
    now: int | None = None,
    clock_skew_seconds: int = 60,
) -> VerifiedIdToken:
    """Verify RS256 signature and the OIDC claims bound to one PKCE request."""

    compact = _require_text("id_token", token, max_length=_MAX_TOKEN_LENGTH)
    parts = compact.split(".")
    if len(parts) != 3 or any(not part for part in parts):
        raise OidcIdTokenError("ID token must be a three-part compact JWS")
    header = _plain_json_object("ID token header", parts[0])
    claims = _plain_json_object("ID token payload", parts[1])

    if header.get("alg") != "RS256":
        raise OidcIdTokenError("ID token must use RS256")
    if header.get("typ") not in (None, "JWT"):
        raise OidcIdTokenError("ID token typ is unsupported")
    if "crit" in header:
        raise OidcIdTokenError("ID token critical extensions are unsupported")
    kid = _require_text("ID token kid", header.get("kid"), max_length=256)
    modulus, exponent = _select_rsa_key(jwks, kid=kid)
    signature = _b64url_decode("ID token signature", parts[2], limit=2048)
    _verify_rs256(
        f"{parts[0]}.{parts[1]}".encode("ascii"),
        signature,
        modulus=modulus,
        exponent=exponent,
    )

    issuer = _require_text("ID token iss", claims.get("iss"), max_length=2048)
    trusted_issuer = _require_text("expected_issuer", expected_issuer, max_length=2048)
    if not secrets.compare_digest(issuer, trusted_issuer):
        raise OidcIdTokenError("ID token issuer does not match configured issuer")

    trusted_client = _require_text("client_id", client_id, max_length=512)
    audience = _audiences(claims.get("aud"))
    if trusted_client not in audience:
        raise OidcIdTokenError("ID token audience does not include this client")
    authorized_party = claims.get("azp")
    if len(audience) > 1:
        if authorized_party != trusted_client:
            raise OidcIdTokenError("multi-audience ID token requires matching azp")
    elif authorized_party is not None and authorized_party != trusted_client:
        raise OidcIdTokenError("ID token azp does not match this client")

    nonce = _require_text("ID token nonce", claims.get("nonce"), max_length=512)
    request_nonce = _require_text("expected_nonce", expected_nonce, max_length=512)
    if not secrets.compare_digest(nonce, request_nonce):
        raise OidcIdTokenError("ID token nonce does not match the authorization request")

    if type(clock_skew_seconds) is not int or not 0 <= clock_skew_seconds <= _MAX_CLOCK_SKEW:
        raise OidcIdTokenError("clock skew must be an integer between 0 and 300 seconds")
    current = int(time.time()) if now is None else now
    if type(current) is not int or current < 0:
        raise OidcIdTokenError("verification time must be a non-negative integer")
    expires_at = _numeric_date(claims, "exp", required=True)
    issued_at = _numeric_date(claims, "iat", required=True)
    not_before = _numeric_date(claims, "nbf", required=False)
    assert expires_at is not None and issued_at is not None
    if current - clock_skew_seconds >= expires_at:
        raise OidcIdTokenError("ID token is expired")
    if issued_at > current + clock_skew_seconds:
        raise OidcIdTokenError("ID token iat is in the future")
    if not_before is not None and not_before > current + clock_skew_seconds:
        raise OidcIdTokenError("ID token is not yet valid")

    subject = _require_text("ID token sub", claims.get("sub"), max_length=1024)
    return VerifiedIdToken(
        subject=subject,
        issuer=issuer,
        audience=audience,
        issued_at=issued_at,
        expires_at=expires_at,
        claims=dict(claims),
    )


__all__ = ["OidcIdTokenError", "VerifiedIdToken", "verify_id_token"]
