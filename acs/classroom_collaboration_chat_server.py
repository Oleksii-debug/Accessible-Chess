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
_SERVER_SCHEMA_VERSION = 4
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


def _stored_nonnegative_integer(
    value: object,
    label: str,
    *,
    maximum: int,
) -> int:
    if (
        type(value) is not int
        or not 0 <= value <= maximum
    ):
        raise ClassroomChatServerError(f"stored {label} is invalid")
    return value


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
        path = str(database_path)
        if path in {"", ":memory:"}:
            raise ClassroomChatServerError(
                "durable classroom chat server database path is required"
            )
        self._path = path
        self._ensure_schema()

    def _connect(self) -> sqlite3.Connection:
        db: sqlite3.Connection | None = None
        try:
            db = sqlite3.connect(self._path, timeout=30.0)
            db.row_factory = sqlite3.Row
            db.execute("PRAGMA foreign_keys=ON")
            # Retention redaction must not merely unlink the logical TEXT
            # value while leaving recoverable payload bytes in SQLite free
            # space. Make secure deletion an invariant of every authority
            # connection rather than relying on build-specific defaults.
            db.execute("PRAGMA secure_delete=ON")
            secure_delete = db.execute("PRAGMA secure_delete").fetchone()
            if (
                secure_delete is None
                or type(secure_delete[0]) is not int
                or secure_delete[0] != 1
            ):
                raise ClassroomChatServerError(
                    "classroom chat server secure deletion is unavailable"
                )
            return db
        except ClassroomChatServerError:
            if db is not None:
                db.close()
            raise
        except sqlite3.Error:
            if db is not None:
                db.close()
            raise ClassroomChatServerError(
                "classroom chat server database open failed"
            ) from None

    @staticmethod
    def _validate_no_authority_triggers(db: sqlite3.Connection) -> None:
        trigger_row = db.execute(
            """
            SELECT 1 FROM sqlite_master
            WHERE type='trigger'
              AND (
                name LIKE 'classroom_chat_server_%'
                OR tbl_name LIKE 'classroom_chat_server_%'
              )
            LIMIT 1
            """
        ).fetchone()
        if trigger_row is not None:
            raise ClassroomChatServerError(
                "classroom chat server schema contains unsupported trigger"
            )

    @staticmethod
    def _validate_room_hidden_state(
        db: sqlite3.Connection,
        room_id: str,
    ) -> None:
        invalid_message_flag = db.execute(
            """
            SELECT 1
            FROM classroom_chat_server_messages
            WHERE room_id=?
              AND (
                typeof(hidden) != 'integer'
                OR hidden NOT IN (0,1)
              )
            LIMIT 1
            """,
            (room_id,),
        ).fetchone()
        if invalid_message_flag is not None:
            raise ClassroomChatServerError(
                "stored message hidden flag is invalid"
            )

        message_columns = {
            row["name"]
            for row in db.execute(
                "PRAGMA table_info(classroom_chat_server_messages)"
            )
        }
        if "redacted" in message_columns:
            invalid_redacted_flag = db.execute(
                """
                SELECT 1
                FROM classroom_chat_server_messages
                WHERE room_id=?
                  AND (
                    typeof(redacted) != 'integer'
                    OR redacted NOT IN (0,1)
                    OR (redacted=1 AND body != '')
                  )
                LIMIT 1
                """,
                (room_id,),
            ).fetchone()
            if invalid_redacted_flag is not None:
                raise ClassroomChatServerError(
                    "stored message redaction state is invalid"
                )

        invalid_revision = db.execute(
            """
            SELECT 1
            FROM classroom_chat_server_state_updates
            WHERE room_id=?
              AND (
                typeof(revision) != 'integer'
                OR revision < 0
                OR revision > ?
              )
            LIMIT 1
            """,
            (room_id, MAX_WIRE_INTEGER),
        ).fetchone()
        if invalid_revision is not None:
            raise ClassroomChatServerError(
                "stored moderation revision is invalid"
            )

        state_columns = {
            row["name"]
            for row in db.execute(
                "PRAGMA table_info(classroom_chat_server_state_updates)"
            )
        }
        if "redacted" in state_columns:
            invalid_hidden_flag = db.execute(
                """
                SELECT 1
                FROM classroom_chat_server_state_updates
                WHERE room_id=?
                  AND (
                    typeof(hidden) != 'integer'
                    OR hidden NOT IN (0,1)
                  )
                LIMIT 1
                """,
                (room_id,),
            ).fetchone()
            if invalid_hidden_flag is not None:
                raise ClassroomChatServerError(
                    "stored moderation hidden flag is invalid"
                )
            invalid_redacted_flag = db.execute(
                """
                SELECT 1
                FROM classroom_chat_server_state_updates
                WHERE room_id=?
                  AND (
                    typeof(redacted) != 'integer'
                    OR redacted NOT IN (0,1)
                    OR (hidden=0 AND redacted=0)
                  )
                LIMIT 1
                """,
                (room_id,),
            ).fetchone()
            if invalid_redacted_flag is not None:
                raise ClassroomChatServerError(
                    "stored chat redaction state is invalid"
                )
        else:
            invalid_state_flag = db.execute(
                """
                SELECT 1
                FROM classroom_chat_server_state_updates
                WHERE room_id=?
                  AND (
                    typeof(hidden) != 'integer'
                    OR hidden != 1
                  )
                LIMIT 1
                """,
                (room_id,),
            ).fetchone()
            if invalid_state_flag is not None:
                raise ClassroomChatServerError(
                    "stored moderation hidden flag is invalid"
                )

        orphan_state = db.execute(
            """
            SELECT 1
            FROM classroom_chat_server_state_updates AS s
            LEFT JOIN classroom_chat_server_messages AS m
              ON m.room_id=s.room_id AND m.message_id=s.message_id
            WHERE s.room_id=? AND m.message_id IS NULL
            LIMIT 1
            """,
            (room_id,),
        ).fetchone()
        if orphan_state is not None:
            raise ClassroomChatServerError(
                "stored moderation state is inconsistent"
            )

        if "redacted" in state_columns and "redacted" in message_columns:
            hidden_mismatch = db.execute(
                """
                SELECT
                    m.hidden AS message_hidden,
                    COALESCE(MAX(s.hidden), 0) AS state_hidden
                FROM classroom_chat_server_messages AS m
                LEFT JOIN classroom_chat_server_state_updates AS s
                  ON s.room_id=m.room_id AND s.message_id=m.message_id
                WHERE m.room_id=?
                GROUP BY m.message_id
                HAVING m.hidden != COALESCE(MAX(s.hidden), 0)
                LIMIT 1
                """,
                (room_id,),
            ).fetchone()
            if hidden_mismatch is not None:
                if _stored_bool(
                    hidden_mismatch["message_hidden"],
                    "message hidden flag",
                ):
                    raise ClassroomChatServerError(
                        "stored hidden message state is inconsistent"
                    )
                raise ClassroomChatServerError(
                    "stored visible message state is inconsistent"
                )
            redacted_mismatch = db.execute(
                """
                SELECT 1
                FROM classroom_chat_server_messages AS m
                LEFT JOIN classroom_chat_server_state_updates AS s
                  ON s.room_id=m.room_id AND s.message_id=m.message_id
                WHERE m.room_id=?
                GROUP BY m.message_id
                HAVING m.redacted != COALESCE(MAX(s.redacted), 0)
                LIMIT 1
                """,
                (room_id,),
            ).fetchone()
            if redacted_mismatch is not None:
                raise ClassroomChatServerError(
                    "stored redacted message state is inconsistent"
                )
            duplicate_transition = db.execute(
                """
                SELECT 1
                FROM classroom_chat_server_state_updates
                WHERE room_id=?
                GROUP BY message_id
                HAVING
                    SUM(CASE WHEN hidden=1 THEN 1 ELSE 0 END) > 1
                    OR SUM(CASE WHEN redacted=1 THEN 1 ELSE 0 END) > 1
                LIMIT 1
                """,
                (room_id,),
            ).fetchone()
            if duplicate_transition is not None:
                raise ClassroomChatServerError(
                    "stored chat message state transition is duplicated"
                )
        else:
            hidden_mismatch = db.execute(
                """
                SELECT 1
                FROM classroom_chat_server_messages AS m
                LEFT JOIN classroom_chat_server_state_updates AS s
                  ON s.room_id=m.room_id AND s.message_id=m.message_id
                WHERE m.room_id=? AND m.hidden=1
                GROUP BY m.message_id
                HAVING COUNT(s.message_id) != 1
                LIMIT 1
                """,
                (room_id,),
            ).fetchone()
            if hidden_mismatch is not None:
                raise ClassroomChatServerError(
                    "stored hidden message state is inconsistent"
                )

            visible_mismatch = db.execute(
                """
                SELECT 1
                FROM classroom_chat_server_messages AS m
                LEFT JOIN classroom_chat_server_state_updates AS s
                  ON s.room_id=m.room_id AND s.message_id=m.message_id
                WHERE m.room_id=? AND m.hidden=0
                GROUP BY m.message_id
                HAVING COUNT(s.message_id) != 0
                LIMIT 1
                """,
                (room_id,),
            ).fetchone()
            if visible_mismatch is not None:
                raise ClassroomChatServerError(
                    "stored visible message state is inconsistent"
                )

    @staticmethod
    def _validate_schema_shape(
        db: sqlite3.Connection,
        *,
        version: int,
    ) -> None:
        expected: dict[str, tuple[tuple[object, ...], ...]] = {
            "classroom_chat_server_meta": (
                ("key", "TEXT", 0, None, 1),
                ("value", "INTEGER", 1, None, 0),
            ),
            "classroom_chat_server_messages": (
                ("message_id", "TEXT", 0, None, 1),
                ("room_id", "TEXT", 1, None, 0),
                ("sender_id", "TEXT", 1, None, 0),
                ("sequence_no", "INTEGER", 1, None, 0),
                ("body", "TEXT", 1, None, 0),
                ("retention", "TEXT", 1, None, 0),
                ("hidden", "INTEGER", 1, "0", 0),
                ("sent_at_unix_ms", "INTEGER", 1, None, 0),
            ) + (
                (("redacted", "INTEGER", 1, "0", 0),)
                if version >= 4
                else ()
            ),
            "classroom_chat_server_permissions": (
                ("room_id", "TEXT", 1, None, 1),
                ("target_id", "TEXT", 1, None, 2),
                ("allowed", "INTEGER", 1, None, 0),
            ),
            "classroom_chat_server_moderation_ops": (
                ("room_id", "TEXT", 1, None, 1),
                ("operation_id", "TEXT", 1, None, 2),
                ("fingerprint", "TEXT", 1, None, 0),
            ),
        }
        if version >= 2:
            expected["classroom_chat_server_state_updates"] = (
                ("room_id", "TEXT", 1, None, 1),
                ("revision", "INTEGER", 1, None, 2),
                ("message_id", "TEXT", 1, None, 0),
                ("hidden", "INTEGER", 1, None, 0),
            ) + (
                (("redacted", "INTEGER", 1, "0", 0),)
                if version >= 4
                else ()
            )

        for table, wanted in expected.items():
            rows = db.execute(f"PRAGMA table_info({table})").fetchall()
            actual = tuple(
                (
                    row["name"],
                    str(row["type"]).upper(),
                    int(row["notnull"]),
                    row["dflt_value"],
                    int(row["pk"]),
                )
                for row in rows
            )
            if actual != wanted:
                raise ClassroomChatServerError(
                    "classroom chat server schema shape is incompatible"
                )

        message_sql_row = db.execute(
            """
            SELECT sql FROM sqlite_master
            WHERE type='table'
              AND name='classroom_chat_server_messages'
            """
        ).fetchone()
        if (
            message_sql_row is None
            or type(message_sql_row["sql"]) is not str
            or "unique(room_id,sequence_no)" not in "".join(
                message_sql_row["sql"].lower().split()
            )
        ):
            raise ClassroomChatServerError(
                "classroom chat server message ordering constraint is missing"
            )

    @staticmethod
    def _reconcile_hidden_state_migration(
        db: sqlite3.Connection,
    ) -> None:
        expected_sequence: dict[str, int] = {}
        message_keys: set[tuple[str, str]] = set()
        hidden_message_keys: set[tuple[str, str]] = set()
        hidden_messages: list[ChatMessageMetadata] = []
        for stored in db.execute(
            """
            SELECT * FROM classroom_chat_server_messages
            ORDER BY room_id, sequence_no
            """
        ):
            message = ClassroomChatServerSQLiteStore._row_message(stored)
            expected = expected_sequence.get(message.room_id, 0)
            if message.sequence_no != expected:
                raise ClassroomChatServerError(
                    "legacy server message sequence is not contiguous"
                )
            expected_sequence[message.room_id] = expected + 1
            key = (message.room_id, message.message_id)
            message_keys.add(key)
            if message.hidden:
                hidden_message_keys.add(key)
                hidden_messages.append(message)

        next_revision: dict[str, int] = {}
        state_message_keys: set[tuple[str, str]] = set()
        for stored in db.execute(
            """
            SELECT room_id, revision, message_id, hidden
            FROM classroom_chat_server_state_updates
            ORDER BY room_id, revision
            """
        ):
            room = _identifier(
                stored["room_id"],
                "stored moderation state room id",
            )
            message_id = _identifier(
                stored["message_id"],
                "stored moderation state message id",
            )
            revision = _stored_nonnegative_integer(
                stored["revision"],
                "moderation revision",
                maximum=MAX_WIRE_INTEGER,
            )
            expected = next_revision.get(room, 0)
            if revision != expected:
                raise ClassroomChatServerError(
                    "legacy moderation revision is not contiguous"
                )
            if not _stored_bool(
                stored["hidden"],
                "moderation hidden flag",
            ):
                raise ClassroomChatServerError(
                    "legacy moderation state is not hidden"
                )
            key = (room, message_id)
            if key not in message_keys:
                raise ClassroomChatServerError(
                    "legacy moderation state references unknown message"
                )
            if key not in hidden_message_keys:
                raise ClassroomChatServerError(
                    "legacy moderation state references visible message"
                )
            if key in state_message_keys:
                raise ClassroomChatServerError(
                    "legacy moderation state duplicates hidden message"
                )
            state_message_keys.add(key)
            next_revision[room] = revision + 1

        for message in hidden_messages:
            key = (message.room_id, message.message_id)
            if key in state_message_keys:
                continue
            revision = next_revision.get(message.room_id, 0)
            if revision > MAX_WIRE_INTEGER:
                raise ClassroomChatServerError(
                    "legacy moderation revision is exhausted"
                )
            db.execute(
                """
                INSERT INTO classroom_chat_server_state_updates(
                    room_id, revision, message_id, hidden
                ) VALUES(?,?,?,1)
                """,
                (
                    message.room_id,
                    revision,
                    message.message_id,
                ),
            )
            state_message_keys.add(key)
            next_revision[message.room_id] = revision + 1

    def _ensure_schema(self) -> None:
        with closing(self._connect()) as db, db:
            try:
                # Keep schema DDL, migration repair, and schema_version in one
                # atomic unit. sqlite3.executescript() would implicitly commit
                # before running its script and can leave a half-migrated DB.
                db.execute("BEGIN IMMEDIATE")
                # Persistent triggers on any canonical authority table can
                # mutate or erase otherwise validated writes after this code has
                # computed sequence/idempotency state. They are never part of the
                # supported schema, so fail closed before migration or repair.
                self._validate_no_authority_triggers(db)

                namespace_rows = db.execute(
                    """
                    SELECT name FROM sqlite_master
                    WHERE type IN ('table','index')
                      AND name LIKE 'classroom_chat_server_%'
                    """
                ).fetchall()
                namespace_objects = {row["name"] for row in namespace_rows}
                meta_exists = (
                    "classroom_chat_server_meta" in namespace_objects
                )
                version: int | None = None
                if meta_exists:
                    row = db.execute(
                        """
                        SELECT value FROM classroom_chat_server_meta
                        WHERE key='schema_version'
                        """
                    ).fetchone()
                    if (
                        row is None
                        or type(row["value"]) is not int
                        or row["value"] < 1
                    ):
                        raise ClassroomChatServerError(
                            "invalid classroom chat server schema version"
                        )
                    version = row["value"]
                    if version > _SERVER_SCHEMA_VERSION:
                        raise ClassroomChatServerError(
                            "unsupported classroom chat server schema"
                        )
                    required_tables = {
                        "classroom_chat_server_meta",
                        "classroom_chat_server_messages",
                        "classroom_chat_server_permissions",
                        "classroom_chat_server_moderation_ops",
                    }
                    if version >= 2:
                        required_tables.add(
                            "classroom_chat_server_state_updates"
                        )
                    if not required_tables.issubset(namespace_objects):
                        raise ClassroomChatServerError(
                            "classroom chat server schema is incomplete"
                        )
                    self._validate_schema_shape(
                        db,
                        version=version,
                    )
                    if (
                        version == 1
                        and "classroom_chat_server_state_updates"
                        in namespace_objects
                    ):
                        self._validate_schema_shape(
                            db,
                            version=2,
                        )
                        if db.execute(
                            """
                            SELECT 1
                            FROM classroom_chat_server_state_updates
                            LIMIT 1
                            """
                        ).fetchone() is not None:
                            raise ClassroomChatServerError(
                                "version one chat state migration is partial"
                            )
                elif namespace_objects:
                    raise ClassroomChatServerError(
                        "classroom chat server schema metadata is missing"
                    )

                schema_statements = (
                    """
                    CREATE TABLE IF NOT EXISTS classroom_chat_server_meta(
                        key TEXT PRIMARY KEY,
                        value INTEGER NOT NULL
                    )
                    """,
                    """
                    CREATE TABLE IF NOT EXISTS classroom_chat_server_messages(
                        message_id TEXT PRIMARY KEY,
                        room_id TEXT NOT NULL,
                        sender_id TEXT NOT NULL,
                        sequence_no INTEGER NOT NULL CHECK(sequence_no >= 0),
                        body TEXT NOT NULL,
                        retention TEXT NOT NULL,
                        hidden INTEGER NOT NULL DEFAULT 0 CHECK(hidden IN (0,1)),
                        sent_at_unix_ms INTEGER NOT NULL CHECK(sent_at_unix_ms >= 0),
                        redacted INTEGER NOT NULL DEFAULT 0 CHECK(redacted IN (0,1)),
                        UNIQUE(room_id, sequence_no)
                    )
                    """,
                    """
                    CREATE INDEX IF NOT EXISTS idx_classroom_chat_server_messages_room
                    ON classroom_chat_server_messages(room_id, sequence_no)
                    """,
                    """
                    CREATE TABLE IF NOT EXISTS classroom_chat_server_permissions(
                        room_id TEXT NOT NULL,
                        target_id TEXT NOT NULL,
                        allowed INTEGER NOT NULL CHECK(allowed IN (0,1)),
                        PRIMARY KEY(room_id, target_id)
                    )
                    """,
                    """
                    CREATE TABLE IF NOT EXISTS classroom_chat_server_moderation_ops(
                        room_id TEXT NOT NULL,
                        operation_id TEXT NOT NULL,
                        fingerprint TEXT NOT NULL,
                        PRIMARY KEY(room_id, operation_id)
                    )
                    """,
                    """
                    CREATE TABLE IF NOT EXISTS classroom_chat_server_state_updates(
                        room_id TEXT NOT NULL,
                        revision INTEGER NOT NULL CHECK(revision >= 0),
                        message_id TEXT NOT NULL,
                        hidden INTEGER NOT NULL CHECK(hidden IN (0,1)),
                        redacted INTEGER NOT NULL DEFAULT 0 CHECK(redacted IN (0,1)),
                        CHECK(hidden = 1 OR redacted = 1),
                        PRIMARY KEY(room_id, revision)
                    )
                    """,
                    """
                    CREATE INDEX IF NOT EXISTS idx_classroom_chat_server_state_updates_message
                    ON classroom_chat_server_state_updates(room_id, message_id)
                    """,
                )
                for statement in schema_statements:
                    db.execute(statement)
                if version is None:
                    db.execute(
                        """
                        INSERT INTO classroom_chat_server_meta(key,value)
                        VALUES('schema_version',?)
                        """,
                        (_SERVER_SCHEMA_VERSION,),
                    )
                elif version < _SERVER_SCHEMA_VERSION:
                    self._reconcile_hidden_state_migration(db)
                    message_columns = {
                        row["name"]
                        for row in db.execute(
                            "PRAGMA table_info(classroom_chat_server_messages)"
                        )
                    }
                    if "redacted" not in message_columns:
                        db.execute(
                            "ALTER TABLE classroom_chat_server_messages "
                            "ADD COLUMN redacted INTEGER NOT NULL DEFAULT 0 "
                            "CHECK(redacted IN (0,1))"
                        )
                    state_columns = {
                        row["name"]
                        for row in db.execute(
                            "PRAGMA table_info(classroom_chat_server_state_updates)"
                        )
                    }
                    if "redacted" not in state_columns:
                        # v2/v3 constrained hidden=1 at table level. Adding a
                        # redacted column in place would still reject a
                        # redaction-only state transition, so rebuild the state
                        # authority atomically with the v4 monotonic-state shape.
                        db.execute(
                            "DROP INDEX IF EXISTS "
                            "idx_classroom_chat_server_state_updates_message"
                        )
                        db.execute(
                            "ALTER TABLE classroom_chat_server_state_updates "
                            "RENAME TO classroom_chat_server_state_updates_v3"
                        )
                        db.execute(
                            """
                            CREATE TABLE classroom_chat_server_state_updates(
                                room_id TEXT NOT NULL,
                                revision INTEGER NOT NULL CHECK(revision >= 0),
                                message_id TEXT NOT NULL,
                                hidden INTEGER NOT NULL CHECK(hidden IN (0,1)),
                                redacted INTEGER NOT NULL DEFAULT 0
                                    CHECK(redacted IN (0,1)),
                                CHECK(hidden = 1 OR redacted = 1),
                                PRIMARY KEY(room_id, revision)
                            )
                            """
                        )
                        db.execute(
                            """
                            INSERT INTO classroom_chat_server_state_updates(
                                room_id, revision, message_id, hidden, redacted
                            )
                            SELECT room_id, revision, message_id, hidden, 0
                            FROM classroom_chat_server_state_updates_v3
                            """
                        )
                        db.execute(
                            "DROP TABLE classroom_chat_server_state_updates_v3"
                        )
                        db.execute(
                            """
                            CREATE INDEX
                            idx_classroom_chat_server_state_updates_message
                            ON classroom_chat_server_state_updates(
                                room_id, message_id
                            )
                            """
                        )
                    db.execute(
                        """
                        UPDATE classroom_chat_server_meta
                        SET value=? WHERE key='schema_version'
                        """,
                        (_SERVER_SCHEMA_VERSION,),
                    )
                self._validate_schema_shape(
                    db,
                    version=_SERVER_SCHEMA_VERSION,
                )
            except ClassroomChatServerError:
                raise
            except sqlite3.Error:
                raise ClassroomChatServerError(
                    "classroom chat server schema initialization failed"
                ) from None

    @staticmethod
    def _row_message(row: sqlite3.Row) -> ChatMessageMetadata:
        try:
            return ChatMessageMetadata(
                message_id=row["message_id"],
                room_id=row["room_id"],
                sender_id=row["sender_id"],
                sequence_no=_stored_nonnegative_integer(
                    row["sequence_no"],
                    "message sequence",
                    maximum=MAX_WIRE_INTEGER,
                ),
                body=row["body"],
                retention=row["retention"],
                hidden=_stored_bool(row["hidden"], "message hidden flag"),
                sent_at_unix_ms=_stored_nonnegative_integer(
                    row["sent_at_unix_ms"],
                    "message timestamp",
                    maximum=MAX_CHAT_TIMESTAMP_UNIX_MS,
                ),
                redacted=(
                    _stored_bool(row["redacted"], "message redacted flag")
                    if "redacted" in row.keys()
                    else False
                ),
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
                self._validate_room_hidden_state(db, draft.room_id)
                row = db.execute(
                    "SELECT * FROM classroom_chat_server_messages WHERE message_id=?",
                    (draft.message_id,),
                ).fetchone()
        except ClassroomChatServerError:
            raise
        except sqlite3.Error:
            raise ClassroomChatServerError(
                "classroom chat server message read failed"
            ) from None
        if row is None:
            return None
        message = self._row_message(row)
        if message.redacted:
            raise ClassroomChatServerError(
                "message content was already redacted; resend identity cannot be verified"
            )
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
                self._validate_no_authority_triggers(db)
                self._validate_room_hidden_state(db, draft.room_id)
                existing = db.execute(
                    "SELECT * FROM classroom_chat_server_messages WHERE message_id=?",
                    (draft.message_id,),
                ).fetchone()
                if existing is not None:
                    message = self._row_message(existing)
                    if message.redacted:
                        raise ClassroomChatServerError(
                            "message content was already redacted; resend identity cannot be verified"
                        )
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

                sequence_stats = db.execute(
                    """
                    SELECT COUNT(*) AS item_count, MAX(sequence_no) AS maximum_sequence
                    FROM classroom_chat_server_messages
                    WHERE room_id=?
                    """,
                    (draft.room_id,),
                ).fetchone()
                item_count = sequence_stats["item_count"]
                maximum_sequence = sequence_stats["maximum_sequence"]
                if type(item_count) is not int or item_count < 0:
                    raise ClassroomChatServerError(
                        "stored message count is invalid"
                    )
                if maximum_sequence is None:
                    if item_count != 0:
                        raise ClassroomChatServerError(
                            "stored message sequence is not contiguous"
                        )
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
                    if maximum_sequence + 1 != item_count:
                        raise ClassroomChatServerError(
                            "stored message sequence is not contiguous"
                        )
                    sequence = maximum_sequence + 1
                db.execute(
                    """
                    INSERT INTO classroom_chat_server_messages(
                        message_id, room_id, sender_id, sequence_no, body,
                        retention, hidden, sent_at_unix_ms, redacted
                    ) VALUES(?,?,?,?,?,?,0,?,0)
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
                stats = db.execute(
                    """
                    SELECT COUNT(*) AS item_count, MAX(sequence_no) AS maximum_sequence
                    FROM classroom_chat_server_messages
                    WHERE room_id=?
                    """,
                    (room,),
                ).fetchone()
                item_count = stats["item_count"]
                maximum_sequence = stats["maximum_sequence"]
                if type(item_count) is not int or item_count < 0:
                    raise ClassroomChatServerError(
                        "stored message count is invalid"
                    )
                if maximum_sequence is None:
                    if item_count != 0:
                        raise ClassroomChatServerError(
                            "stored message sequence is not contiguous"
                        )
                else:
                    _stored_nonnegative_integer(
                        maximum_sequence,
                        "message sequence",
                        maximum=MAX_WIRE_INTEGER,
                    )
                    if maximum_sequence + 1 != item_count:
                        raise ClassroomChatServerError(
                            "stored message sequence is not contiguous"
                        )
                self._validate_room_hidden_state(db, room)
                rows = db.execute(sql, tuple(params)).fetchall()
        except ClassroomChatServerError:
            raise
        except sqlite3.Error:
            raise ClassroomChatServerError(
                "classroom chat server history read failed"
            ) from None

        decoded = tuple(self._row_message(row) for row in rows)
        expected = 0 if after is None else after + 1
        for message in decoded:
            if message.sequence_no != expected:
                raise ClassroomChatServerError(
                    "stored message history is not contiguous"
                )
            expected += 1
        return decoded

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
            "SELECT room_id, revision, message_id, hidden, redacted "
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
                stats = db.execute(
                    """
                    SELECT COUNT(*) AS item_count, MAX(revision) AS maximum_revision
                    FROM classroom_chat_server_state_updates
                    WHERE room_id=?
                    """,
                    (room,),
                ).fetchone()
                item_count = stats["item_count"]
                maximum_revision = stats["maximum_revision"]
                if type(item_count) is not int or item_count < 0:
                    raise ClassroomChatServerError(
                        "stored moderation revision count is invalid"
                    )
                if maximum_revision is None:
                    if item_count != 0:
                        raise ClassroomChatServerError(
                            "stored moderation revision is not contiguous"
                        )
                else:
                    _stored_nonnegative_integer(
                        maximum_revision,
                        "moderation revision",
                        maximum=MAX_WIRE_INTEGER,
                    )
                    if maximum_revision + 1 != item_count:
                        raise ClassroomChatServerError(
                            "stored moderation revision is not contiguous"
                        )
                self._validate_room_hidden_state(db, room)
                rows = db.execute(sql, tuple(params)).fetchall()
        except ClassroomChatServerError:
            raise
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
                        revision=_stored_nonnegative_integer(
                            row["revision"],
                            "moderation revision",
                            maximum=MAX_WIRE_INTEGER,
                        ),
                        hidden=_stored_bool(
                            row["hidden"],
                            "chat state hidden flag",
                        ),
                        redacted=_stored_bool(
                            row["redacted"],
                            "chat state redacted flag",
                        ),
                    )
                )
            except ClassroomChatServerError:
                raise
            except (TypeError, ValueError, KeyError, IndexError, OverflowError):
                raise ClassroomChatServerError(
                    "stored classroom chat state update is invalid"
                ) from None
        expected = 0 if after_revision is None else after_revision + 1
        for update in decoded:
            if update.revision != expected:
                raise ClassroomChatServerError(
                    "stored moderation state history is not contiguous"
                )
            expected += 1
        return tuple(decoded)

    def redact_retention(
        self,
        *,
        room_id: str,
        retentions: tuple[str, ...],
    ) -> tuple[ChatMessageStateUpdate, ...]:
        """Redact expired non-persistent message bodies without breaking history.

        This is a trusted server lifecycle operation, not a client moderation
        action. Message identity, room sequence, sender, retention and timestamp
        remain durable while the replicated body is irreversibly cleared.
        """

        room = _identifier(room_id, "room id")
        if (
            type(retentions) is not tuple
            or not retentions
            or any(
                type(retention) is not str
                or retention not in {"transient", "session"}
                for retention in retentions
            )
            or len(set(retentions)) != len(retentions)
        ):
            raise ClassroomChatServerError(
                "retention redaction policy is invalid"
            )

        placeholders = ",".join("?" for _ in retentions)
        with closing(self._connect()) as db:
            try:
                db.execute("BEGIN IMMEDIATE")
                self._validate_no_authority_triggers(db)
                self._validate_room_hidden_state(db, room)
                candidates = db.execute(
                    f"""
                    SELECT *
                    FROM classroom_chat_server_messages
                    WHERE room_id=?
                      AND redacted=0
                      AND retention IN ({placeholders})
                    ORDER BY sequence_no
                    """,
                    (room, *retentions),
                ).fetchall()
                if not candidates:
                    db.commit()
                    return ()

                stats = db.execute(
                    """
                    SELECT COUNT(*) AS item_count, MAX(revision) AS maximum_revision
                    FROM classroom_chat_server_state_updates
                    WHERE room_id=?
                    """,
                    (room,),
                ).fetchone()
                item_count = stats["item_count"]
                maximum_revision = stats["maximum_revision"]
                if type(item_count) is not int or item_count < 0:
                    raise ClassroomChatServerError(
                        "stored chat state revision count is invalid"
                    )
                if maximum_revision is None:
                    if item_count != 0:
                        raise ClassroomChatServerError(
                            "stored chat state revision is not contiguous"
                        )
                else:
                    maximum = _stored_nonnegative_integer(
                        maximum_revision,
                        "chat state revision",
                        maximum=MAX_WIRE_INTEGER,
                    )
                    if maximum + 1 != item_count:
                        raise ClassroomChatServerError(
                            "stored chat state revision is not contiguous"
                        )
                if item_count + len(candidates) - 1 > MAX_WIRE_INTEGER:
                    raise ClassroomChatServerError(
                        "server chat state revision exhausted"
                    )

                updates: list[ChatMessageStateUpdate] = []
                for offset, row in enumerate(candidates):
                    message = self._row_message(row)
                    if message.redacted:
                        raise ClassroomChatServerError(
                            "retention redaction candidate is already redacted"
                        )
                    if message.retention not in retentions:
                        raise ClassroomChatServerError(
                            "retention redaction candidate changed policy"
                        )
                    revision = item_count + offset
                    updated = db.execute(
                        """
                        UPDATE classroom_chat_server_messages
                        SET body='', redacted=1
                        WHERE room_id=? AND message_id=? AND redacted=0
                        """,
                        (room, message.message_id),
                    )
                    if updated.rowcount != 1:
                        raise ClassroomChatServerError(
                            "retention redaction lost message authority"
                        )
                    db.execute(
                        """
                        INSERT INTO classroom_chat_server_state_updates(
                            room_id, revision, message_id, hidden, redacted
                        ) VALUES(?,?,?,0,1)
                        """,
                        (room, revision, message.message_id),
                    )
                    updates.append(
                        ChatMessageStateUpdate(
                            room_id=room,
                            message_id=message.message_id,
                            revision=revision,
                            hidden=False,
                            redacted=True,
                        )
                    )
                self._validate_room_hidden_state(db, room)
                db.commit()
                return tuple(updates)
            except ClassroomChatServerError:
                db.rollback()
                raise
            except sqlite3.Error:
                db.rollback()
                raise ClassroomChatServerError(
                    "classroom chat server retention redaction failed"
                ) from None

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
                self._validate_no_authority_triggers(db)
                self._validate_room_hidden_state(db, room)
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
                            SELECT hidden, redacted FROM classroom_chat_server_messages
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
                        target_state_rows = db.execute(
                            """
                            SELECT revision, hidden, redacted
                            FROM classroom_chat_server_state_updates
                            WHERE room_id=? AND message_id=?
                            ORDER BY revision
                            """,
                            (room, command.message_id),
                        ).fetchall()
                        for target_state in target_state_rows:
                            _stored_nonnegative_integer(
                                target_state["revision"],
                                "moderation revision",
                                maximum=MAX_WIRE_INTEGER,
                            )
                            _stored_bool(
                                target_state["hidden"],
                                "chat state hidden flag",
                            )
                            _stored_bool(
                                target_state["redacted"],
                                "chat state redacted flag",
                            )
                            if (
                                not target_state["hidden"]
                                and not target_state["redacted"]
                            ):
                                raise ClassroomChatServerError(
                                    "stored chat state has no monotonic transition"
                                )
                        hidden_transitions = sum(
                            1
                            for target_state in target_state_rows
                            if _stored_bool(
                                target_state["hidden"],
                                "chat state hidden flag",
                            )
                        )
                        if target_hidden != (hidden_transitions > 0):
                            raise ClassroomChatServerError(
                                "stored hidden message state is inconsistent"
                            )
                        if hidden_transitions > 1:
                            raise ClassroomChatServerError(
                                "stored hidden message state is duplicated"
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
                            revision_stats = db.execute(
                                """
                                SELECT COUNT(*) AS item_count, MAX(revision) AS maximum_revision
                                FROM classroom_chat_server_state_updates
                                WHERE room_id=?
                                """,
                                (room,),
                            ).fetchone()
                            revision_count = revision_stats["item_count"]
                            maximum_revision = revision_stats["maximum_revision"]
                            if type(revision_count) is not int or revision_count < 0:
                                raise ClassroomChatServerError(
                                    "stored moderation revision count is invalid"
                                )
                            if maximum_revision is None:
                                if revision_count != 0:
                                    raise ClassroomChatServerError(
                                        "stored moderation revision is not contiguous"
                                    )
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
                                if maximum_revision + 1 != revision_count:
                                    raise ClassroomChatServerError(
                                        "stored moderation revision is not contiguous"
                                    )
                                revision = maximum_revision + 1
                            db.execute(
                                """
                                INSERT INTO classroom_chat_server_state_updates(
                                    room_id, revision, message_id, hidden, redacted
                                ) VALUES(?,?,?,1,0)
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
                self._validate_no_authority_triggers(db)
                row = db.execute("PRAGMA integrity_check").fetchone()
                if row is None or row[0] != "ok":
                    raise ClassroomChatServerError(
                        "classroom chat server database failed integrity check"
                    )

                expected_sequence: dict[str, int] = {}
                message_keys: set[tuple[str, str]] = set()
                hidden_message_keys: set[tuple[str, str]] = set()
                for stored in db.execute(
                    """
                    SELECT * FROM classroom_chat_server_messages
                    ORDER BY room_id, sequence_no
                    """
                ):
                    message = self._row_message(stored)
                    expected = expected_sequence.get(message.room_id, 0)
                    if message.sequence_no != expected:
                        raise ClassroomChatServerError(
                            "server message sequence is not contiguous"
                        )
                    expected_sequence[message.room_id] = expected + 1
                    key = (message.room_id, message.message_id)
                    message_keys.add(key)
                    if message.hidden:
                        hidden_message_keys.add(key)

                for stored in db.execute(
                    """
                    SELECT room_id, target_id, allowed
                    FROM classroom_chat_server_permissions
                    """
                ):
                    _identifier(
                        stored["room_id"],
                        "stored chat permission room id",
                    )
                    _identifier(
                        stored["target_id"],
                        "stored chat permission target id",
                    )
                    _stored_bool(
                        stored["allowed"],
                        "chat permission flag",
                    )

                for stored in db.execute(
                    """
                    SELECT room_id, operation_id, fingerprint
                    FROM classroom_chat_server_moderation_ops
                    """
                ):
                    _identifier(
                        stored["room_id"],
                        "stored moderation room id",
                    )
                    _identifier(
                        stored["operation_id"],
                        "stored moderation operation id",
                    )
                    fingerprint = stored["fingerprint"]
                    if (
                        type(fingerprint) is not str
                        or len(fingerprint) != 64
                        or any(
                            ch not in "0123456789abcdef"
                            for ch in fingerprint
                        )
                    ):
                        raise ClassroomChatServerError(
                            "stored moderation fingerprint is invalid"
                        )

                expected_revision: dict[str, int] = {}
                for stored in db.execute(
                    """
                    SELECT room_id, revision, message_id, hidden, redacted
                    FROM classroom_chat_server_state_updates
                    ORDER BY room_id, revision
                    """
                ):
                    room = _identifier(
                        stored["room_id"],
                        "stored moderation state room id",
                    )
                    message_id = _identifier(
                        stored["message_id"],
                        "stored moderation state message id",
                    )
                    revision = _stored_nonnegative_integer(
                        stored["revision"],
                        "moderation revision",
                        maximum=MAX_WIRE_INTEGER,
                    )
                    if revision != expected_revision.get(room, 0):
                        raise ClassroomChatServerError(
                            "server moderation revision is not contiguous"
                        )
                    expected_revision[room] = revision + 1
                    hidden = _stored_bool(
                        stored["hidden"],
                        "chat state hidden flag",
                    )
                    redacted = _stored_bool(
                        stored["redacted"],
                        "chat state redacted flag",
                    )
                    if not hidden and not redacted:
                        raise ClassroomChatServerError(
                            "stored chat state has no monotonic transition"
                        )
                    key = (room, message_id)
                    if key not in message_keys:
                        raise ClassroomChatServerError(
                            "chat state references unknown message"
                        )

                rooms = {
                    stored["room_id"]
                    for stored in db.execute(
                        """
                        SELECT room_id FROM classroom_chat_server_messages
                        UNION
                        SELECT room_id FROM classroom_chat_server_state_updates
                        """
                    )
                }
                for room_id in rooms:
                    room = _identifier(room_id, "stored chat state room id")
                    self._validate_room_hidden_state(db, room)
        except ClassroomChatServerError:
            raise
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
        retention_policy: Callable[[str], str] | None = None,
    ) -> None:
        if not isinstance(store, ClassroomChatServerSQLiteStore):
            raise TypeError("store must be ClassroomChatServerSQLiteStore")
        if authorization is None:
            raise TypeError("authorization port is required")
        if not callable(clock_unix_ms):
            raise TypeError("clock_unix_ms must be callable")
        if retention_policy is not None and not callable(retention_policy):
            raise TypeError("retention_policy must be callable or None")
        self._store = store
        self._authorization = authorization
        self._clock_unix_ms = clock_unix_ms
        self._retention_policy = retention_policy

    def _room_retention(self, room_id: str) -> str:
        if self._retention_policy is None:
            return "session"
        try:
            retention = self._retention_policy(room_id)
        except Exception:
            raise ClassroomChatServerError(
                "chat retention policy lookup failed"
            ) from None
        if (
            type(retention) is not str
            or retention not in {"transient", "session", "persistent"}
        ):
            raise ClassroomChatServerError(
                "chat retention policy is invalid"
            )
        return retention

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
            authorization_result = self._authorization.authorize_chat_send(
                room_id=draft.room_id,
                caller_identity=caller,
                sender_id=draft.sender_id,
            )
            if authorization_result is not None:
                raise RuntimeError("authorization port returned an invalid result")
        except Exception:
            raise ClassroomChatServerError("chat send is not authorized") from None
        existing = self._store.existing_for_draft(draft)
        if existing is not None:
            return existing
        if draft.retention != self._room_retention(draft.room_id):
            raise ClassroomChatServerError(
                "chat retention does not match server policy"
            )
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
            authorization_result = self._authorization.authorize_chat_history(
                room_id=room,
                caller_identity=caller,
            )
            if authorization_result is not None:
                raise RuntimeError("authorization port returned an invalid result")
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
            authorization_result = self._authorization.authorize_chat_history(
                room_id=room,
                caller_identity=caller,
            )
            if authorization_result is not None:
                raise RuntimeError("authorization port returned an invalid result")
        except Exception:
            raise ClassroomChatServerError(
                "chat state history is not authorized"
            ) from None
        return self._store.state_updates_after(
            room_id=room,
            after_revision=after_revision,
            limit=bounded,
        )

    def redact_retention(
        self,
        *,
        room_id: str,
        retentions: tuple[str, ...],
    ) -> tuple[ChatMessageStateUpdate, ...]:
        """Run a trusted room lifecycle retention transition.

        This method is intentionally not part of ChatTransportPort and accepts
        no participant identity: callers must be trusted server lifecycle
        composition, never browser/client RPC.
        """

        return self._store.redact_retention(
            room_id=room_id,
            retentions=retentions,
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
            authorization_result = self._authorization.authorize_chat_moderation(
                room_id=room,
                caller_identity=caller,
                commands=commands,
            )
            if authorization_result is not None:
                raise RuntimeError("authorization port returned an invalid result")
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
