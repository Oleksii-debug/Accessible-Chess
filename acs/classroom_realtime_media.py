from __future__ import annotations

"""Provider-neutral realtime-media contract for classroom sessions.

This module deliberately does not own classroom membership, chess state, lesson
state, token issuance, networking, or provider SDK objects. Participant identity,
role, and board-control permission are read from an external roster authority.
The module owns only transient media policy/orchestration at the desktop boundary.
"""

from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from enum import Enum
import re
from typing import Protocol


MAX_JOIN_TTL_SECONDS = 15 * 60
MAX_TOKEN_LENGTH = 8192
MAX_DEVICE_ID_LENGTH = 512
MAX_ROOM_PARTICIPANTS = 5000
_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")


class ClassroomMediaError(ValueError):
    """Raised when realtime-media input or state is unsafe or non-canonical."""


class ClassroomRole(str, Enum):
    TEACHER = "teacher"
    CO_TEACHER = "co_teacher"
    STUDENT = "student"
    OBSERVER = "observer"


class MediaSource(str, Enum):
    MICROPHONE = "microphone"
    CAMERA = "camera"
    SCREEN_SHARE = "screen_share"


class MediaDeviceKind(str, Enum):
    MICROPHONE = "microphone"
    SPEAKER = "speaker"
    CAMERA = "camera"


class ModerationAction(str, Enum):
    PUBLISH_PERMISSION = "publish_permission"
    SOFT_MUTE = "soft_mute"
    REMOVE = "remove"


@dataclass(frozen=True, slots=True)
class JoinCredential:
    """Short-lived server-issued room credential.

    The token is intentionally excluded from repr so diagnostic formatting cannot
    disclose it accidentally. No serialization helper is provided by this module.
    """

    room_id: str
    participant_id: str
    token: str = field(repr=False)
    issued_at: datetime
    expires_at: datetime

    def __post_init__(self) -> None:
        object.__setattr__(self, "room_id", _id(self.room_id, "room id"))
        object.__setattr__(
            self,
            "participant_id",
            _id(self.participant_id, "participant id"),
        )
        _secret_token(self.token)
        issued = _utc(self.issued_at, "credential issued_at")
        expires = _utc(self.expires_at, "credential expires_at")
        if expires <= issued:
            raise ClassroomMediaError("join credential expiry must follow issuance")
        if (expires - issued).total_seconds() > MAX_JOIN_TTL_SECONDS:
            raise ClassroomMediaError("join credential exceeds short-lived TTL limit")
        object.__setattr__(self, "issued_at", issued)
        object.__setattr__(self, "expires_at", expires)

    def assert_usable(self, now: datetime) -> None:
        current = _utc(now, "current time")
        if current < self.issued_at or current >= self.expires_at:
            raise ClassroomMediaError("join credential is not currently valid")


@dataclass(frozen=True, slots=True)
class SourcePolicy:
    source: MediaSource
    publish_allowed: bool
    soft_muted: bool = False

    def __post_init__(self) -> None:
        source = _enum(self.source, MediaSource, "media source")
        if type(self.publish_allowed) is not bool or type(self.soft_muted) is not bool:
            raise ClassroomMediaError("media policy flags must be boolean")
        if source is not MediaSource.MICROPHONE and self.soft_muted:
            raise ClassroomMediaError("soft mute applies only to microphone audio")
        object.__setattr__(self, "source", source)


@dataclass(frozen=True, slots=True)
class ParticipantMediaPolicy:
    """Transient media policy projected over externally owned participant identity."""

    participant_id: str
    role: ClassroomRole
    board_control_allowed: bool
    sources: tuple[SourcePolicy, ...]
    removed: bool = False
    blocked: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "participant_id",
            _id(self.participant_id, "participant id"),
        )
        role = _enum(self.role, ClassroomRole, "classroom role")
        if type(self.board_control_allowed) is not bool:
            raise ClassroomMediaError("board-control permission must be boolean")
        if type(self.sources) is not tuple or len(self.sources) != len(MediaSource):
            raise ClassroomMediaError("participant media policy must cover every source")
        if any(type(item) is not SourcePolicy for item in self.sources):
            raise ClassroomMediaError("participant media policy contains invalid source state")
        source_ids = tuple(item.source for item in self.sources)
        if set(source_ids) != set(MediaSource) or len(set(source_ids)) != len(MediaSource):
            raise ClassroomMediaError("participant media sources must be unique and complete")
        if type(self.removed) is not bool or type(self.blocked) is not bool:
            raise ClassroomMediaError("participant removal flags must be boolean")
        if self.blocked and not self.removed:
            raise ClassroomMediaError("blocked participant must also be removed")
        object.__setattr__(self, "role", role)

    def source(self, source: MediaSource | str) -> SourcePolicy:
        wanted = _enum(source, MediaSource, "media source")
        return next(item for item in self.sources if item.source is wanted)


