from __future__ import annotations

"""Trusted provider-neutral server authority for classroom file collaboration.

The desktop-facing adapter implements the canonical FileTransferPort/FileStorePort
contracts but owns no provider secret. Authorization, malware scanning, durable
object storage and short-lived read-token issuance are injected on the trusted
server side. SQLite owns only authoritative attachment metadata/recovery state.
"""

from contextlib import closing
from dataclasses import replace
import hashlib
from pathlib import Path
import sqlite3
from typing import Callable, Protocol

from .classroom_domain import MAX_WIRE_INTEGER
from .classroom_collaboration import (
    MAX_DOWNLOAD_TOKEN_CHARS,
    AttachmentHistoryPage,
    MAX_SYNC_ATTACHMENTS,
    FileQuotaPolicy,
    FileTransferProgress,
    PreparedFile,
    _canonical_object_key,
    _id,
)
from .classroom_collaboration_storage import (
    AttachmentMetadata,
    AttachmentStateUpdate,
    CollaborationConflictError,
    CollaborationQuotaError,
    FileStorePort,
)


SERVER_SCHEMA_VERSION = 1
_FILE_READ_CHUNK_BYTES = 1024 * 1024


class ClassroomFileServerError(RuntimeError):
    """Sanitized trusted file-server failure."""


class ClassroomFileAuthorizationPort(Protocol):
    """Canonical external room/membership policy; this service does not own roster truth."""

    def authorize_file_action(
        self,
        *,
        trusted_caller_identity: str,
        room_id: str,
        action: str,
        attachment_id: str | None,
        retention: str | None,
    ) -> bool:
        ...


class ClassroomFileScannerPort(Protocol):
    """Server-side opaque-byte scan boundary."""

    def scan(
        self,
        *,
        room_id: str,
        sender_id: str,
        display_name: str,
        sha256: str,
        content: bytes,
    ) -> str:
        """Return exactly clean, blocked or failed."""
        ...


class ClassroomFileObjectStorePort(FileStorePort, Protocol):
    """Durable object authority with exact retry reconciliation.

    stored_sha256 is the authoritative pre-retry observation. It returns the
    lowercase SHA-256 of the complete durable object, None when the object is
    definitely absent, and raises when presence/integrity cannot be established.
    The file server never blindly repeats an ambiguous PUT.
    """

    def stored_sha256(self, *, object_key: str) -> str | None:
        ...


def _server_id(value: object, label: str) -> str:
    try:
        return _id(value, label)
    except Exception as error:
        raise ClassroomFileServerError(f"invalid {label}") from None


def _bounded_cursor(value: object, label: str) -> int | None:
    if value is None:
        return None
    if type(value) is not int or not 0 <= value <= MAX_WIRE_INTEGER:
        raise ClassroomFileServerError(f"invalid {label}")
    return value


def _bounded_limit(value: object) -> int:
    if type(value) is not int or not 1 <= value <= MAX_SYNC_ATTACHMENTS:
        raise ClassroomFileServerError("invalid file history limit")
    return value


