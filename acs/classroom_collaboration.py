from __future__ import annotations

"""Provider-neutral classroom chat and file-transfer application boundary.

Membership and participant roles are never owned here. They are read from the
canonical ClassroomRosterPort introduced by the realtime-media contract. Realtime
transport, durable object storage and malware scanning remain infrastructure ports.
"""

from dataclasses import dataclass
from enum import Enum
import hashlib
import mimetypes
from pathlib import Path
import re
from typing import Protocol

from .classroom_collaboration_storage import (
    AttachmentMetadata,
    ChatMessageMetadata,
    ClassroomCollaborationSQLiteStore,
    FileStorePort,
    safe_display_filename,
)
from .classroom_realtime_media import ClassroomRole, ClassroomRosterPort


MAX_CHAT_BODY_CHARS = 4000
MAX_SYNC_MESSAGES = 10000
MAX_FILE_BYTES_DEFAULT = 100 * 1024 * 1024
MAX_ROOM_BYTES_DEFAULT = 1024 * 1024 * 1024
_HASH_CHUNK_BYTES = 1024 * 1024
_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")


class CollaborationError(ValueError):
    """Raised for unsafe, unauthorized or ambiguous collaboration operations."""


class ChatModerationAction(str, Enum):
    SET_SEND_PERMISSION = "set_send_permission"
    HIDE_MESSAGE = "hide_message"


@dataclass(frozen=True, slots=True)
class ChatDraft:
    message_id: str
    room_id: str
    sender_id: str
    body: str
    retention: str = "session"

    def __post_init__(self) -> None:
        object.__setattr__(self, "message_id", _id(self.message_id, "message id"))
        object.__setattr__(self, "room_id", _id(self.room_id, "room id"))
        object.__setattr__(self, "sender_id", _id(self.sender_id, "sender id"))
        body = _chat_body(self.body)
        if self.retention not in {"transient", "session", "persistent"}:
            raise CollaborationError("unsupported chat retention policy")
        object.__setattr__(self, "body", body)


@dataclass(frozen=True, slots=True)
class ChatModerationCommand:
    operation_id: str
    room_id: str
    actor_id: str
    target_id: str | None
    action: ChatModerationAction
    allowed: bool | None = None
    message_id: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "operation_id", _id(self.operation_id, "operation id"))
        object.__setattr__(self, "room_id", _id(self.room_id, "room id"))
        object.__setattr__(self, "actor_id", _id(self.actor_id, "actor id"))
        action = _enum(self.action, ChatModerationAction, "chat moderation action")
        if action is ChatModerationAction.SET_SEND_PERMISSION:
            if self.target_id is None or type(self.allowed) is not bool or self.message_id is not None:
                raise CollaborationError("send-permission command shape is invalid")
            object.__setattr__(self, "target_id", _id(self.target_id, "target id"))
        elif action is ChatModerationAction.HIDE_MESSAGE:
            if self.target_id is not None or self.allowed is not None or self.message_id is None:
                raise CollaborationError("hide-message command shape is invalid")
            object.__setattr__(self, "message_id", _id(self.message_id, "message id"))
        object.__setattr__(self, "action", action)


@dataclass(frozen=True, slots=True)
class FileQuotaPolicy:
    max_file_bytes: int = MAX_FILE_BYTES_DEFAULT
    max_room_bytes: int = MAX_ROOM_BYTES_DEFAULT

    def __post_init__(self) -> None:
        for value, label in (
            (self.max_file_bytes, "max file bytes"),
            (self.max_room_bytes, "max room bytes"),
        ):
            if type(value) is not int or value <= 0:
                raise CollaborationError(f"{label} must be a positive integer")
        if self.max_file_bytes > self.max_room_bytes:
            raise CollaborationError("max file bytes cannot exceed max room bytes")


@dataclass(frozen=True, slots=True)
class PreparedFile:
    local_path: Path
    metadata: AttachmentMetadata

    def __post_init__(self) -> None:
        if type(self.local_path) is not Path:
            raise CollaborationError("prepared file path must be pathlib.Path")
        if type(self.metadata) is not AttachmentMetadata:
            raise CollaborationError("prepared file metadata is invalid")


