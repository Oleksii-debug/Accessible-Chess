from __future__ import annotations

"""Provider-neutral validation for successful OAuth token responses.

Network transport and persistence are intentionally out of scope. This module
turns already-decoded JSON into a bounded value object whose repr does not expose
tokens, so later adapters have one fail-closed success boundary before DPAPI.
"""

from dataclasses import dataclass, field
from typing import Mapping

from .oauth_pkce import OAuthContractError, _require_text

_MAX_TOKEN_CHARS = 256 * 1024
_MAX_SCOPE_CHARS = 4096
_MAX_EXPIRES_SECONDS = 366 * 24 * 60 * 60


def _token(name: str, value: object, *, required: bool) -> str | None:
    if value is None and not required:
        return None
    return _require_text(name, value, max_length=_MAX_TOKEN_CHARS)


@dataclass(frozen=True)
class OAuthTokenResponse:
    access_token: str = field(repr=False)
    token_type: str
    expires_in: int | None
    scope: tuple[str, ...] | None
    refresh_token: str | None = field(default=None, repr=False)
    id_token: str | None = field(default=None, repr=False)

    @classmethod
    def from_mapping(cls, document: Mapping[str, object]) -> "OAuthTokenResponse":
        if type(document) is not dict:
            raise OAuthContractError("OAuth token response must be a plain JSON object")

        # A success parser must never reinterpret an OAuth error document as a
        # partial success, even if hostile input mixes success and error fields.
        if "error" in document:
            raise OAuthContractError("OAuth token response reported an error")

        access_token = _token("access_token", document.get("access_token"), required=True)
        token_type = _require_text("token_type", document.get("token_type"), max_length=64)
        if token_type.casefold() != "bearer":
            raise OAuthContractError("OAuth token response requires Bearer token type")

        expires_raw = document.get("expires_in")
        expires_in: int | None
        if expires_raw is None:
            expires_in = None
        elif type(expires_raw) is not int or not 1 <= expires_raw <= _MAX_EXPIRES_SECONDS:
            raise OAuthContractError("OAuth expires_in is outside the accepted range")
        else:
            expires_in = expires_raw

        scope_raw = document.get("scope")
        scope: tuple[str, ...] | None
        if scope_raw is None:
            scope = None
        else:
            scope_text = _require_text("scope", scope_raw, max_length=_MAX_SCOPE_CHARS)
            values = tuple(scope_text.split(" "))
            if any(not value or any(char.isspace() for char in value) for value in values):
                raise OAuthContractError("OAuth scope response is not canonical space-delimited text")
            if len(set(values)) != len(values):
                raise OAuthContractError("OAuth scope response contains duplicate values")
            scope = values

        refresh_token = _token(
            "refresh_token", document.get("refresh_token"), required=False
        )
        id_token = _token("id_token", document.get("id_token"), required=False)

        return cls(
            access_token=access_token,
            token_type="Bearer",
            expires_in=expires_in,
            scope=scope,
            refresh_token=refresh_token,
            id_token=id_token,
        )


__all__ = ["OAuthTokenResponse"]
