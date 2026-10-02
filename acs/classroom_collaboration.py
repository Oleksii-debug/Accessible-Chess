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
    ChatMessageStateUpdate,
    ClassroomCollaborationSQLiteStore,
    CollaborationQuotaError,
    CollaborationSequenceGapError,
    CollaborationStorageError,
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
        if not isinstance(self.local_path, Path):
            raise CollaborationError("prepared file path must be pathlib.Path")
        if type(self.metadata) is not AttachmentMetadata:
            raise CollaborationError("prepared file metadata is invalid")


class ChatTransportPort(Protocol):
    """Server-authoritative room chat transport.

    send_message must be idempotent for the same message_id and returns the
    server-assigned room sequence plus a stable UTC Unix-millisecond send timestamp.
    The transport is also the authoritative send-permission enforcement boundary:
    a participant locked by moderation must be rejected here independently of any
    client/controller lifetime or reconnect. history_after is bounded by the caller
    and returns that same authoritative timestamp for every message.
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

    def state_updates_after(
        self,
        *,
        room_id: str,
        after_revision: int | None,
        limit: int,
    ) -> tuple[ChatMessageStateUpdate, ...]:
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
        self._require_member(self.local_participant_id)

    def send_chat(
        self,
        *,
        message_id: str,
        body: str,
        retention: str = "session",
    ) -> ChatMessageMetadata:
        self._require_member(self.local_participant_id)
        draft = ChatDraft(
            message_id=message_id,
            room_id=self.room_id,
            sender_id=self.local_participant_id,
            body=body,
            retention=retention,
        )
        delivered = self._chat.send_message(draft)
        self._validate_delivered_message(draft, delivered)
        return self._persist_chat_with_gap_recovery(delivered)

    def receive_chat(self, message: ChatMessageMetadata) -> ChatMessageMetadata:
        self._require_member(self.local_participant_id)
        if type(message) is not ChatMessageMetadata:
            raise CollaborationError("received chat message has invalid type")
        if message.room_id != self.room_id:
            raise CollaborationError("received chat message belongs to another room")
        self._require_member(message.sender_id)
        _chat_body(message.body)
        self._require_transport_timestamp(message)
        return self._persist_chat_with_gap_recovery(message)

    def _persist_chat_with_gap_recovery(
        self,
        message: ChatMessageMetadata,
    ) -> ChatMessageMetadata:
        try:
            return self._store.append_message(message)
        except CollaborationSequenceGapError:
            self.sync_chat()
            return self._store.append_message(message)

    def sync_chat(self) -> tuple[ChatMessageMetadata, ...]:
        self._require_member(self.local_participant_id)
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
            self._require_transport_timestamp(message)
            saved = self._store.append_message(message)
            if not saved.hidden:
                persisted.append(saved)
            previous = message.sequence_no

        state_after = self._store.chat_state_revision(self.room_id)
        updates = self._chat.state_updates_after(
            room_id=self.room_id,
            after_revision=state_after,
            limit=MAX_SYNC_MESSAGES,
        )
        if type(updates) is not tuple or len(updates) > MAX_SYNC_MESSAGES:
            raise CollaborationError(
                "chat moderation state response is invalid or too large"
            )
        state_previous = state_after
        for update in updates:
            if type(update) is not ChatMessageStateUpdate:
                raise CollaborationError(
                    "chat moderation state contains invalid update type"
                )
            if update.room_id != self.room_id:
                raise CollaborationError(
                    "chat moderation state crossed room boundary"
                )
            expected_revision = 0 if state_previous is None else state_previous + 1
            if update.revision != expected_revision:
                raise CollaborationError(
                    "chat moderation state has an unresolved revision gap"
                )
            state_previous = update.revision
        try:
            self._store.apply_message_state_updates(
                room_id=self.room_id,
                updates=updates,
            )
        except CollaborationStorageError as error:
            raise CollaborationError(
                "chat moderation state could not be reconciled"
            ) from error
        if updates and persisted:
            visible_ids = {
                message.message_id
                for message in self._store.room_messages(self.room_id)
            }
            persisted = [
                message
                for message in persisted
                if message.message_id in visible_ids
            ]
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

    def set_all_students_chat_send_permission(
        self,
        *,
        actor_id: str,
        allowed: bool,
        operation_id: str,
    ) -> tuple[str, ...]:
        if type(allowed) is not bool:
            raise CollaborationError("chat send permission must be boolean")
        actor = self._local_moderation_actor(actor_id)
        self._require_moderator(actor)
        targets = tuple(sorted(
            participant
            for participant in self._participant_ids()
            if self._role(participant) is ClassroomRole.STUDENT
        ))
        commands = tuple(
            ChatModerationCommand(
                operation_id=_child_operation_id(operation_id, target),
                room_id=self.room_id,
                actor_id=actor,
                target_id=target,
                action=ChatModerationAction.SET_SEND_PERMISSION,
                allowed=allowed,
            )
            for target in targets
        )
        if commands:
            self._chat.apply_moderation(commands)
        return targets

    def hide_message(
        self,
        *,
        actor_id: str,
        message_id: str,
        operation_id: str,
    ) -> ChatMessageMetadata:
        actor = self._local_moderation_actor(actor_id)
        self._require_moderator(actor)
        message = self._message(_id(message_id, "message id"))
        command = ChatModerationCommand(
            operation_id=operation_id,
            room_id=self.room_id,
            actor_id=actor,
            target_id=None,
            action=ChatModerationAction.HIDE_MESSAGE,
            message_id=message.message_id,
        )
        self._chat.apply_moderation((command,))
        return self._store.set_message_hidden(message.message_id, True)

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
        key = object_key or (
            f"rooms/{_storage_key_segment(self.room_id)}/"
            f"{_storage_key_segment(attachment)}"
        )
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
        self._require_member(self.local_participant_id)
        self._validate_prepared(prepared)
        try:
            pending = self._store.register_attachment(
                prepared.metadata,
                max_room_bytes=self._quota.max_room_bytes,
            )
        except CollaborationQuotaError as error:
            raise CollaborationError("room file quota would be exceeded") from error
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
        self._require_member(self.local_participant_id)
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
        if current.scan_state == "blocked":
            raise CollaborationError("blocked attachment cannot be retried")
        retry_scan_state = (
            "pending"
            if current.scan_state == "failed"
            else current.scan_state
        )
        uploading = self._store.update_attachment_state(
            current.attachment_id,
            transfer_state="uploading",
            scan_state=retry_scan_state,
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
        self._require_member(self.local_participant_id)
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
        self._require_member(self.local_participant_id)
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

    def _message(self, message_id: str) -> ChatMessageMetadata:
        matches = tuple(
            item
            for item in self._store.room_messages(
                self.room_id,
                include_hidden=True,
            )
            if item.message_id == message_id
        )
        if len(matches) != 1:
            raise CollaborationError("unknown message in current room")
        return matches[0]

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
            or message.sent_at_unix_ms is None
        ):
            raise CollaborationError("chat transport changed immutable message identity")

    @staticmethod
    def _require_transport_timestamp(message: ChatMessageMetadata) -> None:
        if message.sent_at_unix_ms is None:
            raise CollaborationError("chat transport omitted authoritative send timestamp")

    def _moderation_pair(self, actor_id: str, target_id: str) -> tuple[str, str]:
        actor = self._local_moderation_actor(actor_id)
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

    def _local_moderation_actor(self, actor_id: str) -> str:
        actor = _id(actor_id, "actor id")
        if actor != self.local_participant_id:
            raise CollaborationError(
                "moderation actor must be the local participant"
            )
        self._require_member(actor)
        return actor

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
    if not isinstance(value, Path):
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


def _storage_key_segment(identifier: str) -> str:
    identifier = _id(identifier, "storage identity")
    if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}", identifier):
        return identifier
    digest = hashlib.sha256(identifier.encode("utf-8")).hexdigest()
    return f"id-{digest}"


def _child_operation_id(root: str, target_id: str) -> str:
    root = _id(root, "operation id")
    target = _id(target_id, "target id")
    digest = hashlib.sha256(
        root.encode("utf-8") + b"\x00" + target.encode("utf-8")
    ).hexdigest()
    return _id(f"batch:{digest}", "operation id")


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
