from __future__ import annotations

"""Durable trusted classroom media-policy authority.

Membership, role and board permission remain owned by an injected canonical
roster. This module persists only media-specific hard source overrides and
durable blocks. Join authorization reads the same durable state that moderation
updates, so a hard revoke cannot disappear on reconnect or process restart.

Soft mute remains a current-session provider effect and is intentionally not
converted into a hard token publication denial.
"""

from contextlib import closing
from dataclasses import dataclass
from pathlib import Path
import re
import sqlite3
from typing import Protocol

from .classroom_join_credentials import ClassroomJoinGrant
from .classroom_realtime_media import (
    ClassroomRole,
    ClassroomRosterPort,
    MAX_ROOM_PARTICIPANTS,
    MediaSource,
    ModerationAction,
    ModerationCommand,
    ParticipantMediaPolicy,
    SourcePolicy,
    classroom_media_moderation_allowed,
    default_source_policies,
)


MAX_POLICY_COMMANDS = 256
_IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_SOURCE_COLUMN = {
    MediaSource.MICROPHONE: "microphone_allowed",
    MediaSource.CAMERA: "camera_allowed",
    MediaSource.SCREEN_SHARE: "screen_share_allowed",
}
_SCHEMA = """
CREATE TABLE IF NOT EXISTS classroom_media_policy (
    room_id TEXT NOT NULL,
    participant_id TEXT NOT NULL,
    microphone_allowed INTEGER NULL
        CHECK (microphone_allowed IS NULL OR microphone_allowed IN (0, 1)),
    camera_allowed INTEGER NULL
        CHECK (camera_allowed IS NULL OR camera_allowed IN (0, 1)),
    screen_share_allowed INTEGER NULL
        CHECK (screen_share_allowed IS NULL OR screen_share_allowed IN (0, 1)),
    blocked INTEGER NOT NULL DEFAULT 0 CHECK (blocked IN (0, 1)),
    revision INTEGER NOT NULL DEFAULT 0 CHECK (revision >= 0),
    PRIMARY KEY (room_id, participant_id)
)
"""


class ClassroomMediaPolicyError(RuntimeError):
    """Sanitized trusted-policy failure safe for service boundaries."""


class ClassroomRosterResolverPort(Protocol):
    """Resolve the already-canonical room roster without owning membership."""

    def roster_for_room(self, room_id: str) -> ClassroomRosterPort:
        ...


class ClassroomModerationProviderPort(Protocol):
    async def apply_moderation_command(
        self,
        *,
        room_id: str,
        command: ModerationCommand,
    ) -> None:
        ...


@dataclass(frozen=True, slots=True)
class _Overrides:
    microphone_allowed: bool | None = None
    camera_allowed: bool | None = None
    screen_share_allowed: bool | None = None
    blocked: bool = False
    revision: int = 0

    def for_source(self, source: MediaSource) -> bool | None:
        return getattr(self, _SOURCE_COLUMN[source])


