from __future__ import annotations

"""Trusted transport-neutral join-credential service for classroom media.

This module deliberately does not authenticate users, own classroom membership,
mint provider tokens itself, or contain provider credentials. An authenticated
server transport supplies the trusted caller identity. Canonical classroom
authorization maps that caller to one exact room-scoped participant and source
publication grant. A separate injected provider issuer mints the short-lived
provider token.

The returned credential is validated through JoinCredential so desktop,
provider-adapter, and server boundaries share the same token/identity/TTL
contract without creating a second media authority.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import json
import re
from typing import Callable, Protocol

from .classroom_realtime_media import (
    ClassroomMediaError,
    JoinCredential,
    MAX_JOIN_TTL_SECONDS,
    MediaSource,
)


JOIN_REQUEST_VERSION = 1
MAX_JOIN_REQUEST_BYTES = 4096
MAX_JOIN_RESPONSE_BYTES = 12 * 1024
MAX_IDENTIFIER_LENGTH = 128
_IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_REQUEST_FIELDS = frozenset({"version", "room_id", "participant_id"})


class ClassroomJoinCredentialError(ValueError):
    """Fail-closed join-credential service error safe for transport handling."""


def _unique_json_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    value: dict[str, object] = {}
    for key, item in pairs:
        if key in value:
            raise ClassroomJoinCredentialError(
                "join request JSON object fields must be unique"
            )
        value[key] = item
    return value


@dataclass(frozen=True, slots=True)
class ClassroomJoinGrant:
    """Canonical authorization result passed to the provider token issuer."""

    room_id: str
    participant_id: str
    publish_sources: tuple[MediaSource, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "room_id", _identifier(self.room_id, "grant room id"))
        object.__setattr__(
            self,
            "participant_id",
            _identifier(self.participant_id, "grant participant id"),
        )
        if type(self.publish_sources) is not tuple:
            raise ClassroomJoinCredentialError("join grant sources must be a tuple")
        try:
            normalized = tuple(MediaSource(value) for value in self.publish_sources)
        except (TypeError, ValueError):
            raise ClassroomJoinCredentialError("join grant contains invalid media source") from None
        if len(set(normalized)) != len(normalized):
            raise ClassroomJoinCredentialError("join grant media sources must be unique")
        canonical = tuple(source for source in MediaSource if source in normalized)
        object.__setattr__(self, "publish_sources", canonical)


@dataclass(frozen=True, slots=True)
class ParsedJoinRequest:
    room_id: str
    participant_id: str
    trusted_caller_identity: str


class ClassroomJoinAuthorizationPort(Protocol):
    """Canonical server-side membership/identity/media-policy authority."""

    def authorize_join(
        self,
        *,
        room_id: str,
        trusted_caller_identity: str,
        requested_participant_id: str,
    ) -> ClassroomJoinGrant:
        """Return the exact canonical grant or raise when joining is forbidden."""


class ClassroomJoinTokenIssuerPort(Protocol):
    """Provider token minting boundary held only by trusted server code."""

    async def issue_join_token(
        self,
        *,
        grant: ClassroomJoinGrant,
        issued_at: datetime,
        expires_at: datetime,
    ) -> str:
        """Mint a provider token for exactly the supplied canonical grant."""


def parse_join_request(
    payload: object,
    *,
    trusted_caller_identity: str,
) -> ParsedJoinRequest:
    """Parse untrusted client JSON against authenticated transport context."""

    caller = _identifier(trusted_caller_identity, "trusted caller identity")
    if type(payload) is not str:
        raise ClassroomJoinCredentialError("join request payload must be text")
    try:
        encoded = payload.encode("utf-8")
    except UnicodeEncodeError:
        raise ClassroomJoinCredentialError("join request payload is not valid UTF-8 text") from None
    if not encoded or len(encoded) > MAX_JOIN_REQUEST_BYTES:
        raise ClassroomJoinCredentialError("join request payload size is invalid")
    try:
        decoded = json.loads(payload, object_pairs_hook=_unique_json_object)
    except ClassroomJoinCredentialError:
        raise
    except (TypeError, ValueError, json.JSONDecodeError):
        raise ClassroomJoinCredentialError("join request payload is invalid JSON") from None
    if type(decoded) is not dict or set(decoded) != _REQUEST_FIELDS:
        raise ClassroomJoinCredentialError("join request fields are invalid")
    if type(decoded["version"]) is not int or decoded["version"] != JOIN_REQUEST_VERSION:
        raise ClassroomJoinCredentialError("join request version is invalid")
    return ParsedJoinRequest(
        room_id=_identifier(decoded["room_id"], "requested room id"),
        participant_id=_identifier(decoded["participant_id"], "requested participant id"),
        trusted_caller_identity=caller,
    )


class ClassroomJoinCredentialService:
    """Authorize and issue one fresh short-lived provider credential."""

    def __init__(
        self,
        *,
        authorization: ClassroomJoinAuthorizationPort,
        token_issuer: ClassroomJoinTokenIssuerPort,
        ttl_seconds: int = 60,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        if authorization is None or token_issuer is None:
            raise TypeError("join credential service ports are required")
        if (
            type(ttl_seconds) is not int
            or ttl_seconds <= 0
            or ttl_seconds > MAX_JOIN_TTL_SECONDS
        ):
            raise ValueError("join credential TTL is outside the canonical limit")
        self._authorization = authorization
        self._token_issuer = token_issuer
        self._ttl_seconds = ttl_seconds
        self._now = now or (lambda: datetime.now(timezone.utc))

    async def issue(
        self,
        *,
        trusted_caller_identity: str,
        payload: object,
    ) -> str:
        request = parse_join_request(
            payload,
            trusted_caller_identity=trusted_caller_identity,
        )

        try:
            clock_value = self._now()
        except Exception:
            raise ClassroomJoinCredentialError(
                "join credential clock failed"
            ) from None
        try:
            issued_at = _utc(clock_value, "join credential clock")
        except ClassroomJoinCredentialError:
            raise
        except Exception:
            raise ClassroomJoinCredentialError(
                "join credential clock failed"
            ) from None
        expires_at = issued_at + timedelta(seconds=self._ttl_seconds)

        try:
            grant = self._authorization.authorize_join(
                room_id=request.room_id,
                trusted_caller_identity=request.trusted_caller_identity,
                requested_participant_id=request.participant_id,
            )
        except Exception as error:
            raise ClassroomJoinCredentialError("join request is not authorized") from None
        if type(grant) is not ClassroomJoinGrant:
            raise ClassroomJoinCredentialError("join authorization returned invalid grant")
        if grant.room_id != request.room_id or grant.participant_id != request.participant_id:
            raise ClassroomJoinCredentialError(
                "join authorization identity does not match request"
            )

        try:
            token = await self._token_issuer.issue_join_token(
                grant=grant,
                issued_at=issued_at,
                expires_at=expires_at,
            )
        except Exception as error:
            raise ClassroomJoinCredentialError("join token issuance failed") from None

        # Token minting can cross a network/provider boundary. Revalidate the
        # canonical classroom authority before returning that token so a
        # membership removal, participant rebind, or publish-permission change
        # that occurred during mint cannot be delivered as a stale credential.
        try:
            current_grant = self._authorization.authorize_join(
                room_id=request.room_id,
                trusted_caller_identity=request.trusted_caller_identity,
                requested_participant_id=request.participant_id,
            )
        except Exception:
            raise ClassroomJoinCredentialError(
                "join request is no longer authorized"
            ) from None
        if type(current_grant) is not ClassroomJoinGrant or current_grant != grant:
            raise ClassroomJoinCredentialError(
                "join authorization changed during token issuance"
            )

        try:
            credential = JoinCredential(
                room_id=grant.room_id,
                participant_id=grant.participant_id,
                token=token,
                issued_at=issued_at,
                expires_at=expires_at,
            )
        except (ClassroomMediaError, TypeError, ValueError) as error:
            raise ClassroomJoinCredentialError(
                "join token issuer returned invalid credential"
            ) from None

        try:
            completion_time = _utc(self._now(), "join credential completion clock")
            credential.assert_usable(completion_time)
        except Exception:
            raise ClassroomJoinCredentialError(
                "join token issuer returned unusable credential"
            ) from None

        response = json.dumps(
            {
                "version": JOIN_REQUEST_VERSION,
                "room_id": credential.room_id,
                "participant_id": credential.participant_id,
                "token": credential.token,
                "issued_at": _iso_utc(credential.issued_at),
                "expires_at": _iso_utc(credential.expires_at),
            },
            ensure_ascii=False,
            separators=(",", ":"),
        )
        if len(response.encode("utf-8")) > MAX_JOIN_RESPONSE_BYTES:
            raise ClassroomJoinCredentialError("join credential response is too large")
        return response


def _identifier(value: object, label: str) -> str:
    if (
        type(value) is not str
        or len(value) > MAX_IDENTIFIER_LENGTH
        or _IDENTIFIER_RE.fullmatch(value) is None
    ):
        raise ClassroomJoinCredentialError(f"{label} is invalid")
    return value


def _utc(value: object, label: str) -> datetime:
    if type(value) is not datetime or value.tzinfo is None or value.utcoffset() is None:
        raise ClassroomJoinCredentialError(f"{label} must be timezone-aware datetime")
    return value.astimezone(timezone.utc)


def _iso_utc(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


__all__ = [
    "ClassroomJoinAuthorizationPort",
    "ClassroomJoinCredentialError",
    "ClassroomJoinCredentialService",
    "ClassroomJoinGrant",
    "ClassroomJoinTokenIssuerPort",
    "JOIN_REQUEST_VERSION",
    "MAX_JOIN_REQUEST_BYTES",
    "MAX_JOIN_RESPONSE_BYTES",
    "ParsedJoinRequest",
    "parse_join_request",
]
