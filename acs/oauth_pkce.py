from __future__ import annotations

"""Provider-neutral OAuth 2.0 / OIDC PKCE request construction.

This module deliberately owns no network transport, browser automation, token
storage, entitlement policy, billing policy, or provider-specific endpoints.
It provides the small fail-closed boundary needed by a later accessible login
surface and transport adapter.
"""

from dataclasses import dataclass
import base64
import hashlib
import secrets
from typing import Iterable, Mapping
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit


class OAuthContractError(ValueError):
    """Raised when an authorization request would violate the local contract."""


_RESERVED_AUTHORIZATION_PARAMETERS = frozenset(
    {
        "client_id",
        "code_challenge",
        "code_challenge_method",
        "nonce",
        "redirect_uri",
        "response_type",
        "scope",
        "state",
    }
)


def _require_text(name: str, value: object, *, max_length: int = 4096) -> str:
    if not isinstance(value, str):
        raise OAuthContractError(f"{name} must be text")
    if not value or value != value.strip():
        raise OAuthContractError(f"{name} must be non-empty canonical text")
    if len(value) > max_length or any(ord(char) < 0x20 for char in value):
        raise OAuthContractError(f"{name} is invalid")
    return value


def _split_url(name: str, value: str):
    try:
        parsed = urlsplit(value)
        # Accessing hostname/port performs additional structural validation and
        # raises for malformed bracket/port forms that a raw split can retain.
        _ = parsed.hostname
        _ = parsed.port
    except (TypeError, ValueError) as exc:
        raise OAuthContractError(f"{name} is not a valid URL") from exc
    return parsed


def _validate_endpoint(name: str, value: object) -> str:
    endpoint = _require_text(name, value)
    parsed = _split_url(name, endpoint)
    if parsed.scheme != "https" or not parsed.netloc or not parsed.hostname:
        raise OAuthContractError(f"{name} must be an absolute HTTPS URL")
    if parsed.username is not None or parsed.password is not None or parsed.fragment:
        raise OAuthContractError(f"{name} must not contain userinfo or a fragment")
    return endpoint


def _validate_redirect_uri(value: object) -> str:
    redirect_uri = _require_text("redirect_uri", value)
    parsed = _split_url("redirect_uri", redirect_uri)
    if not parsed.scheme or not parsed.netloc or not parsed.hostname or parsed.fragment:
        raise OAuthContractError("redirect_uri must be absolute and fragment-free")
    if parsed.username is not None or parsed.password is not None:
        raise OAuthContractError("redirect_uri must not contain userinfo")
    if parsed.scheme == "https":
        return redirect_uri
    # RFC 8252 native-app loopback redirects use literal loopback addresses so
    # local name resolution cannot redirect the callback to a non-loopback host.
    if parsed.scheme == "http" and parsed.hostname in {"127.0.0.1", "::1"}:
        return redirect_uri
    raise OAuthContractError("redirect_uri must use HTTPS or a literal loopback HTTP host")


def _normalize_scopes(scopes: Iterable[str]) -> tuple[str, ...]:
    if isinstance(scopes, (str, bytes)):
        raise OAuthContractError("scopes must be an iterable of individual values")
    result: list[str] = []
    seen: set[str] = set()
    for scope in scopes:
        value = _require_text("scope", scope, max_length=256)
        if any(char.isspace() for char in value):
            raise OAuthContractError("individual scopes must not contain whitespace")
        if value not in seen:
            seen.add(value)
            result.append(value)
    if not result:
        raise OAuthContractError("at least one scope is required")
    return tuple(result)


def generate_code_verifier() -> str:
    """Generate an RFC 7636 verifier using a cryptographic random source."""

    verifier = secrets.token_urlsafe(48).rstrip("=")
    if not 43 <= len(verifier) <= 128:
        raise RuntimeError("generated PKCE verifier length is outside RFC 7636 bounds")
    return verifier


