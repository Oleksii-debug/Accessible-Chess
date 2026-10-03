from __future__ import annotations

"""Room-bound LiveKit provider administration for canonical moderation commands.

Authorization, operation ids, replay suppression, and classroom policy remain
owned by ClassroomModerationRpcService and its canonical ports. This adapter
only translates an already-authorized ModerationCommand to the pinned LiveKit
RoomService API.
"""

from importlib import metadata
import importlib
from types import ModuleType

from .classroom_realtime_media import (
    MediaSource,
    ModerationAction,
    ModerationCommand,
)


LIVEKIT_API_DISTRIBUTION = "livekit-api"
LIVEKIT_API_VERSION = "1.2.1"


class LiveKitClassroomModerationAdminError(RuntimeError):
    """Sanitized failure at the concrete LiveKit room-admin boundary."""


class LiveKitClassroomModerationAdmin:
    """Apply authorized moderation as idempotent provider state assignments."""

    __slots__ = ("_room", "_api")

    def __init__(
        self,
        *,
        room_service: object,
        api_module: ModuleType | object | None = None,
        sdk_version: str | None = None,
    ) -> None:
        if room_service is None:
            raise LiveKitClassroomModerationAdminError(
                "LiveKit room service is required"
            )
        self._api = _load_api(api_module=api_module, sdk_version=sdk_version)
        for name in (
            "get_participant",
            "update_participant",
            "mute_published_track",
            "remove_participant",
        ):
            if not callable(getattr(room_service, name, None)):
                raise LiveKitClassroomModerationAdminError(
                    "LiveKit room service API is unavailable"
                )
        self._room = room_service

    def __repr__(self) -> str:
        return (
            "LiveKitClassroomModerationAdmin("
            f"sdk_version={LIVEKIT_API_VERSION!r})"
        )

    async def apply_moderation_command(
        self,
        *,
        room_id: str,
        command: ModerationCommand,
    ) -> None:
        if type(room_id) is not str or not room_id or room_id != room_id.strip():
            raise LiveKitClassroomModerationAdminError(
                "LiveKit moderation room id is invalid"
            )
        if type(command) is not ModerationCommand:
            raise LiveKitClassroomModerationAdminError(
                "LiveKit moderation command is invalid"
            )

        try:
            if command.action is ModerationAction.PUBLISH_PERMISSION:
                await self._set_publish_permission(room_id=room_id, command=command)
            elif command.action is ModerationAction.SOFT_MUTE:
                await self._set_soft_mute(room_id=room_id, command=command)
            elif command.action is ModerationAction.REMOVE:
                await self._remove(room_id=room_id, command=command)
            else:
                raise LiveKitClassroomModerationAdminError(
                    "LiveKit moderation action is unsupported"
                )
        except LiveKitClassroomModerationAdminError:
            raise
        except Exception:
            raise LiveKitClassroomModerationAdminError(
                "LiveKit moderation provider operation failed"
            ) from None

    async def _set_publish_permission(
        self,
        *,
        room_id: str,
        command: ModerationCommand,
    ) -> None:
        if command.source is None:
            raise LiveKitClassroomModerationAdminError(
                "LiveKit publish permission source is missing"
            )
        participant = await self._participant(
            room_id=room_id,
            participant_id=command.target_id,
        )
        permission = getattr(participant, "permission", None)
        if permission is None:
            raise LiveKitClassroomModerationAdminError(
                "LiveKit participant permission is unavailable"
            )
        if getattr(participant, "identity", None) != command.target_id:
            raise LiveKitClassroomModerationAdminError(
                "LiveKit participant identity is not canonical"
            )
        allowed = _explicit_publish_sources(self._api, permission)
        source = _provider_source(self._api, command.source)
        desired = bool(command.value)
        if (source in allowed) is desired:
            return
        if desired:
            allowed.add(source)
        else:
            allowed.discard(source)

        next_permission = _copy_permission(self._api, permission)
        try:
            del next_permission.can_publish_sources[:]
            next_permission.can_publish_sources.extend(
                _ordered_sources(self._api, allowed)
            )
            next_permission.can_publish = bool(allowed)
            request = self._api.UpdateParticipantRequest(
                room=room_id,
                identity=command.target_id,
                permission=next_permission,
            )
            updated = await self._room.update_participant(request)
        except LiveKitClassroomModerationAdminError:
            raise
        except Exception:
            raise LiveKitClassroomModerationAdminError(
                "LiveKit publish permission update failed"
            ) from None

        if getattr(updated, "identity", None) != command.target_id:
            raise LiveKitClassroomModerationAdminError(
                "LiveKit permission update identity is not canonical"
            )
        updated_permission = getattr(updated, "permission", None)
        if updated_permission is None:
            raise LiveKitClassroomModerationAdminError(
                "LiveKit permission update returned no permission state"
            )
        updated_allowed = _explicit_publish_sources(self._api, updated_permission)
        if (source in updated_allowed) is not desired:
            raise LiveKitClassroomModerationAdminError(
                "LiveKit permission update did not reach requested state"
            )

    async def _set_soft_mute(
        self,
        *,
        room_id: str,
        command: ModerationCommand,
    ) -> None:
        if command.source is not MediaSource.MICROPHONE:
            raise LiveKitClassroomModerationAdminError(
                "LiveKit soft mute source is invalid"
            )

        # Releasing a teacher soft-mute is permission release, not a forced
        # remote unmute. LiveKit intentionally disables remote unmute by
        # default; the participant may unmute their own microphone afterwards.
        if command.value is False:
            return

        participant = await self._participant(
            room_id=room_id,
            participant_id=command.target_id,
        )
        if getattr(participant, "identity", None) != command.target_id:
            raise LiveKitClassroomModerationAdminError(
                "LiveKit participant identity is not canonical"
            )
        microphone = _provider_source(self._api, MediaSource.MICROPHONE)
        tracks = tuple(getattr(participant, "tracks", ()) or ())
        for track in tracks:
            if getattr(track, "source", None) != microphone:
                continue
            if bool(getattr(track, "muted", False)):
                continue
            sid = getattr(track, "sid", None)
            if type(sid) is not str or not sid:
                raise LiveKitClassroomModerationAdminError(
                    "LiveKit microphone track id is invalid"
                )
            try:
                request = self._api.MuteRoomTrackRequest(
                    room=room_id,
                    identity=command.target_id,
                    track_sid=sid,
                    muted=True,
                )
                response = await self._room.mute_published_track(request)
            except Exception:
                raise LiveKitClassroomModerationAdminError(
                    "LiveKit microphone mute failed"
                ) from None
            updated_track = getattr(response, "track", None)
            if (
                updated_track is None
                or getattr(updated_track, "sid", None) != sid
                or getattr(updated_track, "muted", None) is not True
            ):
                raise LiveKitClassroomModerationAdminError(
                    "LiveKit microphone mute did not reach requested state"
                )

    async def _remove(
        self,
        *,
        room_id: str,
        command: ModerationCommand,
    ) -> None:
        try:
            request = self._api.RoomParticipantIdentity(
                room=room_id,
                identity=command.target_id,
            )
            await self._room.remove_participant(request)
        except Exception as error:
            if _is_not_found(self._api, error):
                return
            raise LiveKitClassroomModerationAdminError(
                "LiveKit participant removal failed"
            ) from None

    async def _participant(
        self,
        *,
        room_id: str,
        participant_id: str,
    ) -> object:
        try:
            request = self._api.RoomParticipantIdentity(
                room=room_id,
                identity=participant_id,
            )
            return await self._room.get_participant(request)
        except Exception as error:
            if _is_not_found(self._api, error):
                raise LiveKitClassroomModerationAdminError(
                    "LiveKit moderation participant is unavailable"
                ) from None
            raise LiveKitClassroomModerationAdminError(
                "LiveKit participant lookup failed"
            ) from None


