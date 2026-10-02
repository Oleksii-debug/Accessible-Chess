from __future__ import annotations

"""Concrete LiveKit server token issuer for canonical classroom join grants.

This adapter is server-only. It consumes the provider-neutral
``ClassroomJoinGrant`` produced by trusted classroom authorization and mints a
least-privilege LiveKit join token. It never owns classroom membership, role,
chess state, or provider policy, and it never serializes API credentials.
"""

from datetime import datetime, timedelta, timezone
from importlib import metadata
import re
from typing import Callable

from .classroom_join_credentials import ClassroomJoinGrant
from .classroom_realtime_media import MAX_JOIN_TTL_SECONDS, MAX_TOKEN_LENGTH


LIVEKIT_API_DISTRIBUTION = "livekit-api"
LIVEKIT_API_VERSION = "1.2.1"
MAX_PROVIDER_CREDENTIAL_LENGTH = 4096
_LIVEKIT_COMPACT_JWT_RE = re.compile(r"^[A-Za-z0-9_-]+\\.[A-Za-z0-9_-]+\\.[A-Za-z0-9_-]+$")


class LiveKitClassroomTokenIssuerError(ValueError):
    """Sanitized fail-closed LiveKit token-issuer error."""


def _utc(value: object, label: str) -> datetime:
    if type(value) is not datetime or value.tzinfo is None or value.utcoffset() is None:
        raise LiveKitClassroomTokenIssuerError(
            f"{label} must be timezone-aware datetime"
        )
    return value.astimezone(timezone.utc)


def _provider_credential(value: object, label: str) -> str:
    if (
        type(value) is not str
        or not value
        or len(value) > MAX_PROVIDER_CREDENTIAL_LENGTH
        or value != value.strip()
        or any(
            character.isspace()
            or ord(character) < 0x20
            or ord(character) == 0x7F
            for character in value
        )
    ):
        raise LiveKitClassroomTokenIssuerError(f"{label} is invalid")
    return value


def _provider_token(value: object) -> str:
    if (
        type(value) is not str
        or len(value) > MAX_TOKEN_LENGTH
        or _LIVEKIT_COMPACT_JWT_RE.fullmatch(value) is None
    ):
        raise LiveKitClassroomTokenIssuerError("LiveKit token output is invalid")
    return value


class LiveKitClassroomJoinTokenIssuer:
    """Mint exact-room LiveKit tokens behind ``ClassroomJoinTokenIssuerPort``.

    ``api_key`` and ``api_secret`` must come from trusted server configuration.
    The normal runtime path requires the exact reviewed ``livekit-api`` version.
    ``api_module`` exists only as an explicit dependency-injection seam for tests.
    """

    __slots__ = ("_api_key", "_api_secret", "_api_module", "_now")

    def __init__(
        self,
        *,
        api_key: str,
        api_secret: str,
        now: Callable[[], datetime] | None = None,
        api_module: object | None = None,
    ) -> None:
        self._api_key = _provider_credential(api_key, "LiveKit API key")
        self._api_secret = _provider_credential(api_secret, "LiveKit API secret")
        self._now = now or (lambda: datetime.now(timezone.utc))
        self._api_module = api_module

    def __repr__(self) -> str:
        return "LiveKitClassroomJoinTokenIssuer(configured=True)"

    def _api(self) -> object:
        if self._api_module is not None:
            return self._api_module
        try:
            installed = metadata.version(LIVEKIT_API_DISTRIBUTION)
        except metadata.PackageNotFoundError:
            raise LiveKitClassroomTokenIssuerError(
                "pinned LiveKit server SDK is unavailable"
            ) from None
        if installed != LIVEKIT_API_VERSION:
            raise LiveKitClassroomTokenIssuerError(
                "installed LiveKit server SDK does not match the reviewed version"
            )
        try:
            from livekit import api
        except Exception:
            raise LiveKitClassroomTokenIssuerError(
                "pinned LiveKit server SDK is unavailable"
            ) from None
        return api

    async def issue_join_token(
        self,
        *,
        grant: ClassroomJoinGrant,
        issued_at: datetime,
        expires_at: datetime,
    ) -> str:
        if type(grant) is not ClassroomJoinGrant:
            raise LiveKitClassroomTokenIssuerError("canonical join grant is required")
        issued = _utc(issued_at, "join grant issued_at")
        expires = _utc(expires_at, "join grant expires_at")
        if expires <= issued:
            raise LiveKitClassroomTokenIssuerError(
                "join grant expiry must follow issuance"
            )
        lifetime = (expires - issued).total_seconds()
        if lifetime > MAX_JOIN_TTL_SECONDS:
            raise LiveKitClassroomTokenIssuerError(
                "join grant exceeds canonical TTL limit"
            )

        current = _utc(self._now(), "LiveKit token clock")
        if current < issued:
            raise LiveKitClassroomTokenIssuerError("join grant is not active yet")
        remaining_seconds = int((expires - current).total_seconds())
        if remaining_seconds <= 0:
            raise LiveKitClassroomTokenIssuerError(
                "join grant has expired before token issuance"
            )

        api = self._api()
        sources = [source.value for source in grant.publish_sources]
        try:
            grants = api.VideoGrants(
                room_join=True,
                room=grant.room_id,
                room_admin=False,
                can_publish=bool(sources),
                can_subscribe=True,
                # Classroom moderation uses LiveKit RPC signaling, not arbitrary
                # room data publication. Keep generic data publication disabled.
                can_publish_data=False,
                can_publish_sources=sources,
                can_update_own_metadata=False,
                hidden=False,
            )
            token = (
                api.AccessToken(api_key=self._api_key, api_secret=self._api_secret)
                .with_identity(grant.participant_id)
                .with_ttl(timedelta(seconds=remaining_seconds))
                .with_grants(grants)
                .to_jwt()
            )
        except LiveKitClassroomTokenIssuerError:
            raise
        except Exception:
            raise LiveKitClassroomTokenIssuerError(
                "LiveKit token issuance failed"
            ) from None
        return _provider_token(token)


__all__ = [
    "LIVEKIT_API_DISTRIBUTION",
    "LIVEKIT_API_VERSION",
    "LiveKitClassroomJoinTokenIssuer",
    "LiveKitClassroomTokenIssuerError",
]
