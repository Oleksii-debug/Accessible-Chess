from __future__ import annotations

"""Provider-neutral OAuth 2.0 / OIDC PKCE request construction.

This module deliberately owns no network transport, browser automation, token
storage, entitlement policy, billing policy, or provider-specific endpoints.
It provides the small fail-closed boundary needed by a later accessible login
surface and transport adapter.
"""

from collections import Counter
from dataclasses import dataclass, field
import base64
import hashlib
import secrets
from typing import Iterable, Mapping
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit


class OAuthContractError(ValueError):
    """Raised when an authorization request would violate the local contract."""


class OAuthAuthorizationError(OAuthContractError):
    """A validated callback reported an OAuth authorization error."""

    def __init__(self, error_code: str) -> None:
        super().__init__("authorization server returned an OAuth error")
        self.error_code = error_code


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
_CALLBACK_PARAMETERS = frozenset({"code", "error", "state"})
_MAX_SCOPES = 64
_MAX_EXTRA_AUTHORIZATION_PARAMETERS = 64
_MAX_AUTHORIZATION_URL = 16 * 1024


def _require_text(name: str, value: object, *, max_length: int = 4096) -> str:
    # Security-boundary inputs must be plain built-in text. A str subclass can
    # override helpers such as strip()/__eq__ and run attacker-controlled code
    # during validation before the OAuth contract has accepted the value.
    if type(value) is not str:
        raise OAuthContractError(f"{name} must be text")
    if not value or value != value.strip():
        raise OAuthContractError(f"{name} must be non-empty canonical text")
    if len(value) > max_length or any(ord(char) < 0x20 for char in value):
        raise OAuthContractError(f"{name} is invalid")
    return value


def _split_url(name: str, value: str):
    # Backslash handling differs across URL consumers (notably browser-like
    # WHATWG parsers versus urllib/RFC-style parsing). Reject it before parsing
    # so an OAuth authority cannot be rebound by a downstream interpretation.
    if "\\" in value:
        raise OAuthContractError(f"{name} contains an ambiguous backslash")
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
    query_keys = {key for key, _ in parse_qsl(parsed.query, keep_blank_values=True)}
    if query_keys & _CALLBACK_PARAMETERS:
        raise OAuthContractError("redirect_uri query must not predefine OAuth callback parameters")
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
    try:
        for index, scope in enumerate(scopes):
            if index >= _MAX_SCOPES:
                raise OAuthContractError("scope count exceeds the accepted bound")
            value = _require_text("scope", scope, max_length=256)
            if any(char.isspace() for char in value):
                raise OAuthContractError("individual scopes must not contain whitespace")
            if value not in seen:
                seen.add(value)
                result.append(value)
    except OAuthContractError:
        raise
    except Exception:
        raise OAuthContractError("scopes could not be enumerated safely") from None
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
    state: str = field(repr=False)
    nonce: str = field(repr=False)
    code_verifier: str = field(repr=False)

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
            state=_require_text(
                "state",
                state if state is not None else secrets.token_urlsafe(32),
                max_length=512,
            ),
            nonce=_require_text(
                "nonce",
                nonce if nonce is not None else secrets.token_urlsafe(32),
                max_length=512,
            ),
            code_verifier=(
                code_verifier if code_verifier is not None else generate_code_verifier()
            ),
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
        try:
            extra_items = (extra_parameters or {}).items()
            for index, (key, raw_value) in enumerate(extra_items):
                if index >= _MAX_EXTRA_AUTHORIZATION_PARAMETERS:
                    raise OAuthContractError("extra authorization parameter count exceeds the accepted bound")
                name = _require_text("extra parameter name", key, max_length=128)
                value = _require_text("extra parameter value", raw_value, max_length=2048)
                if name in _RESERVED_AUTHORIZATION_PARAMETERS:
                    raise OAuthContractError(
                        f"extra parameter collides with reserved OAuth parameter: {name}"
                    )
                extras.append((name, value))
        except OAuthContractError:
            raise
        except Exception:
            raise OAuthContractError("extra authorization parameters could not be enumerated safely") from None

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
        result = urlunsplit(parsed._replace(query=urlencode(query)))
        if len(result) > _MAX_AUTHORIZATION_URL:
            raise OAuthContractError("authorization URL exceeds the accepted size bound")
        return result

    def authorization_code_from_callback(self, callback_url: str) -> str:
        """Validate redirect binding + state and return one authorization code.

        Network/browser adapters hand the received callback URL to this method.
        The method deliberately ignores non-critical provider extension fields,
        but critical callback parameters must be singular and fail closed.
        """

        self.validated()
        callback = _require_text("callback_url", callback_url, max_length=16384)
        actual = _split_url("callback_url", callback)
        expected = _split_url("redirect_uri", self.redirect_uri)

        if actual.fragment:
            raise OAuthContractError("authorization callback must not contain a fragment")
        expected_origin_path = (expected.scheme, expected.hostname, expected.port, expected.path)
        actual_origin_path = (actual.scheme, actual.hostname, actual.port, actual.path)
        if actual_origin_path != expected_origin_path:
            raise OAuthContractError("authorization callback does not match redirect_uri")
        if actual.username is not None or actual.password is not None:
            raise OAuthContractError("authorization callback must not contain userinfo")

        expected_query = Counter(parse_qsl(expected.query, keep_blank_values=True))
        actual_pairs = parse_qsl(actual.query, keep_blank_values=True)
        actual_query = Counter(actual_pairs)
        for pair, count in expected_query.items():
            if actual_query[pair] < count:
                raise OAuthContractError("authorization callback lost redirect_uri query data")

        critical: dict[str, list[str]] = {key: [] for key in _CALLBACK_PARAMETERS}
        for key, value in actual_pairs:
            if key in critical:
                critical[key].append(value)
        for key, values in critical.items():
            if len(values) > 1:
                raise OAuthContractError(f"authorization callback contains duplicate {key}")

        states = critical["state"]
        if len(states) != 1 or not secrets.compare_digest(states[0], self.state):
            raise OAuthContractError("authorization callback state mismatch")

        codes = critical["code"]
        errors = critical["error"]
        if bool(codes) == bool(errors):
            raise OAuthContractError("authorization callback must contain exactly one code or error")
        if errors:
            error_code = _require_text("oauth_error", errors[0], max_length=128)
            raise OAuthAuthorizationError(error_code)
        return _require_text("authorization_code", codes[0], max_length=8192)

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
    "OAuthAuthorizationError",
    "OAuthContractError",
    "code_challenge_s256",
    "generate_code_verifier",
]