def _load_api(*, api_module: object | None, sdk_version: str | None) -> object:
    if api_module is None:
        try:
            installed = metadata.version(LIVEKIT_API_DISTRIBUTION)
        except metadata.PackageNotFoundError:
            raise LiveKitClassroomModerationAdminError(
                "Pinned LiveKit server SDK is unavailable"
            ) from None
        if installed != LIVEKIT_API_VERSION:
            raise LiveKitClassroomModerationAdminError(
                "LiveKit server SDK version is not approved"
            )
        try:
            api_module = importlib.import_module("livekit.api")
        except Exception:
            raise LiveKitClassroomModerationAdminError(
                "Pinned LiveKit server SDK is unavailable"
            ) from None
    elif sdk_version is not None and sdk_version != LIVEKIT_API_VERSION:
        raise LiveKitClassroomModerationAdminError(
            "LiveKit server SDK version is not approved"
        )

    for name in (
        "ParticipantPermission",
        "UpdateParticipantRequest",
        "RoomParticipantIdentity",
        "MuteRoomTrackRequest",
        "ServerError",
        "ServerErrorCode",
        "TrackSource",
    ):
        if getattr(api_module, name, None) is None:
            raise LiveKitClassroomModerationAdminError(
                "LiveKit server SDK room API is unavailable"
            )
    return api_module


