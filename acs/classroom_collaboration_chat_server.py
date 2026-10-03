from __future__ import annotations

"""Trusted provider-neutral server authority for classroom room chat.

This module is the server-side counterpart to the client-facing ChatTransportPort
in classroom_collaboration. It owns durable room sequencing, resend idempotence,
authoritative send time, server-enforced chat send locks, ordered reconnect
history, and idempotent moderation state.

It deliberately does not own classroom membership/roles. Every request is
authorized through an injected canonical server authority. It also contains no
provider SDK, credential, browser surface, file/object storage, analytics, or
chess-rule logic.
"""

from contextlib import closing
import hashlib
import json
import re
import sqlite3
from pathlib import Path
from typing import Callable, Protocol

from .classroom_collaboration import (
    MAX_SYNC_MESSAGES,
    ChatDraft,
    ChatModerationAction,
    ChatModerationCommand,
)
from .classroom_collaboration_storage import (
    ChatMessageMetadata,
    ChatMessageStateUpdate,
    MAX_CHAT_TIMESTAMP_UNIX_MS,
)
from .classroom_domain import MAX_WIRE_INTEGER


# The trusted server must accept the exact bounded page requested by the
# canonical client transport contract; a smaller independent cap makes the
# two sides impossible to compose without a lossy adapter.
MAX_SERVER_HISTORY_MESSAGES = MAX_SYNC_MESSAGES
# Canonical classroom rosters are bounded to 5,000 participants. A teacher's
# one-shot all-student moderation command must remain composable at that bound.
MAX_SERVER_MODERATION_COMMANDS = 5000
_SERVER_SCHEMA_VERSION = 2
_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")


class ClassroomChatServerError(RuntimeError):
    """Fail-closed server chat error safe to expose at a service boundary."""


class ClassroomChatAuthorizationPort(Protocol):
    """Canonical server-side classroom membership/role authorization."""

    def authorize_chat_send(
        self,
        *,
        room_id: str,
        caller_identity: str,
        sender_id: str,
    ) -> None:
        ...

    def authorize_chat_history(
        self,
        *,
        room_id: str,
        caller_identity: str,
    ) -> None:
        ...

    def authorize_chat_moderation(
        self,
        *,
        room_id: str,
        caller_identity: str,
        commands: tuple[ChatModerationCommand, ...],
    ) -> None:
        ...


def _identifier(value: object, label: str) -> str:
    if type(value) is not str or _ID_RE.fullmatch(value) is None:
        raise ClassroomChatServerError(f"{label} is invalid")
    return value


def _nonnegative_sequence(value: object) -> int | None:
    if value is None:
        return None
    if type(value) is not int or not 0 <= value <= MAX_WIRE_INTEGER:
        raise ClassroomChatServerError("history sequence is invalid")
    return value


def _history_limit(value: object) -> int:
    if (
        type(value) is not int
        or value <= 0
        or value > MAX_SERVER_HISTORY_MESSAGES
    ):
        raise ClassroomChatServerError("history limit is invalid")
    return value


def _clock_value(value: object) -> int:
    if (
        type(value) is not int
        or value < 0
        or value > MAX_CHAT_TIMESTAMP_UNIX_MS
    ):
        raise ClassroomChatServerError("server clock returned invalid UTC milliseconds")
    return value


def _stored_bool(value: object, label: str) -> bool:
    if type(value) is not int or value not in (0, 1):
        raise ClassroomChatServerError(f"stored {label} is invalid")
    return bool(value)


def _moderation_fingerprint(command: ChatModerationCommand) -> str:
    payload = {
        "operation_id": command.operation_id,
        "room_id": command.room_id,
        "actor_id": command.actor_id,
        "target_id": command.target_id,
        "action": command.action.value,
        "allowed": command.allowed,
        "message_id": command.message_id,
    }
    wire = json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(wire).hexdigest()


