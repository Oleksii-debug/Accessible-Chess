from __future__ import annotations

"""Server-only LiveKit token issuer for canonical classroom join grants.

Canonical room/participant identity, media authorization and the outer expiry
come from ClassroomJoinCredentialService. This adapter maps that already
authorized grant to the one pinned LiveKit server SDK, then independently
verifies the signed provider token before returning it.

Provider credentials are explicit server-only inputs. No ambient credentials,
roster policy, room creation, chess authority or desktop secret path is owned
here.
"""

import base64
from datetime import datetime, timedelta, timezone
import importlib
from importlib import metadata
import json
from types import ModuleType
from typing import Callable

from .classroom_join_credentials import ClassroomJoinGrant
from .classroom_realtime_media import (
    ClassroomMediaError,
    JoinCredential,
    MAX_JOIN_TTL_SECONDS,
    MediaSource,
)


LIVEKIT_API_DISTRIBUTION = "livekit-api"
LIVEKIT_API_VERSION = "1.2.1"
LIVEKIT_API_WHEEL_SHA256 = (
    "aa15b0a194c9e8167d4261bc61381682df23f98bc6d77760fcded93d2ce4b4ca"
)
MAX_LIVEKIT_CREDENTIAL_CHARS = 4096
_PROVIDER_CLOCK_SAFETY = timedelta(seconds=1)

_SOURCE_TO_LIVEKIT = {
    MediaSource.MICROPHONE: "microphone",
    MediaSource.CAMERA: "camera",
    MediaSource.SCREEN_SHARE: "screen_share",
}


class LiveKitJoinTokenIssuerError(RuntimeError):
    """Sanitized failure at the concrete LiveKit token-minting boundary."""