class ClassroomFileServerSQLiteStore:
    """Durable authoritative file metadata, sequencing and deletion recovery."""

    def __init__(self, path: str) -> None:
        if type(path) is not str or path in {"", ":memory:"}:
            raise ClassroomFileServerError(
                "durable file-server database path is required"
            )
        self._path = path
        self._migrate()

    def _connect(self) -> sqlite3.Connection:
        db: sqlite3.Connection | None = None
        try:
            db = sqlite3.connect(self._path, timeout=30.0)
            db.row_factory = sqlite3.Row
            db.execute("PRAGMA foreign_keys=ON")
            db.execute("PRAGMA journal_mode=WAL")
            db.execute("PRAGMA synchronous=FULL")
            return db
        except sqlite3.Error:
            if db is not None:
                db.close()
            raise ClassroomFileServerError(
                "classroom file-server database open failed"
            ) from None

    def _migrate(self) -> None:
        with closing(self._connect()) as db:
            try:
                db.execute("BEGIN IMMEDIATE")
                db.execute(
                    """
                    CREATE TABLE IF NOT EXISTS classroom_file_server_meta(
                        key TEXT PRIMARY KEY,
                        value INTEGER NOT NULL
                    )
                    """
                )
                row = db.execute(
                    "SELECT value FROM classroom_file_server_meta "
                    "WHERE key='schema_version'"
                ).fetchone()
                if row is not None:
                    value = row["value"]
                    if type(value) is not int or value != SERVER_SCHEMA_VERSION:
                        raise ClassroomFileServerError(
                            "unsupported classroom file-server schema"
                        )
                    self._verify_current_schema(db)
                    db.commit()
                    return

                db.execute(
                    """
                    CREATE TABLE classroom_file_server_attachments(
                        attachment_id TEXT PRIMARY KEY,
                        room_id TEXT NOT NULL,
                        sender_id TEXT NOT NULL,
                        sequence_no INTEGER,
                        display_name TEXT NOT NULL,
                        mime_type TEXT,
                        size_bytes INTEGER NOT NULL,
                        sha256 TEXT NOT NULL,
                        object_key TEXT NOT NULL UNIQUE,
                        retention TEXT NOT NULL,
                        transfer_state TEXT NOT NULL,
                        scan_state TEXT NOT NULL,
                        delete_completed INTEGER NOT NULL DEFAULT 1
                            CHECK(delete_completed IN (0,1))
                    )
                    """
                )
                db.execute(
                    """
                    CREATE UNIQUE INDEX
                    uq_classroom_file_server_room_sequence
                    ON classroom_file_server_attachments(room_id, sequence_no)
                    WHERE transfer_state IN ('stored','deleted')
                    """
                )
                db.execute(
                    """
                    CREATE INDEX idx_classroom_file_server_room
                    ON classroom_file_server_attachments(room_id, sequence_no)
                    """
                )
                db.execute(
                    """
                    CREATE TABLE classroom_file_server_state_updates(
                        room_id TEXT NOT NULL,
                        revision INTEGER NOT NULL,
                        attachment_id TEXT NOT NULL,
                        transfer_state TEXT NOT NULL,
                        scan_state TEXT NOT NULL,
                        PRIMARY KEY(room_id, revision),
                        FOREIGN KEY(attachment_id)
                            REFERENCES classroom_file_server_attachments(attachment_id)
                    )
                    """
                )
                db.execute(
                    """
                    INSERT INTO classroom_file_server_meta(key,value)
                    VALUES('schema_version',?)
                    """,
                    (SERVER_SCHEMA_VERSION,),
                )
                self._verify_current_schema(db)
                db.commit()
            except ClassroomFileServerError:
                db.rollback()
                raise
            except sqlite3.Error:
                db.rollback()
                raise ClassroomFileServerError(
                    "classroom file-server schema migration failed"
                ) from None
            except Exception:
                db.rollback()
                raise

    @staticmethod
    def _verify_current_schema(db: sqlite3.Connection) -> None:
        required = {
            "classroom_file_server_meta",
            "classroom_file_server_attachments",
            "classroom_file_server_state_updates",
        }
        tables = {
            row["name"]
            for row in db.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
        if not required.issubset(tables):
            raise ClassroomFileServerError(
                "classroom file-server schema is incomplete"
            )

        expected_columns = {
            "classroom_file_server_meta": (
                ("key", "TEXT", 1),
                ("value", "INTEGER", 0),
            ),
            "classroom_file_server_attachments": (
                ("attachment_id", "TEXT", 1),
                ("room_id", "TEXT", 0),
                ("sender_id", "TEXT", 0),
                ("sequence_no", "INTEGER", 0),
                ("display_name", "TEXT", 0),
                ("mime_type", "TEXT", 0),
                ("size_bytes", "INTEGER", 0),
                ("sha256", "TEXT", 0),
                ("object_key", "TEXT", 0),
                ("retention", "TEXT", 0),
                ("transfer_state", "TEXT", 0),
                ("scan_state", "TEXT", 0),
                ("delete_completed", "INTEGER", 0),
            ),
            "classroom_file_server_state_updates": (
                ("room_id", "TEXT", 1),
                ("revision", "INTEGER", 2),
                ("attachment_id", "TEXT", 0),
                ("transfer_state", "TEXT", 0),
                ("scan_state", "TEXT", 0),
            ),
        }
        required_not_null = {
            "classroom_file_server_meta": {"value"},
            "classroom_file_server_attachments": {
                "room_id", "sender_id", "display_name", "size_bytes", "sha256",
                "object_key", "retention", "transfer_state", "scan_state",
                "delete_completed",
            },
            "classroom_file_server_state_updates": {
                "room_id", "revision", "attachment_id",
                "transfer_state", "scan_state",
            },
        }
        for table_name, expected in expected_columns.items():
            rows = db.execute(f"PRAGMA table_info('{table_name}')").fetchall()
            actual = tuple(
                (row["name"], str(row["type"]).upper(), int(row["pk"]))
                for row in rows
            )
            if actual != expected:
                raise ClassroomFileServerError(
                    "classroom file-server schema columns are incompatible"
                )
            actual_not_null = {
                row["name"] for row in rows if int(row["notnull"]) == 1
            }
            if not required_not_null[table_name].issubset(actual_not_null):
                raise ClassroomFileServerError(
                    "classroom file-server schema nullability is incompatible"
                )

        attachment_indexes = db.execute(
            "PRAGMA index_list('classroom_file_server_attachments')"
        ).fetchall()
        sequence_index = next(
            (
                row for row in attachment_indexes
                if row["name"] == "uq_classroom_file_server_room_sequence"
            ),
            None,
        )
        if (
            sequence_index is None
            or int(sequence_index["unique"]) != 1
            or int(sequence_index["partial"]) != 1
        ):
            raise ClassroomFileServerError(
                "classroom file-server sequence authority is invalid"
            )
        sequence_columns = tuple(
            row["name"]
            for row in db.execute(
                "PRAGMA index_info('uq_classroom_file_server_room_sequence')"
            )
        )
        if sequence_columns != ("room_id", "sequence_no"):
            raise ClassroomFileServerError(
                "classroom file-server sequence authority is invalid"
            )
        index = db.execute(
            "SELECT sql FROM sqlite_master WHERE type='index' "
            "AND name='uq_classroom_file_server_room_sequence'"
        ).fetchone()
        if (
            index is None
            or type(index["sql"]) is not str
            or "WHERE transfer_state IN ('stored','deleted')" not in (
                " ".join(index["sql"].split()).replace(", ", ",")
            )
        ):
            raise ClassroomFileServerError(
                "classroom file-server sequence authority is invalid"
            )

        object_key_unique = False
        for index_row in attachment_indexes:
            if int(index_row["unique"]) != 1:
                continue
            columns = tuple(
                row["name"]
                for row in db.execute(
                    f"PRAGMA index_info('{index_row['name']}')"
                )
            )
            if columns == ("object_key",):
                object_key_unique = True
                break
        if not object_key_unique:
            raise ClassroomFileServerError(
                "classroom file-server object namespace is not unique"
            )

        foreign_keys = db.execute(
            "PRAGMA foreign_key_list('classroom_file_server_state_updates')"
        ).fetchall()
        if (
            len(foreign_keys) != 1
            or foreign_keys[0]["table"] != "classroom_file_server_attachments"
            or foreign_keys[0]["from"] != "attachment_id"
            or foreign_keys[0]["to"] != "attachment_id"
        ):
            raise ClassroomFileServerError(
                "classroom file-server state authority is invalid"
            )

        attachment_sql = db.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' "
            "AND name='classroom_file_server_attachments'"
        ).fetchone()
        normalized_attachment_sql = (
            ""
            if attachment_sql is None or type(attachment_sql["sql"]) is not str
            else " ".join(attachment_sql["sql"].split()).replace(", ", ",")
        )
        if "CHECK(delete_completed IN (0,1))" not in normalized_attachment_sql:
            raise ClassroomFileServerError(
                "classroom file-server deletion authority is invalid"
            )

    @staticmethod
    def _immutable_tuple(metadata: AttachmentMetadata) -> tuple[object, ...]:
        return (
            metadata.attachment_id,
            metadata.room_id,
            metadata.sender_id,
            metadata.display_name,
            metadata.mime_type,
            metadata.size_bytes,
            metadata.sha256,
            metadata.object_key,
            metadata.retention,
        )

    @staticmethod
    def _row_immutable_tuple(row: sqlite3.Row) -> tuple[object, ...]:
        return (
            row["attachment_id"],
            row["room_id"],
            row["sender_id"],
            row["display_name"],
            row["mime_type"],
            row["size_bytes"],
            row["sha256"],
            row["object_key"],
            row["retention"],
        )

    @staticmethod
    def _canonical_row_object_key(row: sqlite3.Row) -> str:
        try:
            expected = _canonical_object_key(
                row["room_id"],
                row["attachment_id"],
            )
        except Exception:
            raise ClassroomFileServerError(
                "stored attachment namespace is invalid"
            ) from None
        if row["object_key"] != expected:
            raise ClassroomFileServerError(
                "stored attachment namespace is invalid"
            )
        return expected

    @staticmethod
    def _terminal_from_row(row: sqlite3.Row) -> AttachmentMetadata:
        object_key = ClassroomFileServerSQLiteStore._canonical_row_object_key(row)
        sequence = row["sequence_no"]
        if type(sequence) is not int or not 0 <= sequence <= MAX_WIRE_INTEGER:
            raise ClassroomFileServerError(
                "stored attachment sequence is invalid"
            )
        if row["transfer_state"] not in {"stored", "deleted"}:
            raise ClassroomFileServerError(
                "non-terminal server attachment cannot enter history"
            )
        try:
            return AttachmentMetadata(
                row["attachment_id"],
                row["room_id"],
                row["sender_id"],
                sequence,
                row["display_name"],
                row["mime_type"],
                row["size_bytes"],
                row["sha256"],
                object_key,
                row["transfer_state"],
                row["retention"],
                row["scan_state"],
            )
        except (TypeError, ValueError, OverflowError) as error:
            raise ClassroomFileServerError(
                "stored attachment metadata is invalid"
            ) from None

    @staticmethod
    def _state_from_row(row: sqlite3.Row) -> AttachmentStateUpdate:
        try:
            return AttachmentStateUpdate(
                row["room_id"],
                row["attachment_id"],
                row["revision"],
                row["transfer_state"],
                row["scan_state"],
            )
        except (TypeError, ValueError, OverflowError) as error:
            raise ClassroomFileServerError(
                "stored attachment state update is invalid"
            ) from None

    def existing_upload(
        self,
        metadata: AttachmentMetadata,
    ) -> tuple[AttachmentMetadata | None, bool]:
        """Return terminal replay state plus whether exact bytes already passed scan.

        An uploading row exists only after this exact immutable payload passed
        a clean server-side scan. It deliberately survives an ambiguous
        object-store write, so an exact retry can repeat the idempotent
        put/finalize sequence without depending on a later scanner result.
        """
        with closing(self._connect()) as db:
            row = db.execute(
                "SELECT * FROM classroom_file_server_attachments "
                "WHERE attachment_id=?",
                (metadata.attachment_id,),
            ).fetchone()
        if row is None:
            return None, False
        if self._row_immutable_tuple(row) != self._immutable_tuple(metadata):
            raise CollaborationConflictError(
                "attachment identity was reused with different payload"
            )
        if row["transfer_state"] == "stored":
            return self._terminal_from_row(row), True
        if row["transfer_state"] == "deleted":
            raise CollaborationConflictError(
                "deleted attachment identity cannot be reused"
            )
        if row["transfer_state"] == "cancelled":
            raise CollaborationConflictError(
                "attachment cancellation cleanup is still pending"
            )
        if row["transfer_state"] != "uploading":
            raise ClassroomFileServerError(
                "stored upload reservation has invalid state"
            )
        return None, True

    def reserve_upload(
        self,
        metadata: AttachmentMetadata,
        *,
        quota: FileQuotaPolicy,
    ) -> AttachmentMetadata | None:
        """Reserve quota/identity; return existing stored result on exact replay."""
        with closing(self._connect()) as db:
            try:
                db.execute("BEGIN IMMEDIATE")
                row = db.execute(
                    "SELECT * FROM classroom_file_server_attachments "
                    "WHERE attachment_id=?",
                    (metadata.attachment_id,),
                ).fetchone()
                if row is not None:
                    if self._row_immutable_tuple(row) != self._immutable_tuple(metadata):
                        raise CollaborationConflictError(
                            "attachment identity was reused with different payload"
                        )
                    if row["transfer_state"] == "deleted":
                        raise CollaborationConflictError(
                            "deleted attachment identity cannot be reused"
                        )
                    if row["transfer_state"] == "cancelled":
                        raise CollaborationConflictError(
                            "attachment cancellation cleanup is still pending"
                        )
                    if row["transfer_state"] == "stored":
                        result = self._terminal_from_row(row)
                        db.commit()
                        return result
                    if row["transfer_state"] != "uploading":
                        raise ClassroomFileServerError(
                            "stored upload reservation has invalid state"
                        )
                    db.commit()
                    return None

                sequence_stats = db.execute(
                    """
                    SELECT COUNT(*) AS item_count,
                           MAX(sequence_no) AS last_sequence
                    FROM classroom_file_server_attachments
                    WHERE room_id=? AND transfer_state IN ('stored','deleted')
                    """,
                    (metadata.room_id,),
                ).fetchone()
                item_count = sequence_stats["item_count"]
                last_sequence = sequence_stats["last_sequence"]
                if type(item_count) is not int or item_count < 0:
                    raise ClassroomFileServerError(
                        "authoritative file sequence count is corrupt"
                    )
                if last_sequence is None:
                    if item_count != 0:
                        raise ClassroomFileServerError(
                            "authoritative file sequence has a gap"
                        )
                elif (
                    type(last_sequence) is not int
                    or not 0 <= last_sequence <= MAX_WIRE_INTEGER
                ):
                    raise ClassroomFileServerError(
                        "authoritative file sequence is exhausted or corrupt"
                    )
                elif last_sequence + 1 != item_count:
                    raise ClassroomFileServerError(
                        "authoritative file sequence has a gap"
                    )

                if metadata.size_bytes > quota.max_file_bytes:
                    raise CollaborationQuotaError(
                        "file exceeds authoritative server size limit"
                    )
                used_row = db.execute(
                    """
                    SELECT COALESCE(SUM(size_bytes),0) AS used
                    FROM classroom_file_server_attachments
                    WHERE room_id=?
                      AND (
                          transfer_state!='deleted'
                          OR delete_completed=0
                      )
                    """,
                    (metadata.room_id,),
                ).fetchone()
                used = used_row["used"]
                if type(used) is not int or used < 0:
                    raise ClassroomFileServerError(
                        "stored room quota accounting is invalid"
                    )
                if used + metadata.size_bytes > quota.max_room_bytes:
                    raise CollaborationQuotaError(
                        "room file quota would be exceeded"
                    )
                db.execute(
                    """
                    INSERT INTO classroom_file_server_attachments(
                        attachment_id, room_id, sender_id, sequence_no,
                        display_name, mime_type, size_bytes, sha256, object_key,
                        retention, transfer_state, scan_state, delete_completed
                    ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,1)
                    """,
                    (
                        metadata.attachment_id,
                        metadata.room_id,
                        metadata.sender_id,
                        None,
                        metadata.display_name,
                        metadata.mime_type,
                        metadata.size_bytes,
                        metadata.sha256,
                        metadata.object_key,
                        metadata.retention,
                        "uploading",
                        "pending",
                    ),
                )
                db.commit()
                return None
            except Exception:
                db.rollback()
                raise

    def finalize_upload(self, attachment_id: str) -> AttachmentMetadata:
        attachment = _server_id(attachment_id, "attachment id")
        with closing(self._connect()) as db:
            try:
                db.execute("BEGIN IMMEDIATE")
                row = db.execute(
                    "SELECT * FROM classroom_file_server_attachments "
                    "WHERE attachment_id=?",
                    (attachment,),
                ).fetchone()
                if row is None:
                    raise ClassroomFileServerError(
                        "upload reservation is missing"
                    )
                if row["transfer_state"] == "stored":
                    result = self._terminal_from_row(row)
                    db.commit()
                    return result
                if row["transfer_state"] != "uploading":
                    raise ClassroomFileServerError(
                        "upload reservation is not finalizable"
                    )
                sequence_stats = db.execute(
                    """
                    SELECT COUNT(*) AS item_count,
                           MAX(sequence_no) AS last_sequence
                    FROM classroom_file_server_attachments
                    WHERE room_id=? AND transfer_state IN ('stored','deleted')
                    """,
                    (row["room_id"],),
                ).fetchone()
                item_count = sequence_stats["item_count"]
                last = sequence_stats["last_sequence"]
                if type(item_count) is not int or item_count < 0:
                    raise ClassroomFileServerError(
                        "authoritative file sequence count is corrupt"
                    )
                if last is None:
                    if item_count != 0:
                        raise ClassroomFileServerError(
                            "authoritative file sequence has a gap"
                        )
                    sequence = 0
                elif type(last) is int and 0 <= last < MAX_WIRE_INTEGER:
                    if last + 1 != item_count:
                        raise ClassroomFileServerError(
                            "authoritative file sequence has a gap"
                        )
                    sequence = last + 1
                else:
                    raise ClassroomFileServerError(
                        "authoritative file sequence is exhausted or corrupt"
                    )
                db.execute(
                    """
                    UPDATE classroom_file_server_attachments
                    SET sequence_no=?, transfer_state='stored',
                        scan_state='clean', delete_completed=1
                    WHERE attachment_id=?
                    """,
                    (sequence, attachment),
                )
                updated = db.execute(
                    "SELECT * FROM classroom_file_server_attachments "
                    "WHERE attachment_id=?",
                    (attachment,),
                ).fetchone()
                result = self._terminal_from_row(updated)
                db.commit()
                return result
            except Exception:
                db.rollback()
                raise

    def recover_after_unconfirmed_finalize(
        self,
        metadata: AttachmentMetadata,
    ) -> AttachmentMetadata | None:
        """Recover authority after PUT succeeded but upload finalization did not confirm.

        A concurrent provisional cancellation may delete its reservation and
        complete object cleanup before a slow PUT returns. Recreate a durable
        cancelled cleanup receipt before attempting to delete those late bytes.
        If finalization actually committed and only its acknowledgement was
        ambiguous, return the authoritative stored row instead of deleting it.
        """
        if type(metadata) is not AttachmentMetadata:
            raise ClassroomFileServerError("invalid attachment metadata")
        with closing(self._connect()) as db:
            try:
                db.execute("BEGIN IMMEDIATE")
                row = db.execute(
                    "SELECT * FROM classroom_file_server_attachments "
                    "WHERE attachment_id=?",
                    (metadata.attachment_id,),
                ).fetchone()
                if row is None:
                    db.execute(
                        """
                        INSERT INTO classroom_file_server_attachments(
                            attachment_id, room_id, sender_id, sequence_no,
                            display_name, mime_type, size_bytes, sha256, object_key,
                            retention, transfer_state, scan_state, delete_completed
                        ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,0)
                        """,
                        (
                            metadata.attachment_id,
                            metadata.room_id,
                            metadata.sender_id,
                            None,
                            metadata.display_name,
                            metadata.mime_type,
                            metadata.size_bytes,
                            metadata.sha256,
                            metadata.object_key,
                            metadata.retention,
                            "cancelled",
                            "pending",
                        ),
                    )
                    db.commit()
                    return None
                if self._row_immutable_tuple(row) != self._immutable_tuple(metadata):
                    raise CollaborationConflictError(
                        "attachment identity was reused with different payload"
                    )
                if row["transfer_state"] == "stored":
                    result = self._terminal_from_row(row)
                    db.commit()
                    return result
                if row["transfer_state"] == "deleted":
                    db.execute(
                        "UPDATE classroom_file_server_attachments "
                        "SET delete_completed=0 WHERE attachment_id=?",
                        (metadata.attachment_id,),
                    )
                    db.commit()
                    return None
                if row["transfer_state"] not in {"uploading", "cancelled"}:
                    raise ClassroomFileServerError(
                        "upload recovery found invalid reservation state"
                    )
                db.execute(
                    """
                    UPDATE classroom_file_server_attachments
                    SET transfer_state='cancelled', delete_completed=0
                    WHERE attachment_id=?
                    """,
                    (metadata.attachment_id,),
                )
                db.commit()
                return None
            except Exception:
                db.rollback()
                raise

    def cancel(
        self,
        *,
        trusted_sender_id: str,
        attachment_id: str,
    ) -> tuple[AttachmentMetadata | None, str | None]:
        sender = _server_id(trusted_sender_id, "trusted sender identity")
        attachment = _server_id(attachment_id, "attachment id")
        with closing(self._connect()) as db:
            try:
                db.execute("BEGIN IMMEDIATE")
                row = db.execute(
                    "SELECT * FROM classroom_file_server_attachments "
                    "WHERE attachment_id=?",
                    (attachment,),
                ).fetchone()
                if row is None:
                    db.commit()
                    return None, None
                if row["sender_id"] != sender:
                    raise ClassroomFileServerError(
                        "participant cannot cancel another participant's attachment"
                    )
                object_key = self._canonical_row_object_key(row)
                if row["transfer_state"] == "uploading":
                    # The object-store put may have succeeded before its
                    # acknowledgement was lost. Keep a durable internal
                    # cancellation row until byte deletion is confirmed.
                    db.execute(
                        """
                        UPDATE classroom_file_server_attachments
                        SET transfer_state='cancelled', delete_completed=0
                        WHERE attachment_id=?
                        """,
                        (attachment,),
                    )
                    db.commit()
                    return None, object_key
                if row["transfer_state"] == "cancelled":
                    object_key = object_key if row["delete_completed"] == 0 else None
                    db.commit()
                    return None, object_key
                if row["transfer_state"] == "deleted":
                    result = self._terminal_from_row(row)
                    key = result.object_key if not bool(row["delete_completed"]) else None
                    db.commit()
                    return result, key
                if row["transfer_state"] != "stored":
                    raise ClassroomFileServerError(
                        "attachment has invalid cancellation state"
                    )

                revision_stats = db.execute(
                    """
                    SELECT COUNT(*) AS item_count,
                           MAX(revision) AS last_revision
                    FROM classroom_file_server_state_updates
                    WHERE room_id=?
                    """,
                    (row["room_id"],),
                ).fetchone()
                revision_count = revision_stats["item_count"]
                revisions = revision_stats["last_revision"]
                if type(revision_count) is not int or revision_count < 0:
                    raise ClassroomFileServerError(
                        "attachment state revision count is corrupt"
                    )
                if revisions is None:
                    if revision_count != 0:
                        raise ClassroomFileServerError(
                            "attachment state revision has a gap"
                        )
                    revision = 0
                elif type(revisions) is int and 0 <= revisions < MAX_WIRE_INTEGER:
                    if revisions + 1 != revision_count:
                        raise ClassroomFileServerError(
                            "attachment state revision has a gap"
                        )
                    revision = revisions + 1
                else:
                    raise ClassroomFileServerError(
                        "attachment state revision is exhausted or corrupt"
                    )
                db.execute(
                    """
                    UPDATE classroom_file_server_attachments
                    SET transfer_state='deleted', delete_completed=0
                    WHERE attachment_id=?
                    """,
                    (attachment,),
                )
                db.execute(
                    """
                    INSERT INTO classroom_file_server_state_updates(
                        room_id, revision, attachment_id,
                        transfer_state, scan_state
                    ) VALUES(?,?,?,?,?)
                    """,
                    (
                        row["room_id"],
                        revision,
                        attachment,
                        "deleted",
                        row["scan_state"],
                    ),
                )
                updated = db.execute(
                    "SELECT * FROM classroom_file_server_attachments "
                    "WHERE attachment_id=?",
                    (attachment,),
                ).fetchone()
                result = self._terminal_from_row(updated)
                db.commit()
                return result, result.object_key
            except Exception:
                db.rollback()
                raise

    def history_after(
        self,
        *,
        room_id: str,
        after_sequence: int | None,
        limit: int,
    ) -> AttachmentHistoryPage:
        """Read attachment snapshots and their mutable-state watermark atomically."""
        room = _server_id(room_id, "room id")
        after = _bounded_cursor(after_sequence, "attachment sequence cursor")
        count = _bounded_limit(limit)
        query = (
            "SELECT * FROM classroom_file_server_attachments "
            "WHERE room_id=? AND transfer_state IN ('stored','deleted') "
        )
        args: list[object] = [room]
        if after is not None:
            query += "AND sequence_no>? "
            args.append(after)
        query += "ORDER BY sequence_no LIMIT ?"
        args.append(count)

        with closing(self._connect()) as db:
            try:
                # Explicit read transaction is required: the attachment rows and
                # the room-wide revision watermark must describe one SQLite
                # snapshot. Two autocommit SELECTs could otherwise straddle a
                # concurrent cancellation and let reconnect skip mutable state.
                db.execute("BEGIN")
                rows = db.execute(query, tuple(args)).fetchall()
                revision_stats = db.execute(
                    """
                    SELECT COUNT(*) AS item_count,
                           MAX(revision) AS last_revision
                    FROM classroom_file_server_state_updates
                    WHERE room_id=?
                    """,
                    (room,),
                ).fetchone()
                item_count = revision_stats["item_count"]
                last_revision = revision_stats["last_revision"]
                if type(item_count) is not int or item_count < 0:
                    raise ClassroomFileServerError(
                        "authoritative attachment state count is corrupt"
                    )
                if last_revision is None:
                    if item_count != 0:
                        raise ClassroomFileServerError(
                            "authoritative attachment state revision has a gap"
                        )
                    snapshot_state_revision = None
                elif (
                    type(last_revision) is int
                    and 0 <= last_revision <= MAX_WIRE_INTEGER
                    and last_revision + 1 == item_count
                ):
                    snapshot_state_revision = last_revision
                else:
                    raise ClassroomFileServerError(
                        "authoritative attachment state revision has a gap"
                    )
                db.commit()
            except ClassroomFileServerError:
                db.rollback()
                raise
            except sqlite3.Error:
                db.rollback()
                raise ClassroomFileServerError(
                    "classroom file history read failed"
                ) from None

        items = tuple(self._terminal_from_row(row) for row in rows)
        expected_sequence = 0 if after is None else after + 1
        for item in items:
            if item.sequence_no != expected_sequence:
                raise ClassroomFileServerError(
                    "authoritative file history has a sequence gap"
                )
            expected_sequence += 1
        return AttachmentHistoryPage(items, snapshot_state_revision)

    def state_updates_after(
        self,
        *,
        room_id: str,
        after_revision: int | None,
        limit: int,
    ) -> tuple[AttachmentStateUpdate, ...]:
        room = _server_id(room_id, "room id")
        after = _bounded_cursor(after_revision, "attachment state cursor")
        count = _bounded_limit(limit)
        query = (
            "SELECT * FROM classroom_file_server_state_updates "
            "WHERE room_id=? "
        )
        args: list[object] = [room]
        if after is not None:
            query += "AND revision>? "
            args.append(after)
        query += "ORDER BY revision LIMIT ?"
        args.append(count)
        with closing(self._connect()) as db:
            rows = db.execute(query, tuple(args)).fetchall()
        items = tuple(self._state_from_row(row) for row in rows)
        expected_revision = 0 if after is None else after + 1
        for item in items:
            if item.revision != expected_revision:
                raise ClassroomFileServerError(
                    "authoritative attachment state has a revision gap"
                )
            expected_revision += 1
        return items

    def attachment_for_object_key(
        self,
        object_key: str,
    ) -> AttachmentMetadata | None:
        if type(object_key) is not str:
            raise ClassroomFileServerError("invalid object key")
        with closing(self._connect()) as db:
            row = db.execute(
                "SELECT * FROM classroom_file_server_attachments "
                "WHERE object_key=? AND transfer_state IN ('stored','deleted')",
                (object_key,),
            ).fetchone()
        return None if row is None else self._terminal_from_row(row)

    def queue_pending_upload_rollbacks(self) -> tuple[tuple[str, str], ...]:
        """Atomically stop uncommitted uploads before quiescent restart cleanup."""
        with closing(self._connect()) as db:
            try:
                db.execute("BEGIN IMMEDIATE")
                rows = db.execute(
                    """
                    SELECT *
                    FROM classroom_file_server_attachments
                    WHERE transfer_state='uploading'
                    ORDER BY room_id, attachment_id
                    """
                ).fetchall()
                pending = tuple(
                    (row["attachment_id"], self._canonical_row_object_key(row))
                    for row in rows
                )
                for attachment_id, _object_key in pending:
                    db.execute(
                        """
                        UPDATE classroom_file_server_attachments
                        SET transfer_state='cancelled', delete_completed=0
                        WHERE attachment_id=? AND transfer_state='uploading'
                        """,
                        (attachment_id,),
                    )
                db.commit()
                return pending
            except Exception:
                db.rollback()
                raise

    def pending_deletions(self) -> tuple[tuple[str, str], ...]:
        with closing(self._connect()) as db:
            rows = db.execute(
                """
                SELECT *
                FROM classroom_file_server_attachments
                WHERE transfer_state IN ('deleted','cancelled')
                  AND delete_completed=0
                ORDER BY room_id, sequence_no, attachment_id
                """
            ).fetchall()
        return tuple(
            (row["attachment_id"], self._canonical_row_object_key(row))
            for row in rows
        )

    def complete_deletion(self, attachment_id: str) -> None:
        attachment = _server_id(attachment_id, "attachment id")
        with closing(self._connect()) as db, db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT transfer_state FROM classroom_file_server_attachments "
                "WHERE attachment_id=?",
                (attachment,),
            ).fetchone()
            if row is None:
                raise ClassroomFileServerError(
                    "file deletion completion lost cleanup authority"
                )
            if row["transfer_state"] == "cancelled":
                db.execute(
                    "DELETE FROM classroom_file_server_attachments "
                    "WHERE attachment_id=?",
                    (attachment,),
                )
                return
            if row["transfer_state"] != "deleted":
                raise ClassroomFileServerError(
                    "file deletion completion lost tombstone authority"
                )
            db.execute(
                "UPDATE classroom_file_server_attachments "
                "SET delete_completed=1 WHERE attachment_id=?",
                (attachment,),
            )

    def integrity_check(self) -> None:
        with closing(self._connect()) as db:
            if db.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise ClassroomFileServerError(
                    "classroom file-server SQLite integrity check failed"
                )
            self._verify_current_schema(db)
            version = db.execute(
                "SELECT value FROM classroom_file_server_meta "
                "WHERE key='schema_version'"
            ).fetchone()
            if (
                version is None
                or type(version["value"]) is not int
                or version["value"] != SERVER_SCHEMA_VERSION
            ):
                raise ClassroomFileServerError(
                    "classroom file-server schema version is invalid"
                )

            expected_by_room: dict[str, int] = {}
            for row in db.execute(
                """
                SELECT *
                FROM classroom_file_server_attachments
                WHERE transfer_state IN ('stored','deleted')
                ORDER BY room_id, sequence_no
                """
            ):
                item = self._terminal_from_row(row)
                expected = expected_by_room.get(item.room_id, 0)
                if item.sequence_no != expected:
                    raise ClassroomFileServerError(
                        "authoritative file history has a sequence gap"
                    )
                expected_by_room[item.room_id] = expected + 1
                delete_completed = row["delete_completed"]
                if type(delete_completed) is not int or delete_completed not in {0, 1}:
                    raise ClassroomFileServerError(
                        "stored deletion completion flag is invalid"
                    )
                if item.transfer_state == "stored" and delete_completed != 1:
                    raise ClassroomFileServerError(
                        "stored attachment cannot have pending deletion"
                    )

            for row in db.execute(
                """
                SELECT *
                FROM classroom_file_server_attachments
                WHERE transfer_state NOT IN ('stored','deleted')
                """
            ):
                self._canonical_row_object_key(row)
                state = row["transfer_state"]
                if state not in {"uploading", "cancelled"}:
                    raise ClassroomFileServerError(
                        "stored upload reservation state is invalid"
                    )
                if row["sequence_no"] is not None:
                    raise ClassroomFileServerError(
                        "provisional server attachment cannot own room sequence"
                    )
                expected_delete = 0 if state == "cancelled" else 1
                if row["delete_completed"] != expected_delete:
                    raise ClassroomFileServerError(
                        "provisional cleanup state is inconsistent"
                    )

            last_revision: dict[str, int] = {}
            for row in db.execute(
                "SELECT * FROM classroom_file_server_state_updates "
                "ORDER BY room_id, revision"
            ):
                update = self._state_from_row(row)
                expected = last_revision.get(update.room_id, -1) + 1
                if update.revision != expected:
                    raise ClassroomFileServerError(
                        "attachment state history has a revision gap"
                    )
                target = db.execute(
                    "SELECT room_id, transfer_state, scan_state "
                    "FROM classroom_file_server_attachments WHERE attachment_id=?",
                    (update.attachment_id,),
                ).fetchone()
                if (
                    target is None
                    or target["room_id"] != update.room_id
                    or target["transfer_state"] != "deleted"
                    or update.transfer_state != "deleted"
                ):
                    raise ClassroomFileServerError(
                        "attachment state update lost tombstone authority"
                    )
                last_revision[update.room_id] = update.revision