@dataclass(frozen=True, slots=True)
class LocalMediaState:
    room_id: str | None
    participant_id: str
    connected: bool
    desired_sources: frozenset[MediaSource]
    revision: int = 0

    def __post_init__(self) -> None:
        if self.room_id is not None:
            object.__setattr__(self, "room_id", _id(self.room_id, "room id"))
        object.__setattr__(
            self,
            "participant_id",
            _id(self.participant_id, "participant id"),
        )
        if type(self.connected) is not bool:
            raise ClassroomMediaError("connected state must be boolean")
        if type(self.desired_sources) is not frozenset:
            raise ClassroomMediaError("desired sources must be a frozenset")
        normalized = frozenset(
            _enum(item, MediaSource, "desired media source") for item in self.desired_sources
        )
        if type(self.revision) is not int or self.revision < 0:
            raise ClassroomMediaError("media revision must be a non-negative integer")
        object.__setattr__(self, "desired_sources", normalized)


@dataclass(frozen=True, slots=True)
class ModerationCommand:
    operation_id: str
    actor_id: str
    target_id: str
    action: ModerationAction
    source: MediaSource | None = None
    value: bool | None = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "operation_id",
            _id(self.operation_id, "moderation operation id"),
        )
        object.__setattr__(self, "actor_id", _id(self.actor_id, "moderation actor id"))
        object.__setattr__(self, "target_id", _id(self.target_id, "moderation target id"))
        action = _enum(self.action, ModerationAction, "moderation action")
        source = None if self.source is None else _enum(self.source, MediaSource, "media source")
        if action is ModerationAction.PUBLISH_PERMISSION:
            if source is None or type(self.value) is not bool:
                raise ClassroomMediaError("publish-permission command requires source and boolean value")
        elif action is ModerationAction.SOFT_MUTE:
            if source is not MediaSource.MICROPHONE or type(self.value) is not bool:
                raise ClassroomMediaError("soft-mute command requires microphone and boolean value")
        elif action is ModerationAction.REMOVE:
            if source is not None or type(self.value) is not bool:
                raise ClassroomMediaError("remove command uses boolean block value and no source")
        object.__setattr__(self, "action", action)
        object.__setattr__(self, "source", source)


class ClassroomRosterPort(Protocol):
    """Read-only authority for participant membership/role/board permission."""

    def participant_ids(self) -> tuple[str, ...]:
        ...

    def role_for(self, participant_id: str) -> ClassroomRole:
        ...

    def board_control_allowed(self, participant_id: str) -> bool:
        ...


class RealtimeMediaPort(Protocol):
    """Provider adapter boundary. Implementations may use LiveKit or another provider."""

    def connect(
        self,
        credential: JoinCredential,
        *,
        enabled_sources: tuple[MediaSource, ...],
    ) -> None:
        ...

    def reconnect(
        self,
        credential: JoinCredential,
        *,
        enabled_sources: tuple[MediaSource, ...],
    ) -> None:
        ...

    def disconnect(self) -> None:
        ...

    def set_local_source(self, source: MediaSource, enabled: bool) -> None:
        ...

    def apply_moderation(self, commands: tuple[ModerationCommand, ...]) -> None:
        ...

    def recover_device(
        self,
        kind: MediaDeviceKind,
        device_id: str,
        *,
        republish_enabled: bool,
    ) -> None:
        ...


