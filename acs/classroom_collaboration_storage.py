from __future__ import annotations

import hashlib
from contextlib import closing
import re
import sqlite3
import unicodedata
from dataclasses import dataclass
from pathlib import PurePath
from typing import Protocol, runtime_checkable

from .classroom_domain import MAX_WIRE_INTEGER

SCHEMA_VERSION = 10
MAX_CHAT_TIMESTAMP_UNIX_MS = 253402300799999
MAX_CHAT_BODY_CHARS = 4000
MAX_ID_CHARS = 128
MAX_OBJECT_KEY_CHARS = 1024
MAX_MIME_CHARS = 255
MAX_WINDOWS_FILENAME_UTF16_UNITS = 255
_WINDOWS_INVALID_FILENAME_CHARS = frozenset('<>:"/\\|?*')
_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_OBJECT_SEGMENT_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_WINDOWS_RESERVED_BASENAMES = frozenset(
    {
        "CON",
        "PRN",
        "AUX",
        "NUL",
        *(f"COM{index}" for index in range(1, 10)),
        "COM¹",
        "COM²",
        "COM³",
        *(f"LPT{index}" for index in range(1, 10)),
        "LPT¹",
        "LPT²",
        "LPT³",
    }
)


class CollaborationStorageError(RuntimeError):
    pass


class CollaborationConflictError(CollaborationStorageError):
    pass


class CollaborationQuotaError(CollaborationStorageError):
    pass


class CollaborationSequenceGapError(CollaborationStorageError):
    pass


@dataclass(frozen=True)
class ChatMessageMetadata:
    message_id: str
    room_id: str
    sender_id: str
    sequence_no: int
    body: str
    retention: str = "session"
    hidden: bool = False
    sent_at_unix_ms: int | None = None
    redacted: bool = False

    def __post_init__(self) -> None:
        _canonical_id(self.message_id, "message id")
        _canonical_id(self.room_id, "room id")
        _canonical_id(self.sender_id, "sender id")
        if (
            type(self.sequence_no) is not int
            or not 0 <= self.sequence_no <= MAX_WIRE_INTEGER
        ):
            raise ValueError("sequence_no must be a bounded JSON-safe integer")
        if type(self.body) is not str:
            raise ValueError("message body must be text")
        if type(self.redacted) is not bool:
            raise ValueError("redacted flag must be boolean")
        if self.redacted:
            if self.body != "":
                raise ValueError("redacted message body must be empty")
        else:
            if not self.body.strip():
                raise ValueError("message body must be non-empty text")
            if len(self.body) > MAX_CHAT_BODY_CHARS or "\x00" in self.body:
                raise ValueError("message body exceeds safety boundary")
            if any(0xD800 <= ord(ch) <= 0xDFFF for ch in self.body):
                raise ValueError("message body contains invalid Unicode surrogate")
        if self.retention not in {"transient", "session", "persistent"}:
            raise ValueError("unsupported retention policy")
        if self.redacted and self.retention == "persistent":
            raise ValueError("persistent chat content cannot be retention-redacted")
        if type(self.hidden) is not bool:
            raise ValueError("hidden flag must be boolean")
        if self.sent_at_unix_ms is not None and (
            type(self.sent_at_unix_ms) is not int
            or not 0 <= self.sent_at_unix_ms <= MAX_CHAT_TIMESTAMP_UNIX_MS
        ):
            raise ValueError("sent_at_unix_ms must be a bounded UTC Unix millisecond timestamp")


@dataclass(frozen=True)
class ChatMessageStateUpdate:
    room_id: str
    message_id: str
    revision: int
    hidden: bool = True
    redacted: bool = False

    def __post_init__(self) -> None:
        _canonical_id(self.room_id, "room id")
        _canonical_id(self.message_id, "message id")
        if (
            type(self.revision) is not int
            or not 0 <= self.revision <= MAX_WIRE_INTEGER
        ):
            raise ValueError("state revision must be a bounded JSON-safe integer")
        if type(self.hidden) is not bool or type(self.redacted) is not bool:
            raise ValueError("chat message state flags must be boolean")
        if not self.hidden and not self.redacted:
            raise ValueError("chat message state update must be monotonic")


@dataclass(frozen=True)
class AttachmentMetadata:
    attachment_id: str
    room_id: str
    sender_id: str
    sequence_no: int
    display_name: str
    mime_type: str | None
    size_bytes: int
    sha256: str
    object_key: str
    transfer_state: str
    retention: str = "session"
    scan_state: str = "pending"

    def __post_init__(self) -> None:
        _canonical_id(self.attachment_id, "attachment id")
        _canonical_id(self.room_id, "room id")
        _canonical_id(self.sender_id, "sender id")
        if (
            type(self.sequence_no) is not int
            or not 0 <= self.sequence_no <= MAX_WIRE_INTEGER
        ):
            raise ValueError("sequence_no must be a bounded JSON-safe integer")
        if (
            type(self.size_bytes) is not int
            or not 0 <= self.size_bytes <= MAX_WIRE_INTEGER
        ):
            raise ValueError("size_bytes must be a bounded JSON-safe integer")
        if safe_display_filename(self.display_name) != self.display_name:
            raise ValueError("display_name must already be sanitized")
        if self.mime_type is not None:
            if type(self.mime_type) is not str or len(self.mime_type) > MAX_MIME_CHARS:
                raise ValueError("mime_type exceeds safety boundary")
            if any(ord(ch) < 32 or ord(ch) == 127 for ch in self.mime_type):
                raise ValueError("mime_type contains control characters")
        _safe_object_key(self.object_key)
        if self.retention not in {"transient", "session", "persistent"}:
            raise ValueError("unsupported retention policy")
        if self.transfer_state not in {"pending", "uploading", "stored", "failed", "deleted"}:
            raise ValueError("unsupported transfer state")
        if self.scan_state not in {"pending", "clean", "blocked", "failed", "not_required"}:
            raise ValueError("unsupported scan state")
        digest = self.sha256.lower()
        if len(digest) != 64 or any(ch not in "0123456789abcdef" for ch in digest):
            raise ValueError("sha256 must be a 64-character hexadecimal digest")
        object.__setattr__(self, "sha256", digest)


@dataclass(frozen=True)
class AttachmentStateUpdate:
    room_id: str
    attachment_id: str
    revision: int
    transfer_state: str
    scan_state: str

    def __post_init__(self) -> None:
        _canonical_id(self.room_id, "room id")
        _canonical_id(self.attachment_id, "attachment id")
        if (
            type(self.revision) is not int
            or not 0 <= self.revision <= MAX_WIRE_INTEGER
        ):
            raise ValueError(
                "attachment state revision must be a bounded JSON-safe integer"
            )
        if self.transfer_state not in {"stored", "deleted"}:
            raise ValueError(
                "attachment state update requires authoritative terminal transfer state"
            )
        if self.scan_state not in {
            "pending",
            "clean",
            "blocked",
            "failed",
            "not_required",
        }:
            raise ValueError("unsupported attachment scan state")


@runtime_checkable
class FileStorePort(Protocol):
    """Opaque persistent-byte boundary. Implementations enforce authorization and storage policy."""

    def put(self, *, object_key: str, content: bytes, expected_sha256: str) -> None: ...
    def issue_read_token(self, *, object_key: str, participant_id: str, ttl_seconds: int) -> str: ...
    def delete(self, *, object_key: str) -> None:
        """Idempotently delete durable bytes for crash-safe tombstone recovery."""
        ...


def _canonical_id(value: object, label: str) -> str:
    if type(value) is not str or len(value) > MAX_ID_CHARS or _ID_RE.fullmatch(value) is None:
        raise ValueError(f"{label} must be a canonical opaque identifier")
    return value


def _stored_integer(
    value: object,
    label: str,
    *,
    maximum: int = MAX_WIRE_INTEGER,
) -> int:
    if type(value) is not int or not 0 <= value <= maximum:
        raise CollaborationStorageError(
            f"stored {label} must be a bounded non-negative integer"
        )
    return value


def _stored_snapshot_revision(value: object) -> int:
    if type(value) is not int or not 0 <= value <= MAX_WIRE_INTEGER:
        raise CollaborationStorageError(
            "stored attachment snapshot watermark is invalid"
        )
    return value


def _stored_boolean(value: object, label: str) -> bool:
    if type(value) is not int or value not in {0, 1}:
        raise CollaborationStorageError(
            f"stored {label} must be canonical SQLite boolean 0 or 1"
        )
    return bool(value)


def _safe_object_key(value: object) -> str:
    if type(value) is not str or not value or len(value) > MAX_OBJECT_KEY_CHARS:
        raise ValueError("object_key must be a bounded relative storage key")
    if "\\" in value or value.startswith("/") or value.endswith("/"):
        raise ValueError("object_key must use canonical relative slash-separated form")
    parts = value.split("/")
    if not parts or any(
        part in {"", ".", ".."} or _OBJECT_SEGMENT_RE.fullmatch(part) is None
        for part in parts
    ):
        raise ValueError("unsafe object_key")
    return value


def _validate_transfer_transition(current: str, target: str) -> None:
    allowed = {
        "pending": {"pending", "uploading", "deleted"},
        "uploading": {"uploading", "stored", "failed", "deleted"},
        "failed": {"failed", "uploading", "deleted"},
        "stored": {"stored", "deleted"},
        "deleted": {"deleted"},
    }
    if target not in allowed.get(current, set()):
        raise CollaborationStorageError(
            f"invalid attachment transfer transition: {current} -> {target}"
        )


