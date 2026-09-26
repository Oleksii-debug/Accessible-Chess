from __future__ import annotations

import hashlib
import re
import sqlite3
from dataclasses import dataclass
from pathlib import PurePath
from typing import Protocol, runtime_checkable

SCHEMA_VERSION = 1
MAX_CHAT_BODY_CHARS = 4000
MAX_ID_CHARS = 128
MAX_OBJECT_KEY_CHARS = 1024
MAX_MIME_CHARS = 255
_SAFE_NAME_RE = re.compile(r"[^A-Za-z0-9._()\- ]+")
_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_OBJECT_SEGMENT_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")


class CollaborationStorageError(RuntimeError):
    pass


class CollaborationConflictError(CollaborationStorageError):
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

    def __post_init__(self) -> None:
        _canonical_id(self.message_id, "message id")
        _canonical_id(self.room_id, "room id")
        _canonical_id(self.sender_id, "sender id")
        if type(self.sequence_no) is not int or self.sequence_no < 0:
            raise ValueError("sequence_no must be a non-negative integer")
        if type(self.body) is not str or not self.body.strip():
            raise ValueError("message body must be non-empty text")
        if len(self.body) > MAX_CHAT_BODY_CHARS or "\x00" in self.body:
            raise ValueError("message body exceeds safety boundary")
        if self.retention not in {"transient", "session", "persistent"}:
            raise ValueError("unsupported retention policy")
        if type(self.hidden) is not bool:
            raise ValueError("hidden flag must be boolean")


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
        if type(self.sequence_no) is not int or self.sequence_no < 0:
            raise ValueError("sequence_no must be a non-negative integer")
        if type(self.size_bytes) is not int or self.size_bytes < 0:
            raise ValueError("size_bytes must be a non-negative integer")
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


@runtime_checkable
class FileStorePort(Protocol):
    """Opaque persistent-byte boundary. Implementations enforce authorization and storage policy."""

    def put(self, *, object_key: str, content: bytes, expected_sha256: str) -> None: ...
    def issue_read_token(self, *, object_key: str, participant_id: str, ttl_seconds: int) -> str: ...
    def delete(self, *, object_key: str) -> None: ...


def _canonical_id(value: object, label: str) -> str:
    if type(value) is not str or len(value) > MAX_ID_CHARS or _ID_RE.fullmatch(value) is None:
        raise ValueError(f"{label} must be a canonical opaque identifier")
    return value


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


def safe_display_filename(value: str) -> str:
    raw = str(value).replace("\\", "/")
    if raw.startswith("/") or ".." in PurePath(raw).parts:
        raise ValueError("unsafe file path")
    name = PurePath(raw).name.strip()
    if not name or name in {".", ".."}:
        raise ValueError("filename must not be empty")
    clean = _SAFE_NAME_RE.sub("_", name).strip(" .")
    if not clean:
        raise ValueError("filename has no safe display characters")
    return clean[:255]


def content_sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


