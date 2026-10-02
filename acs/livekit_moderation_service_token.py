from __future__ import annotations

"""Least-privilege LiveKit token issuer for the trusted moderation service.

This is not a classroom-member join authority. Deployment binds one issuer to
one exact room and one exact moderation-service identity. The issued token can
join that room and publish data required for LiveKit RPC responses, but cannot
publish media, subscribe to classroom media, administer the room, create/list
rooms, record, mutate metadata, or act as an agent.

API credentials remain server-only explicit inputs. No environment lookup,
desktop/browser credential path, roster, chess, membership, or media-policy
authority is owned here.
"""

import base64
from datetime import datetime, timedelta, timezone
import importlib
from importlib import metadata
import json
import re
from types import ModuleType
from typing import Callable

from .classroom_realtime_media import MAX_JOIN_TTL_SECONDS
from .livekit_join_token_issuer import (
    LIVEKIT_API_DISTRIBUTION,
    LIVEKIT_API_VERSION,
    LIVEKIT_API_WHEEL_SHA256,
    MAX_LIVEKIT_CREDENTIAL_CHARS,
)


MAX_SERVICE_IDENTIFIER_CHARS = 128
MIN_MODERATION_SERVICE_TTL_SECONDS = 2
_IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_PROVIDER_CLOCK_SAFETY = timedelta(seconds=1)


class LiveKitModerationServiceTokenError(RuntimeError):
    """Sanitized trusted-service token issuance failure."""


