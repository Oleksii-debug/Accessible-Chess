from __future__ import annotations

"""LiveKit server token issuer for the canonical classroom join contract.

This module is server-only. It deliberately does not read environment variables,
authenticate callers, own classroom membership, or expose provider credentials to
desktop code. ClassroomJoinCredentialService performs canonical authorization;
this adapter only converts that exact grant into one least-privilege LiveKit token.
"""

from datetime import datetime, timedelta, timezone
from importlib import metadata
from typing import Any, Callable

from .classroom_join_credentials import ClassroomJoinGrant
from .classroom_realtime_media import MAX_JOIN_TTL_SECONDS, MediaSource


LIVEKIT_API_PACKAGE_VERSION = "1.2.1"
MAX_PROVIDER_CREDENTIAL_LENGTH = 4096
_PROVIDER_CLOCK_SAFETY = timedelta(seconds=1)

_LIVEKIT_SOURCE = {
    MediaSource.MICROPHONE: "microphone",
    MediaSource.CAMERA: "camera",
    MediaSource.SCREEN_SHARE: "screen_share",
}


class ClassroomLiveKitServerError(ValueError):
    """Sanitized failure at the trusted LiveKit server boundary."""


class LiveKitJoinTokenIssuer:
    """Mint source-scoped LiveKit join JWTs without leaking server credentials."""

    __slots__ = ("_api_key", "_api_secret", "_api_module", "_now")

    def __init__(
        self,
        *,
        api_key: str,
        api_secret: str,
        api_module: Any | None = None,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self._api_key = _provider_credential(api_key, "LiveKit API key")
        self._api_secret = _provider_credential(api_secret, "LiveKit API secret")
        self._api_module = api_module
        self._now = now or (lambda: datetime.now(timezone.utc))

    def __repr__(self) -> str:
        return "LiveKitJoinTokenIssuer(credentials=<redacted>)"

    async def issue_join_token(
        self,
        *,
        grant: ClassroomJoinGrant,
        issued_at: datetime,
        expires_at: datetime,
    ) -> str:
        if type(grant) is not ClassroomJoinGrant:
            raise ClassroomLiveKitServerError("LiveKit token issuance requires canonical join grant")
        issued = _utc(issued_at, "LiveKit token issued_at")
        expires = _utc(expires_at, "LiveKit token expires_at")
        ttl = expires - issued
        seconds = ttl.total_seconds()
        if seconds <= 0 or seconds > MAX_JOIN_TTL_SECONDS:
            raise ClassroomLiveKitServerError("LiveKit token TTL is outside canonical limit")

        current = _utc(self._now(), "LiveKit token clock")
        if current < issued:
            raise ClassroomLiveKitServerError(
                "LiveKit token clock precedes canonical issuance"
            )
        provider_ttl = expires - current - _PROVIDER_CLOCK_SAFETY
        if provider_ttl <= timedelta(0):
            raise ClassroomLiveKitServerError(
                "LiveKit join grant expires before safe token minting"
            )

        provider_sources = [_LIVEKIT_SOURCE[source] for source in grant.publish_sources]
        api = self._provider_api()
        try:
            grants = api.VideoGrants(
                room_join=True,
                room=grant.room_id,
                room_admin=False,
                can_publish=bool(provider_sources),
                can_subscribe=True,
                # The integrated desktop adapter sends moderation through LiveKit
                # participant RPC. RPC is transported as a data packet, so this
                # permission is required; the trusted moderation service still
                # authorizes role, room, target and operation semantics separately.
                can_publish_data=True,
                can_publish_sources=provider_sources,
                can_update_own_metadata=False,
            )
            token = (
                api.AccessToken(
                    api_key=self._api_key,
                    api_secret=self._api_secret,
                )
                .with_identity(grant.participant_id)
                .with_ttl(provider_ttl)
                .with_grants(grants)
                .to_jwt()
            )
        except Exception:
            raise ClassroomLiveKitServerError("LiveKit join token issuance failed") from None
        if type(token) is not str or not token:
            raise ClassroomLiveKitServerError("LiveKit join token issuance returned invalid token")
        return token

    def _provider_api(self) -> Any:
        if self._api_module is not None:
            return self._api_module
        try:
            installed = metadata.version("livekit-api")
        except metadata.PackageNotFoundError:
            raise ClassroomLiveKitServerError(
                "Pinned LiveKit server SDK is unavailable"
            ) from None
        if installed != LIVEKIT_API_PACKAGE_VERSION:
            raise ClassroomLiveKitServerError(
                "LiveKit server SDK version is not approved"
            )
        try:
            from livekit import api as livekit_api
        except Exception:
            raise ClassroomLiveKitServerError(
                "Pinned LiveKit server SDK is unavailable"
            ) from None
        self._api_module = livekit_api
        return livekit_api


def _provider_credential(value: object, label: str) -> str:
    if (
        type(value) is not str
        or not value
        or len(value) > MAX_PROVIDER_CREDENTIAL_LENGTH
        or any(character.isspace() for character in value)
        or "\x00" in value
    ):
        raise ClassroomLiveKitServerError(f"{label} is invalid")
    return value


def _utc(value: object, label: str) -> datetime:
    if type(value) is not datetime or value.tzinfo is None or value.utcoffset() is None:
        raise ClassroomLiveKitServerError(f"{label} must be timezone-aware datetime")
    return value.astimezone(timezone.utc)


__all__ = [
    "ClassroomLiveKitServerError",
    "LIVEKIT_API_PACKAGE_VERSION",
    "LiveKitJoinTokenIssuer",
    "MAX_PROVIDER_CREDENTIAL_LENGTH",
]
