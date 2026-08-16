from __future__ import annotations

from dataclasses import dataclass, replace
from enum import Enum
from typing import Mapping, Protocol


class ClassroomRole(str, Enum):
    TEACHER = "teacher"
    CO_TEACHER = "co_teacher"
    STUDENT = "student"
    OBSERVER = "observer"


class BoardControl(str, Enum):
    NONE = "none"
    WHITE = "white"
    BLACK = "black"
    BOTH = "both"


class StatisticsScope(str, Enum):
    LOCAL_ONLY = "local_only"
    CLASSROOM = "classroom"
    OPTED_IN_PRODUCT = "opted_in_product"


@dataclass(frozen=True)
class ParticipantIdentity:
    """Room identity is unique; display name is human-facing and may duplicate."""

    room_identity: str
    display_name: str
    installation_id: str | None = None
    generated_alias: bool = False

    def __post_init__(self) -> None:
        room_identity = str(self.room_identity).strip()
        display_name = str(self.display_name).strip()
        if not room_identity:
            raise ValueError("room_identity must not be empty")
        if not display_name:
            raise ValueError("display_name must not be empty")
        object.__setattr__(self, "room_identity", room_identity)
        object.__setattr__(self, "display_name", display_name)
        if self.installation_id is not None:
            installation_id = str(self.installation_id).strip()
            if not installation_id:
                raise ValueError("installation_id cannot be blank")
            object.__setattr__(self, "installation_id", installation_id)


@dataclass(frozen=True)
class ClassroomPermissions:
    can_publish_microphone: bool = True
    board_control: BoardControl = BoardControl.NONE
    can_point: bool = True
    can_annotate: bool = False
    can_deploy_positions: bool = False
    can_moderate: bool = False

    def can_move_side(self, side: str) -> bool:
        side = str(side).strip().lower()
        if side not in {"w", "b"}:
            raise ValueError("side must be w or b")
        if self.board_control is BoardControl.BOTH:
            return True
        if side == "w":
            return self.board_control is BoardControl.WHITE
        return self.board_control is BoardControl.BLACK


@dataclass(frozen=True)
class ClassroomParticipant:
    identity: ParticipantIdentity
    role: ClassroomRole
    permissions: ClassroomPermissions
    microphone_muted: bool = True
    microphone_hard_locked: bool = False
    connected: bool = True

    def __post_init__(self) -> None:
        if self.microphone_hard_locked and self.permissions.can_publish_microphone:
            raise ValueError("hard-locked microphone cannot keep publish permission")


@dataclass(frozen=True)
class UsageStatisticsPolicy:
    scope: StatisticsScope = StatisticsScope.LOCAL_ONLY
    collect_session_duration: bool = True
    collect_game_counters: bool = True
    collect_training_counters: bool = True
    collect_classroom_attendance: bool = True
    upload_raw_games: bool = False
    upload_book_or_database_content: bool = False
    record_audio: bool = False

    def __post_init__(self) -> None:
        if self.upload_raw_games or self.upload_book_or_database_content or self.record_audio:
            raise ValueError(
                "raw chess content or audio recording is not part of aggregate statistics policy"
            )


class ClassroomRoster:
    """Deterministic room roster and teacher moderation model.

    Network providers consume the resulting state changes but do not own room
    policy. This class never handles audio bytes, chess board state or secrets.
    """

    def __init__(self, participants: tuple[ClassroomParticipant, ...] = ()) -> None:
        self._participants: dict[str, ClassroomParticipant] = {}
        for participant in participants:
            self.add(participant)

    def add(self, participant: ClassroomParticipant) -> None:
        key = participant.identity.room_identity
        if key in self._participants:
            raise ValueError(f"participant already exists: {key}")
        self._participants[key] = participant

    def remove(self, room_identity: str) -> ClassroomParticipant:
        key = str(room_identity).strip()
        if key not in self._participants:
            raise KeyError(key)
        return self._participants.pop(key)

    def get(self, room_identity: str) -> ClassroomParticipant:
        key = str(room_identity).strip()
        if key not in self._participants:
            raise KeyError(key)
        return self._participants[key]

    def snapshot(self) -> tuple[ClassroomParticipant, ...]:
        return tuple(self._participants.values())

    def rename(self, room_identity: str, display_name: str) -> ClassroomParticipant:
        current = self.get(room_identity)
        identity = replace(current.identity, display_name=str(display_name).strip(), generated_alias=False)
        updated = replace(current, identity=identity)
        self._participants[current.identity.room_identity] = updated
        return updated

    def soft_mute(self, room_identity: str, muted: bool = True) -> ClassroomParticipant:
        current = self.get(room_identity)
        updated = replace(current, microphone_muted=bool(muted))
        self._participants[current.identity.room_identity] = updated
        return updated

    def set_microphone_lock(self, room_identity: str, locked: bool) -> ClassroomParticipant:
        current = self.get(room_identity)
        permissions = replace(current.permissions, can_publish_microphone=not bool(locked))
        updated = replace(
            current,
            permissions=permissions,
            microphone_hard_locked=bool(locked),
            microphone_muted=True if locked else current.microphone_muted,
        )
        self._participants[current.identity.room_identity] = updated
        return updated

    def set_board_control(self, room_identity: str, control: BoardControl) -> ClassroomParticipant:
        current = self.get(room_identity)
        updated = replace(current, permissions=replace(current.permissions, board_control=control))
        self._participants[current.identity.room_identity] = updated
        return updated

    def mute_all_students(self, *, hard_lock: bool = False) -> tuple[ClassroomParticipant, ...]:
        changed: list[ClassroomParticipant] = []
        for participant in tuple(self._participants.values()):
            if participant.role is not ClassroomRole.STUDENT:
                continue
            if hard_lock:
                changed.append(self.set_microphone_lock(participant.identity.room_identity, True))
            else:
                changed.append(self.soft_mute(participant.identity.room_identity, True))
        return tuple(changed)


class AudioRoomPort(Protocol):
    """Provider-neutral online audio room boundary.

    A LiveKit adapter can implement this port; tests can use an in-memory fake.
    Server-issued tokens/credentials are deliberately not represented here.
    """

    def join(self, room_id: str, identity: ParticipantIdentity) -> None: ...

    def leave(self) -> None: ...

    def set_local_microphone_enabled(self, enabled: bool) -> None: ...

    def mute_remote_microphone(self, room_identity: str, muted: bool) -> None: ...

    def update_remote_permissions(self, room_identity: str, permissions: ClassroomPermissions) -> None: ...

    def remove_participant(self, room_identity: str) -> None: ...

    def close(self) -> None: ...


def generated_alias(serial: int, *, lang: str = "uk") -> str:
    if isinstance(serial, bool) or int(serial) < 0:
        raise ValueError("serial must be non-negative")
    prefix = "Player" if lang == "en" else "Учень"
    return f"{prefix} {int(serial):04d}"