class SqliteClassroomMediaPolicyAuthority:
    """Join + moderation authorization over durable media-only state."""

    __slots__ = ("_path", "_resolver", "_timeout_seconds")

    def __init__(
        self,
        path: str | Path,
        *,
        roster_resolver: ClassroomRosterResolverPort,
        timeout_seconds: float = 5.0,
    ) -> None:
        if isinstance(path, Path):
            storage_path = path
        elif type(path) is str and path:
            storage_path = Path(path)
        else:
            raise ClassroomMediaPolicyError("media policy path is invalid")
        if str(storage_path) == ":memory:":
            raise ClassroomMediaPolicyError(
                "media policy authority requires durable file storage"
            )
        if roster_resolver is None or not callable(
            getattr(roster_resolver, "roster_for_room", None)
        ):
            raise ClassroomMediaPolicyError("canonical roster resolver is unavailable")
        if (
            type(timeout_seconds) not in (int, float)
            or isinstance(timeout_seconds, bool)
            or timeout_seconds <= 0
            or timeout_seconds > 60
        ):
            raise ClassroomMediaPolicyError("media policy timeout is invalid")

        self._path = storage_path
        self._resolver = roster_resolver
        self._timeout_seconds = float(timeout_seconds)
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            with closing(self._connect()) as connection:
                connection.execute("PRAGMA journal_mode=WAL")
                connection.execute(_SCHEMA)
        except (OSError, sqlite3.Error):
            raise ClassroomMediaPolicyError(
                "media policy initialization failed"
            ) from None

    def __repr__(self) -> str:
        return "SqliteClassroomMediaPolicyAuthority(path=<redacted>)"

    def participant_policy(
        self,
        *,
        room_id: str,
        participant_id: str,
    ) -> ParticipantMediaPolicy:
        room = _identifier(room_id, "room id")
        participant = _identifier(participant_id, "participant id")
        roster, participants = self._roster(room)
        if participant not in participants:
            raise ClassroomMediaPolicyError(
                "participant is not present in canonical roster"
            )
        role = _role(roster, participant)
        board_allowed = _board_control(roster, participant)
        overrides = self._read_overrides(room, participant)
        sources = []
        for item in default_source_policies(role):
            override = overrides.for_source(item.source)
            sources.append(
                SourcePolicy(
                    source=item.source,
                    publish_allowed=(
                        item.publish_allowed if override is None else override
                    ),
                )
            )
        return ParticipantMediaPolicy(
            participant_id=participant,
            role=role,
            board_control_allowed=board_allowed,
            sources=tuple(sources),
            removed=overrides.blocked,
            blocked=overrides.blocked,
        )

    def policy_revision(
        self,
        *,
        room_id: str,
        participant_id: str,
    ) -> int:
        room = _identifier(room_id, "room id")
        participant = _identifier(participant_id, "participant id")
        return self._read_overrides(room, participant).revision

    def authorize_join(
        self,
        *,
        room_id: str,
        trusted_caller_identity: str,
        requested_participant_id: str,
    ) -> ClassroomJoinGrant:
        room = _identifier(room_id, "room id")
        caller = _identifier(trusted_caller_identity, "trusted caller identity")
        participant = _identifier(
            requested_participant_id,
            "requested participant id",
        )
        if caller != participant:
            raise ClassroomMediaPolicyError(
                "join participant does not match trusted caller"
            )
        policy = self.participant_policy(
            room_id=room,
            participant_id=participant,
        )
        if policy.blocked:
            raise ClassroomMediaPolicyError("participant is blocked from classroom media")
        return ClassroomJoinGrant(
            room_id=room,
            participant_id=participant,
            publish_sources=tuple(
                item.source for item in policy.sources if item.publish_allowed
            ),
        )

    def authorize_moderation_batch(
        self,
        *,
        room_id: str,
        caller_identity: str,
        commands: tuple[ModerationCommand, ...],
    ) -> None:
        room = _identifier(room_id, "room id")
        caller = _identifier(caller_identity, "moderation caller identity")
        if (
            type(commands) is not tuple
            or not commands
            or len(commands) > MAX_POLICY_COMMANDS
            or any(type(item) is not ModerationCommand for item in commands)
        ):
            raise ClassroomMediaPolicyError("moderation command batch is invalid")

        roster, participants = self._roster(room)
        if caller not in participants:
            raise ClassroomMediaPolicyError(
                "moderation caller is not present in canonical roster"
            )
        caller_policy = self.participant_policy(
            room_id=room,
            participant_id=caller,
        )
        if caller_policy.blocked:
            raise ClassroomMediaPolicyError("blocked participant cannot moderate media")
        actor_role = caller_policy.role

        for command in commands:
            if command.actor_id != caller:
                raise ClassroomMediaPolicyError(
                    "moderation actor does not match trusted caller"
                )
            if command.target_id == caller:
                raise ClassroomMediaPolicyError(
                    "participant cannot moderate own media policy"
                )
            if command.target_id not in participants:
                raise ClassroomMediaPolicyError(
                    "moderation target is not present in canonical roster"
                )
            target_role = _role(roster, command.target_id)
            if not classroom_media_moderation_allowed(actor_role, target_role):
                raise ClassroomMediaPolicyError(
                    "participant is not allowed to moderate target"
                )

    def record_authorized_command(
        self,
        *,
        room_id: str,
        command: ModerationCommand,
    ) -> None:
        """Persist durable semantics before an already-authorized provider effect."""

        if type(command) is not ModerationCommand:
            raise ClassroomMediaPolicyError("moderation command is invalid")
        room = _identifier(room_id, "room id")
        self.authorize_moderation_batch(
            room_id=room,
            caller_identity=command.actor_id,
            commands=(command,),
        )

        if command.action is ModerationAction.PUBLISH_PERMISSION:
            source = command.source
            value = command.value
            if source is None or type(value) is not bool:
                raise ClassroomMediaPolicyError(
                    "publish-permission command is invalid"
                )
            self._set_source_override(
                room,
                command.target_id,
                source,
                value,
            )
        elif command.action is ModerationAction.REMOVE and command.value is True:
            self._set_blocked(room, command.target_id)
        # Soft mute is session-only. REMOVE(block=False) is a kick, not an
        # unblock, and cannot erase an existing durable block.

    def _roster(
        self,
        room_id: str,
    ) -> tuple[ClassroomRosterPort, tuple[str, ...]]:
        try:
            roster = self._resolver.roster_for_room(room_id)
        except Exception:
            raise ClassroomMediaPolicyError(
                "canonical classroom roster lookup failed"
            ) from None
        for name in ("participant_ids", "role_for", "board_control_allowed"):
            if not callable(getattr(roster, name, None)):
                raise ClassroomMediaPolicyError(
                    "canonical classroom roster is invalid"
                )
        try:
            raw = roster.participant_ids()
        except Exception:
            raise ClassroomMediaPolicyError(
                "canonical classroom roster lookup failed"
            ) from None
        if type(raw) is not tuple or len(raw) > MAX_ROOM_PARTICIPANTS:
            raise ClassroomMediaPolicyError(
                "canonical classroom roster participant list is invalid"
            )
        participants = tuple(
            _identifier(value, "roster participant id") for value in raw
        )
        if len(set(participants)) != len(participants):
            raise ClassroomMediaPolicyError(
                "canonical classroom roster participant ids are not unique"
            )
        return roster, participants

    def _read_overrides(
        self,
        room_id: str,
        participant_id: str,
    ) -> _Overrides:
        try:
            with closing(self._connect()) as connection:
                row = connection.execute(
                    """
                    SELECT microphone_allowed, camera_allowed, screen_share_allowed,
                           blocked, revision
                    FROM classroom_media_policy
                    WHERE room_id = ? AND participant_id = ?
                    """,
                    (room_id, participant_id),
                ).fetchone()
        except sqlite3.Error:
            raise ClassroomMediaPolicyError("media policy read failed") from None
        return _decode_overrides(row)

    def _set_source_override(
        self,
        room_id: str,
        participant_id: str,
        source: MediaSource,
        allowed: bool,
    ) -> None:
        if type(allowed) is not bool:
            raise ClassroomMediaPolicyError("source permission must be boolean")
        column = _SOURCE_COLUMN[source]
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                """
                SELECT microphone_allowed, camera_allowed, screen_share_allowed,
                       blocked, revision
                FROM classroom_media_policy
                WHERE room_id = ? AND participant_id = ?
                """,
                (room_id, participant_id),
            ).fetchone()
            current = _decode_overrides(row)
            if current.for_source(source) is allowed:
                connection.execute("COMMIT")
                return
            if row is None:
                values = {
                    "microphone_allowed": None,
                    "camera_allowed": None,
                    "screen_share_allowed": None,
                }
                values[column] = int(allowed)
                connection.execute(
                    """
                    INSERT INTO classroom_media_policy (
                        room_id, participant_id,
                        microphone_allowed, camera_allowed, screen_share_allowed,
                        blocked, revision
                    ) VALUES (?, ?, ?, ?, ?, 0, 1)
                    """,
                    (
                        room_id,
                        participant_id,
                        values["microphone_allowed"],
                        values["camera_allowed"],
                        values["screen_share_allowed"],
                    ),
                )
            else:
                connection.execute(
                    f"""
                    UPDATE classroom_media_policy
                    SET {column} = ?, revision = revision + 1
                    WHERE room_id = ? AND participant_id = ?
                    """,
                    (int(allowed), room_id, participant_id),
                )
            connection.execute("COMMIT")
        except ClassroomMediaPolicyError:
            _rollback(connection)
            raise
        except sqlite3.Error:
            _rollback(connection)
            raise ClassroomMediaPolicyError(
                "media policy source update failed"
            ) from None
        finally:
            connection.close()

    def _set_blocked(self, room_id: str, participant_id: str) -> None:
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                """
                SELECT microphone_allowed, camera_allowed, screen_share_allowed,
                       blocked, revision
                FROM classroom_media_policy
                WHERE room_id = ? AND participant_id = ?
                """,
                (room_id, participant_id),
            ).fetchone()
            current = _decode_overrides(row)
            if current.blocked:
                connection.execute("COMMIT")
                return
            if row is None:
                connection.execute(
                    """
                    INSERT INTO classroom_media_policy (
                        room_id, participant_id, blocked, revision
                    ) VALUES (?, ?, 1, 1)
                    """,
                    (room_id, participant_id),
                )
            else:
                connection.execute(
                    """
                    UPDATE classroom_media_policy
                    SET blocked = 1, revision = revision + 1
                    WHERE room_id = ? AND participant_id = ?
                    """,
                    (room_id, participant_id),
                )
            connection.execute("COMMIT")
        except ClassroomMediaPolicyError:
            _rollback(connection)
            raise
        except sqlite3.Error:
            _rollback(connection)
            raise ClassroomMediaPolicyError(
                "media policy block update failed"
            ) from None
        finally:
            connection.close()

    def _connect(self) -> sqlite3.Connection:
        connection: sqlite3.Connection | None = None
        try:
            connection = sqlite3.connect(
                str(self._path),
                timeout=self._timeout_seconds,
                isolation_level=None,
            )
            connection.execute("PRAGMA journal_mode=WAL")
            connection.execute("PRAGMA synchronous=FULL")
            connection.execute("PRAGMA foreign_keys=ON")
            connection.execute(
                f"PRAGMA busy_timeout={int(self._timeout_seconds * 1000)}"
            )
            return connection
        except sqlite3.Error:
            if connection is not None:
                try:
                    connection.close()
                except Exception:
                    pass
            raise ClassroomMediaPolicyError(
                "media policy storage is unavailable"
            ) from None