class ChatTransportPort(Protocol):
    """Server-authoritative room chat transport.

    send_message must be idempotent for the same message_id and returns the
    server-assigned room sequence. history_after is bounded by the caller.
    """

    def send_message(self, draft: ChatDraft) -> ChatMessageMetadata:
        ...

    def history_after(
        self,
        *,
        room_id: str,
        after_sequence: int | None,
        limit: int,
    ) -> tuple[ChatMessageMetadata, ...]:
        ...

    def apply_moderation(self, commands: tuple[ChatModerationCommand, ...]) -> None:
        ...


class FileTransferPort(Protocol):
    """Realtime/provider upload boundary over opaque local bytes."""

    def upload(self, prepared: PreparedFile) -> AttachmentMetadata:
        ...

    def cancel(self, *, attachment_id: str) -> None:
        ...

    def retry(self, prepared: PreparedFile) -> AttachmentMetadata:
        ...


class ClassroomCollaborationController:
    """Room collaboration orchestration over canonical external membership."""

    def __init__(
        self,
        *,
        room_id: str,
        local_participant_id: str,
        roster: ClassroomRosterPort,
        chat: ChatTransportPort,
        files: FileTransferPort,
        store: ClassroomCollaborationSQLiteStore,
        file_store: FileStorePort | None = None,
        quota: FileQuotaPolicy = FileQuotaPolicy(),
    ) -> None:
        self.room_id = _id(room_id, "room id")
        self.local_participant_id = _id(local_participant_id, "local participant id")
        self._roster = roster
        self._chat = chat
        self._files = files
        self._store = store
        self._file_store = file_store
        self._quota = quota
        self._chat_locked: set[str] = set()
        self._require_member(self.local_participant_id)

    def send_chat(
        self,
        *,
        message_id: str,
        body: str,
        retention: str = "session",
    ) -> ChatMessageMetadata:
        self._require_member(self.local_participant_id)
        if self.local_participant_id in self._chat_locked:
            raise CollaborationError("chat sending is locked for participant")
        draft = ChatDraft(
            message_id=message_id,
            room_id=self.room_id,
            sender_id=self.local_participant_id,
            body=body,
            retention=retention,
        )
        delivered = self._chat.send_message(draft)
        self._validate_delivered_message(draft, delivered)
        return self._store.append_message(delivered)

    def receive_chat(self, message: ChatMessageMetadata) -> ChatMessageMetadata:
        if type(message) is not ChatMessageMetadata:
            raise CollaborationError("received chat message has invalid type")
        if message.room_id != self.room_id:
            raise CollaborationError("received chat message belongs to another room")
        self._require_member(message.sender_id)
        _chat_body(message.body)
        return self._store.append_message(message)

    def sync_chat(self) -> tuple[ChatMessageMetadata, ...]:
        existing = self._store.room_messages(self.room_id, include_hidden=True)
        after = existing[-1].sequence_no if existing else None
        incoming = self._chat.history_after(
            room_id=self.room_id,
            after_sequence=after,
            limit=MAX_SYNC_MESSAGES,
        )
        if type(incoming) is not tuple or len(incoming) > MAX_SYNC_MESSAGES:
            raise CollaborationError("chat history response is invalid or too large")
        previous = after
        persisted: list[ChatMessageMetadata] = []
        for message in incoming:
            if type(message) is not ChatMessageMetadata:
                raise CollaborationError("chat history contains invalid message type")
            if message.room_id != self.room_id:
                raise CollaborationError("chat history crossed room boundary")
            if previous is not None and message.sequence_no <= previous:
                raise CollaborationError("chat history is not strictly ordered")
            self._require_member(message.sender_id)
            _chat_body(message.body)
            persisted.append(self._store.append_message(message))
            previous = message.sequence_no
        return tuple(persisted)

    def set_chat_send_permission(
        self,
        *,
        actor_id: str,
        target_id: str,
        allowed: bool,
        operation_id: str,
    ) -> None:
        if type(allowed) is not bool:
            raise CollaborationError("chat send permission must be boolean")
        actor, target = self._moderation_pair(actor_id, target_id)
        command = ChatModerationCommand(
            operation_id=operation_id,
            room_id=self.room_id,
            actor_id=actor,
            target_id=target,
            action=ChatModerationAction.SET_SEND_PERMISSION,
            allowed=allowed,
        )
        self._chat.apply_moderation((command,))
        if allowed:
            self._chat_locked.discard(target)
        else:
            self._chat_locked.add(target)

    def set_all_students_chat_send_permission(
        self,
        *,
        actor_id: str,
        allowed: bool,
        operation_id: str,
    ) -> tuple[str, ...]:
        if type(allowed) is not bool:
            raise CollaborationError("chat send permission must be boolean")
        actor = _id(actor_id, "actor id")
        self._require_moderator(actor)
        targets = tuple(
            participant
            for participant in self._participant_ids()
            if self._role(participant) is ClassroomRole.STUDENT
        )
        commands = tuple(
            ChatModerationCommand(
                operation_id=_child_operation_id(operation_id, index),
                room_id=self.room_id,
                actor_id=actor,
                target_id=target,
                action=ChatModerationAction.SET_SEND_PERMISSION,
                allowed=allowed,
            )
            for index, target in enumerate(targets, 1)
        )
        if commands:
            self._chat.apply_moderation(commands)
            if allowed:
                self._chat_locked.difference_update(targets)
            else:
                self._chat_locked.update(targets)
        return targets

    def hide_message(
        self,
        *,
        actor_id: str,
        message_id: str,
        operation_id: str,
    ) -> ChatMessageMetadata:
        actor = _id(actor_id, "actor id")
        self._require_moderator(actor)
        command = ChatModerationCommand(
            operation_id=operation_id,
            room_id=self.room_id,
            actor_id=actor,
            target_id=None,
            action=ChatModerationAction.HIDE_MESSAGE,
            message_id=message_id,
        )
        self._chat.apply_moderation((command,))
        return self._store.set_message_hidden(_id(message_id, "message id"), True)

    def prepare_file(
        self,
        *,
        attachment_id: str,
        local_path: Path,
        sequence_no: int,
        retention: str = "session",
        object_key: str | None = None,
    ) -> PreparedFile:
        self._require_member(self.local_participant_id)
        attachment = _id(attachment_id, "attachment id")
        path = _existing_regular_file(local_path)
        size = path.stat().st_size
        if size > self._quota.max_file_bytes:
            raise CollaborationError("file exceeds configured size limit")
        room_used = sum(
            item.size_bytes
            for item in self._store.room_attachments(self.room_id)
            if item.transfer_state != "deleted"
        )
        if room_used + size > self._quota.max_room_bytes:
            raise CollaborationError("room file quota would be exceeded")
        display_name = safe_display_filename(path.name)
        digest = _sha256_path(path)
        mime_type, _encoding = mimetypes.guess_type(display_name)
        key = object_key or f"rooms/{self.room_id}/{attachment}"
        metadata = AttachmentMetadata(
            attachment_id=attachment,
            room_id=self.room_id,
            sender_id=self.local_participant_id,
            sequence_no=_nonnegative_int(sequence_no, "file sequence"),
            display_name=display_name,
            mime_type=mime_type,
            size_bytes=size,
            sha256=digest,
            object_key=key,
            transfer_state="pending",
            retention=retention,
            scan_state="pending",
        )
        return PreparedFile(path, metadata)

    def upload_file(self, prepared: PreparedFile) -> AttachmentMetadata:
        self._validate_prepared(prepared)
        pending = self._store.register_attachment(prepared.metadata)
        uploading = self._store.update_attachment_state(
            pending.attachment_id,
            transfer_state="uploading",
        )
        candidate = PreparedFile(
            prepared.local_path,
            AttachmentMetadata(
                uploading.attachment_id,
                uploading.room_id,
                uploading.sender_id,
                uploading.sequence_no,
                uploading.display_name,
                uploading.mime_type,
                uploading.size_bytes,
                uploading.sha256,
                uploading.object_key,
                uploading.transfer_state,
                uploading.retention,
                uploading.scan_state,
            ),
        )
        try:
            result = self._files.upload(candidate)
            self._validate_uploaded_result(uploading, result)
        except Exception:
            self._store.update_attachment_state(
                uploading.attachment_id,
                transfer_state="failed",
            )
            raise
        return self._store.update_attachment_state(
            uploading.attachment_id,
            transfer_state=result.transfer_state,
            scan_state=result.scan_state,
        )

    def retry_file(self, prepared: PreparedFile) -> AttachmentMetadata:
        self._validate_prepared(prepared)
        current = self._attachment(prepared.metadata.attachment_id)
        if current.transfer_state != "failed":
            raise CollaborationError("only failed transfer can be retried")
        if (
            current.sha256 != prepared.metadata.sha256
            or current.size_bytes != prepared.metadata.size_bytes
            or current.object_key != prepared.metadata.object_key
        ):
            raise CollaborationError("retry source no longer matches stored attachment identity")
        uploading = self._store.update_attachment_state(
            current.attachment_id,
            transfer_state="uploading",
        )
        candidate = PreparedFile(prepared.local_path, uploading)
        try:
            result = self._files.retry(candidate)
            self._validate_uploaded_result(uploading, result)
        except Exception:
            self._store.update_attachment_state(
                current.attachment_id,
                transfer_state="failed",
            )
            raise
        return self._store.update_attachment_state(
            current.attachment_id,
            transfer_state=result.transfer_state,
            scan_state=result.scan_state,
        )

    def cancel_file(self, attachment_id: str) -> AttachmentMetadata:
        attachment = self._attachment(_id(attachment_id, "attachment id"))
        if attachment.transfer_state not in {"pending", "uploading", "failed"}:
            raise CollaborationError("attachment cannot be cancelled from current state")
        self._files.cancel(attachment_id=attachment.attachment_id)
        return self._store.update_attachment_state(
            attachment.attachment_id,
            transfer_state="deleted",
        )

    def issue_download_token(
        self,
        *,
        attachment_id: str,
        ttl_seconds: int = 300,
    ) -> str:
        if self._file_store is None:
            raise CollaborationError("durable file storage is unavailable")
        attachment = self._attachment(_id(attachment_id, "attachment id"))
        if attachment.transfer_state != "stored":
            raise CollaborationError("attachment is not durably stored")
        if attachment.scan_state != "clean":
            raise CollaborationError("attachment is not cleared for download")
        if type(ttl_seconds) is not int or not 1 <= ttl_seconds <= 3600:
            raise CollaborationError("download token TTL must be from 1 to 3600 seconds")
        token = self._file_store.issue_read_token(
            object_key=attachment.object_key,
            participant_id=self.local_participant_id,
            ttl_seconds=ttl_seconds,
        )
        if type(token) is not str or not token or any(ch.isspace() for ch in token):
            raise CollaborationError("file store returned invalid short-lived token")
        return token

    def _attachment(self, attachment_id: str) -> AttachmentMetadata:
        matches = tuple(
            item
            for item in self._store.room_attachments(self.room_id)
            if item.attachment_id == attachment_id
        )
        if len(matches) != 1:
            raise CollaborationError("unknown attachment in current room")
        return matches[0]

    def _validate_prepared(self, prepared: PreparedFile) -> None:
        if type(prepared) is not PreparedFile:
            raise CollaborationError("file upload requires PreparedFile")
        metadata = prepared.metadata
        if metadata.room_id != self.room_id:
            raise CollaborationError("prepared file belongs to another room")
        if metadata.sender_id != self.local_participant_id:
            raise CollaborationError("prepared file belongs to another sender")
        path = _existing_regular_file(prepared.local_path)
        if path.stat().st_size != metadata.size_bytes:
            raise CollaborationError("prepared file size changed before upload")
        if _sha256_path(path) != metadata.sha256:
            raise CollaborationError("prepared file content changed before upload")

    @staticmethod
    def _validate_uploaded_result(
        expected: AttachmentMetadata,
        result: AttachmentMetadata,
    ) -> None:
        if type(result) is not AttachmentMetadata:
            raise CollaborationError("file transport returned invalid metadata")
        immutable = (
            "attachment_id",
            "room_id",
            "sender_id",
            "sequence_no",
            "display_name",
            "mime_type",
            "size_bytes",
            "sha256",
            "object_key",
            "retention",
        )
        if any(getattr(result, field) != getattr(expected, field) for field in immutable):
            raise CollaborationError("file transport changed immutable attachment identity")
        if result.transfer_state not in {"stored", "failed"}:
            raise CollaborationError("file transport returned non-terminal upload state")

    def _validate_delivered_message(
        self,
        draft: ChatDraft,
        message: ChatMessageMetadata,
    ) -> None:
        if type(message) is not ChatMessageMetadata:
            raise CollaborationError("chat transport returned invalid message metadata")
        if (
            message.message_id != draft.message_id
            or message.room_id != draft.room_id
            or message.sender_id != draft.sender_id
            or message.body != draft.body
            or message.retention != draft.retention
            or message.hidden
        ):
            raise CollaborationError("chat transport changed immutable message identity")

    def _moderation_pair(self, actor_id: str, target_id: str) -> tuple[str, str]:
        actor = _id(actor_id, "actor id")
        target = _id(target_id, "target id")
        if actor == target:
            raise CollaborationError("participant cannot moderate own chat permission")
        self._require_moderator(actor)
        target_role = self._role(target)
        actor_role = self._role(actor)
        if actor_role is ClassroomRole.CO_TEACHER and target_role in {
            ClassroomRole.TEACHER,
            ClassroomRole.CO_TEACHER,
        }:
            raise CollaborationError("co-teacher cannot moderate teacher roles")
        if actor_role is ClassroomRole.TEACHER and target_role is ClassroomRole.TEACHER:
            raise CollaborationError("teacher cannot moderate another teacher")
        return actor, target

    def _require_moderator(self, participant_id: str) -> None:
        role = self._role(participant_id)
        if role not in {ClassroomRole.TEACHER, ClassroomRole.CO_TEACHER}:
            raise CollaborationError("participant cannot moderate room collaboration")

    def _require_member(self, participant_id: str) -> None:
        participant = _id(participant_id, "participant id")
        if participant not in self._participant_ids():
            raise CollaborationError("participant is not present in canonical room roster")

    def _participant_ids(self) -> tuple[str, ...]:
        raw = self._roster.participant_ids()
        if type(raw) is not tuple or len(raw) > 5000:
            raise CollaborationError("canonical room roster is invalid or too large")
        values = tuple(_id(item, "participant id") for item in raw)
        if len(set(values)) != len(values):
            raise CollaborationError("canonical room roster contains duplicate identities")
        return values

    def _role(self, participant_id: str) -> ClassroomRole:
        self._require_member(participant_id)
        try:
            return ClassroomRole(self._roster.role_for(participant_id))
        except (TypeError, ValueError, KeyError) as exc:
            raise CollaborationError("canonical room role lookup failed") from exc


