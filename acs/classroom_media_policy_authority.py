from __future__ import annotations

"""Durable trusted classroom media-policy authority.

Membership, role and board permission remain owned by an injected canonical
roster. This module persists only media-specific hard source overrides and
durable blocks. Join authorization reads the same durable state that moderation
updates, so a hard revoke cannot disappear on reconnect or process restart.

Soft mute remains a current-session provider effect and is intentionally not
converted into a hard token publication denial.
"""

import asyncio
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
_EFFECT_LOCK_SCHEMA = """
CREATE TABLE IF NOT EXISTS classroom_moderation_effect_lock (
    singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
    generation INTEGER NOT NULL DEFAULT 0 CHECK (generation >= 0)
)
"""


class ClassroomMediaPolicyError(RuntimeError):
    """Sanitized trusted-policy failure safe for service boundaries."""


class ClassroomRosterResolverPort(Protocol):
    """Resolve the already-canonical room roster without owning membership."""

    def roster_for_room(self, room_id: str) -> ClassroomRosterPort:
        ...


class ClassroomJoinIdentityResolverPort(Protocol):
    """Map an authenticated caller to its canonical room-scoped participant."""

    def participant_for_caller(
        self,
        *,
        room_id: str,
        trusted_caller_identity: str,
    ) -> str:
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

    __slots__ = (
        "_path",
        "_effect_lock_path",
        "_resolver",
        "_join_identity_resolver",
        "_timeout_seconds",
    )

    def __init__(
        self,
        path: str | Path,
        *,
        roster_resolver: ClassroomRosterResolverPort,
        join_identity_resolver: ClassroomJoinIdentityResolverPort,
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
        try:
            # Derive policy + provider-effect lock storage from one canonical
            # filesystem spelling. Otherwise two services can open the same
            # policy database through different symlink aliases while taking
            # different companion locks, defeating cross-process serialization.
            storage_path = storage_path.resolve(strict=False)
        except (OSError, RuntimeError):
            raise ClassroomMediaPolicyError("media policy path is invalid") from None
        if roster_resolver is None or not callable(
            getattr(roster_resolver, "roster_for_room", None)
        ):
            raise ClassroomMediaPolicyError("canonical roster resolver is unavailable")
        if join_identity_resolver is None or not callable(
            getattr(join_identity_resolver, "participant_for_caller", None)
        ):
            raise ClassroomMediaPolicyError(
                "canonical join identity resolver is unavailable"
            )
        if (
            type(timeout_seconds) not in (int, float)
            or isinstance(timeout_seconds, bool)
            or timeout_seconds <= 0
            or timeout_seconds > 60
        ):
            raise ClassroomMediaPolicyError("media policy timeout is invalid")

        self._path = storage_path
        self._effect_lock_path = storage_path.with_name(
            storage_path.name + ".provider-effect-lock.sqlite3"
        )
        self._resolver = roster_resolver
        self._join_identity_resolver = join_identity_resolver
        self._timeout_seconds = float(timeout_seconds)
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            with closing(self._connect()) as connection:
                connection.execute("PRAGMA journal_mode=WAL")
                connection.execute(_SCHEMA)
            with closing(self._connect_effect_lock()) as connection:
                connection.execute("PRAGMA journal_mode=WAL")
                connection.execute(_EFFECT_LOCK_SCHEMA)
                connection.execute(
                    """
                    INSERT OR IGNORE INTO classroom_moderation_effect_lock
                        (singleton, generation)
                    VALUES (1, 0)
                    """
                )
        except (OSError, sqlite3.Error):
            raise ClassroomMediaPolicyError(
                "media policy initialization failed"
            ) from None

    def __repr__(self) -> str:
        return "SqliteClassroomMediaPolicyAuthority(path=<redacted>)"

    def provider_effect_scope(
        self,
        *,
        room_id: str,
        participant_id: str,
    ) -> "_SqliteProviderEffectScope":
        """Serialize provider mutations across processes sharing this policy path."""

        room = _identifier(room_id, "room id")
        participant = _identifier(participant_id, "participant id")
        return _SqliteProviderEffectScope(
            path=self._effect_lock_path,
            timeout_seconds=self._timeout_seconds,
            room_id=room,
            participant_id=participant,
        )

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
        try:
            canonical_participant = self._join_identity_resolver.participant_for_caller(
                room_id=room,
                trusted_caller_identity=caller,
            )
        except Exception:
            raise ClassroomMediaPolicyError(
                "canonical join identity lookup failed"
            ) from None
        canonical_participant = _identifier(
            canonical_participant,
            "canonical join participant id",
        )
        if canonical_participant != participant:
            raise ClassroomMediaPolicyError(
                "requested participant is not authorized for caller"
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

    def _connect_effect_lock(self) -> sqlite3.Connection:
        connection: sqlite3.Connection | None = None
        try:
            connection = sqlite3.connect(
                str(self._effect_lock_path),
                timeout=self._timeout_seconds,
                isolation_level=None,
                check_same_thread=False,
            )
            connection.execute("PRAGMA journal_mode=WAL")
            connection.execute("PRAGMA synchronous=FULL")
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
                "moderation effect serialization storage is unavailable"
            ) from None


class _SqliteProviderEffectScope:
    """Crash-released cross-process provider-effect mutex.

    SQLite permits one writer for a database at a time. The companion lock
    database is deliberately separate from media-policy storage: waiting for
    this mutex therefore never blocks the synchronous durable-policy writes
    that occur while another provider call is awaiting network I/O.
    """

    __slots__ = (
        "_path",
        "_timeout_seconds",
        "_room_id",
        "_participant_id",
        "_connection",
    )

    def __init__(
        self,
        *,
        path: Path,
        timeout_seconds: float,
        room_id: str,
        participant_id: str,
    ) -> None:
        self._path = path
        self._timeout_seconds = timeout_seconds
        self._room_id = room_id
        self._participant_id = participant_id
        self._connection: sqlite3.Connection | None = None

    async def __aenter__(self) -> "_SqliteProviderEffectScope":
        if self._connection is not None:
            raise ClassroomMediaPolicyError(
                "moderation effect serialization scope is already active"
            )
        acquisition = asyncio.create_task(
            asyncio.to_thread(
                _acquire_effect_lock,
                self._path,
                self._timeout_seconds,
            )
        )
        cancelled: asyncio.CancelledError | None = None
        while self._connection is None:
            try:
                self._connection = await asyncio.shield(acquisition)
            except asyncio.CancelledError as error:
                # The worker thread cannot be cancelled while sqlite is waiting.
                # Remember caller cancellation and keep the Future shielded until
                # its terminal result can be explicitly released.
                if cancelled is None:
                    cancelled = error
                if acquisition.done() and acquisition.cancelled():
                    raise cancelled from None
                continue
            except Exception:
                if cancelled is not None:
                    # Once cancellation was observed it remains caller authority,
                    # even if the eventually completed acquisition itself fails.
                    raise cancelled from None
                raise

        if cancelled is not None:
            connection = self._connection
            self._connection = None
            try:
                await _release_effect_lock_async(connection)
            except asyncio.CancelledError:
                # Cleanup itself is shielded and has already reached terminal
                # release; preserve the first cancellation as caller authority.
                pass
            raise cancelled from None
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        connection = self._connection
        self._connection = None
        if connection is None:
            return
        try:
            await _release_effect_lock_async(connection)
        except ClassroomMediaPolicyError:
            if exc_type is None:
                raise
            # Preserve the original provider/policy failure after best-effort
            # close has already released the SQLite file lock.
            return

    def __repr__(self) -> str:
        return (
            "_SqliteProviderEffectScope("
            "room=<redacted>, participant=<redacted>, storage=<redacted>)"
        )


def _acquire_effect_lock(
    path: Path,
    timeout_seconds: float,
) -> sqlite3.Connection:
    connection: sqlite3.Connection | None = None
    try:
        connection = sqlite3.connect(
            str(path),
            timeout=timeout_seconds,
            isolation_level=None,
            check_same_thread=False,
        )
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA synchronous=FULL")
        connection.execute(f"PRAGMA busy_timeout={int(timeout_seconds * 1000)}")
        connection.execute("BEGIN IMMEDIATE")
        cursor = connection.execute(
            """
            UPDATE classroom_moderation_effect_lock
            SET generation = generation + 1
            WHERE singleton = 1
            """
        )
        if cursor.rowcount != 1:
            raise ClassroomMediaPolicyError(
                "moderation effect serialization state is invalid"
            )
        return connection
    except ClassroomMediaPolicyError:
        if connection is not None:
            _close_effect_lock_connection(connection)
        raise
    except sqlite3.Error:
        if connection is not None:
            _close_effect_lock_connection(connection)
        raise ClassroomMediaPolicyError(
            "moderation effect serialization acquisition failed"
        ) from None


async def _release_effect_lock_async(connection: sqlite3.Connection) -> None:
    cleanup = asyncio.create_task(
        asyncio.to_thread(_release_effect_lock, connection)
    )
    try:
        await asyncio.shield(cleanup)
    except asyncio.CancelledError:
        # A cancellation during cleanup must not leak the cross-process lock.
        await cleanup
        raise


def _release_effect_lock(connection: sqlite3.Connection) -> None:
    failed = False
    try:
        connection.execute("ROLLBACK")
    except sqlite3.Error:
        failed = True
    try:
        connection.close()
    except sqlite3.Error:
        failed = True
    if failed:
        raise ClassroomMediaPolicyError(
            "moderation effect serialization release failed"
        )


def _close_effect_lock_connection(connection: sqlite3.Connection) -> None:
    try:
        connection.execute("ROLLBACK")
    except sqlite3.Error:
        pass
    try:
        connection.close()
    except sqlite3.Error:
        pass


class ClassroomMediaPolicyProviderAdmin:
    """Compose durable hard policy with the current provider assignment.

    Every provider mutation is serialized across processes that share the same
    durable policy path. Restrictive changes persist before their provider
    effect so reconnect stays fail-closed on provider failure. Permission
    restoration is deliberately the inverse: authorization happens first, the
    provider must accept the grant, and only then may a fresh join credential
    observe that durable grant before the serialized scope is released.
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

    async def _await_provider_terminal(
        self,
        *,
        room_id: str,
        command: ModerationCommand,
    ) -> asyncio.CancelledError | None:
        """Keep caller cancellation from abandoning an in-flight provider effect.

        The provider task is shielded from caller cancellation. If cancellation
        arrives, remember it and continue consuming later cancellation requests
        until the provider reaches a known terminal outcome. The caller can then
        re-propagate cancellation only after any required durable post-provider
        publication is complete and while the effect mutex is still held.
        """

        async def invoke_provider() -> None:
            # Keep even a malformed synchronous provider implementation inside
            # the task boundary so its failure is sanitized like async failures.
            await self._provider_admin.apply_moderation_command(
                room_id=room_id,
                command=command,
            )

        operation = asyncio.create_task(invoke_provider())
        cancelled: asyncio.CancelledError | None = None
        provider_failed = False
        while not operation.done():
            try:
                await asyncio.shield(operation)
            except asyncio.CancelledError as error:
                if operation.done() and operation.cancelled():
                    provider_failed = True
                    break
                if cancelled is None:
                    cancelled = error
            except Exception:
                provider_failed = True
                break

        if operation.cancelled():
            provider_failed = True
        elif not provider_failed:
            try:
                operation.result()
            except Exception:
                provider_failed = True

        if provider_failed:
            if cancelled is not None:
                raise cancelled from None
            raise ClassroomMediaPolicyError(
                "media policy provider operation failed"
            ) from None
        return cancelled

    async def apply_moderation_command(
        self,
        *,
        room_id: str,
        command: ModerationCommand,
    ) -> None:
        if type(command) is not ModerationCommand:
            raise ClassroomMediaPolicyError("moderation command is invalid")
        restore_after_provider = (
            command.action is ModerationAction.PUBLISH_PERMISSION
            and command.value is True
        )

        # The provider adapter performs a read/modify/write of the participant's
        # complete permission state. Distinct operation ids must therefore share
        # one cross-process effect order or two stale reads can each re-enable
        # the source revoked by the other. The companion SQLite writer lock is
        # held across durable-policy ordering and the provider await.
        async with self._authority.provider_effect_scope(
            room_id=room_id,
            participant_id=command.target_id,
        ):
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
                # Persist restrictive semantics *inside* the same serialized
                # order but before the provider effect. If provider mutation
                # fails, reconnect remains fail-closed.
                self._authority.record_authorized_command(
                    room_id=room_id,
                    command=command,
                )

            cancelled = await self._await_provider_terminal(
                room_id=room_id,
                command=command,
            )

            if restore_after_provider:
                # A failed provider grant must never become a reconnect grant.
                # Persist restoration only after provider success and before
                # releasing the serialized effect order, so a later revoke
                # cannot be overwritten by an earlier restore.
                self._authority.record_authorized_command(
                    room_id=room_id,
                    command=command,
                )

            if cancelled is not None:
                # The requested cancellation becomes observable only after the
                # provider outcome and any durable restore are both committed.
                raise cancelled


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
    "ClassroomJoinIdentityResolverPort",
    "ClassroomMediaPolicyError",
    "ClassroomMediaPolicyProviderAdmin",
    "ClassroomModerationProviderPort",
    "ClassroomRosterResolverPort",
    "MAX_POLICY_COMMANDS",
    "SqliteClassroomMediaPolicyAuthority",
]