class ClassroomChatServerSQLiteStore:
    """Durable atomic server state for the provider-neutral room-chat service."""

    def __init__(self, database_path: str | Path) -> None:
        if not isinstance(database_path, (str, Path)):
            raise TypeError("database_path must be str or pathlib.Path")
        self._path = str(database_path)
        self._ensure_schema()

    def _connect(self) -> sqlite3.Connection:
        db = sqlite3.connect(self._path, timeout=30.0)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        return db

    def _ensure_schema(self) -> None:
        with closing(self._connect()) as db, db:
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS classroom_chat_server_meta(
                    key TEXT PRIMARY KEY,
                    value INTEGER NOT NULL
                );
                CREATE TABLE IF NOT EXISTS classroom_chat_server_messages(
                    message_id TEXT PRIMARY KEY,
                    room_id TEXT NOT NULL,
                    sender_id TEXT NOT NULL,
                    sequence_no INTEGER NOT NULL CHECK(sequence_no >= 0),
                    body TEXT NOT NULL,
                    retention TEXT NOT NULL,
                    hidden INTEGER NOT NULL DEFAULT 0 CHECK(hidden IN (0,1)),
                    sent_at_unix_ms INTEGER NOT NULL CHECK(sent_at_unix_ms >= 0),
                    UNIQUE(room_id, sequence_no)
                );
                CREATE INDEX IF NOT EXISTS idx_classroom_chat_server_messages_room
                    ON classroom_chat_server_messages(room_id, sequence_no);
                CREATE TABLE IF NOT EXISTS classroom_chat_server_permissions(
                    room_id TEXT NOT NULL,
                    target_id TEXT NOT NULL,
                    allowed INTEGER NOT NULL CHECK(allowed IN (0,1)),
                    PRIMARY KEY(room_id, target_id)
                );
                CREATE TABLE IF NOT EXISTS classroom_chat_server_moderation_ops(
                    room_id TEXT NOT NULL,
                    operation_id TEXT NOT NULL,
                    fingerprint TEXT NOT NULL,
                    PRIMARY KEY(room_id, operation_id)
                );
                CREATE TABLE IF NOT EXISTS classroom_chat_server_state_updates(
                    room_id TEXT NOT NULL,
                    revision INTEGER NOT NULL CHECK(revision >= 0),
                    message_id TEXT NOT NULL,
                    hidden INTEGER NOT NULL CHECK(hidden = 1),
                    PRIMARY KEY(room_id, revision)
                );
                CREATE INDEX IF NOT EXISTS idx_classroom_chat_server_state_updates_message
                    ON classroom_chat_server_state_updates(room_id, message_id);
                """
            )
            row = db.execute(
                "SELECT value FROM classroom_chat_server_meta WHERE key='schema_version'"
            ).fetchone()
            if row is None:
                db.execute(
                    "INSERT INTO classroom_chat_server_meta(key,value) VALUES('schema_version',?)",
                    (_SERVER_SCHEMA_VERSION,),
                )
            else:
                try:
                    version = int(row["value"])
                except (TypeError, ValueError, OverflowError):
                    raise ClassroomChatServerError(
                        "invalid classroom chat server schema version"
                    ) from None
                if version < 1:
                    raise ClassroomChatServerError(
                        "invalid classroom chat server schema version"
                    )
                if version > _SERVER_SCHEMA_VERSION:
                    raise ClassroomChatServerError(
                        "unsupported classroom chat server schema"
                    )
                if version < 2:
                    db.execute(
                        "UPDATE classroom_chat_server_meta SET value=? WHERE key='schema_version'",
                        (_SERVER_SCHEMA_VERSION,),
                    )

    @staticmethod
    def _row_message(row: sqlite3.Row) -> ChatMessageMetadata:
        try:
            return ChatMessageMetadata(
                message_id=row["message_id"],
                room_id=row["room_id"],
                sender_id=row["sender_id"],
                sequence_no=int(row["sequence_no"]),
                body=row["body"],
                retention=row["retention"],
                hidden=_stored_bool(row["hidden"], "message hidden flag"),
                sent_at_unix_ms=int(row["sent_at_unix_ms"]),
            )
        except ClassroomChatServerError:
            raise
        except (TypeError, ValueError, KeyError, IndexError, OverflowError):
            raise ClassroomChatServerError(
                "stored classroom chat message is invalid"
            ) from None

    @staticmethod
    def _same_draft(message: ChatMessageMetadata, draft: ChatDraft) -> bool:
        return (
            message.message_id == draft.message_id
            and message.room_id == draft.room_id
            and message.sender_id == draft.sender_id
            and message.body == draft.body
            and message.retention == draft.retention
        )

    def existing_for_draft(
        self,
        draft: ChatDraft,
    ) -> ChatMessageMetadata | None:
        if type(draft) is not ChatDraft:
            raise ClassroomChatServerError("chat draft type is invalid")
        try:
            with closing(self._connect()) as db:
                row = db.execute(
                    "SELECT * FROM classroom_chat_server_messages WHERE message_id=?",
                    (draft.message_id,),
                ).fetchone()
        except sqlite3.Error:
            raise ClassroomChatServerError(
                "classroom chat server message read failed"
            ) from None
        if row is None:
            return None
        message = self._row_message(row)
        if not self._same_draft(message, draft):
            raise ClassroomChatServerError(
                "message id was reused with different immutable content"
            )
        return message

    def append_authoritative(
        self,
        draft: ChatDraft,
        *,
        sent_at_unix_ms: int,
    ) -> ChatMessageMetadata:
        if type(draft) is not ChatDraft:
            raise ClassroomChatServerError("chat draft type is invalid")
        timestamp = _clock_value(sent_at_unix_ms)
        with closing(self._connect()) as db:
            try:
                db.execute("BEGIN IMMEDIATE")
                existing = db.execute(
                    "SELECT * FROM classroom_chat_server_messages WHERE message_id=?",
                    (draft.message_id,),
                ).fetchone()
                if existing is not None:
                    message = self._row_message(existing)
                    if not self._same_draft(message, draft):
                        raise ClassroomChatServerError(
                            "message id was reused with different immutable content"
                        )
                    db.commit()
                    return message

                permission = db.execute(
                    """
                    SELECT allowed FROM classroom_chat_server_permissions
                    WHERE room_id=? AND target_id=?
                    """,
                    (draft.room_id, draft.sender_id),
                ).fetchone()
                if permission is not None:
                    allowed = _stored_bool(
                        permission["allowed"],
                        "chat permission flag",
                    )
                    if not allowed:
                        raise ClassroomChatServerError(
                            "chat sending is disabled for participant"
                        )

                maximum_sequence = db.execute(
                    """
                    SELECT MAX(sequence_no)
                    FROM classroom_chat_server_messages
                    WHERE room_id=?
                    """,
                    (draft.room_id,),
                ).fetchone()[0]
                if maximum_sequence is None:
                    sequence = 0
                else:
                    if (
                        type(maximum_sequence) is not int
                        or not 0 <= maximum_sequence <= MAX_WIRE_INTEGER
                    ):
                        raise ClassroomChatServerError(
                            "stored message sequence is invalid"
                        )
                    if maximum_sequence == MAX_WIRE_INTEGER:
                        raise ClassroomChatServerError(
                            "server message sequence exhausted"
                        )
                    sequence = maximum_sequence + 1
                db.execute(
                    """
                    INSERT INTO classroom_chat_server_messages(
                        message_id, room_id, sender_id, sequence_no, body,
                        retention, hidden, sent_at_unix_ms
                    ) VALUES(?,?,?,?,?,?,0,?)
                    """,
                    (
                        draft.message_id,
                        draft.room_id,
                        draft.sender_id,
                        sequence,
                        draft.body,
                        draft.retention,
                        timestamp,
                    ),
                )
                row = db.execute(
                    "SELECT * FROM classroom_chat_server_messages WHERE message_id=?",
                    (draft.message_id,),
                ).fetchone()
                db.commit()
            except ClassroomChatServerError:
                db.rollback()
                raise
            except sqlite3.Error:
                db.rollback()
                raise ClassroomChatServerError(
                    "classroom chat server storage write failed"
                ) from None
        if row is None:
            raise ClassroomChatServerError("classroom chat server storage lost message")
        return self._row_message(row)

    def history_after(
        self,
        *,
        room_id: str,
        after_sequence: int | None,
        limit: int,
    ) -> tuple[ChatMessageMetadata, ...]:
        room = _identifier(room_id, "room id")
        after = _nonnegative_sequence(after_sequence)
        bounded = _history_limit(limit)
        sql = (
            "SELECT * FROM classroom_chat_server_messages "
            "WHERE room_id=? "
        )
        params: list[object] = [room]
        if after is not None:
            sql += "AND sequence_no>? "
            params.append(after)
        sql += "ORDER BY sequence_no ASC LIMIT ?"
        params.append(bounded)
        try:
            with closing(self._connect()) as db:
                rows = db.execute(sql, tuple(params)).fetchall()
        except sqlite3.Error:
            raise ClassroomChatServerError(
                "classroom chat server history read failed"
            ) from None
        return tuple(self._row_message(row) for row in rows)

    def state_updates_after(
        self,
        *,
        room_id: str,
        after_revision: int | None,
        limit: int,
    ) -> tuple[ChatMessageStateUpdate, ...]:
        room = _identifier(room_id, "room id")
        if after_revision is not None and (
            type(after_revision) is not int
            or not 0 <= after_revision <= MAX_WIRE_INTEGER
        ):
            raise ClassroomChatServerError("state revision is invalid")
        bounded = _history_limit(limit)
        sql = (
            "SELECT room_id, revision, message_id, hidden "
            "FROM classroom_chat_server_state_updates WHERE room_id=? "
        )
        params: list[object] = [room]
        if after_revision is not None:
            sql += "AND revision>? "
            params.append(after_revision)
        sql += "ORDER BY revision ASC LIMIT ?"
        params.append(bounded)
        try:
            with closing(self._connect()) as db:
                rows = db.execute(sql, tuple(params)).fetchall()
        except sqlite3.Error:
            raise ClassroomChatServerError(
                "classroom chat server state history read failed"
            ) from None
        decoded: list[ChatMessageStateUpdate] = []
        for row in rows:
            try:
                decoded.append(
                    ChatMessageStateUpdate(
                        room_id=row["room_id"],
                        message_id=row["message_id"],
                        revision=int(row["revision"]),
                        hidden=_stored_bool(
                            row["hidden"],
                            "moderation hidden flag",
                        ),
                    )
                )
            except ClassroomChatServerError:
                raise
            except (TypeError, ValueError, KeyError, IndexError, OverflowError):
                raise ClassroomChatServerError(
                    "stored classroom chat state update is invalid"
                ) from None
        return tuple(decoded)

    def apply_moderation(
        self,
        commands: tuple[ChatModerationCommand, ...],
    ) -> None:
        if (
            type(commands) is not tuple
            or not commands
            or len(commands) > MAX_SERVER_MODERATION_COMMANDS
            or any(type(command) is not ChatModerationCommand for command in commands)
        ):
            raise ClassroomChatServerError("moderation command batch is invalid")
        room = commands[0].room_id
        if any(command.room_id != room for command in commands):
            raise ClassroomChatServerError("moderation batch crossed room boundary")

        with closing(self._connect()) as db:
            try:
                db.execute("BEGIN IMMEDIATE")
                for command in commands:
                    fingerprint = _moderation_fingerprint(command)
                    previous = db.execute(
                        """
                        SELECT fingerprint FROM classroom_chat_server_moderation_ops
                        WHERE room_id=? AND operation_id=?
                        """,
                        (room, command.operation_id),
                    ).fetchone()
                    if previous is not None:
                        if previous["fingerprint"] != fingerprint:
                            raise ClassroomChatServerError(
                                "moderation operation id was reused with different semantics"
                            )
                        continue

                    if command.action is ChatModerationAction.SET_SEND_PERMISSION:
                        db.execute(
                            """
                            INSERT INTO classroom_chat_server_permissions(
                                room_id, target_id, allowed
                            ) VALUES(?,?,?)
                            ON CONFLICT(room_id,target_id)
                            DO UPDATE SET allowed=excluded.allowed
                            """,
                            (room, command.target_id, int(bool(command.allowed))),
                        )
                    elif command.action is ChatModerationAction.HIDE_MESSAGE:
                        target = db.execute(
                            """
                            SELECT hidden FROM classroom_chat_server_messages
                            WHERE room_id=? AND message_id=?
                            """,
                            (room, command.message_id),
                        ).fetchone()
                        if target is None:
                            raise ClassroomChatServerError(
                                "message to hide does not exist in room"
                            )
                        target_hidden = _stored_bool(
                            target["hidden"],
                            "message hidden flag",
                        )
                        if not target_hidden:
                            db.execute(
                                """
                                UPDATE classroom_chat_server_messages
                                SET hidden=1
                                WHERE room_id=? AND message_id=?
                                """,
                                (room, command.message_id),
                            )
                            maximum_revision = db.execute(
                                """
                                SELECT MAX(revision)
                                FROM classroom_chat_server_state_updates
                                WHERE room_id=?
                                """,
                                (room,),
                            ).fetchone()[0]
                            if maximum_revision is None:
                                revision = 0
                            else:
                                if (
                                    type(maximum_revision) is not int
                                    or not 0 <= maximum_revision <= MAX_WIRE_INTEGER
                                ):
                                    raise ClassroomChatServerError(
                                        "stored moderation revision is invalid"
                                    )
                                if maximum_revision == MAX_WIRE_INTEGER:
                                    raise ClassroomChatServerError(
                                        "server moderation revision exhausted"
                                    )
                                revision = maximum_revision + 1
                            db.execute(
                                """
                                INSERT INTO classroom_chat_server_state_updates(
                                    room_id, revision, message_id, hidden
                                ) VALUES(?,?,?,1)
                                """,
                                (room, revision, command.message_id),
                            )
                    else:
                        raise ClassroomChatServerError(
                            "unsupported chat moderation action"
                        )

                    db.execute(
                        """
                        INSERT INTO classroom_chat_server_moderation_ops(
                            room_id, operation_id, fingerprint
                        ) VALUES(?,?,?)
                        """,
                        (room, command.operation_id, fingerprint),
                    )
                db.commit()
            except ClassroomChatServerError:
                db.rollback()
                raise
            except sqlite3.Error:
                db.rollback()
                raise ClassroomChatServerError(
                    "classroom chat server moderation write failed"
                ) from None

    def integrity_check(self) -> None:
        try:
            with closing(self._connect()) as db:
                row = db.execute("PRAGMA integrity_check").fetchone()
                if row is None or row[0] != "ok":
                    raise ClassroomChatServerError(
                        "classroom chat server database failed integrity check"
                    )
        except sqlite3.Error:
            raise ClassroomChatServerError(
                "classroom chat server integrity check failed"
            ) from None


class ClassroomChatServerService:
    """Authorize and serve canonical ChatTransportPort semantics server-side."""

    def __init__(
        self,
        *,
        store: ClassroomChatServerSQLiteStore,
        authorization: ClassroomChatAuthorizationPort,
        clock_unix_ms: Callable[[], int],
    ) -> None:
        if not isinstance(store, ClassroomChatServerSQLiteStore):
            raise TypeError("store must be ClassroomChatServerSQLiteStore")
        if authorization is None:
            raise TypeError("authorization port is required")
        if not callable(clock_unix_ms):
            raise TypeError("clock_unix_ms must be callable")
        self._store = store
        self._authorization = authorization
        self._clock_unix_ms = clock_unix_ms

    def send_message(
        self,
        *,
        trusted_caller_identity: str,
        draft: ChatDraft,
    ) -> ChatMessageMetadata:
        caller = _identifier(trusted_caller_identity, "trusted caller identity")
        if type(draft) is not ChatDraft:
            raise ClassroomChatServerError("chat draft type is invalid")
        if draft.sender_id != caller:
            raise ClassroomChatServerError(
                "chat sender does not match trusted caller identity"
            )
        try:
            self._authorization.authorize_chat_send(
                room_id=draft.room_id,
                caller_identity=caller,
                sender_id=draft.sender_id,
            )
        except Exception:
            raise ClassroomChatServerError("chat send is not authorized") from None
        existing = self._store.existing_for_draft(draft)
        if existing is not None:
            return existing
        try:
            timestamp = _clock_value(self._clock_unix_ms())
        except ClassroomChatServerError:
            raise
        except Exception:
            raise ClassroomChatServerError("server clock failed") from None
        return self._store.append_authoritative(
            draft,
            sent_at_unix_ms=timestamp,
        )

    def history_after(
        self,
        *,
        trusted_caller_identity: str,
        room_id: str,
        after_sequence: int | None,
        limit: int,
    ) -> tuple[ChatMessageMetadata, ...]:
        caller = _identifier(trusted_caller_identity, "trusted caller identity")
        room = _identifier(room_id, "room id")
        after = _nonnegative_sequence(after_sequence)
        bounded = _history_limit(limit)
        try:
            self._authorization.authorize_chat_history(
                room_id=room,
                caller_identity=caller,
            )
        except Exception:
            raise ClassroomChatServerError("chat history is not authorized") from None
        return self._store.history_after(
            room_id=room,
            after_sequence=after,
            limit=bounded,
        )

    def state_updates_after(
        self,
        *,
        trusted_caller_identity: str,
        room_id: str,
        after_revision: int | None,
        limit: int,
    ) -> tuple[ChatMessageStateUpdate, ...]:
        caller = _identifier(trusted_caller_identity, "trusted caller identity")
        room = _identifier(room_id, "room id")
        if after_revision is not None and (
            type(after_revision) is not int
            or not 0 <= after_revision <= MAX_WIRE_INTEGER
        ):
            raise ClassroomChatServerError("state revision is invalid")
        bounded = _history_limit(limit)
        try:
            self._authorization.authorize_chat_history(
                room_id=room,
                caller_identity=caller,
            )
        except Exception:
            raise ClassroomChatServerError(
                "chat state history is not authorized"
            ) from None
        return self._store.state_updates_after(
            room_id=room,
            after_revision=after_revision,
            limit=bounded,
        )

    def apply_moderation(
        self,
        *,
        trusted_caller_identity: str,
        commands: tuple[ChatModerationCommand, ...],
    ) -> None:
        caller = _identifier(trusted_caller_identity, "trusted caller identity")
        if (
            type(commands) is not tuple
            or not commands
            or len(commands) > MAX_SERVER_MODERATION_COMMANDS
            or any(type(command) is not ChatModerationCommand for command in commands)
        ):
            raise ClassroomChatServerError("moderation command batch is invalid")
        room = commands[0].room_id
        if any(command.room_id != room for command in commands):
            raise ClassroomChatServerError("moderation batch crossed room boundary")
        if any(command.actor_id != caller for command in commands):
            raise ClassroomChatServerError(
                "moderation actor does not match trusted caller identity"
            )
        try:
            self._authorization.authorize_chat_moderation(
                room_id=room,
                caller_identity=caller,
                commands=commands,
            )
        except Exception:
            raise ClassroomChatServerError(
                "chat moderation is not authorized"
            ) from None
        self._store.apply_moderation(commands)


__all__ = [
    "ClassroomChatAuthorizationPort",
    "ClassroomChatServerError",
    "ClassroomChatServerSQLiteStore",
    "ClassroomChatServerService",
    "MAX_SERVER_HISTORY_MESSAGES",
    "MAX_SERVER_MODERATION_COMMANDS",
]
