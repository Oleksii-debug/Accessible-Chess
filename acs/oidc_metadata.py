from __future__ import annotations

"""Fail-closed validation for provider-neutral OIDC discovery metadata.

Fetching discovery JSON belongs to a later network adapter. This module accepts
an already-decoded document and validates only the security capabilities needed
by the native public-client Authorization Code + PKCE flow. A transport that
intends to trust discovery metadata must use ``from_mapping_for_issuer`` so the
returned issuer is bound to locally configured authority rather than merely to
whatever HTTPS document was fetched.
"""

from dataclasses import dataclass
import secrets
from typing import Mapping

from .oauth_pkce import (
    AuthorizationRequest,
    OAuthContractError,
    _require_text,
    _split_url,
    _validate_endpoint,
)


def _string_array(name: str, value: object) -> tuple[str, ...]:
    if type(value) not in (list, tuple):
        raise OAuthContractError(f"{name} must be an array of text values")
    result = tuple(_require_text(name, item, max_length=256) for item in value)
    if not result:
        raise OAuthContractError(f"{name} must not be empty")
    if len(set(result)) != len(result):
        raise OAuthContractError(f"{name} must not contain duplicates")
    return result


def _canonical_issuer(value: object) -> str:
    issuer = _validate_endpoint("issuer", value)
    parts = _split_url("issuer", issuer)
    if parts.query:
        raise OAuthContractError("OIDC issuer must not contain a query")
    # Issuer identifiers are exact strings in OIDC. A trailing slash changes the
    # issuer and therefore must not be silently normalized here.
    return issuer


@dataclass(frozen=True)
class OidcProviderMetadata:
    issuer: str
    authorization_endpoint: str
    token_endpoint: str
    response_types_supported: tuple[str, ...]
    code_challenge_methods_supported: tuple[str, ...]
    token_endpoint_auth_methods_supported: tuple[str, ...]
    scopes_supported: tuple[str, ...] | None = None

    @classmethod
    def from_mapping(cls, document: Mapping[str, object]) -> "OidcProviderMetadata":
        """Parse capabilities without asserting local issuer trust.

        This is useful for inspection/tests only. Network authentication adapters
        should call ``from_mapping_for_issuer`` with the configured authority.
        """

        if type(document) is not dict:
            raise OAuthContractError("OIDC metadata must be a plain JSON object")

        issuer = _canonical_issuer(document.get("issuer"))
        authorization_endpoint = _validate_endpoint(
            "authorization_endpoint", document.get("authorization_endpoint")
        )
        token_endpoint = _validate_endpoint("token_endpoint", document.get("token_endpoint"))
        response_types = _string_array(
            "response_types_supported", document.get("response_types_supported")
        )
        challenge_methods = _string_array(
            "code_challenge_methods_supported",
            document.get("code_challenge_methods_supported"),
        )
        token_auth_methods = _string_array(
            "token_endpoint_auth_methods_supported",
            document.get("token_endpoint_auth_methods_supported"),
        )

        if "code" not in response_types:
            raise OAuthContractError("OIDC provider does not advertise authorization code flow")
        if "S256" not in challenge_methods:
            raise OAuthContractError("OIDC provider does not advertise PKCE S256")
        if "none" not in token_auth_methods:
            raise OAuthContractError(
                "OIDC provider does not advertise public-client token authentication"
            )

        grant_types_raw = document.get("grant_types_supported")
        if grant_types_raw is not None:
            grant_types = _string_array("grant_types_supported", grant_types_raw)
            if "authorization_code" not in grant_types:
                raise OAuthContractError(
                    "OIDC provider does not advertise authorization_code grant"
                )

        scopes_raw = document.get("scopes_supported")
        scopes: tuple[str, ...] | None = None
        if scopes_raw is not None:
            scopes = _string_array("scopes_supported", scopes_raw)
            if "openid" not in scopes:
                raise OAuthContractError("OIDC provider metadata does not advertise openid scope")

        return cls(
            issuer=issuer,
            authorization_endpoint=authorization_endpoint,
            token_endpoint=token_endpoint,
            response_types_supported=response_types,
            code_challenge_methods_supported=challenge_methods,
            token_endpoint_auth_methods_supported=token_auth_methods,
            scopes_supported=scopes,
        )

    @classmethod
    def from_mapping_for_issuer(
        cls,
        document: Mapping[str, object],
        *,
        expected_issuer: str,
    ) -> "OidcProviderMetadata":
        expected = _canonical_issuer(expected_issuer)
        metadata = cls.from_mapping(document)
        # Exact-string comparison is intentional: issuer identifiers are not URL
        # origins. Constant-time comparison avoids giving future shared adapters a
        # reason to replace this with normalization or partial matching.
        if not secrets.compare_digest(metadata.issuer, expected):
            raise OAuthContractError("OIDC discovery issuer does not match configured issuer")
        return metadata

    def validated(self) -> "OidcProviderMetadata":
        _canonical_issuer(self.issuer)
        _validate_endpoint("authorization_endpoint", self.authorization_endpoint)
        _validate_endpoint("token_endpoint", self.token_endpoint)

        response_types = _string_array(
            "response_types_supported", self.response_types_supported
        )
        challenge_methods = _string_array(
            "code_challenge_methods_supported",
            self.code_challenge_methods_supported,
        )
        token_auth_methods = _string_array(
            "token_endpoint_auth_methods_supported",
            self.token_endpoint_auth_methods_supported,
        )
        if "code" not in response_types:
            raise OAuthContractError("OIDC provider does not advertise authorization code flow")
        if "S256" not in challenge_methods:
            raise OAuthContractError("OIDC provider does not advertise PKCE S256")
        if "none" not in token_auth_methods:
            raise OAuthContractError(
                "OIDC provider does not advertise public-client token authentication"
            )

        if self.scopes_supported is not None:
            scopes_supported = _string_array(
                "scopes_supported", self.scopes_supported
            )
            if "openid" not in scopes_supported:
                raise OAuthContractError(
                    "OIDC provider metadata does not advertise openid scope"
                )
        return self

    def create_authorization_request(
        self,
        *,
        client_id: str,
        redirect_uri: str,
        scopes: tuple[str, ...] = ("openid", "profile"),
    ) -> AuthorizationRequest:
        self.validated()
        if "openid" not in scopes:
            raise OAuthContractError("OIDC authorization request requires openid scope")
        if self.scopes_supported is not None:
            unsupported = tuple(scope for scope in scopes if scope not in self.scopes_supported)
            if unsupported:
                raise OAuthContractError("OIDC authorization request contains unsupported scope")
        return AuthorizationRequest.create(
            authorization_endpoint=self.authorization_endpoint,
            token_endpoint=self.token_endpoint,
            client_id=client_id,
            redirect_uri=redirect_uri,
            scopes=scopes,
        )


__all__ = ["OidcProviderMetadata"]