class LiveKitModerationServiceTokenIssuer:
    """Mint one-room tokens for the non-media moderation RPC participant."""

    __slots__ = (
        "_api_key",
        "_api_secret",
        "_room_id",
        "_identity",
        "_ttl_seconds",
        "_api",
        "_now",
    )

    def __init__(
        self,
        *,
        api_key: str,
        api_secret: str,
        room_id: str,
        moderation_participant_identity: str,
        ttl_seconds: int = 60,
        api_module: ModuleType | object | None = None,
        sdk_version: str | None = None,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self._api_key = _credential(api_key, "LiveKit API key")
        self._api_secret = _credential(api_secret, "LiveKit API secret")
        self._room_id = _identifier(room_id, "moderation service room id")
        self._identity = _identifier(
            moderation_participant_identity,
            "moderation service participant identity",
        )
        if (
            type(ttl_seconds) is not int
            or ttl_seconds < MIN_MODERATION_SERVICE_TTL_SECONDS
            or ttl_seconds > MAX_JOIN_TTL_SECONDS
        ):
            raise LiveKitModerationServiceTokenError(
                "moderation service token TTL is invalid"
            )
        self._ttl_seconds = ttl_seconds
        self._api = _load_api(api_module=api_module, sdk_version=sdk_version)
        self._now = now or (lambda: datetime.now(timezone.utc))

    def __repr__(self) -> str:
        return (
            "LiveKitModerationServiceTokenIssuer("
            f"sdk_version={LIVEKIT_API_VERSION!r}, "
            "room=<redacted>, participant=<redacted>, "
            "api_key=<redacted>, api_secret=<redacted>)"
        )

    def issue_token(self) -> str:
        try:
            issued_at = _utc(self._now(), "moderation service token clock")
        except LiveKitModerationServiceTokenError:
            raise
        except Exception:
            raise LiveKitModerationServiceTokenError(
                "moderation service token clock failed"
            ) from None

        outer_expires = issued_at + timedelta(seconds=self._ttl_seconds)
        provider_ttl = timedelta(seconds=self._ttl_seconds) - _PROVIDER_CLOCK_SAFETY
        if provider_ttl <= timedelta(0):
            raise LiveKitModerationServiceTokenError(
                "moderation service token TTL is invalid"
            )

        try:
            grants = self._api.VideoGrants(
                room_create=False,
                room_list=False,
                room_record=False,
                room_admin=False,
                room_join=True,
                room=self._room_id,
                destination_room=None,
                can_publish=False,
                can_subscribe=False,
                # LiveKit RPC responses use the data transport. This capability
                # does not grant classroom moderation authorization; #1069 does.
                can_publish_data=True,
                can_publish_sources=[],
                can_update_own_metadata=False,
                ingress_admin=False,
                hidden=False,
                recorder=False,
                agent=False,
                can_manage_agent_session=False,
            )
            token = (
                self._api.AccessToken(self._api_key, self._api_secret)
                .with_identity(self._identity)
                .with_grants(grants)
                .with_ttl(provider_ttl)
                .to_jwt()
            )
        except Exception:
            raise LiveKitModerationServiceTokenError(
                "LiveKit moderation service token issuance failed"
            ) from None

        if type(token) is not str or not token or len(token) > 32 * 1024:
            raise LiveKitModerationServiceTokenError(
                "LiveKit moderation service token is invalid"
            )

        try:
            verified = self._api.TokenVerifier(
                self._api_key,
                self._api_secret,
                leeway=timedelta(seconds=5),
            ).verify(token)
            _verify_provider_claims(
                verified,
                room_id=self._room_id,
                participant_id=self._identity,
            )
            _verify_temporal_claims(
                _jwt_payload(token),
                issued_at=issued_at,
                expires_at=outer_expires,
            )
        except LiveKitModerationServiceTokenError:
            raise
        except Exception:
            raise LiveKitModerationServiceTokenError(
                "LiveKit moderation service token verification failed"
            ) from None

        return token


def _load_api(*, api_module: object | None, sdk_version: str | None) -> object:
    if api_module is None:
        try:
            installed = metadata.version(LIVEKIT_API_DISTRIBUTION)
        except metadata.PackageNotFoundError:
            raise LiveKitModerationServiceTokenError(
                "Pinned LiveKit server SDK is unavailable"
            ) from None
        if installed != LIVEKIT_API_VERSION:
            raise LiveKitModerationServiceTokenError(
                "LiveKit server SDK version is not approved"
            )
        try:
            api_module = importlib.import_module("livekit.api")
        except Exception:
            raise LiveKitModerationServiceTokenError(
                "Pinned LiveKit server SDK is unavailable"
            ) from None
    elif sdk_version != LIVEKIT_API_VERSION:
        raise LiveKitModerationServiceTokenError(
            "LiveKit server SDK version is not approved"
        )

    for name in ("AccessToken", "VideoGrants", "TokenVerifier"):
        if not callable(getattr(api_module, name, None)):
            raise LiveKitModerationServiceTokenError(
                "LiveKit server SDK token API is unavailable"
            )
    return api_module


def _verify_provider_claims(
    claims: object,
    *,
    room_id: str,
    participant_id: str,
) -> None:
    if getattr(claims, "identity", None) != participant_id:
        raise LiveKitModerationServiceTokenError(
            "LiveKit moderation service identity is not canonical"
        )
    video = getattr(claims, "video", None)
    if video is None:
        raise LiveKitModerationServiceTokenError(
            "LiveKit moderation service media grant is missing"
        )

    exact = {
        "room_create": False,
        "room_list": False,
        "room_record": False,
        "room_admin": False,
        "room_join": True,
        "room": room_id,
        "can_publish": False,
        "can_subscribe": False,
        "can_publish_data": True,
        "can_publish_sources": [],
        "can_update_own_metadata": False,
        "ingress_admin": False,
        "hidden": False,
        "recorder": False,
        "agent": False,
        "can_manage_agent_session": False,
    }
    for name, expected in exact.items():
        if getattr(video, name, None) != expected:
            raise LiveKitModerationServiceTokenError(
                f"LiveKit moderation service grant verification failed for {name}"
            )
    if getattr(video, "destination_room", None) not in (None, ""):
        raise LiveKitModerationServiceTokenError(
            "LiveKit moderation service destination-room grant is forbidden"
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
        raise LiveKitModerationServiceTokenError(
            "LiveKit moderation service temporal claims are invalid"
        )
    if not_before < int(issued_at.timestamp()):
        raise LiveKitModerationServiceTokenError(
            "LiveKit moderation service token predates issuance"
        )
    if expires > int(expires_at.timestamp()):
        raise LiveKitModerationServiceTokenError(
            "LiveKit moderation service token exceeds configured expiry"
        )
    if expires <= not_before:
        raise LiveKitModerationServiceTokenError(
            "LiveKit moderation service temporal claims are invalid"
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
        raise LiveKitModerationServiceTokenError(
            "LiveKit moderation service token payload is invalid"
        ) from None
    if type(value) is not dict:
        raise LiveKitModerationServiceTokenError(
            "LiveKit moderation service token payload is invalid"
        )
    return value


def _credential(value: object, label: str) -> str:
    if (
        type(value) is not str
        or not value
        or len(value) > MAX_LIVEKIT_CREDENTIAL_CHARS
        or value != value.strip()
        or any(character.isspace() or ord(character) < 32 for character in value)
    ):
        raise LiveKitModerationServiceTokenError(f"{label} is invalid")
    return value


def _identifier(value: object, label: str) -> str:
    if (
        type(value) is not str
        or not value
        or len(value) > MAX_SERVICE_IDENTIFIER_CHARS
        or _IDENTIFIER_RE.fullmatch(value) is None
    ):
        raise LiveKitModerationServiceTokenError(f"{label} is invalid")
    return value


def _utc(value: object, label: str) -> datetime:
    if type(value) is not datetime or value.tzinfo is None or value.utcoffset() is None:
        raise LiveKitModerationServiceTokenError(
            f"{label} must be timezone-aware datetime"
        )
    return value.astimezone(timezone.utc)


__all__ = [
    "LIVEKIT_API_VERSION",
    "LIVEKIT_API_WHEEL_SHA256",
    "LiveKitModerationServiceTokenError",
    "LiveKitModerationServiceTokenIssuer",
    "MIN_MODERATION_SERVICE_TTL_SECONDS",
]