class ClassroomFileServerService:
    """Trusted file metadata/bytes authority behind authenticated transport."""

    def __init__(
        self,
        *,
        store: ClassroomFileServerSQLiteStore,
        authorization: ClassroomFileAuthorizationPort,
        scanner: ClassroomFileScannerPort,
        object_store: ClassroomFileObjectStorePort,
        quota: FileQuotaPolicy = FileQuotaPolicy(),
    ) -> None:
        if not callable(getattr(object_store, "stored_sha256", None)):
            raise TypeError(
                "object_store must support stored_sha256 reconciliation"
            )
        self._store = store
        self._authorization = authorization
        self._scanner = scanner
        self._object_store = object_store
        self._quota = quota

    def _authorize(
        self,
        *,
        caller: str,
        room_id: str,
        action: str,
        attachment_id: str | None = None,
        retention: str | None = None,
    ) -> None:
        trusted = _server_id(caller, "trusted caller identity")
        room = _server_id(room_id, "room id")
        try:
            allowed = self._authorization.authorize_file_action(
                trusted_caller_identity=trusted,
                room_id=room,
                action=action,
                attachment_id=attachment_id,
                retention=retention,
            )
        except Exception as error:
            raise ClassroomFileServerError(
                "classroom file authorization failed"
            ) from None
        if allowed is not True:
            raise ClassroomFileServerError(
                "classroom file action is not authorized"
            )

    @staticmethod
    def _require_expected_room(
        actual_room_id: str,
        expected_room_id: str | None,
    ) -> None:
        if expected_room_id is None:
            return
        expected = _server_id(expected_room_id, "expected room id")
        if actual_room_id != expected:
            raise ClassroomFileServerError(
                "classroom file operation crossed authenticated room"
            )

    @staticmethod
    def _validate_upload(
        caller: str,
        metadata: AttachmentMetadata,
        content: bytes,
    ) -> None:
        if type(metadata) is not AttachmentMetadata:
            raise ClassroomFileServerError("invalid attachment metadata")
        if metadata.sender_id != caller:
            raise ClassroomFileServerError(
                "attachment sender does not match authenticated caller"
            )
        if metadata.transfer_state not in {"pending", "uploading"}:
            raise ClassroomFileServerError(
                "upload metadata must be provisional"
            )
        try:
            canonical_key = _canonical_object_key(
                metadata.room_id,
                metadata.attachment_id,
            )
        except Exception as error:
            raise ClassroomFileServerError(
                "attachment namespace is invalid"
            ) from None
        if metadata.object_key != canonical_key:
            raise ClassroomFileServerError(
                "attachment object key is outside canonical namespace"
            )
        if type(content) is not bytes:
            raise ClassroomFileServerError("file upload requires opaque bytes")
        if len(content) != metadata.size_bytes:
            raise ClassroomFileServerError("file size changed during upload")
        digest = hashlib.sha256(content).hexdigest()
        if digest != metadata.sha256:
            raise ClassroomFileServerError("file hash changed during upload")

    def upload(
        self,
        *,
        trusted_caller_identity: str,
        metadata: AttachmentMetadata,
        content: bytes,
    ) -> AttachmentMetadata:
        caller = _server_id(trusted_caller_identity, "trusted caller identity")
        self._validate_upload(caller, metadata, content)
        self._authorize(
            caller=caller,
            room_id=metadata.room_id,
            action="upload",
            attachment_id=metadata.attachment_id,
            retention=metadata.retention,
        )
        existing, scan_approved = self._store.existing_upload(metadata)
        if existing is not None:
            # Exact retry of a committed upload is recovery, not a new scan or
            # policy decision. The accepted immutable identity is authoritative.
            return existing
        if not scan_approved:
            # Reject a payload the authoritative server can never accept before
            # invoking a potentially expensive malware scanner. Exact retries
            # of an already scan-approved reservation intentionally bypass this
            # policy recheck so recovery cannot drift after an ambiguous write.
            if metadata.size_bytes > self._quota.max_file_bytes:
                raise CollaborationQuotaError(
                    "file exceeds authoritative server size limit"
                )
            try:
                scan_state = self._scanner.scan(
                    room_id=metadata.room_id,
                    sender_id=caller,
                    display_name=metadata.display_name,
                    sha256=metadata.sha256,
                    content=content,
                )
            except Exception:
                scan_state = "failed"
            if scan_state not in {"clean", "blocked", "failed"}:
                raise ClassroomFileServerError(
                    "malware scanner returned invalid state"
                )
            if scan_state != "clean":
                return replace(
                    metadata,
                    transfer_state="failed",
                    scan_state=scan_state,
                )

            # Scanning is an external, potentially slow boundary. Recheck the
            # canonical room policy before reserving quota or creating durable
            # recovery state so revoked membership cannot survive scan latency.
            self._authorize(
                caller=caller,
                room_id=metadata.room_id,
                action="upload",
                attachment_id=metadata.attachment_id,
                retention=metadata.retention,
            )
            existing = self._store.reserve_upload(metadata, quota=self._quota)
            if existing is not None:
                return existing

        # Every scan-approved reservation may be a retry after an ambiguous
        # object-store acknowledgement. Reconcile durable state before any PUT.
        try:
            stored_sha256 = self._object_store.stored_sha256(
                object_key=metadata.object_key,
            )
        except Exception:
            raise ClassroomFileServerError(
                "durable object storage status is unavailable"
            ) from None
        if stored_sha256 is not None:
            if (
                type(stored_sha256) is not str
                or len(stored_sha256) != 64
                or stored_sha256 != stored_sha256.lower()
                or any(ch not in "0123456789abcdef" for ch in stored_sha256)
            ):
                raise ClassroomFileServerError(
                    "durable object storage returned invalid status"
                )
            if stored_sha256 != metadata.sha256:
                raise CollaborationConflictError(
                    "durable object identity conflicts with upload reservation"
                )
            self._authorize(
                caller=caller,
                room_id=metadata.room_id,
                action="upload",
                attachment_id=metadata.attachment_id,
                retention=metadata.retention,
            )
            return self._store.finalize_upload(metadata.attachment_id)

        # Recheck immediately before the external durable mutation as status
        # reconciliation can itself cross a slow provider boundary.
        self._authorize(
            caller=caller,
            room_id=metadata.room_id,
            action="upload",
            attachment_id=metadata.attachment_id,
            retention=metadata.retention,
        )
        try:
            self._object_store.put(
                object_key=metadata.object_key,
                content=content,
                expected_sha256=metadata.sha256,
            )
        except Exception:
            raise ClassroomFileServerError(
                "durable object storage write failed"
            ) from None
        try:
            return self._store.finalize_upload(metadata.attachment_id)
        except Exception:
            # PUT may race a provisional cancellation: cancellation can finish
            # deleting the pre-PUT object state and remove its reservation while
            # this slow PUT is still in flight. Re-establish durable cleanup
            # authority before touching the late bytes. Conversely, if finalize
            # committed and only its acknowledgement was ambiguous, preserve
            # that authoritative stored result.
            recovered = self._store.recover_after_unconfirmed_finalize(metadata)
            if recovered is not None:
                return recovered
            try:
                self._object_store.delete(object_key=metadata.object_key)
            except Exception:
                raise ClassroomFileServerError(
                    "upload finalization failed; durable object cleanup is pending"
                ) from None
            try:
                self._store.complete_deletion(metadata.attachment_id)
            except Exception:
                # The byte deletion already succeeded. Another idempotent
                # cancellation/recovery worker may have consumed the same
                # provisional cleanup receipt; never resurrect the upload.
                raise ClassroomFileServerError(
                    "upload finalization failed after durable object cleanup"
                ) from None
            raise ClassroomFileServerError(
                "upload was cancelled before finalization"
            ) from None

    def cancel(
        self,
        *,
        trusted_caller_identity: str,
        attachment_id: str,
        expected_room_id: str | None = None,
    ) -> None:
        caller = _server_id(trusted_caller_identity, "trusted caller identity")
        attachment = _server_id(attachment_id, "attachment id")
        # The room is obtained from durable state when accepted; an unknown
        # identity may be an exact retry of a cancellation that preceded server
        # acceptance, so authorization is deferred until a record exists.
        record_room: str | None = None
        with closing(self._store._connect()) as db:
            row = db.execute(
                "SELECT room_id FROM classroom_file_server_attachments "
                "WHERE attachment_id=?",
                (attachment,),
            ).fetchone()
            if row is not None:
                record_room = row["room_id"]
        if record_room is None:
            return
        self._require_expected_room(record_room, expected_room_id)
        self._authorize(
            caller=caller,
            room_id=record_room,
            action="cancel",
            attachment_id=attachment,
        )
        _result, object_key = self._store.cancel(
            trusted_sender_id=caller,
            attachment_id=attachment,
        )
        if object_key is None:
            return
        try:
            self._object_store.delete(object_key=object_key)
        except Exception as error:
            raise ClassroomFileServerError(
                "durable object deletion failed"
            ) from None
        # Terminal tombstones retain a completion receipt; provisional
        # cancellations are removed only after byte deletion succeeds.
        self._store.complete_deletion(attachment)

    def history_after(
        self,
        *,
        trusted_caller_identity: str,
        room_id: str,
        after_sequence: int | None,
        limit: int,
    ) -> AttachmentHistoryPage:
        caller = _server_id(trusted_caller_identity, "trusted caller identity")
        room = _server_id(room_id, "room id")
        self._authorize(caller=caller, room_id=room, action="history")
        return self._store.history_after(
            room_id=room,
            after_sequence=after_sequence,
            limit=limit,
        )

    def state_updates_after(
        self,
        *,
        trusted_caller_identity: str,
        room_id: str,
        after_revision: int | None,
        limit: int,
    ) -> tuple[AttachmentStateUpdate, ...]:
        caller = _server_id(trusted_caller_identity, "trusted caller identity")
        room = _server_id(room_id, "room id")
        self._authorize(caller=caller, room_id=room, action="state")
        return self._store.state_updates_after(
            room_id=room,
            after_revision=after_revision,
            limit=limit,
        )

    def issue_read_token(
        self,
        *,
        trusted_caller_identity: str,
        object_key: str,
        ttl_seconds: int,
        expected_room_id: str | None = None,
    ) -> str:
        caller = _server_id(trusted_caller_identity, "trusted caller identity")
        if type(ttl_seconds) is not int or not 1 <= ttl_seconds <= 3600:
            raise ClassroomFileServerError("invalid download token TTL")
        attachment = self._store.attachment_for_object_key(object_key)
        if (
            attachment is None
            or attachment.transfer_state != "stored"
            or attachment.scan_state != "clean"
        ):
            raise ClassroomFileServerError(
                "attachment is not cleared for download"
            )
        self._require_expected_room(attachment.room_id, expected_room_id)
        self._authorize(
            caller=caller,
            room_id=attachment.room_id,
            action="download",
            attachment_id=attachment.attachment_id,
        )
        try:
            stored_sha256 = self._object_store.stored_sha256(
                object_key=attachment.object_key,
            )
        except Exception:
            raise ClassroomFileServerError(
                "durable object storage status is unavailable"
            ) from None
        if stored_sha256 is None:
            raise ClassroomFileServerError(
                "durable attachment bytes are unavailable"
            )
        if (
            type(stored_sha256) is not str
            or len(stored_sha256) != 64
            or stored_sha256 != stored_sha256.lower()
            or any(ch not in "0123456789abcdef" for ch in stored_sha256)
        ):
            raise ClassroomFileServerError(
                "durable object storage returned invalid status"
            )
        if stored_sha256 != attachment.sha256:
            raise CollaborationConflictError(
                "durable object integrity conflicts with attachment metadata"
            )
        current = self._store.attachment_for_object_key(attachment.object_key)
        if (
            current is None
            or current.transfer_state != "stored"
            or current.scan_state != "clean"
            or current.sha256 != attachment.sha256
        ):
            raise ClassroomFileServerError(
                "attachment is no longer cleared for download"
            )
        attachment = current
        # Status verification can cross a slow provider boundary. Recheck the
        # canonical room policy immediately before minting a new read token so
        # revocation during integrity verification cannot leak fresh access.
        self._authorize(
            caller=caller,
            room_id=attachment.room_id,
            action="download",
            attachment_id=attachment.attachment_id,
        )
        try:
            token = self._object_store.issue_read_token(
                object_key=attachment.object_key,
                participant_id=caller,
                ttl_seconds=ttl_seconds,
            )
        except Exception as error:
            raise ClassroomFileServerError(
                "durable read-token issuance failed"
            ) from None
        if (
            type(token) is not str
            or not token
            or len(token) > MAX_DOWNLOAD_TOKEN_CHARS
            or any(
                ch.isspace() or ord(ch) < 32 or ord(ch) == 127
                for ch in token
            )
        ):
            raise ClassroomFileServerError(
                "durable object store returned invalid read token"
            )
        return token

    def delete_object(
        self,
        *,
        trusted_caller_identity: str,
        object_key: str,
        expected_room_id: str | None = None,
    ) -> None:
        caller = _server_id(trusted_caller_identity, "trusted caller identity")
        attachment = self._store.attachment_for_object_key(object_key)
        if attachment is None or attachment.transfer_state != "deleted":
            raise ClassroomFileServerError(
                "object deletion requires authoritative tombstone"
            )
        self._require_expected_room(attachment.room_id, expected_room_id)
        self._authorize(
            caller=caller,
            room_id=attachment.room_id,
            action="delete",
            attachment_id=attachment.attachment_id,
        )
        try:
            self._object_store.delete(object_key=attachment.object_key)
        except Exception as error:
            raise ClassroomFileServerError(
                "durable object deletion failed"
            ) from None
        self._store.complete_deletion(attachment.attachment_id)

    def rollback_pending_uploads(self) -> int:
        """Rollback uncommitted uploads during a quiescent restart/operator pass.

        This must run only when requests from the prior server process are no
        longer executing. Reservations are atomically moved out of uploading
        state before any object deletion so they can never later finalize into
        authoritative room history. Failed byte deletion remains durable as the
        existing cancelled cleanup state for a later recovery pass.
        """
        pending = self._store.queue_pending_upload_rollbacks()
        completed = 0
        incomplete = False
        for attachment_id, object_key in pending:
            try:
                self._object_store.delete(object_key=object_key)
            except Exception:
                incomplete = True
                continue
            self._store.complete_deletion(attachment_id)
            completed += 1
        if incomplete:
            raise ClassroomFileServerError(
                "durable upload rollback incomplete"
            )
        return completed

    def drain_pending_deletions(self) -> int:
        """Trusted restart/operator recovery; no client authorization is involved."""
        completed = 0
        incomplete = False
        for attachment_id, object_key in self._store.pending_deletions():
            try:
                self._object_store.delete(object_key=object_key)
            except Exception:
                incomplete = True
                continue
            self._store.complete_deletion(attachment_id)
            completed += 1
        if incomplete:
            raise ClassroomFileServerError(
                "durable object deletion recovery incomplete"
            )
        return completed

    def integrity_check(self) -> None:
        self._store.integrity_check()


