from __future__ import annotations

"""Concrete LiveKit room-admin adapter for canonical classroom moderation.

This module is intentionally an effect adapter only. Moderation identity, role
authorization, operation ids, replay safety, and persistent classroom policy
remain owned by ClassroomModerationRpcService and its injected authorities.

The adapter maps one already-authorized ModerationCommand to LiveKit's backend
RoomService while preserving unrelated provider permissions. Provider failures
are sanitized, and a target that is already absent is treated as the achieved
state for current-session effects so exact retries remain idempotent.
"""

import importlib
from importlib import metadata
from typing import Iterable

from .classroom_moderation_rpc import ClassroomModerationProviderAdminPort
from .classroom_realtime_media import MediaSource, ModerationAction, ModerationCommand


LIVEKIT_API_DISTRIBUTION = "livekit-api"
LIVEKIT_API_VERSION = "1.2.1"

# Pinned LiveKit TrackSource wire values. The qualification workflow verifies
# these against the installed 1.2.1 protobuf descriptor before tests run.
_PROVIDER_CAMERA = 1
_PROVIDER_MICROPHONE = 2
_PROVIDER_SCREEN_SHARE = 3
_PROVIDER_SCREEN_SHARE_AUDIO = 4
_PROVIDER_ALL_PUBLISH_SOURCES = (
    _PROVIDER_CAMERA,
    _PROVIDER_MICROPHONE,
    _PROVIDER_SCREEN_SHARE,
    _PROVIDER_SCREEN_SHARE_AUDIO,
)
_MEDIA_TO_PROVIDER_SOURCE = {
    MediaSource.CAMERA: _PROVIDER_CAMERA,
    MediaSource.MICROPHONE: _PROVIDER_MICROPHONE,
    MediaSource.SCREEN_SHARE: _PROVIDER_SCREEN_SHARE,
}


class LiveKitModerationProviderError(RuntimeError):
    """Sanitized LiveKit moderation-adapter failure."""


