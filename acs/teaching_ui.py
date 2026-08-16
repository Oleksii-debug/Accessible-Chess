from __future__ import annotations

from typing import Any, Iterable, Mapping

from .sound_profiles import (
    CORE_SOUND_EVENTS,
    OPTIONAL_CLASSROOM_SOUND_EVENTS,
    SoundEventPreference,
    SoundProfile,
)
from .sound_runtime import ProfiledSoundRuntime, SoundAssetPlaybackPort
from .teaching_controls import (
    AnnotationKind,
    CoachPointerService,
    PointerAction,
    StudentPointerEvent,
    TeachingAnnotation,
    normalize_square,
    spoken_square,
)
from .visual_preferences import BoardVisualPreferences, CoordinateMode, VisualPackManifest


class TeachingUiState:
    """Presentation composition for the isolated teaching/classroom feature lane.

    Chess state is deliberately not owned here. Visual themes, semantic coach
    pointers and annotations are overlays only; changing them cannot mutate a
    board position. Any future Windows mouse mirroring consumes ``pointer`` as
    output and must never become the source of truth.

    Sound preview is also presentation-only. When a playback port is supplied by
    composition, preview goes through ``ProfiledSoundRuntime`` so the same pack,
    per-event selection and effective-volume rules are used as real playback.
    Without a playback port the UI reports preview as unavailable; it never fakes
    success and never falls back to a system beep.
    """

    def __init__(
        self,
        *,
        visual: BoardVisualPreferences | None = None,
        sound: SoundProfile | None = None,
        visual_packs: Iterable[VisualPackManifest] = (),
        sound_playback: SoundAssetPlaybackPort | None = None,
    ) -> None:
        self.visual = visual or BoardVisualPreferences()
        self.sound = sound or SoundProfile()
        self.pointer = CoachPointerService()
        self._annotations: dict[str, TeachingAnnotation] = {}
        self._visual_packs = {pack.pack_id: pack for pack in visual_packs}
        self._sound_runtime = (
            ProfiledSoundRuntime(sound_playback, lambda: self.sound)
            if sound_playback is not None
            else None
        )

    def snapshot(self) -> dict[str, Any]:
        return {
            "visual": self.visual.as_dict(),
            "availablePacks": [self._pack_view(pack) for pack in self._visual_packs.values()],
            "pointer": {
                "square": self.pointer.square,
                "spokenSquare": spoken_square(self.pointer.square) if self.pointer.square else "",
                "generation": self.pointer.generation,
            },
            "studentPointerHistory": [
                {
                    "participantId": event.participant_id,
                    "displayName": event.display_name,
                    "square": event.square,
                    "action": event.action.value,
                    "accessibleText": event.accessible_text(),
                }
                for event in self.pointer.student_history()
            ],
            "annotations": [self._annotation_view(item) for item in self._annotations.values()],
            "sound": self._sound_view(),
        }

    def set_visual_preferences(self, payload: Mapping[str, object]) -> dict[str, Any]:
        current = self.visual.as_dict()
        current.update(dict(payload))
        candidate = BoardVisualPreferences.from_dict(current)
        self._ensure_pack_kind(candidate.board_theme_id, "board")
        self._ensure_pack_kind(candidate.piece_theme_id, "pieces")
        self.visual = candidate
        return self.snapshot()

    def commit_pointer(self, value: str) -> dict[str, Any]:
        commit = self.pointer.commit_text(value)
        return {
            "ok": True,
            "square": commit.square,
            "accessibleText": f"Вказівник: {spoken_square(commit.square)}.",
            "clearInput": commit.clear_input,
            "keepFocus": commit.keep_focus,
            "generation": self.pointer.generation,
        }

    def clear_pointer(self) -> dict[str, Any]:
        self.pointer.clear()
        return {"ok": True, "generation": self.pointer.generation}

    def record_student_pointer(
        self,
        participant_id: str,
        display_name: str,
        square: str,
        action: str = PointerAction.POINT.value,
    ) -> dict[str, Any]:
        event = StudentPointerEvent(
            participant_id=participant_id,
            display_name=display_name,
            square=square,
            action=PointerAction(action),
        )
        self.pointer.record_student_pointer(event)
        return {
            "ok": True,
            "accessibleText": event.accessible_text(),
            "history": self.pointer.recent_accessible_text(limit=10),
        }

    def add_square_annotation(self, annotation_id: str, square: str, style_id: str = "primary") -> dict[str, Any]:
        item = TeachingAnnotation(
            annotation_id=annotation_id,
            kind=AnnotationKind.SQUARE,
            source=square,
            style_id=style_id,
        )
        self._annotations[item.annotation_id] = item
        return {"ok": True, "annotation": self._annotation_view(item)}

    def add_arrow_annotation(
        self,
        annotation_id: str,
        source: str,
        target: str,
        style_id: str = "primary",
    ) -> dict[str, Any]:
        item = TeachingAnnotation(
            annotation_id=annotation_id,
            kind=AnnotationKind.ARROW,
            source=source,
            target=target,
            style_id=style_id,
        )
        self._annotations[item.annotation_id] = item
        return {"ok": True, "annotation": self._annotation_view(item)}

    def remove_annotation(self, annotation_id: str) -> dict[str, Any]:
        removed = self._annotations.pop(str(annotation_id).strip(), None)
        return {"ok": removed is not None}

    def set_sound_master(self, enabled: bool, volume_percent: int) -> dict[str, Any]:
        self.sound = SoundProfile(
            pack_id=self.sound.pack_id,
            master_enabled=bool(enabled),
            master_volume_percent=int(volume_percent),
            events=self.sound.events,
        )
        return self._sound_view()

    def set_sound_event(
        self,
        event_id: str,
        *,
        enabled: bool | None = None,
        volume_percent: int | None = None,
        sound_id: str | None = None,
    ) -> dict[str, Any]:
        self._known_sound_event(event_id)
        current = self.sound.preference_for(event_id)
        preference = SoundEventPreference(
            enabled=current.enabled if enabled is None else bool(enabled),
            volume_percent=current.volume_percent if volume_percent is None else int(volume_percent),
            sound_id=current.sound_id if sound_id is None else sound_id,
        )
        events = dict(self.sound.events)
        events[event_id] = preference
        self.sound = SoundProfile(
            pack_id=self.sound.pack_id,
            master_enabled=self.sound.master_enabled,
            master_volume_percent=self.sound.master_volume_percent,
            events=events,
        )
        return self._sound_event_view(event_id)

    def preview_sound_event(self, event_id: str) -> dict[str, Any]:
        """Preview through the injected real sound-asset playback boundary."""
        self._known_sound_event(event_id)
        pref = self.sound.preference_for(event_id)
        effective = self.sound.effective_volume(event_id)
        sound_id = pref.sound_id or event_id
        base = {
            "eventId": event_id,
            "soundId": sound_id,
            "volumePercent": effective,
        }
        if effective == 0:
            return {
                **base,
                "ok": False,
                "delivered": False,
                "available": self._sound_runtime is not None,
                "accessibleText": f"Звук {event_id} вимкнено.",
            }
        if self._sound_runtime is None:
            return {
                **base,
                "ok": False,
                "delivered": False,
                "available": False,
                "accessibleText": "Попередній перегляд звуку недоступний.",
            }

        result = self._sound_runtime.preview(event_id)
        if result.delivered:
            accessible = f"Звук {event_id} відтворено."
        elif result.error_type is not None:
            accessible = f"Не вдалося відтворити звук {event_id}."
        else:
            accessible = f"Звук {event_id} не відтворено."
        return {
            **base,
            "ok": result.ok and result.delivered,
            "delivered": result.delivered,
            "available": True,
            "accessibleText": accessible,
        }

    def coordinate_labels_for(self, square: str) -> dict[str, bool]:
        """Visual-coordinate flags only; accessible square naming is untouched."""
        square = normalize_square(square)
        file_name, rank = square[0], square[1]
        mode = self.visual.coordinate_mode
        if mode is CoordinateMode.OFF:
            return {"showFile": False, "showRank": False, "showEverySquare": False}
        if mode is CoordinateMode.EVERY_SQUARE:
            return {"showFile": True, "showRank": True, "showEverySquare": True}
        return {
            "showFile": rank == "1",
            "showRank": file_name == "a",
            "showEverySquare": False,
        }

    def _ensure_pack_kind(self, pack_id: str, expected: str) -> None:
        if pack_id == "classic":
            return
        pack = self._visual_packs.get(pack_id)
        if pack is None:
            raise ValueError(f"unknown visual pack: {pack_id}")
        if pack.kind.value != expected:
            raise ValueError(f"visual pack {pack_id} is not a {expected} pack")

    @staticmethod
    def _pack_view(pack: VisualPackManifest) -> dict[str, Any]:
        return {
            "id": pack.pack_id,
            "title": pack.title,
            "version": pack.version,
            "kind": pack.kind.value,
            "author": pack.author,
            "license": pack.license_id,
        }

    @staticmethod
    def _annotation_view(item: TeachingAnnotation) -> dict[str, Any]:
        return {
            "id": item.annotation_id,
            "kind": item.kind.value,
            "source": item.source,
            "target": item.target,
            "styleId": item.style_id,
        }

    def _sound_view(self) -> dict[str, Any]:
        return {
            "packId": self.sound.pack_id,
            "masterEnabled": self.sound.master_enabled,
            "masterVolumePercent": self.sound.master_volume_percent,
            "previewAvailable": self._sound_runtime is not None,
            "events": [self._sound_event_view(event_id) for event_id in self._all_sound_events()],
        }

    def _sound_event_view(self, event_id: str) -> dict[str, Any]:
        pref = self.sound.preference_for(event_id)
        return {
            "eventId": event_id,
            "enabled": pref.enabled,
            "volumePercent": pref.volume_percent,
            "soundId": pref.sound_id or event_id,
            "effectiveVolumePercent": self.sound.effective_volume(event_id),
        }

    @staticmethod
    def _all_sound_events() -> tuple[str, ...]:
        return tuple(CORE_SOUND_EVENTS) + tuple(OPTIONAL_CLASSROOM_SOUND_EVENTS)

    def _known_sound_event(self, event_id: str) -> None:
        if event_id not in self._all_sound_events():
            raise ValueError(f"unknown sound event: {event_id}")