class ClassroomFileServerClient:
    """Identity-bound desktop adapter implementing canonical file transport/storage ports."""

    def __init__(
        self,
        *,
        service: ClassroomFileServerService,
        trusted_caller_identity: str,
    ) -> None:
        self._service = service
        self._caller = _server_id(
            trusted_caller_identity,
            "trusted caller identity",
        )

    @staticmethod
    def _read_prepared(
        prepared: PreparedFile,
        on_progress: Callable[[FileTransferProgress], None] | None,
    ) -> bytes:
        if type(prepared) is not PreparedFile:
            raise ClassroomFileServerError("file transfer requires PreparedFile")
        if on_progress is not None and not callable(on_progress):
            raise ClassroomFileServerError("file progress consumer must be callable")

        expected_size = prepared.metadata.size_bytes
        remaining = expected_size
        transferred = 0
        digest = hashlib.sha256()
        content = bytearray()
        extra = b""
        try:
            with Path(prepared.local_path).open("rb") as source:
                while remaining:
                    chunk = source.read(min(_FILE_READ_CHUNK_BYTES, remaining))
                    if not chunk:
                        break
                    content.extend(chunk)
                    digest.update(chunk)
                    transferred += len(chunk)
                    remaining -= len(chunk)
                    if on_progress is not None:
                        on_progress(
                            FileTransferProgress(
                                prepared.metadata.attachment_id,
                                transferred,
                                expected_size,
                            )
                        )
                # Bound the read to the prepared size while still detecting a
                # file that grew between preparation and upload.
                extra = source.read(1)
        except OSError:
            raise ClassroomFileServerError(
                "selected file could not be read for upload"
            ) from None

        if (
            remaining != 0
            or extra
            or digest.hexdigest() != prepared.metadata.sha256
        ):
            raise ClassroomFileServerError(
                "selected file changed before server upload"
            )
        return bytes(content)

    def upload(
        self,
        prepared: PreparedFile,
        *,
        on_progress: Callable[[FileTransferProgress], None] | None = None,
    ) -> AttachmentMetadata:
        if on_progress is not None and not callable(on_progress):
            raise ClassroomFileServerError("file progress consumer must be callable")
        content = self._read_prepared(prepared, on_progress)
        return self._service.upload(
            trusted_caller_identity=self._caller,
            metadata=prepared.metadata,
            content=content,
        )

    def retry(
        self,
        prepared: PreparedFile,
        *,
        on_progress: Callable[[FileTransferProgress], None] | None = None,
    ) -> AttachmentMetadata:
        return self.upload(prepared, on_progress=on_progress)

    def cancel(self, *, attachment_id: str) -> None:
        self._service.cancel(
            trusted_caller_identity=self._caller,
            attachment_id=attachment_id,
        )

    def history_after(
        self,
        *,
        room_id: str,
        after_sequence: int | None,
        limit: int,
    ) -> AttachmentHistoryPage:
        return self._service.history_after(
            trusted_caller_identity=self._caller,
            room_id=room_id,
            after_sequence=after_sequence,
            limit=limit,
        )

    def state_updates_after(
        self,
        *,
        room_id: str,
        after_revision: int | None,
        limit: int,
    ) -> tuple[AttachmentStateUpdate, ...]:
        return self._service.state_updates_after(
            trusted_caller_identity=self._caller,
            room_id=room_id,
            after_revision=after_revision,
            limit=limit,
        )

    def issue_read_token(
        self,
        *,
        object_key: str,
        participant_id: str,
        ttl_seconds: int,
    ) -> str:
        participant = _server_id(participant_id, "participant id")
        if participant != self._caller:
            raise ClassroomFileServerError(
                "download participant does not match bound caller"
            )
        return self._service.issue_read_token(
            trusted_caller_identity=self._caller,
            object_key=object_key,
            ttl_seconds=ttl_seconds,
        )

    def delete(self, *, object_key: str) -> None:
        self._service.delete_object(
            trusted_caller_identity=self._caller,
            object_key=object_key,
        )


__all__ = [
    "ClassroomFileAuthorizationPort",
    "ClassroomFileObjectStorePort",
    "ClassroomFileScannerPort",
    "ClassroomFileServerClient",
    "ClassroomFileServerError",
    "ClassroomFileServerSQLiteStore",
    "ClassroomFileServerService",
]
