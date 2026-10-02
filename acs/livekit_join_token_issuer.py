from __future__ import annotations

"""Server-only LiveKit token issuer for canonical classroom join grants.

This adapter is deliberately narrow: canonical room/participant identity, media
authorization and TTL are supplied by ClassroomJoinCredentialService. The
adapter only maps that already-authorized grant into LiveKit's official server
SDK. It does not read ambient credentials, own roster policy, create rooms, or
grant room-admin/data-publish privileges.
"""

from datetime import datetime, timezone
import importlib
from types import ModuleType

from .classroom_join_credentials import ClassroomJoinGrant
from .classroom_realtime_media import (
    ClassroomMediaError,
    JoinCredential,
    MAX_JOIN_TTL_SECONDS,
    MediaSource,
)


MAX_LIVEKIT_CREDENTIAL_CHARS = 4096

_SOURCE_TO_LIVEKIT = {
    MediaSource.MICROPHONE: "microphone",
    MediaSource.CAMERA: "camera",
    MediaSource.SCREEN_SHARE: "screen_share",
}


class LiveKitJoinTokenIssuerError(RuntimeError):
    """Sanitized failure at the concrete LiveKit token-minting boundary."""


class LiveKitJoinTokenIssuer:
    """Mint least-privilege LiveKit room tokens behind the canonical issuer port."""

    __slots__ = ("_api_key", "_api_secret", "_api")

    def __init__(
        self,
        *,
        api_key: str,
        api_secret: str,
        api_module: ModuleType | object | None = None,
    ) -> None:
        self._api_key = _credential(api_key, "LiveKit API key")
        self._api_secret = _credential(api_secret, "LiveKit API secret")
        if api_module is None:
            try:
                api_module = importlib.import_module("livekit.api")
            except Exception:
                raise LiveKitJoinTokenIssuerError(
                    "LiveKit server SDK is unavailable"
                ) from None
        self._api = api_module
        for name in ("AccessToken", "VideoGrants"):
            if not callable(getattr(self._api, name, None)):
                raise LiveKitJoinTokenIssuerError(
                    "LiveKit server SDK token API is unavailable"
                )

    def __repr__(self) -> str:
        return "LiveKitJoinTokenIssuer(api_key=<redacted>, api_secret=<redacted>)"

    async def issue_join_token(
        self,
        *,
        grant: ClassroomJoinGrant,
        issued_at: datetime,
        expires_at: datetime,
    ) -> str:
        if type(grant) is not ClassroomJoinGrant:
            raise LiveKitJoinTokenIssuerError("LiveKit join grant is invalid")
        issued = _utc(issued_at, "LiveKit token issued_at")
        expires = _utc(expires_at, "LiveKit token expires_at")
        ttl = expires - issued
        if ttl.total_seconds() <= 0 or ttl.total_seconds() > MAX_JOIN_TTL_SECONDS:
            raise LiveKitJoinTokenIssuerError("LiveKit token TTL is invalid")

        sources = [_SOURCE_TO_LIVEKIT[source] for source in grant.publish_sources]
        try:
            grants = self._api.VideoGrants(
                room_join=True,
                room=grant.room_id,
                can_publish=bool(sources),
                can_subscribe=True,
                can_publish_data=False,
                can_publish_sources=sources,
            )
            token = (
                self._api.AccessToken(self._api_key, self._api_secret)
                .with_identity(grant.participant_id)
                .with_grants(grants)
                .with_ttl(ttl)
                .to_jwt()
            )
            credential = JoinCredential(
                room_id=grant.room_id,
                participant_id=grant.participant_id,
                token=token,
                issued_at=issued,
                expires_at=expires,
            )
        except Exception:
            raise LiveKitJoinTokenIssuerError(
                "LiveKit join token issuance failed"
            ) from None
        return credential.token


def _credential(value: object, label: str) -> str:
    if (
        type(value) is not str
        or not value
        or len(value) > MAX_LIVEKIT_CREDENTIAL_CHARS
        or value != value.strip()
        or any(character in value for character in ("\x00", "\r", "\n"))
    ):
        raise LiveKitJoinTokenIssuerError(f"{label} is invalid")
    return value


def _utc(value: object, label: str) -> datetime:
    if type(value) is not datetime or value.tzinfo is None or value.utcoffset() is None:
        raise LiveKitJoinTokenIssuerError(f"{label} must be timezone-aware datetime")
    return value.astimezone(timezone.utc)


__all__ = [
    "LiveKitJoinTokenIssuer",
    "LiveKitJoinTokenIssuerError",
    "MAX_LIVEKIT_CREDENTIAL_CHARS",
]