class ClassroomCollaborationSQLiteStore:
    """Durable provider-neutral chat/file metadata store.

    SQLite stores metadata only. Persistent file bytes belong behind FileStorePort;
    this class never auto-opens or executes attachments and never emits analytics.
    """

    def __init__(self, path: str) -> None:
        self.path = str(path)
        self._migrate()

    def _connect(self) -> sqlite3.Connection:
        db = sqlite3.connect(self.path)
        db.row_factory = sqlite3.Row
        return db

    def _migrate(self) -> None:
        with self._connect() as db:
            db.execute("CREATE TABLE IF NOT EXISTS collaboration_schema_meta(key TEXT PRIMARY KEY, value INTEGER NOT NULL)")
            row = db.execute("SELECT value FROM collaboration_schema_meta WHERE key='schema_version'").fetchone()
            version = int(row[0]) if row else 0
            if version > SCHEMA_VERSION:
                raise CollaborationStorageError(f"unsupported collaboration schema {version}")
            if version < 1:
                db.executescript(
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
                    );
                    CREATE INDEX idx_collaboration_messages_room
                        ON collaboration_messages(room_id, sequence_no);
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
                    );
                    CREATE INDEX idx_collaboration_attachments_room
                        ON collaboration_attachments(room_id, sequence_no);
                    """
                )
                db.execute(
                    "INSERT INTO collaboration_schema_meta(key,value) VALUES('schema_version',?)",
                    (SCHEMA_VERSION,),
                )

    def append_message(self, message: ChatMessageMetadata) -> ChatMessageMetadata:
        with self._connect() as db:
            existing = db.execute(
                "SELECT * FROM collaboration_messages WHERE message_id=?", (message.message_id,)
            ).fetchone()
            if existing is not None:
                loaded = self._message_from_row(existing)
                if loaded != message:
                    raise CollaborationConflictError("message identity reused with different payload")
                return loaded
            try:
                db.execute(
                    "INSERT INTO collaboration_messages VALUES(?,?,?,?,?,?,?)",
                    (
                        message.message_id, message.room_id, message.sender_id, message.sequence_no,
                        message.body, message.retention, int(message.hidden),
                    ),
                )
            except sqlite3.IntegrityError as exc:
                raise CollaborationConflictError("message conflicts with room ordering") from exc
        return message

    def room_messages(self, room_id: str, *, include_hidden: bool = False) -> tuple[ChatMessageMetadata, ...]:
        query = "SELECT * FROM collaboration_messages WHERE room_id=?"
        args: tuple[object, ...] = (room_id,)
        if not include_hidden:
            query += " AND hidden=0"
        query += " ORDER BY sequence_no"
        with self._connect() as db:
            return tuple(self._message_from_row(row) for row in db.execute(query, args))

    def set_message_hidden(self, message_id: str, hidden: bool) -> ChatMessageMetadata:
        with self._connect() as db:
            row = db.execute("SELECT * FROM collaboration_messages WHERE message_id=?", (message_id,)).fetchone()
            if row is None:
                raise CollaborationStorageError(f"unknown message: {message_id}")
            db.execute("UPDATE collaboration_messages SET hidden=? WHERE message_id=?", (int(hidden), message_id))
            updated = db.execute("SELECT * FROM collaboration_messages WHERE message_id=?", (message_id,)).fetchone()
        return self._message_from_row(updated)

    def register_attachment(self, attachment: AttachmentMetadata) -> AttachmentMetadata:
        safe_name = safe_display_filename(attachment.display_name)
        if safe_name != attachment.display_name:
            raise ValueError("display_name must already be sanitized")
        _safe_object_key(attachment.object_key)
        with self._connect() as db:
            existing = db.execute(
                "SELECT * FROM collaboration_attachments WHERE attachment_id=?", (attachment.attachment_id,)
            ).fetchone()
            if existing is not None:
                loaded = self._attachment_from_row(existing)
                if loaded != attachment:
                    raise CollaborationConflictError("attachment identity reused with different payload")
                return loaded
            try:
                db.execute(
                    "INSERT INTO collaboration_attachments VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        attachment.attachment_id, attachment.room_id, attachment.sender_id,
                        attachment.sequence_no, attachment.display_name, attachment.mime_type,
                        attachment.size_bytes, attachment.sha256, attachment.object_key,
                        attachment.transfer_state, attachment.retention, attachment.scan_state,
                    ),
                )
            except sqlite3.IntegrityError as exc:
                raise CollaborationConflictError("attachment conflicts with ordering or storage identity") from exc
        return attachment

    def update_attachment_state(
        self, attachment_id: str, *, transfer_state: str, scan_state: str | None = None
    ) -> AttachmentMetadata:
        with self._connect() as db:
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
        return candidate

    def room_attachments(self, room_id: str) -> tuple[AttachmentMetadata, ...]:
        with self._connect() as db:
            return tuple(
                self._attachment_from_row(row)
                for row in db.execute(
                    "SELECT * FROM collaboration_attachments WHERE room_id=? ORDER BY sequence_no", (room_id,)
                )
            )

    def integrity_check(self) -> None:
        with self._connect() as db:
            result = db.execute("PRAGMA integrity_check").fetchone()[0]
            if result != "ok":
                raise CollaborationStorageError(f"sqlite integrity check failed: {result}")

    @staticmethod
    def _message_from_row(row: sqlite3.Row) -> ChatMessageMetadata:
        return ChatMessageMetadata(
            row["message_id"], row["room_id"], row["sender_id"], int(row["sequence_no"]),
            row["body"], row["retention"], bool(row["hidden"]),
        )

    @staticmethod
    def _attachment_from_row(row: sqlite3.Row) -> AttachmentMetadata:
        return AttachmentMetadata(
            row["attachment_id"], row["room_id"], row["sender_id"], int(row["sequence_no"]),
            row["display_name"], row["mime_type"], int(row["size_bytes"]), row["sha256"],
            row["object_key"], row["transfer_state"], row["retention"], row["scan_state"],
        )