class LiveKitModerationProviderAdmin(ClassroomModerationProviderAdminPort):
    """Apply canonical moderation as idempotent current-session LiveKit state."""

    __slots__ = ("_room_service", "_api")

    def __init__(
        self,
        *,
        room_service: object,
        api_module: object | None = None,
        sdk_version: str | None = None,
    ) -> None:
        if room_service is None:
            raise TypeError("LiveKit room service is required")
        for name in (
            "get_participant",
            "update_participant",
            "mute_published_track",
            "remove_participant",
        ):
            if not callable(getattr(room_service, name, None)):
                raise LiveKitModerationProviderError(
                    "LiveKit room service surface is incompatible"
                )
        self._api = _load_api(api_module=api_module, sdk_version=sdk_version)
        self._room_service = room_service

    def __repr__(self) -> str:
        return (
            "LiveKitModerationProviderAdmin("
            f"sdk_version={LIVEKIT_API_VERSION!r}, room_service=<redacted>)"
        )

    async def apply_moderation_command(
        self,
        *,
        room_id: str,
        command: ModerationCommand,
    ) -> None:
        if type(room_id) is not str or not room_id:
            raise LiveKitModerationProviderError("LiveKit moderation room id is invalid")
        if type(command) is not ModerationCommand:
            raise LiveKitModerationProviderError(
                "LiveKit moderation command is not canonical"
            )

        try:
            if command.action is ModerationAction.PUBLISH_PERMISSION:
                await self._set_publish_permission(room_id=room_id, command=command)
            elif command.action is ModerationAction.SOFT_MUTE:
                await self._set_soft_mute(room_id=room_id, command=command)
            elif command.action is ModerationAction.REMOVE:
                await self._remove_participant(room_id=room_id, command=command)
            else:
                raise LiveKitModerationProviderError(
                    "LiveKit moderation action is unsupported"
                )
        except LiveKitModerationProviderError:
            raise
        except Exception:
            raise LiveKitModerationProviderError(
                "LiveKit moderation provider operation failed"
            ) from None

    async def _set_publish_permission(
        self,
        *,
        room_id: str,
        command: ModerationCommand,
    ) -> None:
        participant = await self._get_participant_or_none(
            room_id=room_id,
            participant_id=command.target_id,
        )
        if participant is None:
            return
        _require_participant_identity(participant, command.target_id)

        permission = getattr(participant, "permission", None)
        if permission is None:
            raise LiveKitModerationProviderError(
                "LiveKit participant permission state is unavailable"
            )
        source = _MEDIA_TO_PROVIDER_SOURCE[command.source]
        desired = bool(command.value)
        current_sources = _validated_publish_sources(permission)

        if _source_allowed(permission, source, current_sources) is desired:
            return

        new_sources = _mutated_sources(
            permission=permission,
            current_sources=current_sources,
            source=source,
            allowed=desired,
        )
        replacement = self._api.ParticipantPermission()
        try:
            replacement.CopyFrom(permission)
            del replacement.can_publish_sources[:]
            replacement.can_publish_sources.extend(new_sources)
            replacement.can_publish = bool(new_sources)
        except Exception:
            raise LiveKitModerationProviderError(
                "LiveKit participant permission state is incompatible"
            ) from None

        request = self._api.UpdateParticipantRequest(
            room=room_id,
            identity=command.target_id,
            permission=replacement,
        )
        updated = await self._room_service.update_participant(request)
        _require_participant_identity(updated, command.target_id)
        updated_permission = getattr(updated, "permission", None)
        if updated_permission is None:
            raise LiveKitModerationProviderError(
                "LiveKit permission update returned no permission state"
            )
        updated_sources = _validated_publish_sources(updated_permission)
        if _source_allowed(updated_permission, source, updated_sources) is not desired:
            raise LiveKitModerationProviderError(
                "LiveKit permission update did not reach requested state"
            )

    async def _set_soft_mute(
        self,
        *,
        room_id: str,
        command: ModerationCommand,
    ) -> None:
        participant = await self._get_participant_or_none(
            room_id=room_id,
            participant_id=command.target_id,
        )
        if participant is None:
            return
        _require_participant_identity(participant, command.target_id)
        desired = bool(command.value)

        tracks = getattr(participant, "tracks", None)
        if tracks is None:
            raise LiveKitModerationProviderError(
                "LiveKit participant track state is unavailable"
            )
        microphone_tracks = []
        for track in tracks:
            if getattr(track, "source", None) != _PROVIDER_MICROPHONE:
                continue
            sid = getattr(track, "sid", None)
            if type(sid) is not str or not sid:
                raise LiveKitModerationProviderError(
                    "LiveKit microphone track identity is invalid"
                )
            if type(getattr(track, "muted", None)) is not bool:
                raise LiveKitModerationProviderError(
                    "LiveKit microphone mute state is invalid"
                )
            microphone_tracks.append(track)

        for track in microphone_tracks:
            if track.muted is desired:
                continue
            request = self._api.MuteRoomTrackRequest(
                room=room_id,
                identity=command.target_id,
                track_sid=track.sid,
                muted=desired,
            )
            response = await self._room_service.mute_published_track(request)
            updated_track = getattr(response, "track", None)
            if updated_track is None:
                raise LiveKitModerationProviderError(
                    "LiveKit mute update returned no track state"
                )
            if (
                getattr(updated_track, "sid", None) != track.sid
                or getattr(updated_track, "muted", None) is not desired
            ):
                raise LiveKitModerationProviderError(
                    "LiveKit mute update did not reach requested state"
                )

    async def _remove_participant(
        self,
        *,
        room_id: str,
        command: ModerationCommand,
    ) -> None:
        request = self._api.RoomParticipantIdentity(
            room=room_id,
            identity=command.target_id,
        )
        try:
            await self._room_service.remove_participant(request)
        except Exception as error:
            if _is_not_found(self._api, error):
                return
            raise

        # command.value is the canonical block flag. Durable block state belongs
        # to the classroom authorization/join authority, not to this provider
        # effect adapter. LiveKit removal handles only the current room session.

    async def _get_participant_or_none(
        self,
        *,
        room_id: str,
        participant_id: str,
    ) -> object | None:
        request = self._api.RoomParticipantIdentity(
            room=room_id,
            identity=participant_id,
        )
        try:
            return await self._room_service.get_participant(request)
        except Exception as error:
            if _is_not_found(self._api, error):
                return None
            raise