class LiveKitJoinTokenIssuer:
    """Mint and verify least-privilege LiveKit room tokens."""

    __slots__ = ("_api_key", "_api_secret", "_api", "_now")

    def __init__(
        self,
        *,
        api_key: str,
        api_secret: str,
        api_module: ModuleType | object | None = None,
        sdk_version: str | None = None,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self._api_key = _credential(api_key, "LiveKit API key")
        self._api_secret = _credential(api_secret, "LiveKit API secret")
        self._api = _load_api(api_module=api_module, sdk_version=sdk_version)
        self._now = now or (lambda: datetime.now(timezone.utc))

    def __repr__(self) -> str:
        return (
            "LiveKitJoinTokenIssuer("
            "api_key=<redacted>, api_secret=<redacted>, "
            f"sdk_version={LIVEKIT_API_VERSION!r})"
        )

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
        outer_ttl = expires - issued
        if (
            outer_ttl.total_seconds() <= 0
            or outer_ttl.total_seconds() > MAX_JOIN_TTL_SECONDS
        ):
            raise LiveKitJoinTokenIssuerError("LiveKit token TTL is invalid")

        current = _utc(self._now(), "LiveKit token clock")
        if current < issued:
            raise LiveKitJoinTokenIssuerError(
                "LiveKit token clock precedes canonical issuance"
            )
        remaining = expires - current
        provider_ttl = remaining - _PROVIDER_CLOCK_SAFETY
        if provider_ttl <= timedelta(0):
            raise LiveKitJoinTokenIssuerError(
                "LiveKit join grant expires before safe token minting"
            )

        sources = [_SOURCE_TO_LIVEKIT[source] for source in grant.publish_sources]
        try:
            grants = self._api.VideoGrants(
                room_create=False,
                room_list=False,
                room_record=False,
                room_admin=False,
                room_join=True,
                room=grant.room_id,
                destination_room=None,
                can_publish=bool(sources),
                can_subscribe=True,
                # The shipped client sends teacher moderation through LiveKit RPC;
                # RPC rides LiveKit data packets. Transport permission is therefore
                # required for every classroom participant, while the trusted
                # moderation service still authorizes caller role/room/target.
                can_publish_data=True,
                can_publish_sources=sources,
                can_update_own_metadata=False,
                ingress_admin=False,
                hidden=False,
                recorder=False,
                agent=False,
                can_manage_agent_session=False,
            )
            token = (
                self._api.AccessToken(self._api_key, self._api_secret)
                .with_identity(grant.participant_id)
                .with_grants(grants)
                .with_ttl(provider_ttl)
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

        try:
            verified = self._api.TokenVerifier(
                self._api_key,
                self._api_secret,
                leeway=timedelta(seconds=5),
            ).verify(credential.token)
            _verify_provider_claims(
                verified,
                room_id=grant.room_id,
                participant_id=grant.participant_id,
                publish_sources=sources,
            )
            _verify_temporal_claims(
                _jwt_payload(credential.token),
                issued_at=issued,
                expires_at=expires,
            )
        except LiveKitJoinTokenIssuerError:
            raise
        except Exception:
            raise LiveKitJoinTokenIssuerError(
                "LiveKit join token verification failed"
            ) from None

        return credential.token


def _load_api(*, api_module: object | None, sdk_version: str | None) -> object:
    if api_module is None:
        try:
            installed = metadata.version(LIVEKIT_API_DISTRIBUTION)
        except metadata.PackageNotFoundError:
            raise LiveKitJoinTokenIssuerError(
                "Pinned LiveKit server SDK is unavailable"
            ) from None
        if installed != LIVEKIT_API_VERSION:
            raise LiveKitJoinTokenIssuerError(
                "LiveKit server SDK version is not approved"
            )
        try:
            api_module = importlib.import_module("livekit.api")
        except Exception:
            raise LiveKitJoinTokenIssuerError(
                "Pinned LiveKit server SDK is unavailable"
            ) from None
    elif sdk_version is not None and sdk_version != LIVEKIT_API_VERSION:
        raise LiveKitJoinTokenIssuerError(
            "LiveKit server SDK version is not approved"
        )

    for name in ("AccessToken", "VideoGrants", "TokenVerifier"):
        if not callable(getattr(api_module, name, None)):
            raise LiveKitJoinTokenIssuerError(
                "LiveKit server SDK token API is unavailable"
            )
    return api_module


def _verify_provider_claims(
    claims: object,
    *,
    room_id: str,
    participant_id: str,
    publish_sources: list[str],
) -> None:
    if getattr(claims, "identity", None) != participant_id:
        raise LiveKitJoinTokenIssuerError(
            "LiveKit token participant identity is not canonical"
        )
    video = getattr(claims, "video", None)
    if video is None:
        raise LiveKitJoinTokenIssuerError("LiveKit token media grant is missing")

    exact = {
        "room_create": False,
        "room_list": False,
        "room_record": False,
        "room_admin": False,
        "room_join": True,
        "room": room_id,
        "can_publish": bool(publish_sources),
        "can_subscribe": True,
        "can_publish_data": True,
        "can_publish_sources": publish_sources,
        "can_update_own_metadata": False,
        "ingress_admin": False,
        "hidden": False,
        "recorder": False,
        "agent": False,
        "can_manage_agent_session": False,
    }
    for name, expected in exact.items():
        if getattr(video, name, None) != expected:
            raise LiveKitJoinTokenIssuerError(
                f"LiveKit token grant verification failed for {name}"
            )
    if getattr(video, "destination_room", None) not in (None, ""):
        raise LiveKitJoinTokenIssuerError(
            "LiveKit token destination-room grant is forbidden"
        )


def _verify_temporal_claims(
    claims: dict[str, object],
    *,
    issued_at: datetime,
    expires_at: datetime,
) -> None:
    not_before = claims.get("nbf")
    expires = claims.get("exp")
    if type(not_before) is not int or type(expires) is not int:
        raise LiveKitJoinTokenIssuerError(
            "LiveKit token temporal claims are invalid"
        )
    if not_before < int(issued_at.timestamp()):
        raise LiveKitJoinTokenIssuerError(
            "LiveKit token predates canonical issuance"
        )
    if expires > int(expires_at.timestamp()):
        raise LiveKitJoinTokenIssuerError(
            "LiveKit token exceeds canonical expiry"
        )
    if expires <= not_before:
        raise LiveKitJoinTokenIssuerError(
            "LiveKit token temporal claims are invalid"
        )


def _jwt_payload(token: str) -> dict[str, object]:
    try:
        parts = token.split(".")
        if len(parts) != 3 or not parts[1]:
            raise ValueError("invalid JWT")
        payload = parts[1].encode("ascii")
        payload += b"=" * (-len(payload) % 4)
        decoded = base64.b64decode(payload, altchars=b"-_", validate=True)
        value = json.loads(decoded.decode("utf-8"))
    except Exception:
        raise LiveKitJoinTokenIssuerError(
            "LiveKit token payload is invalid"
        ) from None
    if type(value) is not dict:
        raise LiveKitJoinTokenIssuerError(
            "LiveKit token payload is invalid"
        )
    return value


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
    "LIVEKIT_API_DISTRIBUTION",
    "LIVEKIT_API_VERSION",
    "LIVEKIT_API_WHEEL_SHA256",
    "LiveKitJoinTokenIssuer",
    "LiveKitJoinTokenIssuerError",
    "MAX_LIVEKIT_CREDENTIAL_CHARS",
]