def _copy_permission(api: object, permission: object) -> object:
    try:
        copied = api.ParticipantPermission()
        copied.CopyFrom(permission)
        return copied
    except Exception:
        raise LiveKitClassroomModerationAdminError(
            "LiveKit participant permission cannot be copied"
        ) from None


def _provider_source(api: object, source: MediaSource) -> object:
    names = {
        MediaSource.MICROPHONE: "MICROPHONE",
        MediaSource.CAMERA: "CAMERA",
        MediaSource.SCREEN_SHARE: "SCREEN_SHARE",
    }
    try:
        return getattr(api.TrackSource, names[source])
    except (KeyError, AttributeError):
        raise LiveKitClassroomModerationAdminError(
            "LiveKit media source mapping is unavailable"
        ) from None


def _canonical_provider_sources(api: object) -> tuple[object, object, object]:
    return (
        _provider_source(api, MediaSource.MICROPHONE),
        _provider_source(api, MediaSource.CAMERA),
        _provider_source(api, MediaSource.SCREEN_SHARE),
    )


def _explicit_publish_sources(api: object, permission: object) -> set[object]:
    try:
        current = set(permission.can_publish_sources)
    except Exception:
        raise LiveKitClassroomModerationAdminError(
            "LiveKit participant publish sources are unavailable"
        ) from None

    canonical = set(_canonical_provider_sources(api))
    if not current.issubset(canonical):
        raise LiveKitClassroomModerationAdminError(
            "LiveKit participant has noncanonical publish source permission"
        )
    can_publish = bool(getattr(permission, "can_publish", False))
    if can_publish and not current:
        raise LiveKitClassroomModerationAdminError(
            "LiveKit participant has unrestricted publish permission"
        )
    if current and not can_publish:
        raise LiveKitClassroomModerationAdminError(
            "LiveKit participant publish permission state is inconsistent"
        )
    return current


def _ordered_sources(api: object, values: set[object]) -> list[object]:
    return [source for source in _canonical_provider_sources(api) if source in values]


def _is_not_found(api: object, error: BaseException) -> bool:
    server_error = getattr(api, "ServerError", None)
    if not isinstance(server_error, type) or not isinstance(error, server_error):
        return False
    not_found = getattr(getattr(api, "ServerErrorCode", None), "NOT_FOUND", "not_found")
    return getattr(error, "code", None) == not_found


__all__ = [
    "LIVEKIT_API_VERSION",
    "LiveKitClassroomModerationAdmin",
    "LiveKitClassroomModerationAdminError",
]