class ClassroomMediaPolicyProviderAdmin:
    """Compose durable hard policy with the current provider assignment.

    Restrictive changes are persisted before the provider effect so reconnect
    cannot reopen a source or blocked participant after a provider failure.
    Permission restoration is deliberately the inverse: authorization happens
    first, the provider must accept the grant, and only then may a fresh join
    credential observe that durable grant.
    """

    __slots__ = ("_authority", "_provider_admin")

    def __init__(
        self,
        *,
        authority: SqliteClassroomMediaPolicyAuthority,
        provider_admin: ClassroomModerationProviderPort,
    ) -> None:
        if type(authority) is not SqliteClassroomMediaPolicyAuthority:
            raise ClassroomMediaPolicyError("media policy authority is required")
        if provider_admin is None or not callable(
            getattr(provider_admin, "apply_moderation_command", None)
        ):
            raise ClassroomMediaPolicyError("moderation provider admin is unavailable")
        self._authority = authority
        self._provider_admin = provider_admin

    def __repr__(self) -> str:
        return "ClassroomMediaPolicyProviderAdmin(provider=<redacted>)"

    async def apply_moderation_command(
        self,
        *,
        room_id: str,
        command: ModerationCommand,
    ) -> None:
        restore_after_provider = (
            type(command) is ModerationCommand
            and command.action is ModerationAction.PUBLISH_PERMISSION
            and command.value is True
        )

        if restore_after_provider:
            if command.source is None:
                raise ClassroomMediaPolicyError(
                    "publish-permission command is invalid"
                )
            self._authority.authorize_moderation_batch(
                room_id=room_id,
                caller_identity=command.actor_id,
                commands=(command,),
            )
        else:
            # Revocations and durable blocks must win reconnect even when the
            # current provider assignment fails. Session-only operations still
            # pass through this call for canonical authorization but do not
            # mutate durable media policy.
            self._authority.record_authorized_command(
                room_id=room_id,
                command=command,
            )

        try:
            await self._provider_admin.apply_moderation_command(
                room_id=room_id,
                command=command,
            )
        except Exception:
            raise ClassroomMediaPolicyError(
                "media policy provider operation failed"
            ) from None

        if restore_after_provider:
            # A failed provider grant must never become a reconnect grant.
            # Persist only after the provider reached the authorized state.
            # If durable publication now fails, the RPC remains uncommitted;
            # an exact retry is safe because provider assignments are
            # idempotent and the durable state still fails closed.
            self._authority.record_authorized_command(
                room_id=room_id,
                command=command,
            )