def code_challenge_s256(verifier: object) -> str:
    value = _require_text("code_verifier", verifier, max_length=128)
    if not 43 <= len(value) <= 128:
        raise OAuthContractError("code_verifier must contain 43..128 characters")
    allowed = set("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-._~")
    if any(char not in allowed for char in value):
        raise OAuthContractError("code_verifier contains a character outside RFC 7636")
    digest = hashlib.sha256(value.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


@dataclass(frozen=True)
class AuthorizationRequest:
    authorization_endpoint: str
    token_endpoint: str
    client_id: str
    redirect_uri: str
    scopes: tuple[str, ...]
    state: str
    nonce: str
    code_verifier: str

    @classmethod
    def create(
        cls,
        *,
        authorization_endpoint: str,
        token_endpoint: str,
        client_id: str,
        redirect_uri: str,
        scopes: Iterable[str],
        state: str | None = None,
        nonce: str | None = None,
        code_verifier: str | None = None,
    ) -> "AuthorizationRequest":
        return cls(
            authorization_endpoint=_validate_endpoint(
                "authorization_endpoint", authorization_endpoint
            ),
            token_endpoint=_validate_endpoint("token_endpoint", token_endpoint),
            client_id=_require_text("client_id", client_id, max_length=512),
            redirect_uri=_validate_redirect_uri(redirect_uri),
            scopes=_normalize_scopes(scopes),
            state=_require_text("state", state or secrets.token_urlsafe(32), max_length=512),
            nonce=_require_text("nonce", nonce or secrets.token_urlsafe(32), max_length=512),
            code_verifier=code_verifier or generate_code_verifier(),
        ).validated()

    def validated(self) -> "AuthorizationRequest":
        _validate_endpoint("authorization_endpoint", self.authorization_endpoint)
        _validate_endpoint("token_endpoint", self.token_endpoint)
        _require_text("client_id", self.client_id, max_length=512)
        _validate_redirect_uri(self.redirect_uri)
        normalized_scopes = _normalize_scopes(self.scopes)
        if normalized_scopes != self.scopes:
            raise OAuthContractError("scopes must be a normalized tuple without duplicates")
        _require_text("state", self.state, max_length=512)
        _require_text("nonce", self.nonce, max_length=512)
        code_challenge_s256(self.code_verifier)
        return self

    @property
    def code_challenge(self) -> str:
        self.validated()
        return code_challenge_s256(self.code_verifier)

    def authorization_url(
        self, *, extra_parameters: Mapping[str, str] | None = None
    ) -> str:
        self.validated()
        parsed = _split_url("authorization_endpoint", self.authorization_endpoint)
        existing = parse_qsl(parsed.query, keep_blank_values=True)
        existing_keys = {key for key, _ in existing}
        if existing_keys & _RESERVED_AUTHORIZATION_PARAMETERS:
            raise OAuthContractError(
                "authorization_endpoint query must not predefine reserved OAuth parameters"
            )

        extras: list[tuple[str, str]] = []
        for key, raw_value in (extra_parameters or {}).items():
            name = _require_text("extra parameter name", key, max_length=128)
            value = _require_text("extra parameter value", raw_value, max_length=2048)
            if name in _RESERVED_AUTHORIZATION_PARAMETERS:
                raise OAuthContractError(
                    f"extra parameter collides with reserved OAuth parameter: {name}"
                )
            extras.append((name, value))

        query = existing + [
            ("response_type", "code"),
            ("client_id", self.client_id),
            ("redirect_uri", self.redirect_uri),
            ("scope", " ".join(self.scopes)),
            ("state", self.state),
            ("nonce", self.nonce),
            ("code_challenge", code_challenge_s256(self.code_verifier)),
            ("code_challenge_method", "S256"),
        ] + sorted(extras)
        return urlunsplit(parsed._replace(query=urlencode(query)))

    def token_exchange_form(self, authorization_code: str) -> tuple[tuple[str, str], ...]:
        self.validated()
        code = _require_text("authorization_code", authorization_code, max_length=8192)
        return (
            ("grant_type", "authorization_code"),
            ("code", code),
            ("redirect_uri", self.redirect_uri),
            ("client_id", self.client_id),
            ("code_verifier", self.code_verifier),
        )


__all__ = [
    "AuthorizationRequest",
    "OAuthContractError",
    "code_challenge_s256",
    "generate_code_verifier",
]