class ClassroomMediaController:
    """Fail-closed orchestration over a canonical external classroom roster.

    Joining never publishes microphone, camera, or screen share automatically.
    A hard permission revocation turns a source off and restoring permission does
    not silently turn it back on. Board-control permission is read from the roster
    and is never changed by media moderation.
    """

    def __init__(
        self,
        *,
        local_participant_id: str,
        roster: ClassroomRosterPort,
        media: RealtimeMediaPort,
    ) -> None:
        self._local_participant_id = _id(local_participant_id, "local participant id")
        self._roster = roster
        self._media = media
        self._policies: dict[str, tuple[SourcePolicy, ...]] = {}
        self._removed: set[str] = set()
        self._blocked: set[str] = set()
        self._state = LocalMediaState(
            room_id=None,
            participant_id=self._local_participant_id,
            connected=False,
            desired_sources=frozenset(),
        )

    @property
    def state(self) -> LocalMediaState:
        return self._state

    def participant_policy(self, participant_id: str) -> ParticipantMediaPolicy:
        participant = _id(participant_id, "participant id")
        role = self._role(participant)
        board_allowed = self._board_control_allowed(participant)
        sources = self._policies.get(participant)
        if sources is None:
            sources = _default_source_policies(role)
        return ParticipantMediaPolicy(
            participant_id=participant,
            role=role,
            board_control_allowed=board_allowed,
            sources=sources,
            removed=participant in self._removed,
            blocked=participant in self._blocked,
        )

    def join(self, credential: JoinCredential, *, now: datetime) -> LocalMediaState:
        if type(credential) is not JoinCredential:
            raise ClassroomMediaError("join requires JoinCredential")
        if credential.participant_id != self._local_participant_id:
            raise ClassroomMediaError("join credential belongs to another participant")
        if self._state.room_id is not None:
            raise ClassroomMediaError("media session already has room identity")
        credential.assert_usable(now)
        policy = self.participant_policy(self._local_participant_id)
        if policy.removed or policy.blocked:
            raise ClassroomMediaError("participant is not allowed to join")
        self._media.connect(credential, enabled_sources=())
        self._state = LocalMediaState(
            room_id=credential.room_id,
            participant_id=self._local_participant_id,
            connected=True,
            desired_sources=frozenset(),
            revision=self._state.revision + 1,
        )
        return self._state

    def mark_transport_lost(self) -> LocalMediaState:
        if self._state.room_id is None:
            raise ClassroomMediaError("no media session exists")
        if not self._state.connected:
            return self._state
        self._state = replace(
            self._state,
            connected=False,
            revision=self._state.revision + 1,
        )
        return self._state

    def reconnect(self, credential: JoinCredential, *, now: datetime) -> LocalMediaState:
        if type(credential) is not JoinCredential:
            raise ClassroomMediaError("reconnect requires JoinCredential")
        if self._state.room_id is None:
            raise ClassroomMediaError("no prior media session to reconnect")
        if self._state.connected:
            raise ClassroomMediaError("media session is already connected")
        if credential.room_id != self._state.room_id:
            raise ClassroomMediaError("reconnect credential belongs to another room")
        if credential.participant_id != self._local_participant_id:
            raise ClassroomMediaError("reconnect credential belongs to another participant")
        credential.assert_usable(now)
        policy = self.participant_policy(self._local_participant_id)
        if policy.removed or policy.blocked:
            raise ClassroomMediaError("participant is not allowed to reconnect")
        enabled = tuple(
            source
            for source in MediaSource
            if source in self._state.desired_sources
            and policy.source(source).publish_allowed
        )
        self._media.reconnect(credential, enabled_sources=enabled)
        desired = frozenset(enabled)
        self._state = replace(
            self._state,
            connected=True,
            desired_sources=desired,
            revision=self._state.revision + 1,
        )
        return self._state

    def leave(self) -> LocalMediaState:
        if self._state.room_id is None:
            return self._state
        if self._state.connected:
            self._media.disconnect()
        self._state = LocalMediaState(
            room_id=None,
            participant_id=self._local_participant_id,
            connected=False,
            desired_sources=frozenset(),
            revision=self._state.revision + 1,
        )
        return self._state

    def set_local_source(
        self,
        source: MediaSource | str,
        enabled: bool,
    ) -> LocalMediaState:
        wanted = _enum(source, MediaSource, "media source")
        if type(enabled) is not bool:
            raise ClassroomMediaError("local media enabled flag must be boolean")
        self._require_connected()
        policy = self.participant_policy(self._local_participant_id)
        source_policy = policy.source(wanted)
        if enabled and (
            not source_policy.publish_allowed
            or policy.removed
            or policy.blocked
        ):
            raise ClassroomMediaError("media source cannot publish under current policy")
        current = wanted in self._state.desired_sources
        if current == enabled:
            return self._state
        self._media.set_local_source(wanted, enabled)
        if (
            enabled
            and wanted is MediaSource.MICROPHONE
            and source_policy.soft_muted
        ):
            self._apply_soft_mute(self._local_participant_id, False)
        desired = set(self._state.desired_sources)
        if enabled:
            desired.add(wanted)
        else:
            desired.discard(wanted)
        self._state = replace(
            self._state,
            desired_sources=frozenset(desired),
            revision=self._state.revision + 1,
        )
        return self._state

    def set_publish_permission(
        self,
        *,
        actor_id: str,
        target_id: str,
        source: MediaSource | str,
        allowed: bool,
        operation_id: str,
    ) -> ParticipantMediaPolicy:
        wanted = _enum(source, MediaSource, "media source")
        if type(allowed) is not bool:
            raise ClassroomMediaError("publish permission must be boolean")
        actor, target = self._moderation_pair(actor_id, target_id)
        command = ModerationCommand(
            operation_id=operation_id,
            actor_id=actor,
            target_id=target,
            action=ModerationAction.PUBLISH_PERMISSION,
            source=wanted,
            value=allowed,
        )
        self._media.apply_moderation((command,))
        self._apply_policy_permission(target, wanted, allowed)
        if not allowed:
            self._drop_local_desired_source(target, wanted)
        return self.participant_policy(target)

    def set_soft_mute(
        self,
        *,
        actor_id: str,
        target_id: str,
        muted: bool,
        operation_id: str,
    ) -> ParticipantMediaPolicy:
        if type(muted) is not bool:
            raise ClassroomMediaError("soft mute flag must be boolean")
        actor, target = self._moderation_pair(actor_id, target_id)
        command = ModerationCommand(
            operation_id=operation_id,
            actor_id=actor,
            target_id=target,
            action=ModerationAction.SOFT_MUTE,
            source=MediaSource.MICROPHONE,
            value=muted,
        )
        self._media.apply_moderation((command,))
        self._apply_soft_mute(target, muted)
        if muted:
            self._drop_local_desired_source(target, MediaSource.MICROPHONE)
        return self.participant_policy(target)

    def set_all_students_publish_permission(
        self,
        *,
        actor_id: str,
        source: MediaSource | str,
        allowed: bool,
        operation_id: str,
    ) -> tuple[ParticipantMediaPolicy, ...]:
        wanted = _enum(source, MediaSource, "media source")
        if type(allowed) is not bool:
            raise ClassroomMediaError("publish permission must be boolean")
        actor = _id(actor_id, "moderation actor id")
        root = _id(operation_id, "moderation operation id")
        targets = self._student_targets(actor)
        commands = tuple(
            ModerationCommand(
                operation_id=_child_operation_id(root, index),
                actor_id=actor,
                target_id=target,
                action=ModerationAction.PUBLISH_PERMISSION,
                source=wanted,
                value=allowed,
            )
            for index, target in enumerate(targets, 1)
        )
        if commands:
            self._media.apply_moderation(commands)
            for target in targets:
                self._apply_policy_permission(target, wanted, allowed)
            if not allowed and self._local_participant_id in targets:
                self._drop_local_desired_source(self._local_participant_id, wanted)
        return tuple(self.participant_policy(target) for target in targets)

    def set_all_students_soft_mute(
        self,
        *,
        actor_id: str,
        muted: bool,
        operation_id: str,
    ) -> tuple[ParticipantMediaPolicy, ...]:
        if type(muted) is not bool:
            raise ClassroomMediaError("soft mute flag must be boolean")
        actor = _id(actor_id, "moderation actor id")
        root = _id(operation_id, "moderation operation id")
        targets = self._student_targets(actor)
        commands = tuple(
            ModerationCommand(
                operation_id=_child_operation_id(root, index),
                actor_id=actor,
                target_id=target,
                action=ModerationAction.SOFT_MUTE,
                source=MediaSource.MICROPHONE,
                value=muted,
            )
            for index, target in enumerate(targets, 1)
        )
        if commands:
            self._media.apply_moderation(commands)
            for target in targets:
                self._apply_soft_mute(target, muted)
            if muted and self._local_participant_id in targets:
                self._drop_local_desired_source(
                    self._local_participant_id,
                    MediaSource.MICROPHONE,
                )
        return tuple(self.participant_policy(target) for target in targets)

    def remove_participant(
        self,
        *,
        actor_id: str,
        target_id: str,
        block: bool,
        operation_id: str,
    ) -> ParticipantMediaPolicy:
        if type(block) is not bool:
            raise ClassroomMediaError("block flag must be boolean")
        actor, target = self._moderation_pair(actor_id, target_id)
        policy_before_removal = self.participant_policy(target)
        command = ModerationCommand(
            operation_id=operation_id,
            actor_id=actor,
            target_id=target,
            action=ModerationAction.REMOVE,
            value=block,
        )
        self._media.apply_moderation((command,))
        self._removed.add(target)
        if block:
            self._blocked.add(target)
        if target == self._local_participant_id:
            self._state = replace(
                self._state,
                connected=False,
                desired_sources=frozenset(),
                revision=self._state.revision + 1,
            )
        return replace(
            policy_before_removal,
            removed=True,
            blocked=block,
        )

    def recover_device(
        self,
        kind: MediaDeviceKind | str,
        device_id: str,
    ) -> LocalMediaState:
        wanted = _enum(kind, MediaDeviceKind, "media device kind")
        device = _device_id(device_id)
        self._require_connected()
        source = {
            MediaDeviceKind.MICROPHONE: MediaSource.MICROPHONE,
            MediaDeviceKind.CAMERA: MediaSource.CAMERA,
        }.get(wanted)
        republish = source is not None and source in self._state.desired_sources
        self._media.recover_device(
            wanted,
            device,
            republish_enabled=republish,
        )
        self._state = replace(
            self._state,
            revision=self._state.revision + 1,
        )
        return self._state

    def _student_targets(self, actor_id: str) -> tuple[str, ...]:
        actor_role = self._role(actor_id)
        if actor_role not in {ClassroomRole.TEACHER, ClassroomRole.CO_TEACHER}:
            raise ClassroomMediaError("participant is not allowed to moderate media")
        raw = self._roster.participant_ids()
        if type(raw) is not tuple or len(raw) > MAX_ROOM_PARTICIPANTS:
            raise ClassroomMediaError("roster participant list is invalid or too large")
        participants = tuple(_id(item, "participant id") for item in raw)
        if len(set(participants)) != len(participants):
            raise ClassroomMediaError("roster participant ids must be unique")
        targets = tuple(
            participant
            for participant in participants
            if self._role(participant) is ClassroomRole.STUDENT
        )
        for target in targets:
            self._assert_can_moderate(actor_id, target)
        return targets

    def _moderation_pair(self, actor_id: str, target_id: str) -> tuple[str, str]:
        actor = _id(actor_id, "moderation actor id")
        target = _id(target_id, "moderation target id")
        if actor == target:
            raise ClassroomMediaError("participant cannot moderate own media policy")
        self._assert_can_moderate(actor, target)
        return actor, target

    def _assert_can_moderate(self, actor_id: str, target_id: str) -> None:
        actor_role = self._role(actor_id)
        target_role = self._role(target_id)
        if actor_role is ClassroomRole.TEACHER:
            if target_role is ClassroomRole.TEACHER:
                raise ClassroomMediaError("teacher cannot moderate another teacher")
            return
        if actor_role is ClassroomRole.CO_TEACHER:
            if target_role in {ClassroomRole.STUDENT, ClassroomRole.OBSERVER}:
                return
        raise ClassroomMediaError("participant is not allowed to moderate target")

    def _role(self, participant_id: str) -> ClassroomRole:
        participant = _id(participant_id, "participant id")
        participants = self._roster.participant_ids()
        if type(participants) is not tuple or len(participants) > MAX_ROOM_PARTICIPANTS:
            raise ClassroomMediaError("roster participant list is invalid or too large")
        normalized = tuple(_id(item, "participant id") for item in participants)
        if len(set(normalized)) != len(normalized):
            raise ClassroomMediaError("roster participant ids must be unique")
        if participant not in normalized:
            raise ClassroomMediaError("participant is not present in canonical roster")
        try:
            return _enum(
                self._roster.role_for(participant),
                ClassroomRole,
                "classroom role",
            )
        except Exception as exc:
            if isinstance(exc, ClassroomMediaError):
                raise
            raise ClassroomMediaError("canonical roster role lookup failed") from exc

    def _board_control_allowed(self, participant_id: str) -> bool:
        try:
            value = self._roster.board_control_allowed(participant_id)
        except Exception as exc:
            raise ClassroomMediaError("canonical board-control lookup failed") from exc
        if type(value) is not bool:
            raise ClassroomMediaError("canonical board-control permission must be boolean")
        return value

    def _apply_policy_permission(
        self,
        participant_id: str,
        source: MediaSource,
        allowed: bool,
    ) -> None:
        policy = list(self.participant_policy(participant_id).sources)
        for index, item in enumerate(policy):
            if item.source is source:
                policy[index] = SourcePolicy(
                    source=source,
                    publish_allowed=allowed,
                    soft_muted=item.soft_muted,
                )
                break
        self._policies[participant_id] = tuple(policy)

    def _apply_soft_mute(self, participant_id: str, muted: bool) -> None:
        policy = list(self.participant_policy(participant_id).sources)
        for index, item in enumerate(policy):
            if item.source is MediaSource.MICROPHONE:
                policy[index] = SourcePolicy(
                    source=MediaSource.MICROPHONE,
                    publish_allowed=item.publish_allowed,
                    soft_muted=muted,
                )
                break
        self._policies[participant_id] = tuple(policy)

    def _drop_local_desired_source(
        self,
        target_id: str,
        source: MediaSource,
    ) -> None:
        if (
            target_id != self._local_participant_id
            or source not in self._state.desired_sources
        ):
            return
        self._state = replace(
            self._state,
            desired_sources=frozenset(
                item for item in self._state.desired_sources if item is not source
            ),
            revision=self._state.revision + 1,
        )

    def _require_connected(self) -> None:
        if self._state.room_id is None or not self._state.connected:
            raise ClassroomMediaError("media session is not connected")