def _role(roster: ClassroomRosterPort, participant_id: str) -> ClassroomRole:
    try:
        return ClassroomRole(roster.role_for(participant_id))
    except Exception:
        raise ClassroomMediaPolicyError(
            "canonical classroom role lookup failed"
        ) from None


def _board_control(roster: ClassroomRosterPort, participant_id: str) -> bool:
    try:
        value = roster.board_control_allowed(participant_id)
    except Exception:
        raise ClassroomMediaPolicyError(
            "canonical board-control lookup failed"
        ) from None
    if type(value) is not bool:
        raise ClassroomMediaPolicyError(
            "canonical board-control permission is invalid"
        )
    return value


def _decode_nullable_bool(value: object, label: str) -> bool | None:
    if value is None:
        return None
    if type(value) is not int or value not in (0, 1):
        raise ClassroomMediaPolicyError(f"{label} row is invalid")
    return bool(value)


def _decode_overrides(row: tuple[object, ...] | None) -> _Overrides:
    if row is None:
        return _Overrides()
    if type(row) is not tuple or len(row) != 5:
        raise ClassroomMediaPolicyError("media policy row is invalid")
    microphone, camera, screen_share, blocked, revision = row
    if type(blocked) is not int or blocked not in (0, 1):
        raise ClassroomMediaPolicyError("media policy block row is invalid")
    if type(revision) is not int or revision < 0:
        raise ClassroomMediaPolicyError("media policy revision row is invalid")
    return _Overrides(
        microphone_allowed=_decode_nullable_bool(
            microphone, "microphone permission"
        ),
        camera_allowed=_decode_nullable_bool(camera, "camera permission"),
        screen_share_allowed=_decode_nullable_bool(
            screen_share, "screen-share permission"
        ),
        blocked=bool(blocked),
        revision=revision,
    )


def _identifier(value: object, label: str) -> str:
    if type(value) is not str or _IDENTIFIER_RE.fullmatch(value) is None:
        raise ClassroomMediaPolicyError(f"{label} is invalid")
    return value


def _rollback(connection: sqlite3.Connection) -> None:
    try:
        connection.execute("ROLLBACK")
    except sqlite3.Error:
        pass


__all__ = [
    "ClassroomMediaPolicyError",
    "ClassroomMediaPolicyProviderAdmin",
    "ClassroomModerationProviderPort",
    "ClassroomRosterResolverPort",
    "MAX_POLICY_COMMANDS",
    "SqliteClassroomMediaPolicyAuthority",
]