def _load_api(*, api_module: object | None, sdk_version: str | None) -> object:
    if api_module is None:
        try:
            installed = metadata.version(LIVEKIT_API_DISTRIBUTION)
        except metadata.PackageNotFoundError:
            raise LiveKitModerationProviderError(
                "Pinned LiveKit server SDK is unavailable"
            ) from None
        if installed != LIVEKIT_API_VERSION:
            raise LiveKitModerationProviderError(
                "LiveKit server SDK version is not approved"
            )
        try:
            api_module = importlib.import_module("livekit.api")
        except Exception:
            raise LiveKitModerationProviderError(
                "Pinned LiveKit server SDK is unavailable"
            ) from None
    elif sdk_version is not None and sdk_version != LIVEKIT_API_VERSION:
        raise LiveKitModerationProviderError(
            "LiveKit server SDK version is not approved"
        )

    for name in (
        "MuteRoomTrackRequest",
        "ParticipantPermission",
        "RoomParticipantIdentity",
        "ServerError",
        "ServerErrorCode",
        "UpdateParticipantRequest",
    ):
        if getattr(api_module, name, None) is None:
            raise LiveKitModerationProviderError(
                "LiveKit server SDK moderation API is unavailable"
            )
    return api_module


def _validated_publish_sources(permission: object) -> tuple[int, ...]:
    values = getattr(permission, "can_publish_sources", None)
    if values is None:
        raise LiveKitModerationProviderError(
            "LiveKit publish-source permission state is unavailable"
        )
    try:
        normalized = tuple(int(value) for value in values)
    except (TypeError, ValueError):
        raise LiveKitModerationProviderError(
            "LiveKit publish-source permission state is invalid"
        ) from None
    if len(set(normalized)) != len(normalized):
        raise LiveKitModerationProviderError(
            "LiveKit publish-source permission state contains duplicates"
        )
    if any(value not in _PROVIDER_ALL_PUBLISH_SOURCES for value in normalized):
        raise LiveKitModerationProviderError(
            "LiveKit publish-source permission state is unsupported"
        )
    if type(getattr(permission, "can_publish", None)) is not bool:
        raise LiveKitModerationProviderError(
            "LiveKit publish permission state is invalid"
        )
    return normalized


def _source_allowed(
    permission: object,
    source: int,
    current_sources: tuple[int, ...],
) -> bool:
    if not permission.can_publish:
        return False
    if not current_sources:
        return True
    return source in current_sources


def _mutated_sources(
    *,
    permission: object,
    current_sources: tuple[int, ...],
    source: int,
    allowed: bool,
) -> tuple[int, ...]:
    if permission.can_publish and not current_sources:
        values = set(_PROVIDER_ALL_PUBLISH_SOURCES)
    else:
        values = set(current_sources)

    if allowed:
        values.add(source)
    else:
        values.discard(source)
    return tuple(value for value in _PROVIDER_ALL_PUBLISH_SOURCES if value in values)


def _require_participant_identity(participant: object, expected: str) -> None:
    if getattr(participant, "identity", None) != expected:
        raise LiveKitModerationProviderError(
            "LiveKit participant identity does not match canonical target"
        )


def _is_not_found(api: object, error: BaseException) -> bool:
    server_error = getattr(api, "ServerError", None)
    codes = getattr(api, "ServerErrorCode", None)
    if not isinstance(server_error, type) or codes is None:
        return False
    return isinstance(error, server_error) and getattr(error, "code", None) == getattr(
        codes, "NOT_FOUND", object()
    )


__all__ = [
    "LIVEKIT_API_DISTRIBUTION",
    "LIVEKIT_API_VERSION",
    "LiveKitModerationProviderAdmin",
    "LiveKitModerationProviderError",
]
