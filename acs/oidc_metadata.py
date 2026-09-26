from __future__ import annotations

"""Fail-closed validation for provider-neutral OIDC discovery metadata.

Fetching discovery JSON belongs to a later network adapter.  This module accepts
an already-decoded document and validates only the security capabilities needed
by the native public-client Authorization Code + PKCE flow.
"""

from dataclasses import dataclass
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
        # Discovery input is expected to come from decoded JSON. Requiring an
        # exact dict avoids invoking custom Mapping implementations at the trust
        # boundary before validation has run.
        if type(document) is not dict:
            raise OAuthContractError("OIDC metadata must be a plain JSON object")

        issuer = _validate_endpoint("issuer", document.get("issuer"))
        issuer_parts = _split_url("issuer", issuer)
        if issuer_parts.query:
            raise OAuthContractError("OIDC issuer must not contain a query")

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

    def create_authorization_request(
        self,
        *,
        client_id: str,
        redirect_uri: str,
        scopes: tuple[str, ...] = ("openid", "profile"),
    ) -> AuthorizationRequest:
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
