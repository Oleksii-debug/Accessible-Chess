from __future__ import annotations

"""Profile-aware playback for classroom/UI sound events.

This module intentionally does not accept ``SoundEvent`` and never calls
``SoundEventPolicy``. Chess semantic ordering remains owned by
``sound_events``/``GameSoundRuntime``. Classroom and lesson orchestration may
request only namespaced event IDs through this separate runtime.
"""

from dataclasses import dataclass
from typing import Callable

from .sound_profiles import SoundProfile
from .sound_runtime import SoundAssetPlaybackPort, SoundAssetRequest


CLASSROOM_SOUND_NAMESPACE_PREFIXES = ("classroom.", "lesson.", "chat.", "file.")


@dataclass(frozen=True)
class ClassroomSoundResult:
    event_id: str
    request: SoundAssetRequest | None
    delivered: bool
    error_type: str | None = None
    message: str = ""

    @property
    def ok(self) -> bool:
        return self.error_type is None


class ClassroomSoundRuntime:
    """Dispatch namespaced non-chess sounds through the shared sound profile.

    The profile provider is resolved exactly once per dispatch. Intentional
    silence (master disabled, event disabled or zero effective volume) never
    touches the playback adapter and therefore cannot fall back to a system
    beep. This class has no ordering policy: the caller owns classroom/UI event
    order, while chess-event ordering remains isolated in ``GameSoundRuntime``.
    """

    def __init__(
        self,
        playback: SoundAssetPlaybackPort,
        profile: SoundProfile | Callable[[], SoundProfile],
    ) -> None:
        self._playback = playback
        self._profile_provider = profile if callable(profile) else lambda: profile
        self._current_profile()

    def _current_profile(self) -> SoundProfile:
        profile = self._profile_provider()
        if not isinstance(profile, SoundProfile):
            raise TypeError("sound profile provider must return SoundProfile")
        return profile

    @staticmethod
    def _event_id(value: object) -> str:
        event_id = str(value).strip().lower()
        if not event_id or not any(
            event_id.startswith(prefix) for prefix in CLASSROOM_SOUND_NAMESPACE_PREFIXES
        ):
            raise ValueError("classroom sound event must use a classroom/lesson/chat/file namespace")
        allowed = "abcdefghijklmnopqrstuvwxyz0123456789._-"
        if any(ch not in allowed for ch in event_id):
            raise ValueError("classroom sound event id contains unsupported characters")
        parts = event_id.split(".")
        if any(not part for part in parts):
            raise ValueError("classroom sound event id must not contain empty namespace segments")
        return event_id

    def dispatch(self, event_id: str) -> ClassroomSoundResult:
        event_id = self._event_id(event_id)
        profile = self._current_profile()
        volume = profile.effective_volume(event_id)
        if volume == 0:
            return ClassroomSoundResult(event_id, None, False)

        request = SoundAssetRequest(
            pack_id=profile.pack_id,
            event_id=event_id,
            sound_id=profile.selected_sound_id(event_id),
            volume=volume,
            preview=False,
        )
        try:
            self._playback.play_sound(request)
        except Exception as exc:
            return ClassroomSoundResult(
                event_id,
                request,
                False,
                error_type=type(exc).__name__,
                message=str(exc),
            )
        return ClassroomSoundResult(event_id, request, True)

    def preview(self, event_id: str) -> ClassroomSoundResult:
        event_id = self._event_id(event_id)
        profile = self._current_profile()
        volume = profile.effective_volume(event_id)
        if volume == 0:
            return ClassroomSoundResult(event_id, None, False)

        request = SoundAssetRequest(
            pack_id=profile.pack_id,
            event_id=event_id,
            sound_id=profile.selected_sound_id(event_id),
            volume=volume,
            preview=True,
        )
        try:
            self._playback.play_sound(request)
        except Exception as exc:
            return ClassroomSoundResult(
                event_id,
                request,
                False,
                error_type=type(exc).__name__,
                message=str(exc),
            )
        return ClassroomSoundResult(event_id, request, True)