def _validate_scan_transition(current: str, target: str) -> None:
    allowed = {
        "pending": {"pending", "clean", "blocked", "failed", "not_required"},
        "clean": {"clean"},
        "blocked": {"blocked"},
        "failed": {"failed", "pending"},
        "not_required": {"not_required"},
    }
    if target not in allowed.get(current, set()):
        raise CollaborationStorageError(
            f"invalid attachment scan transition: {current} -> {target}"
        )


def _truncate_windows_filename(value: str) -> str:
    units = 0
    kept: list[str] = []
    for char in value:
        width = 2 if ord(char) > 0xFFFF else 1
        if units + width > MAX_WINDOWS_FILENAME_UTF16_UNITS:
            break
        kept.append(char)
        units += width
    return "".join(kept)


def safe_display_filename(value: str) -> str:
    if type(value) is not str:
        raise ValueError("filename must be text")
    raw = value.replace("\\", "/")
    if raw.startswith("/") or ".." in PurePath(raw).parts:
        raise ValueError("unsafe file path")
    name = unicodedata.normalize("NFC", PurePath(raw).name).strip()
    if not name or name in {".", ".."}:
        raise ValueError("filename must not be empty")
    clean = "".join(
        "_"
        if ch in _WINDOWS_INVALID_FILENAME_CHARS
        or unicodedata.category(ch).startswith("C")
        else ch
        for ch in name
    ).strip(" .")
    if not clean:
        raise ValueError("filename has no safe display characters")
    bounded = _truncate_windows_filename(clean).rstrip(" .")
    if not bounded:
        raise ValueError("filename has no safe display characters")
    windows_stem = bounded.split(".", 1)[0].rstrip(" .").upper()
    if windows_stem in _WINDOWS_RESERVED_BASENAMES:
        raise ValueError("filename uses a reserved Windows device name")
    return bounded


def content_sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _next_authoritative_attachment_sequence(
    db: sqlite3.Connection,
    room_id: str,
) -> int:
    rows = db.execute(
        """
        SELECT sequence_no
        FROM collaboration_attachments
        WHERE room_id=? AND transfer_state IN ('stored', 'deleted')
        ORDER BY sequence_no
        """,
        (room_id,),
    ).fetchall()
    expected = 0
    for row in rows:
        sequence = _stored_integer(
            row["sequence_no"],
            "attachment sequence",
        )
        if sequence != expected:
            break
        expected += 1
    return expected


def _queue_attachment_deletion(
    db: sqlite3.Connection,
    attachment: AttachmentMetadata,
) -> None:
    if attachment.transfer_state != "deleted":
        return
    db.execute(
        """
        INSERT OR IGNORE INTO collaboration_attachment_deletions(
            room_id, attachment_id, object_key, completed
        ) VALUES(?,?,?,0)
        """,
        (
            attachment.room_id,
            attachment.attachment_id,
            attachment.object_key,
        ),
    )
    rows = db.execute(
        """
        SELECT room_id, attachment_id, object_key, completed
        FROM collaboration_attachment_deletions
        WHERE attachment_id=? OR object_key=?
        """,
        (attachment.attachment_id, attachment.object_key),
    ).fetchall()
    if (
        len(rows) != 1
        or rows[0]["room_id"] != attachment.room_id
        or rows[0]["attachment_id"] != attachment.attachment_id
        or rows[0]["object_key"] != attachment.object_key
    ):
        raise CollaborationConflictError(
            "attachment deletion intent conflicts with durable storage identity"
        )