def _id(value: object, label: str) -> str:
    if type(value) is not str or _ID_RE.fullmatch(value) is None:
        raise CollaborationError(f"{label} must be a canonical opaque identifier")
    return value


def _chat_body(value: object) -> str:
    if type(value) is not str:
        raise CollaborationError("chat body must be text")
    if not value or not value.strip():
        raise CollaborationError("chat body must not be empty")
    if len(value) > MAX_CHAT_BODY_CHARS:
        raise CollaborationError("chat body exceeds length limit")
    if "\x00" in value:
        raise CollaborationError("chat body contains NUL")
    return value


def _enum(value: object, enum_type: type[Enum], label: str):
    try:
        return enum_type(value)
    except (TypeError, ValueError) as exc:
        raise CollaborationError(f"invalid {label}") from exc


def _nonnegative_int(value: object, label: str) -> int:
    if type(value) is not int or value < 0:
        raise CollaborationError(f"{label} must be a non-negative integer")
    return value


def _existing_regular_file(value: object) -> Path:
    if type(value) is not Path:
        raise CollaborationError("local file path must be pathlib.Path")
    try:
        resolved = value.resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise CollaborationError("selected file is unavailable") from exc
    if not resolved.is_file():
        raise CollaborationError("selected path is not a regular file")
    return resolved


def _sha256_path(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as stream:
            while True:
                chunk = stream.read(_HASH_CHUNK_BYTES)
                if not chunk:
                    break
                digest.update(chunk)
    except OSError as exc:
        raise CollaborationError("selected file could not be read") from exc
    return digest.hexdigest()


def _child_operation_id(root: str, index: int) -> str:
    root = _id(root, "operation id")
    suffix = f":{index}"
    if len(root) + len(suffix) > 128:
        raise CollaborationError("operation id is too long for batch")
    return _id(root + suffix, "operation id")


__all__ = [
    "ChatDraft",
    "ChatModerationAction",
    "ChatModerationCommand",
    "ChatTransportPort",
    "ClassroomCollaborationController",
    "CollaborationError",
    "FileQuotaPolicy",
    "FileTransferPort",
    "PreparedFile",
]