def _default_source_policies(role: ClassroomRole) -> tuple[SourcePolicy, ...]:
    publish = role in {
        ClassroomRole.TEACHER,
        ClassroomRole.CO_TEACHER,
        ClassroomRole.STUDENT,
    }
    screen = role in {ClassroomRole.TEACHER, ClassroomRole.CO_TEACHER}
    return (
        SourcePolicy(MediaSource.MICROPHONE, publish_allowed=publish),
        SourcePolicy(MediaSource.CAMERA, publish_allowed=publish),
        SourcePolicy(MediaSource.SCREEN_SHARE, publish_allowed=screen),
    )


def _child_operation_id(root: str, index: int) -> str:
    suffix = f":{index}"
    if len(root) + len(suffix) > 128:
        raise ClassroomMediaError("moderation operation id is too long for batch")
    return _id(root + suffix, "moderation operation id")


def _id(value: object, label: str) -> str:
    if type(value) is not str or _ID_RE.fullmatch(value) is None:
        raise ClassroomMediaError(f"{label} must be a canonical opaque identifier")
    return value


def _enum(value: object, enum_type: type[Enum], label: str):
    try:
        return enum_type(value)
    except (TypeError, ValueError) as exc:
        raise ClassroomMediaError(f"invalid {label}") from exc