class ClassroomCollaborationSQLiteStore:
    """Durable provider-neutral chat/file metadata store.

    SQLite stores metadata only. Persistent file bytes belong behind FileStorePort;
    this class never auto-opens or executes attachments and never emits analytics.
    """

    def __init__(self, path: str) -> None:
        self.path = str(path)
        self._migrate()

    def _connect(self) -> sqlite3.Connection:
        db: sqlite3.Connection | None = None
        try:
            db = sqlite3.connect(self.path)
            db.row_factory = sqlite3.Row
            # Expired chat payloads must not remain recoverable from SQLite
            # free space after logical redaction on the Windows client.
            db.execute("PRAGMA secure_delete=ON")
            secure_delete = db.execute("PRAGMA secure_delete").fetchone()
            if (
                secure_delete is None
                or type(secure_delete[0]) is not int
                or secure_delete[0] != 1
            ):
                raise CollaborationStorageError(
                    "collaboration SQLite secure deletion is unavailable"
                )
            return db
        except CollaborationStorageError:
            if db is not None:
                db.close()
            raise
        except sqlite3.Error as exc:
            if db is not None:
                db.close()
            raise CollaborationStorageError(
                "collaboration SQLite open failed"
            ) from exc

    def _migrate(self) -> None:
        with closing(self._connect()) as db, db:
            # SQLite DDL is transactional only when we explicitly start the
            # transaction. Keep schema changes and the version marker atomic so
            # a crash cannot leave a half-applied migration that bricks reopen.
            db.execute("BEGIN IMMEDIATE")
            db.execute("CREATE TABLE IF NOT EXISTS collaboration_schema_meta(key TEXT PRIMARY KEY, value INTEGER NOT NULL)")
            row = db.execute("SELECT value FROM collaboration_schema_meta WHERE key='schema_version'").fetchone()
            version = (
                _stored_integer(row[0], "schema version")
                if row
                else 0
            )
            if version > SCHEMA_VERSION:
                raise CollaborationStorageError(f"unsupported collaboration schema {version}")
            if version < 1:
                db.execute(
                    """
                    CREATE TABLE collaboration_messages(
                        message_id TEXT PRIMARY KEY,
                        room_id TEXT NOT NULL,
                        sender_id TEXT NOT NULL,
                        sequence_no INTEGER NOT NULL CHECK(sequence_no >= 0),
                        body TEXT NOT NULL,
                        retention TEXT NOT NULL,
                        hidden INTEGER NOT NULL DEFAULT 0,
                        UNIQUE(room_id, sequence_no)
                    )
                    """
                )
                db.execute(
                    """
                    CREATE INDEX idx_collaboration_messages_room
                    ON collaboration_messages(room_id, sequence_no)
                    """
                )
                db.execute(
                    """
                    CREATE TABLE collaboration_attachments(
                        attachment_id TEXT PRIMARY KEY,
                        room_id TEXT NOT NULL,
                        sender_id TEXT NOT NULL,
                        sequence_no INTEGER NOT NULL CHECK(sequence_no >= 0),
                        display_name TEXT NOT NULL,
                        mime_type TEXT,
                        size_bytes INTEGER NOT NULL CHECK(size_bytes >= 0),
                        sha256 TEXT NOT NULL,
                        object_key TEXT NOT NULL UNIQUE,
                        transfer_state TEXT NOT NULL,
                        retention TEXT NOT NULL,
                        scan_state TEXT NOT NULL,
                        UNIQUE(room_id, sequence_no)
                    )
                    """
                )
                db.execute(
                    """
                    CREATE INDEX idx_collaboration_attachments_room
                    ON collaboration_attachments(room_id, sequence_no)
                    """
                )
                db.execute(
                    "INSERT INTO collaboration_schema_meta(key,value) VALUES('schema_version',?)",
                    (1,),
                )
                version = 1
            if version < 2:
                db.execute(
                    "ALTER TABLE collaboration_messages "
                    "ADD COLUMN sent_at_unix_ms INTEGER "
                    "CHECK(sent_at_unix_ms IS NULL OR sent_at_unix_ms >= 0)"
                )
                db.execute(
                    "UPDATE collaboration_schema_meta SET value=2 WHERE key='schema_version'"
                )
                version = 2
            if version < 3:
                db.execute(
                    """
                    CREATE TABLE collaboration_chat_state_cursors(
                        room_id TEXT PRIMARY KEY,
                        revision INTEGER NOT NULL CHECK(revision >= 0)
                    )
                    """
                )
                db.execute(
                    "UPDATE collaboration_schema_meta SET value=3 WHERE key='schema_version'"
                )
                version = 3
            if version < 4:
                db.execute(
                    """
                    CREATE TABLE collaboration_attachment_state_cursors(
                        room_id TEXT PRIMARY KEY,
                        revision INTEGER NOT NULL CHECK(revision >= 0)
                    )
                    """
                )
                db.execute(
                    "UPDATE collaboration_schema_meta SET value=4 WHERE key='schema_version'"
                )
                version = 4
            if version < 5:
                # File sequence numbers are server-authoritative only after a
                # transfer becomes durable. Provisional/failed local transfers
                # must not reserve a room sequence that can block remote history.
                db.execute(
                    "ALTER TABLE collaboration_attachments "
                    "RENAME TO collaboration_attachments_v4"
                )
                db.execute(
                    """
                    CREATE TABLE collaboration_attachments(
                        attachment_id TEXT PRIMARY KEY,
                        room_id TEXT NOT NULL,
                        sender_id TEXT NOT NULL,
                        sequence_no INTEGER NOT NULL CHECK(sequence_no >= 0),
                        display_name TEXT NOT NULL,
                        mime_type TEXT,
                        size_bytes INTEGER NOT NULL CHECK(size_bytes >= 0),
                        sha256 TEXT NOT NULL,
                        object_key TEXT NOT NULL UNIQUE,
                        transfer_state TEXT NOT NULL,
                        retention TEXT NOT NULL,
                        scan_state TEXT NOT NULL
                    )
                    """
                )
                db.execute(
                    """
                    INSERT INTO collaboration_attachments(
                        attachment_id, room_id, sender_id, sequence_no,
                        display_name, mime_type, size_bytes, sha256,
                        object_key, transfer_state, retention, scan_state
                    )
                    SELECT
                        attachment_id, room_id, sender_id, sequence_no,
                        display_name, mime_type, size_bytes, sha256,
                        object_key, transfer_state, retention, scan_state
                    FROM collaboration_attachments_v4
                    """
                )
                db.execute("DROP TABLE collaboration_attachments_v4")
                db.execute(
                    """
                    CREATE INDEX idx_collaboration_attachments_room
                    ON collaboration_attachments(room_id, sequence_no, attachment_id)
                    """
                )
                db.execute(
                    """
                    CREATE UNIQUE INDEX uq_collaboration_attachments_stored_sequence
                    ON collaboration_attachments(room_id, sequence_no)
                    WHERE transfer_state='stored'
                    """
                )
                db.execute(
                    "UPDATE collaboration_schema_meta SET value=5 WHERE key='schema_version'"
                )
                version = 5
            if version < 6:
                # Deleted attachments are authoritative room-history tombstones.
                # They must keep reserving their server sequence just like stored
                # attachments, while provisional local states remain free to use
                # a placeholder sequence before server reconciliation.
                db.execute(
                    "DROP INDEX IF EXISTS uq_collaboration_attachments_stored_sequence"
                )
                db.execute(
                    "DROP INDEX IF EXISTS uq_collaboration_attachments_terminal_sequence"
                )
                db.execute(
                    """
                    CREATE UNIQUE INDEX uq_collaboration_attachments_authoritative_sequence
                    ON collaboration_attachments(room_id, sequence_no)
                    WHERE transfer_state IN ('stored', 'deleted')
                    """
                )
                db.execute(
                    "UPDATE collaboration_schema_meta SET value=6 WHERE key='schema_version'"
                )
                version = 6
            if version < 7:
                # Tombstone metadata and durable byte cleanup intent must advance
                # atomically. The external delete is acknowledged separately so
                # provider failures and process crashes remain retryable.
                db.execute(
                    """
                    CREATE TABLE collaboration_attachment_deletions(
                        room_id TEXT NOT NULL,
                        attachment_id TEXT NOT NULL UNIQUE,
                        object_key TEXT PRIMARY KEY
                    )
                    """
                )
                db.execute(
                    """
                    INSERT INTO collaboration_attachment_deletions(
                        room_id, attachment_id, object_key
                    )
                    SELECT room_id, attachment_id, object_key
                    FROM collaboration_attachments
                    WHERE transfer_state='deleted'
                    """
                )
                db.execute(
                    "UPDATE collaboration_schema_meta SET value=7 WHERE key='schema_version'"
                )
                version = 7
            if version < 8:
                # v7 deleted cleanup rows after provider acknowledgement, which
                # made a lost/corrupt row indistinguishable from successful byte
                # deletion. Preserve a durable completion receipt instead. Any
                # historical tombstone lacking a v7 row is conservatively
                # re-queued; FileStorePort.delete is explicitly idempotent.
                db.execute(
                    """
                    ALTER TABLE collaboration_attachment_deletions
                    ADD COLUMN completed INTEGER NOT NULL DEFAULT 0
                    CHECK(completed IN (0,1))
                    """
                )
                db.execute(
                    """
                    INSERT OR IGNORE INTO collaboration_attachment_deletions(
                        room_id, attachment_id, object_key, completed
                    )
                    SELECT room_id, attachment_id, object_key, 0
                    FROM collaboration_attachments
                    WHERE transfer_state='deleted'
                    """
                )
                db.execute(
                    "UPDATE collaboration_schema_meta SET value=8 WHERE key='schema_version'"
                )
                version = 8
            if version < 9:
                db.execute(
                    """
                    CREATE TABLE IF NOT EXISTS collaboration_attachment_snapshot_watermarks(
                        attachment_id TEXT PRIMARY KEY,
                        room_id TEXT NOT NULL,
                        revision INTEGER NOT NULL CHECK(
                            revision >= 0 AND revision <= 9007199254740991
                        )
                    )
                    """
                )
                columns = tuple(
                    (
                        row["name"],
                        str(row["type"]).upper(),
                        int(row["notnull"]),
                        int(row["pk"]),
                    )
                    for row in db.execute(
                        "PRAGMA table_info(collaboration_attachment_snapshot_watermarks)"
                    )
                )
                expected_columns = (
                    ("attachment_id", "TEXT", 0, 1),
                    ("room_id", "TEXT", 1, 0),
                    ("revision", "INTEGER", 1, 0),
                )
                if columns != expected_columns:
                    raise CollaborationStorageError(
                        "attachment snapshot watermark schema is incompatible"
                    )
                table_sql_row = db.execute(
                    """
                    SELECT sql FROM sqlite_master
                    WHERE type='table'
                      AND name='collaboration_attachment_snapshot_watermarks'
                    """
                ).fetchone()
                normalized_table_sql = (
                    ""
                    if table_sql_row is None or type(table_sql_row["sql"]) is not str
                    else "".join(table_sql_row["sql"].lower().split())
                )
                if (
                    "check(revision>=0andrevision<=9007199254740991)"
                    not in normalized_table_sql
                ):
                    raise CollaborationStorageError(
                        "attachment snapshot watermark schema is incompatible"
                    )
                db.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_collaboration_attachment_snapshot_watermarks_room
                    ON collaboration_attachment_snapshot_watermarks(room_id, revision)
                    """
                )
                index_columns = tuple(
                    row["name"]
                    for row in db.execute(
                        "PRAGMA index_info(idx_collaboration_attachment_snapshot_watermarks_room)"
                    )
                )
                if index_columns != ("room_id", "revision"):
                    raise CollaborationStorageError(
                        "attachment snapshot watermark index is incompatible"
                    )
                db.execute(
                    "UPDATE collaboration_schema_meta SET value=9 WHERE key='schema_version'"
                )
                version = 9
            if version < 10:
                # Two active pre-convergence lineages independently used schema
                # version 9: file-sync v9 introduced snapshot watermarks while
                # chat-retention v9 introduced message redaction. Converge both
                # shapes explicitly before advancing to v10 so either durable
                # database upgrades without data loss.
                watermark_exists = db.execute(
                    """
                    SELECT 1 FROM sqlite_master
                    WHERE type='table'
                      AND name='collaboration_attachment_snapshot_watermarks'
                    """
                ).fetchone() is not None
                if not watermark_exists:
                    db.execute(
                        """
                        CREATE TABLE collaboration_attachment_snapshot_watermarks(
                            attachment_id TEXT PRIMARY KEY,
                            room_id TEXT NOT NULL,
                            revision INTEGER NOT NULL CHECK(
                                revision >= 0 AND revision <= 9007199254740991
                            )
                        )
                        """
                    )
                    db.execute(
                        """
                        CREATE INDEX idx_collaboration_attachment_snapshot_watermarks_room
                        ON collaboration_attachment_snapshot_watermarks(
                            room_id, revision
                        )
                        """
                    )
                else:
                    columns = tuple(
                        (
                            row["name"],
                            str(row["type"]).upper(),
                            int(row["notnull"]),
                            int(row["pk"]),
                        )
                        for row in db.execute(
                            "PRAGMA table_info(collaboration_attachment_snapshot_watermarks)"
                        )
                    )
                    if columns != (
                        ("attachment_id", "TEXT", 0, 1),
                        ("room_id", "TEXT", 1, 0),
                        ("revision", "INTEGER", 1, 0),
                    ):
                        raise CollaborationStorageError(
                            "attachment snapshot watermark schema is incompatible"
                        )
                    index_columns = tuple(
                        row["name"]
                        for row in db.execute(
                            "PRAGMA index_info(idx_collaboration_attachment_snapshot_watermarks_room)"
                        )
                    )
                    if index_columns != ("room_id", "revision"):
                        raise CollaborationStorageError(
                            "attachment snapshot watermark index is incompatible"
                        )

                message_columns = {
                    row["name"]
                    for row in db.execute(
                        "PRAGMA table_info(collaboration_messages)"
                    )
                }
                if "redacted" not in message_columns:
                    db.execute(
                        "ALTER TABLE collaboration_messages "
                        "ADD COLUMN redacted INTEGER NOT NULL DEFAULT 0 "
                        "CHECK(redacted IN (0,1))"
                    )
                db.execute(
                    "UPDATE collaboration_schema_meta SET value=10 "
                    "WHERE key='schema_version'"
                )
                version = 10

    def append_message(self, message: ChatMessageMetadata) -> ChatMessageMetadata:
        with closing(self._connect()) as db, db:
            db.execute("BEGIN IMMEDIATE")
            existing = db.execute(
                "SELECT * FROM collaboration_messages WHERE message_id=?", (message.message_id,)
            ).fetchone()
            if existing is not None:
                loaded = self._message_from_row(existing)
                immutable_fields = (
                    "message_id",
                    "room_id",
                    "sender_id",
                    "sequence_no",
                    "retention",
                )
                if any(
                    getattr(loaded, field) != getattr(message, field)
                    for field in immutable_fields
                ) or (
                    not loaded.redacted
                    and not message.redacted
                    and loaded.body != message.body
                ):
                    raise CollaborationConflictError(
                        "message identity reused with different payload"
                    )
                if (
                    loaded.sent_at_unix_ms is not None
                    and message.sent_at_unix_ms is not None
                    and loaded.sent_at_unix_ms != message.sent_at_unix_ms
                ):
                    raise CollaborationConflictError(
                        "message identity reused with different authoritative timestamp"
                    )

                hidden = loaded.hidden or message.hidden
                redacted = loaded.redacted or message.redacted
                body = "" if redacted else loaded.body
                sent_at = (
                    loaded.sent_at_unix_ms
                    if loaded.sent_at_unix_ms is not None
                    else message.sent_at_unix_ms
                )
                if (
                    hidden != loaded.hidden
                    or redacted != loaded.redacted
                    or body != loaded.body
                    or sent_at != loaded.sent_at_unix_ms
                ):
                    db.execute(
                        """
                        UPDATE collaboration_messages
                        SET body=?, hidden=?, sent_at_unix_ms=?, redacted=?
                        WHERE message_id=?
                        """,
                        (
                            body,
                            int(hidden),
                            sent_at,
                            int(redacted),
                            loaded.message_id,
                        ),
                    )
                    existing = db.execute(
                        "SELECT * FROM collaboration_messages WHERE message_id=?",
                        (loaded.message_id,),
                    ).fetchone()
                    loaded = self._message_from_row(existing)
                return loaded
            sequence_rows = db.execute(
                """
                SELECT sequence_no
                FROM collaboration_messages
                WHERE room_id=?
                ORDER BY sequence_no
                """,
                (message.room_id,),
            ).fetchall()
            expected_sequence = 0
            for row in sequence_rows:
                sequence = _stored_integer(
                    row["sequence_no"],
                    "message sequence",
                )
                if sequence != expected_sequence:
                    break
                expected_sequence += 1
            if message.sequence_no > expected_sequence:
                raise CollaborationSequenceGapError(
                    "message sequence has an unresolved gap"
                )
            try:
                db.execute(
                    """
                    INSERT INTO collaboration_messages(
                        message_id, room_id, sender_id, sequence_no, body,
                        retention, hidden, sent_at_unix_ms, redacted
                    ) VALUES(?,?,?,?,?,?,?,?,?)
                    """,
                    (
                        message.message_id, message.room_id, message.sender_id, message.sequence_no,
                        message.body, message.retention, int(message.hidden),
                        message.sent_at_unix_ms, int(message.redacted),
                    ),
                )
            except sqlite3.IntegrityError as exc:
                raise CollaborationConflictError("message conflicts with room ordering") from exc
        return message

    def reconcile_message_sync_atomic(
        self,
        *,
        room_id: str,
        messages: tuple[ChatMessageMetadata, ...],
        updates: tuple[ChatMessageStateUpdate, ...],
    ) -> tuple[ChatMessageMetadata, ...]:
        _canonical_id(room_id, "room id")
        if type(messages) is not tuple:
            raise ValueError("message batch must be a tuple")
        if type(updates) is not tuple:
            raise ValueError("message state updates must be a tuple")
        if any(type(message) is not ChatMessageMetadata for message in messages):
            raise ValueError("message batch contains invalid metadata")
        if any(type(update) is not ChatMessageStateUpdate for update in updates):
            raise ValueError("message state update has invalid type")
        if not messages and not updates:
            return ()

        persisted: list[ChatMessageMetadata] = []
        with closing(self._connect()) as db:
            db.execute("BEGIN IMMEDIATE")
            try:
                sequence_rows = db.execute(
                    """
                    SELECT sequence_no FROM collaboration_messages
                    WHERE room_id=? ORDER BY sequence_no
                    """,
                    (room_id,),
                ).fetchall()
                expected_sequence = 0
                for row in sequence_rows:
                    sequence = _stored_integer(
                        row["sequence_no"],
                        "message sequence",
                    )
                    if sequence != expected_sequence:
                        break
                    expected_sequence += 1

                for message in messages:
                    if message.room_id != room_id:
                        raise CollaborationStorageError(
                            "message batch crossed room boundary"
                        )
                    existing = db.execute(
                        "SELECT * FROM collaboration_messages WHERE message_id=?",
                        (message.message_id,),
                    ).fetchone()
                    if existing is not None:
                        loaded = self._message_from_row(existing)
                        immutable_fields = (
                            "message_id",
                            "room_id",
                            "sender_id",
                            "sequence_no",
                            "retention",
                        )
                        if any(
                            getattr(loaded, field) != getattr(message, field)
                            for field in immutable_fields
                        ) or (
                            not loaded.redacted
                            and not message.redacted
                            and loaded.body != message.body
                        ):
                            raise CollaborationConflictError(
                                "message identity reused with different payload"
                            )
                        if (
                            loaded.sent_at_unix_ms is not None
                            and message.sent_at_unix_ms is not None
                            and loaded.sent_at_unix_ms != message.sent_at_unix_ms
                        ):
                            raise CollaborationConflictError(
                                "message identity reused with different authoritative timestamp"
                            )
                        hidden = loaded.hidden or message.hidden
                        redacted = loaded.redacted or message.redacted
                        body = "" if redacted else loaded.body
                        sent_at = (
                            loaded.sent_at_unix_ms
                            if loaded.sent_at_unix_ms is not None
                            else message.sent_at_unix_ms
                        )
                        if (
                            hidden != loaded.hidden
                            or redacted != loaded.redacted
                            or body != loaded.body
                            or sent_at != loaded.sent_at_unix_ms
                        ):
                            db.execute(
                                """
                                UPDATE collaboration_messages
                                SET body=?, hidden=?, sent_at_unix_ms=?, redacted=?
                                WHERE message_id=?
                                """,
                                (
                                    body,
                                    int(hidden),
                                    sent_at,
                                    int(redacted),
                                    loaded.message_id,
                                ),
                            )
                            existing = db.execute(
                                "SELECT * FROM collaboration_messages WHERE message_id=?",
                                (loaded.message_id,),
                            ).fetchone()
                            loaded = self._message_from_row(existing)
                        persisted.append(loaded)
                        if message.sequence_no == expected_sequence:
                            expected_sequence += 1
                        elif message.sequence_no > expected_sequence:
                            raise CollaborationSequenceGapError(
                                "message sequence has an unresolved gap"
                            )
                        continue

                    if message.sequence_no != expected_sequence:
                        raise CollaborationSequenceGapError(
                            "message sequence has an unresolved gap"
                        )
                    try:
                        db.execute(
                            """
                            INSERT INTO collaboration_messages(
                                message_id, room_id, sender_id, sequence_no, body,
                                retention, hidden, sent_at_unix_ms, redacted
                            ) VALUES(?,?,?,?,?,?,?,?,?)
                            """,
                            (
                                message.message_id,
                                message.room_id,
                                message.sender_id,
                                message.sequence_no,
                                message.body,
                                message.retention,
                                int(message.hidden),
                                message.sent_at_unix_ms,
                                int(message.redacted),
                            ),
                        )
                    except sqlite3.IntegrityError as exc:
                        raise CollaborationConflictError(
                            "message batch conflicts with room ordering"
                        ) from exc
                    persisted.append(message)
                    expected_sequence += 1

                cursor = db.execute(
                    "SELECT revision FROM collaboration_chat_state_cursors WHERE room_id=?",
                    (room_id,),
                ).fetchone()
                previous = (
                    None
                    if cursor is None
                    else _stored_integer(
                        cursor["revision"],
                        "chat state revision",
                    )
                )
                for update in updates:
                    if update.room_id != room_id:
                        raise CollaborationStorageError(
                            "message state update crossed room boundary"
                        )
                    expected_revision = 0 if previous is None else previous + 1
                    if update.revision != expected_revision:
                        raise CollaborationStorageError(
                            "message state updates have an unresolved revision gap"
                        )
                    message_row = db.execute(
                        "SELECT room_id, retention, hidden, redacted "
                        "FROM collaboration_messages WHERE message_id=?",
                        (update.message_id,),
                    ).fetchone()
                    if message_row is None or message_row["room_id"] != room_id:
                        raise CollaborationStorageError(
                            "message state update references unknown room message"
                        )
                    hidden = _stored_boolean(
                        message_row["hidden"],
                        "message hidden flag",
                    )
                    redacted = _stored_boolean(
                        message_row["redacted"],
                        "message redacted flag",
                    )
                    if update.redacted and message_row["retention"] == "persistent":
                        raise CollaborationStorageError(
                            "persistent chat content cannot be retention-redacted"
                        )
                    if update.hidden and not hidden:
                        db.execute(
                            "UPDATE collaboration_messages SET hidden=1 WHERE message_id=?",
                            (update.message_id,),
                        )
                    if update.redacted and not redacted:
                        db.execute(
                            "UPDATE collaboration_messages "
                            "SET body='', redacted=1 WHERE message_id=?",
                            (update.message_id,),
                        )
                    db.execute(
                        """
                        INSERT INTO collaboration_chat_state_cursors(room_id, revision)
                        VALUES(?,?)
                        ON CONFLICT(room_id) DO UPDATE SET revision=excluded.revision
                        """,
                        (room_id, update.revision),
                    )
                    previous = update.revision
                db.commit()
            except Exception:
                db.rollback()
                raise
        return tuple(persisted)

    def room_messages(self, room_id: str, *, include_hidden: bool = False) -> tuple[ChatMessageMetadata, ...]:
        with closing(self._connect()) as db, db:
            messages = tuple(
                self._message_from_row(row)
                for row in db.execute(
                    "SELECT * FROM collaboration_messages "
                    "WHERE room_id=? ORDER BY sequence_no",
                    (room_id,),
                )
            )
        if include_hidden:
            return messages
        return tuple(message for message in messages if not message.hidden)

    def set_message_hidden(self, message_id: str, hidden: bool) -> ChatMessageMetadata:
        if type(hidden) is not bool:
            raise ValueError("hidden flag must be boolean")
        if hidden is not True:
            raise CollaborationStorageError(
                "message visibility cannot be restored through monotonic hide state"
            )
        with closing(self._connect()) as db, db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT * FROM collaboration_messages WHERE message_id=?", (message_id,)).fetchone()
            if row is None:
                raise CollaborationStorageError(f"unknown message: {message_id}")
            db.execute("UPDATE collaboration_messages SET hidden=? WHERE message_id=?", (int(hidden), message_id))
            updated = db.execute("SELECT * FROM collaboration_messages WHERE message_id=?", (message_id,)).fetchone()
        return self._message_from_row(updated)

    def chat_state_revision(self, room_id: str) -> int | None:
        _canonical_id(room_id, "room id")
        with closing(self._connect()) as db:
            row = db.execute(
                "SELECT revision FROM collaboration_chat_state_cursors WHERE room_id=?",
                (room_id,),
            ).fetchone()
        return (
            None
            if row is None
            else _stored_integer(
                row["revision"],
                "chat state revision",
            )
        )

    def apply_message_state_updates(
        self,
        *,
        room_id: str,
        updates: tuple[ChatMessageStateUpdate, ...],
    ) -> None:
        _canonical_id(room_id, "room id")
        if type(updates) is not tuple:
            raise ValueError("message state updates must be a tuple")
        if not updates:
            return
        if any(type(update) is not ChatMessageStateUpdate for update in updates):
            raise ValueError("message state update has invalid type")
        with closing(self._connect()) as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT revision FROM collaboration_chat_state_cursors WHERE room_id=?",
                (room_id,),
            ).fetchone()
            previous = (
                None
                if row is None
                else _stored_integer(
                    row["revision"],
                    "chat state revision",
                )
            )
            try:
                for update in updates:
                    if update.room_id != room_id:
                        raise CollaborationStorageError(
                            "message state update crossed room boundary"
                        )
                    expected_revision = 0 if previous is None else previous + 1
                    if update.revision != expected_revision:
                        raise CollaborationStorageError(
                            "message state updates have an unresolved revision gap"
                        )
                    message = db.execute(
                        """
                        SELECT room_id, retention, hidden, redacted
                        FROM collaboration_messages
                        WHERE message_id=?
                        """,
                        (update.message_id,),
                    ).fetchone()
                    if message is None or message["room_id"] != room_id:
                        raise CollaborationStorageError(
                            "message state update references unknown room message"
                        )
                    hidden = _stored_boolean(
                        message["hidden"],
                        "message hidden flag",
                    )
                    redacted = _stored_boolean(
                        message["redacted"],
                        "message redacted flag",
                    )
                    if update.redacted and message["retention"] == "persistent":
                        raise CollaborationStorageError(
                            "persistent chat content cannot be retention-redacted"
                        )
                    if update.hidden and not hidden:
                        db.execute(
                            "UPDATE collaboration_messages SET hidden=1 WHERE message_id=?",
                            (update.message_id,),
                        )
                    if update.redacted and not redacted:
                        db.execute(
                            "UPDATE collaboration_messages "
                            "SET body='', redacted=1 WHERE message_id=?",
                            (update.message_id,),
                        )
                    db.execute(
                        """
                        INSERT INTO collaboration_chat_state_cursors(room_id, revision)
                        VALUES(?,?)
                        ON CONFLICT(room_id) DO UPDATE SET revision=excluded.revision
                        """,
                        (room_id, update.revision),
                    )
                    previous = update.revision
                db.commit()
            except Exception:
                db.rollback()
                raise

    def register_attachment(
        self,
        attachment: AttachmentMetadata,
        *,
        max_room_bytes: int | None = None,
    ) -> AttachmentMetadata:
        safe_name = safe_display_filename(attachment.display_name)
        if safe_name != attachment.display_name:
            raise ValueError("display_name must already be sanitized")
        _safe_object_key(attachment.object_key)
        if max_room_bytes is not None and (
            type(max_room_bytes) is not int or max_room_bytes <= 0
        ):
            raise ValueError("max_room_bytes must be a positive integer")
        with closing(self._connect()) as db, db:
            # Serialize quota accounting with registration so two concurrent
            # uploads cannot both reserve the same remaining room capacity.
            db.execute("BEGIN IMMEDIATE")
            existing = db.execute(
                "SELECT * FROM collaboration_attachments WHERE attachment_id=?",
                (attachment.attachment_id,),
            ).fetchone()
            if existing is not None:
                loaded = self._attachment_from_row(existing)
                if loaded != attachment:
                    raise CollaborationConflictError(
                        "attachment identity reused with different payload"
                    )
                return loaded
            if max_room_bytes is not None:
                used = _stored_integer(
                    db.execute(
                        """
                        SELECT COALESCE(SUM(size_bytes), 0)
                        FROM collaboration_attachments
                        WHERE room_id=? AND transfer_state!='deleted'
                        """,
                        (attachment.room_id,),
                    ).fetchone()[0],
                    "room attachment byte usage",
                )
                if used + attachment.size_bytes > max_room_bytes:
                    raise CollaborationQuotaError(
                        "room file quota would be exceeded"
                    )
            try:
                db.execute(
                    "INSERT INTO collaboration_attachments VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        attachment.attachment_id,
                        attachment.room_id,
                        attachment.sender_id,
                        attachment.sequence_no,
                        attachment.display_name,
                        attachment.mime_type,
                        attachment.size_bytes,
                        attachment.sha256,
                        attachment.object_key,
                        attachment.transfer_state,
                        attachment.retention,
                        attachment.scan_state,
                    ),
                )
            except sqlite3.IntegrityError as exc:
                raise CollaborationConflictError(
                    "attachment conflicts with ordering or storage identity"
                ) from exc
            if attachment.transfer_state == "deleted":
                _queue_attachment_deletion(db, attachment)
        return attachment

    def discard_provisional_attachment(
        self,
        attachment_id: str,
    ) -> AttachmentMetadata:
        _canonical_id(attachment_id, "attachment id")
        with closing(self._connect()) as db:
            db.execute("BEGIN IMMEDIATE")
            try:
                row = db.execute(
                    "SELECT * FROM collaboration_attachments WHERE attachment_id=?",
                    (attachment_id,),
                ).fetchone()
                if row is None:
                    raise CollaborationStorageError(
                        f"unknown attachment: {attachment_id}"
                    )
                current = self._attachment_from_row(row)
                if current.transfer_state not in {"pending", "uploading", "failed"}:
                    raise CollaborationStorageError(
                        "only provisional attachment metadata can be discarded"
                    )
                _validate_transfer_transition(current.transfer_state, "deleted")
                tombstone = AttachmentMetadata(
                    current.attachment_id,
                    current.room_id,
                    current.sender_id,
                    current.sequence_no,
                    current.display_name,
                    current.mime_type,
                    current.size_bytes,
                    current.sha256,
                    current.object_key,
                    "deleted",
                    current.retention,
                    current.scan_state,
                )
                db.execute(
                    "DELETE FROM collaboration_attachments WHERE attachment_id=?",
                    (attachment_id,),
                )
                db.commit()
            except Exception:
                db.rollback()
                raise
        return tombstone

    def register_attachments_atomic(
        self,
        attachments: tuple[AttachmentMetadata, ...],
    ) -> tuple[AttachmentMetadata, ...]:
        if type(attachments) is not tuple:
            raise ValueError("attachment batch must be a tuple")
        for attachment in attachments:
            if type(attachment) is not AttachmentMetadata:
                raise ValueError("attachment batch contains invalid metadata")
            if safe_display_filename(attachment.display_name) != attachment.display_name:
                raise ValueError("display_name must already be sanitized")
            _safe_object_key(attachment.object_key)
            if attachment.transfer_state not in {"stored", "deleted"}:
                raise CollaborationStorageError(
                    "attachment sync requires authoritative terminal metadata"
                )
        if not attachments:
            return ()

        persisted: list[AttachmentMetadata] = []
        with closing(self._connect()) as db, db:
            db.execute("BEGIN IMMEDIATE")
            expected_by_room: dict[str, int] = {}
            for attachment in attachments:
                expected_sequence = expected_by_room.get(attachment.room_id)
                if expected_sequence is None:
                    expected_sequence = _next_authoritative_attachment_sequence(
                        db,
                        attachment.room_id,
                    )
                if attachment.sequence_no > expected_sequence:
                    raise CollaborationSequenceGapError(
                        "attachment sequence has an unresolved gap"
                    )
                existing = db.execute(
                    "SELECT * FROM collaboration_attachments WHERE attachment_id=?",
                    (attachment.attachment_id,),
                ).fetchone()
                if existing is not None:
                    loaded = self._attachment_from_row(existing)
                    if loaded != attachment:
                        raise CollaborationConflictError(
                            "attachment identity reused with different payload"
                        )
                    persisted.append(loaded)
                    if attachment.sequence_no == expected_sequence:
                        expected_sequence += 1
                    expected_by_room[attachment.room_id] = expected_sequence
                    continue
                try:
                    db.execute(
                        "INSERT INTO collaboration_attachments VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                        (
                            attachment.attachment_id,
                            attachment.room_id,
                            attachment.sender_id,
                            attachment.sequence_no,
                            attachment.display_name,
                            attachment.mime_type,
                            attachment.size_bytes,
                            attachment.sha256,
                            attachment.object_key,
                            attachment.transfer_state,
                            attachment.retention,
                            attachment.scan_state,
                        ),
                    )
                except sqlite3.IntegrityError as exc:
                    raise CollaborationConflictError(
                        "attachment batch conflicts with ordering or storage identity"
                    ) from exc
                if attachment.transfer_state == "deleted":
                    _queue_attachment_deletion(db, attachment)
                persisted.append(attachment)
                if attachment.sequence_no == expected_sequence:
                    expected_sequence += 1
                expected_by_room[attachment.room_id] = expected_sequence
        return tuple(persisted)

    def reconcile_attachment_sync_atomic(
        self,
        *,
        room_id: str,
        attachments: tuple[AttachmentMetadata, ...],
        updates: tuple[AttachmentStateUpdate, ...],
        snapshot_state_revision: int | None = None,
    ) -> tuple[AttachmentMetadata, ...]:
        _canonical_id(room_id, "room id")
        if type(attachments) is not tuple:
            raise ValueError("attachment batch must be a tuple")
        if type(updates) is not tuple:
            raise ValueError("attachment state updates must be a tuple")
        for attachment in attachments:
            if type(attachment) is not AttachmentMetadata:
                raise ValueError("attachment batch contains invalid metadata")
            if attachment.room_id != room_id:
                raise CollaborationStorageError(
                    "attachment batch crossed room boundary"
                )
            if safe_display_filename(attachment.display_name) != attachment.display_name:
                raise ValueError("display_name must already be sanitized")
            _safe_object_key(attachment.object_key)
        if any(type(update) is not AttachmentStateUpdate for update in updates):
            raise ValueError("attachment state update has invalid type")
        if snapshot_state_revision is not None and (
            type(snapshot_state_revision) is not int
            or not 0 <= snapshot_state_revision <= MAX_WIRE_INTEGER
        ):
            raise ValueError(
                "snapshot_state_revision must be a bounded JSON-safe integer"
            )
        if not attachments and not updates:
            return ()

        persisted: list[AttachmentMetadata] = []
        with closing(self._connect()) as db:
            db.execute("BEGIN IMMEDIATE")
            try:
                expected_sequence = _next_authoritative_attachment_sequence(
                    db,
                    room_id,
                )
                for attachment in attachments:
                    if attachment.sequence_no > expected_sequence:
                        raise CollaborationSequenceGapError(
                            "attachment sequence has an unresolved gap"
                        )
                    existing = db.execute(
                        "SELECT * FROM collaboration_attachments WHERE attachment_id=?",
                        (attachment.attachment_id,),
                    ).fetchone()
                    if existing is not None:
                        loaded = self._attachment_from_row(existing)
                        if loaded == attachment:
                            persisted.append(loaded)
                            if attachment.sequence_no == expected_sequence:
                                expected_sequence += 1
                            continue
                        immutable = (
                            "attachment_id",
                            "room_id",
                            "sender_id",
                            "display_name",
                            "mime_type",
                            "size_bytes",
                            "sha256",
                            "object_key",
                            "retention",
                        )
                        if any(
                            getattr(loaded, field) != getattr(attachment, field)
                            for field in immutable
                        ):
                            raise CollaborationConflictError(
                                "attachment identity reused with different payload"
                            )
                        if loaded.transfer_state in {"uploading", "failed"}:
                            # A provider call can succeed remotely even when the
                            # client crashes or observes an ambiguous failure.
                            # Server history owns sequence and terminal state,
                            # except that a malware-blocked failure may only be
                            # made safer by authoritative deletion.
                            if (
                                loaded.scan_state == "blocked"
                                and attachment.transfer_state != "deleted"
                            ):
                                raise CollaborationConflictError(
                                    "blocked attachment cannot be restored by sync authority"
                                )
                        else:
                            if loaded.sequence_no != attachment.sequence_no:
                                raise CollaborationConflictError(
                                    "authoritative attachment sequence changed"
                                )
                            _validate_transfer_transition(
                                loaded.transfer_state,
                                attachment.transfer_state,
                            )
                            _validate_scan_transition(
                                loaded.scan_state,
                                attachment.scan_state,
                            )
                        try:
                            db.execute(
                                """
                                UPDATE collaboration_attachments
                                SET sequence_no=?, transfer_state=?, scan_state=?
                                WHERE attachment_id=?
                                """,
                                (
                                    attachment.sequence_no,
                                    attachment.transfer_state,
                                    attachment.scan_state,
                                    attachment.attachment_id,
                                ),
                            )
                        except sqlite3.IntegrityError as exc:
                            raise CollaborationConflictError(
                                "authoritative attachment conflicts with room ordering"
                            ) from exc
                        if (
                            loaded.transfer_state != "deleted"
                            and attachment.transfer_state == "deleted"
                        ):
                            _queue_attachment_deletion(db, attachment)
                        persisted.append(attachment)
                        if attachment.sequence_no == expected_sequence:
                            expected_sequence += 1
                        continue
                    try:
                        db.execute(
                            "INSERT INTO collaboration_attachments VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                            (
                                attachment.attachment_id,
                                attachment.room_id,
                                attachment.sender_id,
                                attachment.sequence_no,
                                attachment.display_name,
                                attachment.mime_type,
                                attachment.size_bytes,
                                attachment.sha256,
                                attachment.object_key,
                                attachment.transfer_state,
                                attachment.retention,
                                attachment.scan_state,
                            ),
                        )
                    except sqlite3.IntegrityError as exc:
                        raise CollaborationConflictError(
                            "attachment batch conflicts with ordering or storage identity"
                        ) from exc
                    if attachment.transfer_state == "deleted":
                        _queue_attachment_deletion(db, attachment)
                    persisted.append(attachment)
                    if attachment.sequence_no == expected_sequence:
                        expected_sequence += 1

                for attachment in attachments:
                    watermark = db.execute(
                        """
                        SELECT room_id, revision
                        FROM collaboration_attachment_snapshot_watermarks
                        WHERE attachment_id=?
                        """,
                        (attachment.attachment_id,),
                    ).fetchone()
                    if watermark is not None:
                        stored_revision = _stored_snapshot_revision(
                            watermark["revision"]
                        )
                        if (
                            snapshot_state_revision is None
                            or watermark["room_id"] != room_id
                            or stored_revision > snapshot_state_revision
                        ):
                            raise CollaborationStorageError(
                                "attachment snapshot state watermark regressed"
                            )
                    if snapshot_state_revision is not None:
                        db.execute(
                            """
                            INSERT INTO collaboration_attachment_snapshot_watermarks(
                                attachment_id, room_id, revision
                            )
                            VALUES(?,?,?)
                            ON CONFLICT(attachment_id) DO UPDATE SET
                                room_id=excluded.room_id,
                                revision=excluded.revision
                            """,
                            (
                                attachment.attachment_id,
                                room_id,
                                snapshot_state_revision,
                            ),
                        )

                cursor = db.execute(
                    "SELECT revision FROM collaboration_attachment_state_cursors WHERE room_id=?",
                    (room_id,),
                ).fetchone()
                previous = (
                    None
                    if cursor is None
                    else _stored_integer(
                        cursor["revision"],
                        "attachment state revision",
                    )
                )
                for update in updates:
                    if update.room_id != room_id:
                        raise CollaborationStorageError(
                            "attachment state update crossed room boundary"
                        )
                    expected_revision = 0 if previous is None else previous + 1
                    if update.revision != expected_revision:
                        raise CollaborationStorageError(
                            "attachment state updates have an unresolved revision gap"
                        )
                    row = db.execute(
                        "SELECT * FROM collaboration_attachments WHERE attachment_id=?",
                        (update.attachment_id,),
                    ).fetchone()
                    if row is None or row["room_id"] != room_id:
                        raise CollaborationStorageError(
                            "attachment state update references unknown room attachment"
                        )
                    watermark = db.execute(
                        """
                        SELECT room_id, revision
                        FROM collaboration_attachment_snapshot_watermarks
                        WHERE attachment_id=?
                        """,
                        (update.attachment_id,),
                    ).fetchone()
                    watermark_revision: int | None = None
                    if watermark is not None:
                        if watermark["room_id"] != room_id:
                            raise CollaborationStorageError(
                                "stored attachment snapshot watermark crossed room boundary"
                            )
                        watermark_revision = _stored_snapshot_revision(watermark["revision"])
                    covered_by_snapshot = (
                        watermark_revision is not None
                        and watermark["room_id"] == room_id
                        and update.revision <= watermark_revision
                    )
                    if not covered_by_snapshot:
                        current = self._attachment_from_row(row)
                        if current.transfer_state not in {"stored", "deleted"}:
                            raise CollaborationStorageError(
                                "attachment state update requires authoritative history"
                            )
                        _validate_transfer_transition(
                            current.transfer_state,
                            update.transfer_state,
                        )
                        _validate_scan_transition(
                            current.scan_state,
                            update.scan_state,
                        )
                        db.execute(
                            """
                            UPDATE collaboration_attachments
                            SET transfer_state=?, scan_state=?
                            WHERE attachment_id=?
                            """,
                            (
                                update.transfer_state,
                                update.scan_state,
                                update.attachment_id,
                            ),
                        )
                        if (
                            current.transfer_state != "deleted"
                            and update.transfer_state == "deleted"
                        ):
                            _queue_attachment_deletion(
                                db,
                                AttachmentMetadata(
                                    current.attachment_id,
                                    current.room_id,
                                    current.sender_id,
                                    current.sequence_no,
                                    current.display_name,
                                    current.mime_type,
                                    current.size_bytes,
                                    current.sha256,
                                    current.object_key,
                                    "deleted",
                                    current.retention,
                                    update.scan_state,
                                ),
                            )
                    db.execute(
                        """
                        INSERT INTO collaboration_attachment_state_cursors(room_id, revision)
                        VALUES(?,?)
                        ON CONFLICT(room_id) DO UPDATE SET revision=excluded.revision
                        """,
                        (room_id, update.revision),
                    )
                    previous = update.revision
                db.commit()
            except Exception:
                db.rollback()
                raise
        return tuple(persisted)

    def adopt_authoritative_attachment(
        self,
        attachment: AttachmentMetadata,
    ) -> AttachmentMetadata:
        if type(attachment) is not AttachmentMetadata:
            raise ValueError("authoritative attachment metadata has invalid type")
        with closing(self._connect()) as db, db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT * FROM collaboration_attachments WHERE attachment_id=?",
                (attachment.attachment_id,),
            ).fetchone()
            if row is None:
                raise CollaborationStorageError(
                    f"unknown attachment: {attachment.attachment_id}"
                )
            current = self._attachment_from_row(row)
            immutable = (
                "attachment_id",
                "room_id",
                "sender_id",
                "display_name",
                "mime_type",
                "size_bytes",
                "sha256",
                "object_key",
                "retention",
            )
            if any(
                getattr(current, field) != getattr(attachment, field)
                for field in immutable
            ):
                raise CollaborationConflictError(
                    "file authority changed immutable attachment identity"
                )
            if current == attachment:
                return current
            if current.transfer_state != "uploading":
                raise CollaborationConflictError(
                    "file authority arrived outside active upload transition"
                )
            if attachment.transfer_state in {"stored", "deleted"}:
                expected_sequence = _next_authoritative_attachment_sequence(
                    db,
                    current.room_id,
                )
                if attachment.sequence_no > expected_sequence:
                    raise CollaborationSequenceGapError(
                        "attachment sequence has an unresolved gap"
                    )
            _validate_transfer_transition(
                current.transfer_state,
                attachment.transfer_state,
            )
            _validate_scan_transition(current.scan_state, attachment.scan_state)
            try:
                db.execute(
                    """
                    UPDATE collaboration_attachments
                    SET sequence_no=?, transfer_state=?, scan_state=?
                    WHERE attachment_id=?
                    """,
                    (
                        attachment.sequence_no,
                        attachment.transfer_state,
                        attachment.scan_state,
                        attachment.attachment_id,
                    ),
                )
            except sqlite3.IntegrityError as exc:
                raise CollaborationConflictError(
                    "authoritative attachment conflicts with room ordering"
                ) from exc
            if attachment.transfer_state == "deleted":
                _queue_attachment_deletion(db, attachment)
            updated = db.execute(
                "SELECT * FROM collaboration_attachments WHERE attachment_id=?",
                (attachment.attachment_id,),
            ).fetchone()
        return self._attachment_from_row(updated)

    def update_attachment_state(
        self, attachment_id: str, *, transfer_state: str, scan_state: str | None = None
    ) -> AttachmentMetadata:
        with closing(self._connect()) as db, db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT * FROM collaboration_attachments WHERE attachment_id=?", (attachment_id,)).fetchone()
            if row is None:
                raise CollaborationStorageError(f"unknown attachment: {attachment_id}")
            current = self._attachment_from_row(row)
            _validate_transfer_transition(current.transfer_state, transfer_state)
            next_scan = current.scan_state if scan_state is None else scan_state
            _validate_scan_transition(current.scan_state, next_scan)
            candidate = AttachmentMetadata(
                current.attachment_id, current.room_id, current.sender_id, current.sequence_no,
                current.display_name, current.mime_type, current.size_bytes, current.sha256,
                current.object_key, transfer_state, current.retention, next_scan,
            )
            db.execute(
                "UPDATE collaboration_attachments SET transfer_state=?, scan_state=? WHERE attachment_id=?",
                (candidate.transfer_state, candidate.scan_state, attachment_id),
            )
            if (
                current.transfer_state != "deleted"
                and candidate.transfer_state == "deleted"
            ):
                _queue_attachment_deletion(db, candidate)
        return candidate

    def room_attachments(self, room_id: str) -> tuple[AttachmentMetadata, ...]:
        with closing(self._connect()) as db, db:
            return tuple(
                self._attachment_from_row(row)
                for row in db.execute(
                    "SELECT * FROM collaboration_attachments "
                    "WHERE room_id=? ORDER BY sequence_no, attachment_id",
                    (room_id,),
                )
            )

    def pending_attachment_deletions(self, room_id: str) -> tuple[str, ...]:
        room = _canonical_id(room_id, "room id")
        with closing(self._connect()) as db:
            rows = db.execute(
                """
                SELECT d.room_id, d.attachment_id, d.object_key, d.completed,
                       a.room_id AS attachment_room_id,
                       a.object_key AS attachment_object_key,
                       a.transfer_state AS attachment_transfer_state
                FROM collaboration_attachment_deletions AS d
                LEFT JOIN collaboration_attachments AS a
                  ON a.attachment_id=d.attachment_id
                WHERE d.room_id=?
                ORDER BY d.attachment_id
                """,
                (room,),
            ).fetchall()
        pending: list[str] = []
        for row in rows:
            deletion_room, _attachment_id, deletion_key, completed = (
                self._deletion_intent_from_row(row)
            )
            if (
                deletion_room != room
                or row["attachment_room_id"] != deletion_room
                or row["attachment_object_key"] != deletion_key
                or row["attachment_transfer_state"] != "deleted"
            ):
                raise CollaborationStorageError(
                    "attachment deletion intent is inconsistent with tombstone metadata"
                )
            if not completed:
                pending.append(deletion_key)
        return tuple(pending)

    def acknowledge_attachment_deletion(
        self,
        *,
        room_id: str,
        object_key: str,
    ) -> None:
        room = _canonical_id(room_id, "room id")
        key = _safe_object_key(object_key)
        with closing(self._connect()) as db, db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                """
                SELECT room_id, attachment_id, object_key, completed
                FROM collaboration_attachment_deletions
                WHERE object_key=?
                """,
                (key,),
            ).fetchone()
            if row is None:
                raise CollaborationStorageError(
                    "attachment deletion acknowledgement has no durable intent"
                )
            deletion_room, deletion_attachment_id, deletion_key, completed = (
                self._deletion_intent_from_row(row)
            )
            if deletion_room != room:
                raise CollaborationStorageError(
                    "attachment deletion acknowledgement crossed room boundary"
                )
            if deletion_key != key:
                raise CollaborationStorageError(
                    "attachment deletion acknowledgement changed storage identity"
                )
            attachment_row = db.execute(
                "SELECT * FROM collaboration_attachments WHERE attachment_id=?",
                (deletion_attachment_id,),
            ).fetchone()
            if attachment_row is None:
                raise CollaborationStorageError(
                    "attachment deletion acknowledgement lost tombstone metadata"
                )
            attachment = self._attachment_from_row(attachment_row)
            if (
                attachment.room_id != room
                or attachment.object_key != key
                or attachment.transfer_state != "deleted"
            ):
                raise CollaborationStorageError(
                    "attachment deletion acknowledgement does not match tombstone"
                )
            if not completed:
                db.execute(
                    """
                    UPDATE collaboration_attachment_deletions
                    SET completed=1
                    WHERE object_key=?
                    """,
                    (key,),
                )

    def attachment_snapshot_state_revision(
        self,
        attachment_id: str,
    ) -> int | None:
        _canonical_id(attachment_id, "attachment id")
        with closing(self._connect()) as db:
            row = db.execute(
                """
                SELECT
                    watermark.room_id,
                    watermark.revision,
                    attachment.room_id AS attachment_room_id
                FROM collaboration_attachment_snapshot_watermarks AS watermark
                LEFT JOIN collaboration_attachments AS attachment
                    ON attachment.attachment_id=watermark.attachment_id
                WHERE watermark.attachment_id=?
                """,
                (attachment_id,),
            ).fetchone()
        if row is None:
            return None
        if (
            row["attachment_room_id"] is None
            or row["room_id"] != row["attachment_room_id"]
        ):
            raise CollaborationStorageError(
                "stored attachment snapshot watermark crossed room boundary"
            )
        return _stored_snapshot_revision(row["revision"])

    def attachment_state_revision(self, room_id: str) -> int | None:
        _canonical_id(room_id, "room id")
        with closing(self._connect()) as db:
            row = db.execute(
                "SELECT revision FROM collaboration_attachment_state_cursors WHERE room_id=?",
                (room_id,),
            ).fetchone()
        return (
            None
            if row is None
            else _stored_integer(
                row["revision"],
                "attachment state revision",
            )
        )

    def apply_attachment_state_updates(
        self,
        *,
        room_id: str,
        updates: tuple[AttachmentStateUpdate, ...],
    ) -> tuple[AttachmentMetadata, ...]:
        _canonical_id(room_id, "room id")
        if type(updates) is not tuple:
            raise ValueError("attachment state updates must be a tuple")
        if any(type(update) is not AttachmentStateUpdate for update in updates):
            raise ValueError("attachment state update has invalid type")
        if not updates:
            return ()

        persisted: list[AttachmentMetadata] = []
        with closing(self._connect()) as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT revision FROM collaboration_attachment_state_cursors WHERE room_id=?",
                (room_id,),
            ).fetchone()
            previous = (
                None
                if row is None
                else _stored_integer(
                    row["revision"],
                    "attachment state revision",
                )
            )
            try:
                for update in updates:
                    if update.room_id != room_id:
                        raise CollaborationStorageError(
                            "attachment state update crossed room boundary"
                        )
                    expected_revision = 0 if previous is None else previous + 1
                    if update.revision != expected_revision:
                        raise CollaborationStorageError(
                            "attachment state updates have an unresolved revision gap"
                        )
                    row = db.execute(
                        "SELECT * FROM collaboration_attachments WHERE attachment_id=?",
                        (update.attachment_id,),
                    ).fetchone()
                    if row is None or row["room_id"] != room_id:
                        raise CollaborationStorageError(
                            "attachment state update references unknown room attachment"
                        )
                    current = self._attachment_from_row(row)
                    if current.transfer_state not in {"stored", "deleted"}:
                        raise CollaborationStorageError(
                            "attachment state update requires authoritative history"
                        )
                    _validate_transfer_transition(
                        current.transfer_state,
                        update.transfer_state,
                    )
                    _validate_scan_transition(
                        current.scan_state,
                        update.scan_state,
                    )
                    candidate = AttachmentMetadata(
                        current.attachment_id,
                        current.room_id,
                        current.sender_id,
                        current.sequence_no,
                        current.display_name,
                        current.mime_type,
                        current.size_bytes,
                        current.sha256,
                        current.object_key,
                        update.transfer_state,
                        current.retention,
                        update.scan_state,
                    )
                    db.execute(
                        """
                        UPDATE collaboration_attachments
                        SET transfer_state=?, scan_state=?
                        WHERE attachment_id=?
                        """,
                        (
                            candidate.transfer_state,
                            candidate.scan_state,
                            candidate.attachment_id,
                        ),
                    )
                    if (
                        current.transfer_state != "deleted"
                        and candidate.transfer_state == "deleted"
                    ):
                        _queue_attachment_deletion(db, candidate)
                    db.execute(
                        """
                        INSERT INTO collaboration_attachment_state_cursors(room_id, revision)
                        VALUES(?,?)
                        ON CONFLICT(room_id) DO UPDATE SET revision=excluded.revision
                        """,
                        (room_id, update.revision),
                    )
                    previous = update.revision
                    persisted.append(candidate)
                db.commit()
            except Exception:
                db.rollback()
                raise
        return tuple(persisted)

    def integrity_check(self) -> None:
        with closing(self._connect()) as db, db:
            result = db.execute("PRAGMA integrity_check").fetchone()[0]
            if result != "ok":
                raise CollaborationStorageError(f"sqlite integrity check failed: {result}")

            schema = db.execute(
                "SELECT value FROM collaboration_schema_meta "
                "WHERE key='schema_version'"
            ).fetchone()
            if (
                schema is None
                or _stored_integer(schema["value"], "schema version")
                != SCHEMA_VERSION
            ):
                raise CollaborationStorageError(
                    "collaboration schema version is not current"
                )

            for row in db.execute("SELECT * FROM collaboration_messages"):
                self._message_from_row(row)
            for row in db.execute("SELECT * FROM collaboration_attachments"):
                self._attachment_from_row(row)
            for table, label in (
                ("collaboration_chat_state_cursors", "chat state revision"),
                (
                    "collaboration_attachment_state_cursors",
                    "attachment state revision",
                ),
            ):
                for cursor in db.execute(
                    f"SELECT room_id, revision FROM {table}"
                ):
                    try:
                        _canonical_id(cursor["room_id"], "state cursor room id")
                    except ValueError as error:
                        raise CollaborationStorageError(
                            "stored state cursor room id is invalid"
                        ) from error
                    _stored_integer(cursor["revision"], label)

            for watermark in db.execute(
                """
                SELECT
                    watermark.attachment_id,
                    watermark.room_id,
                    watermark.revision,
                    attachment.room_id AS attachment_room_id
                FROM collaboration_attachment_snapshot_watermarks AS watermark
                LEFT JOIN collaboration_attachments AS attachment
                    ON attachment.attachment_id=watermark.attachment_id
                """
            ):
                try:
                    _canonical_id(
                        watermark["attachment_id"],
                        "snapshot watermark attachment id",
                    )
                    _canonical_id(
                        watermark["room_id"],
                        "snapshot watermark room id",
                    )
                except ValueError as error:
                    raise CollaborationStorageError(
                        "stored attachment snapshot watermark identity is invalid"
                    ) from error
                _stored_snapshot_revision(watermark["revision"])
                if (
                    watermark["attachment_room_id"] is None
                    or watermark["room_id"] != watermark["attachment_room_id"]
                ):
                    raise CollaborationStorageError(
                        "stored attachment snapshot watermark crossed room boundary"
                    )

            for deletion in db.execute(
                """
                SELECT room_id, attachment_id, object_key, completed
                FROM collaboration_attachment_deletions
                """
            ):
                room, attachment_id, object_key, _completed = (
                    self._deletion_intent_from_row(deletion)
                )
                row = db.execute(
                    "SELECT * FROM collaboration_attachments WHERE attachment_id=?",
                    (attachment_id,),
                ).fetchone()
                if row is None:
                    raise CollaborationStorageError(
                        "attachment deletion intent references missing tombstone"
                    )
                attachment = self._attachment_from_row(row)
                if (
                    attachment.room_id != room
                    or attachment.object_key != object_key
                    or attachment.transfer_state != "deleted"
                ):
                    raise CollaborationStorageError(
                        "attachment deletion intent is inconsistent with tombstone"
                    )

            for tombstone_row in db.execute(
                """
                SELECT *
                FROM collaboration_attachments
                WHERE transfer_state='deleted'
                """
            ):
                tombstone = self._attachment_from_row(tombstone_row)
                receipt = db.execute(
                    """
                    SELECT room_id, attachment_id, object_key, completed
                    FROM collaboration_attachment_deletions
                    WHERE attachment_id=?
                    """,
                    (tombstone.attachment_id,),
                ).fetchone()
                if receipt is None:
                    raise CollaborationStorageError(
                        "attachment tombstone is missing durable deletion record"
                    )
                room, attachment_id, object_key, _completed = (
                    self._deletion_intent_from_row(receipt)
                )
                if (
                    room != tombstone.room_id
                    or attachment_id != tombstone.attachment_id
                    or object_key != tombstone.object_key
                ):
                    raise CollaborationStorageError(
                        "attachment tombstone deletion record changed storage identity"
                    )

    @staticmethod
    def _deletion_intent_from_row(
        row: sqlite3.Row,
    ) -> tuple[str, str, str, bool]:
        try:
            return (
                _canonical_id(row["room_id"], "deletion room id"),
                _canonical_id(row["attachment_id"], "deletion attachment id"),
                _safe_object_key(row["object_key"]),
                _stored_boolean(row["completed"], "deletion completion flag"),
            )
        except (TypeError, ValueError, KeyError, IndexError, OverflowError) as error:
            raise CollaborationStorageError(
                "stored attachment deletion intent is invalid"
            ) from error

    @staticmethod
    def _message_from_row(row: sqlite3.Row) -> ChatMessageMetadata:
        try:
            return ChatMessageMetadata(
                row["message_id"],
                row["room_id"],
                row["sender_id"],
                _stored_integer(row["sequence_no"], "message sequence"),
                row["body"],
                row["retention"],
                _stored_boolean(row["hidden"], "message hidden flag"),
                (
                    _stored_integer(
                        row["sent_at_unix_ms"],
                        "message timestamp",
                        maximum=MAX_CHAT_TIMESTAMP_UNIX_MS,
                    )
                    if row["sent_at_unix_ms"] is not None
                    else None
                ),
                _stored_boolean(row["redacted"], "message redacted flag"),
            )
        except CollaborationStorageError:
            raise
        except (TypeError, ValueError, KeyError, IndexError, OverflowError) as error:
            raise CollaborationStorageError(
                "stored chat message metadata is invalid"
            ) from error

    @staticmethod
    def _attachment_from_row(row: sqlite3.Row) -> AttachmentMetadata:
        try:
            return AttachmentMetadata(
                row["attachment_id"],
                row["room_id"],
                row["sender_id"],
                _stored_integer(row["sequence_no"], "attachment sequence"),
                row["display_name"],
                row["mime_type"],
                _stored_integer(row["size_bytes"], "attachment size"),
                row["sha256"],
                row["object_key"],
                row["transfer_state"],
                row["retention"],
                row["scan_state"],
            )
        except CollaborationStorageError:
            raise
        except (TypeError, ValueError, KeyError, IndexError, OverflowError) as error:
            raise CollaborationStorageError(
                "stored attachment metadata is invalid"
            ) from error