def _secret_token(value: object) -> str:
    if type(value) is not str or not value or len(value) > MAX_TOKEN_LENGTH:
        raise ClassroomMediaError("join credential token is invalid")
    if any(ch.isspace() or ord(ch) < 32 or ord(ch) == 127 for ch in value):
        raise ClassroomMediaError("join credential token is invalid")
    return value


def _utc(value: object, label: str) -> datetime:
    if type(value) is not datetime or value.tzinfo is None or value.utcoffset() is None:
        raise ClassroomMediaError(f"{label} must be timezone-aware datetime")
    return value.astimezone(timezone.utc)


def _device_id(value: object) -> str:
    if type(value) is not str or not value or len(value) > MAX_DEVICE_ID_LENGTH:
        raise ClassroomMediaError("device id is invalid")
    if any(ord(ch) < 32 or ord(ch) == 127 for ch in value):
        raise ClassroomMediaError("device id is invalid")
    return value


__all__ = [
    "ClassroomMediaController",
    "ClassroomMediaError",
    "ClassroomRole",
    "ClassroomRosterPort",
    "JoinCredential",
    "LocalMediaState",
    "MAX_JOIN_TTL_SECONDS",
    "MediaDeviceKind",
    "MediaSource",
    "ModerationAction",
    "ModerationCommand",
    "ParticipantMediaPolicy",
    "RealtimeMediaPort",
    "SourcePolicy",
]
