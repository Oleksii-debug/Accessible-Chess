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
from typing import Callable, Protocol

from .classroom_collaboration_storage import (
    AttachmentMetadata,
    AttachmentStateUpdate,
    ChatMessageMetadata,
    ChatMessageStateUpdate,
    ClassroomCollaborationSQLiteStore,
    CollaborationQuotaError,
    CollaborationSequenceGapError,
    CollaborationStorageError,
    FileStorePort,
    safe_display_filename,
)
from .classroom_domain import MAX_WIRE_INTEGER
from .classroom_realtime_media import ClassroomRole, ClassroomRosterPort


MAX_CHAT_BODY_CHARS = 4000
MAX_SYNC_MESSAGES = 10000
MAX_SYNC_ATTACHMENTS = 10000
MAX_DOWNLOAD_TOKEN_CHARS = 8192
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
            if (
                type(value) is not int
                or not 1 <= value <= MAX_WIRE_INTEGER
            ):
                raise CollaborationError(
                    f"{label} must be a positive bounded JSON-safe integer"
                )
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


@dataclass(frozen=True, slots=True)
class AttachmentHistoryPage:
    """Current attachment snapshots bound to an authoritative state watermark."""

    attachments: tuple[AttachmentMetadata, ...]
    snapshot_state_revision: int | None

    def __post_init__(self) -> None:
        if type(self.attachments) is not tuple or any(
            type(item) is not AttachmentMetadata for item in self.attachments
        ):
            raise CollaborationError(
                "attachment history page must contain attachment metadata"
            )
        if self.snapshot_state_revision is not None and (
            type(self.snapshot_state_revision) is not int
            or not 0 <= self.snapshot_state_revision <= MAX_WIRE_INTEGER
        ):
            raise CollaborationError(
                "attachment history state watermark must be a bounded JSON-safe integer"
            )


@dataclass(frozen=True, slots=True)
class FileTransferProgress:
    """Bounded byte progress for one opaque attachment transfer.

    The completion marker is controller-authoritative. Providers may report all
    bytes sent, but only durable stored reconciliation may set terminal completion.
    """

    attachment_id: str
    transferred_bytes: int
    total_bytes: int
    complete: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "attachment_id",
            _id(self.attachment_id, "attachment id"),
        )
        transferred = _nonnegative_int(
            self.transferred_bytes,
            "transferred bytes",
        )
        total = _nonnegative_int(self.total_bytes, "total bytes")
        if transferred > total:
            raise CollaborationError(
                "transferred bytes cannot exceed total bytes"
            )
        if type(self.complete) is not bool:
            raise CollaborationError("progress completion marker must be boolean")
        if self.complete and transferred != total:
            raise CollaborationError(
                "completed transfer progress must equal total bytes"
            )
        object.__setattr__(self, "transferred_bytes", transferred)
        object.__setattr__(self, "total_bytes", total)


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
    """Server-authoritative file metadata plus opaque-byte transfer boundary.

    The transport owns authoritative room-quota enforcement. It must atomically
    reject a new upload with CollaborationQuotaError when accepting that
    attachment would exceed its server-configured room quota. Client-side quota
    checks are advisory safety only and must not be trusted as room authority.
    Retry of the same attachment must not double-count already stored bytes.

    attachment_id is a server idempotency key: immutable identity (room, sender,
    display name, media type, size, hash, object key and retention) must never be
    replaced by a different payload under the same ID.
    """

    def upload(
        self,
        prepared: PreparedFile,
        *,
        on_progress: Callable[[FileTransferProgress], None],
    ) -> AttachmentMetadata:
        """Upload bytes, enforce server policy, and synchronously report bounded byte progress."""
        ...

    def cancel(self, *, attachment_id: str) -> None:
        """Idempotently cancel the same provisional attachment identity.

        An accepted cancellation may lose its acknowledgement. Callers retain
        provisional metadata after that ambiguous failure and retry the same
        attachment_id, so providers must treat repeated cancellation as success.
        """
        ...

    def retry(
        self,
        prepared: PreparedFile,
        *,
        on_progress: Callable[[FileTransferProgress], None],
    ) -> AttachmentMetadata:
        """Retry bytes and synchronously report bounded byte progress."""
        ...

    def history_after(
        self,
        *,
        room_id: str,
        after_sequence: int | None,
        limit: int,
    ) -> AttachmentHistoryPage:
        """Return current snapshots plus the latest state revision they include.

        snapshot_state_revision is a room-wide causal watermark captured
        atomically with the attachment snapshots. Mutable state updates at or
        below that revision are already reflected by each returned snapshot.
        """
        ...

    def state_updates_after(
        self,
        *,
        room_id: str,
        after_revision: int | None,
        limit: int,
    ) -> tuple[AttachmentStateUpdate, ...]:
        """Return mutable attachment-state updates in exact revision order."""
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
        self._file_progress_consumer_depth = 0
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
        try:
            delivered = self._chat.send_message(draft)
        except Exception as initial_error:
            # The transport contract is idempotent for the same message_id.
            # Retry the exact draft once so an accepted-but-unacknowledged send
            # cannot force callers to mint a second logical message.
            try:
                delivered = self._chat.send_message(draft)
            except Exception:
                existing = self._store.room_messages(
                    self.room_id,
                    include_hidden=True,
                )
                matches = tuple(
                    message
                    for message in existing
                    if message.message_id == draft.message_id
                )
                if not matches:
                    after: int | None = None
                    for current in existing:
                        expected = 0 if after is None else after + 1
                        if current.sequence_no != expected:
                            break
                        after = current.sequence_no
                    try:
                        history = self._chat.history_after(
                            room_id=self.room_id,
                            after_sequence=after,
                            limit=MAX_SYNC_MESSAGES,
                        )
                    except Exception:
                        raise initial_error
                    self._validate_chat_history_page(
                        history,
                        after_sequence=after,
                    )
                    matches = tuple(
                        message
                        for message in history
                        if message.message_id == draft.message_id
                    )
                if len(matches) != 1:
                    if not matches:
                        raise initial_error
                    raise CollaborationError(
                        "ambiguous chat recovery returned duplicate message identity"
                    )
                recovered = matches[0]
                self._validate_recovered_message(draft, recovered)
                return self._persist_chat_with_gap_recovery(recovered)
            # A first call may have committed before its acknowledgement was
            # lost, and moderation may hide that accepted message before this
            # exact retry returns. Hidden is mutable state, not immutable send
            # identity, so preserve the authoritative hidden result instead of
            # turning a successful idempotent recovery into a false send error.
            self._validate_recovered_message(draft, delivered)
            return self._persist_chat_with_gap_recovery(delivered)
        self._validate_delivered_message(draft, delivered)
        return self._persist_chat_with_gap_recovery(delivered)

    def receive_chat(self, message: ChatMessageMetadata) -> ChatMessageMetadata:
        self._require_member(self.local_participant_id)
        if type(message) is not ChatMessageMetadata:
            raise CollaborationError("received chat message has invalid type")
        if message.room_id != self.room_id:
            raise CollaborationError("received chat message belongs to another room")
        self._require_member(message.sender_id)
        self._require_transport_timestamp(message)
        if message.hidden or message.redacted:
            existing = tuple(
                item
                for item in self._store.room_messages(
                    self.room_id,
                    include_hidden=True,
                )
                if item.message_id == message.message_id
            )
            if len(existing) != 1:
                raise CollaborationError(
                    "live mutable chat state requires an existing message identity"
                )
            prior = existing[0]
            immutable_fields = (
                "room_id",
                "sender_id",
                "sequence_no",
                "retention",
            )
            if any(
                getattr(prior, field) != getattr(message, field)
                for field in immutable_fields
            ):
                raise CollaborationError(
                    "live mutable chat state conflicts with message identity"
                )
            if (
                not prior.redacted
                and not message.redacted
                and prior.body != message.body
            ):
                raise CollaborationError(
                    "live mutable chat state conflicts with message body"
                )
            if (
                prior.sent_at_unix_ms is not None
                and message.sent_at_unix_ms is not None
                and prior.sent_at_unix_ms != message.sent_at_unix_ms
            ):
                raise CollaborationError(
                    "live mutable chat state conflicts with authoritative timestamp"
                )
            return self._persist_chat_with_gap_recovery(message)
        _chat_body(message.body)
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

    def _validate_chat_history_page(
        self,
        incoming: tuple[ChatMessageMetadata, ...],
        *,
        after_sequence: int | None,
    ) -> None:
        if type(incoming) is not tuple or len(incoming) > MAX_SYNC_MESSAGES:
            raise CollaborationError("chat history response is invalid or too large")

        previous = after_sequence
        for message in incoming:
            if type(message) is not ChatMessageMetadata:
                raise CollaborationError("chat history contains invalid message type")
            if message.room_id != self.room_id:
                raise CollaborationError("chat history crossed room boundary")
            expected_sequence = 0 if previous is None else previous + 1
            if message.sequence_no != expected_sequence:
                raise CollaborationError(
                    "chat history has an unresolved sequence gap"
                )
            # Historical room messages remain durable after a participant leaves.
            # Current membership is enforced for the local reader and live receive,
            # while replay trusts the room-scoped transport's historical sender ID.
            _id(message.sender_id, "sender id")
            if not message.redacted:
                _chat_body(message.body)
            self._require_transport_timestamp(message)
            previous = message.sequence_no

    def sync_chat(self) -> tuple[ChatMessageMetadata, ...]:
        self._require_member(self.local_participant_id)
        existing = self._store.room_messages(self.room_id, include_hidden=True)
        existing_ids = {message.message_id for message in existing}
        after: int | None = None
        for message in existing:
            expected = 0 if after is None else after + 1
            if message.sequence_no != expected:
                break
            after = message.sequence_no
        incoming = self._chat.history_after(
            room_id=self.room_id,
            after_sequence=after,
            limit=MAX_SYNC_MESSAGES,
        )
        self._validate_chat_history_page(
            incoming,
            after_sequence=after,
        )

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
        history_complete = len(incoming) < MAX_SYNC_MESSAGES
        known_message_ids = {
            message.message_id for message in existing
        }
        known_message_ids.update(message.message_id for message in incoming)

        state_previous = state_after
        validated_updates: list[ChatMessageStateUpdate] = []
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
            validated_updates.append(update)
            state_previous = update.revision

        # History and mutable-state pages are separate transport reads. A message
        # can be accepted and hidden after the first history snapshot but before
        # the state snapshot, making a legitimate state update appear to reference
        # an unknown message. If the first history page was complete, make one
        # bounded catch-up read before classifying that state as corrupt.
        if (
            history_complete
            and any(
                update.message_id not in known_message_ids
                for update in validated_updates
            )
        ):
            remaining = MAX_SYNC_MESSAGES - len(incoming)
            catch_up_after = (
                incoming[-1].sequence_no
                if incoming
                else after
            )
            catch_up = self._chat.history_after(
                room_id=self.room_id,
                after_sequence=catch_up_after,
                limit=remaining,
            )
            if type(catch_up) is not tuple or len(catch_up) > remaining:
                raise CollaborationError(
                    "chat history response exceeded requested catch-up bound"
                )
            self._validate_chat_history_page(
                catch_up,
                after_sequence=catch_up_after,
            )
            incoming = incoming + catch_up
            known_message_ids.update(
                message.message_id for message in catch_up
            )
            history_complete = len(catch_up) < remaining

        applicable_updates: list[ChatMessageStateUpdate] = []
        for update in validated_updates:
            if update.message_id not in known_message_ids:
                if history_complete:
                    raise CollaborationError(
                        "chat moderation state references unknown room message"
                    )
                break
            applicable_updates.append(update)

        try:
            persisted = self._store.reconcile_message_sync_atomic(
                room_id=self.room_id,
                messages=incoming,
                updates=tuple(applicable_updates),
            )
        except CollaborationStorageError as error:
            raise CollaborationError(
                "chat history and moderation state could not be reconciled atomically"
            ) from error

        if not persisted:
            return ()
        current_by_id = {
            message.message_id: message
            for message in self._store.room_messages(
                self.room_id,
                include_hidden=True,
            )
        }
        return tuple(
            current_by_id[message.message_id]
            for message in persisted
            if (
                message.message_id not in existing_ids
                and not current_by_id[message.message_id].hidden
                and not current_by_id[message.message_id].redacted
            )
        )

    def can_moderate_chat(self) -> bool:
        """Return whether the local participant currently has chat moderation authority."""
        try:
            self._require_moderator(self.local_participant_id)
        except CollaborationError:
            return False
        return True

    def can_moderate_chat_participant(self, participant_id: str) -> bool:
        """Return whether the local participant may moderate this chat target.

        This is a side-effect-free projection of the same canonical authorization
        used by set_chat_send_permission. Presentation layers may use it to avoid
        exposing controls that the core will deterministically reject.
        """
        try:
            self._moderation_pair(self.local_participant_id, participant_id)
        except CollaborationError:
            return False
        return True

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
        root_operation = _id(operation_id, "operation id")
        targets = tuple(sorted(
            participant
            for participant in self._participant_ids()
            if self._role(participant) is ClassroomRole.STUDENT
        ))
        commands = tuple(
            ChatModerationCommand(
                operation_id=_child_operation_id(root_operation, target),
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
        canonical_key = _canonical_object_key(self.room_id, attachment)
        if object_key is not None and object_key != canonical_key:
            raise CollaborationError(
                "custom object key does not match canonical attachment namespace"
            )
        key = canonical_key
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

    def _require_file_mutation_outside_progress_consumer(self) -> None:
        if self._file_progress_consumer_depth:
            raise CollaborationError(
                "file state cannot be mutated from a progress consumer"
            )

    def upload_file(
        self,
        prepared: PreparedFile,
        *,
        on_progress: Callable[[FileTransferProgress], None] | None = None,
    ) -> AttachmentMetadata:
        self._require_file_mutation_outside_progress_consumer()
        self._require_member(self.local_participant_id)
        self._validate_prepared(prepared)
        progress, complete_progress, close_progress = self._progress_observers(
            prepared.metadata,
            on_progress,
        )
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
        progress(
            FileTransferProgress(
                uploading.attachment_id,
                0,
                uploading.size_bytes,
            )
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
            result = self._files.upload(
                candidate,
                on_progress=progress,
            )
            self._validate_uploaded_result(uploading, result)
        except CollaborationQuotaError as error:
            close_progress()
            self._store.update_attachment_state(
                uploading.attachment_id,
                transfer_state="failed",
            )
            raise CollaborationError(
                "server room file quota would be exceeded"
            ) from error
        except Exception:
            close_progress()
            self._store.update_attachment_state(
                uploading.attachment_id,
                transfer_state="failed",
            )
            raise
        try:
            adopted = self._adopt_authoritative_upload(result)
        except Exception:
            close_progress()
            raise
        if adopted.transfer_state == "stored":
            complete_progress()
        else:
            close_progress()
        return adopted

    def retry_file(
        self,
        prepared: PreparedFile,
        *,
        on_progress: Callable[[FileTransferProgress], None] | None = None,
    ) -> AttachmentMetadata:
        self._require_file_mutation_outside_progress_consumer()
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
        progress, complete_progress, close_progress = self._progress_observers(
            current,
            on_progress,
        )
        uploading = self._store.update_attachment_state(
            current.attachment_id,
            transfer_state="uploading",
            scan_state=retry_scan_state,
        )
        progress(
            FileTransferProgress(
                uploading.attachment_id,
                0,
                uploading.size_bytes,
            )
        )
        candidate = PreparedFile(prepared.local_path, uploading)
        try:
            result = self._files.retry(
                candidate,
                on_progress=progress,
            )
            self._validate_uploaded_result(uploading, result)
        except CollaborationQuotaError as error:
            close_progress()
            self._store.update_attachment_state(
                current.attachment_id,
                transfer_state="failed",
            )
            raise CollaborationError(
                "server room file quota would be exceeded"
            ) from error
        except Exception:
            close_progress()
            self._store.update_attachment_state(
                current.attachment_id,
                transfer_state="failed",
            )
            raise
        try:
            adopted = self._adopt_authoritative_upload(result)
        except Exception:
            close_progress()
            raise
        if adopted.transfer_state == "stored":
            complete_progress()
        else:
            close_progress()
        return adopted

    def receive_file(self, attachment: AttachmentMetadata) -> AttachmentMetadata:
        self._require_file_mutation_outside_progress_consumer()
        self._require_member(self.local_participant_id)
        self._validate_remote_attachment(
            attachment,
            require_current_sender=True,
            allow_tombstone=False,
        )

        def existing_delivery() -> AttachmentMetadata | None:
            matches = tuple(
                item
                for item in self._store.room_attachments(self.room_id)
                if item.attachment_id == attachment.attachment_id
            )
            if not matches:
                return None
            if len(matches) != 1:
                raise CollaborationError("duplicate attachment identity in current room")
            current = matches[0]
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
                raise CollaborationError(
                    "live file reused attachment identity with different payload"
                )
            if current.transfer_state == "pending":
                # No provider operation has started for a pending row, so a
                # live server event reusing that identity is a collision, not
                # ambiguous-upload recovery.
                raise CollaborationError(
                    "live file conflicts with local pending attachment identity"
                )
            if current.transfer_state in {"uploading", "failed"}:
                # The provider may have committed an upload while this client
                # crashed or observed an ambiguous failure. The local sequence
                # is provisional; allow room authority to reconcile it below.
                return None
            if current.sequence_no != attachment.sequence_no:
                raise CollaborationError(
                    "live file changed authoritative attachment sequence"
                )
            # Preserve any newer mutable state already reconciled locally; a
            # delayed stored push must never resurrect a tombstone or scan block.
            return current

        existing = existing_delivery()
        if existing is not None:
            return existing

        authoritative = tuple(
            item
            for item in self._store.room_attachments(self.room_id)
            if item.transfer_state in {"stored", "deleted"}
        )
        after: int | None = None
        for current in authoritative:
            expected = 0 if after is None else after + 1
            if current.sequence_no != expected:
                break
            after = current.sequence_no
        expected_sequence = 0 if after is None else after + 1
        if attachment.sequence_no > expected_sequence:
            self.sync_files()
            existing = existing_delivery()
            if existing is not None:
                return existing
            authoritative = tuple(
                item
                for item in self._store.room_attachments(self.room_id)
                if item.transfer_state in {"stored", "deleted"}
            )
            after = None
            for current in authoritative:
                expected = 0 if after is None else after + 1
                if current.sequence_no != expected:
                    break
                after = current.sequence_no
            expected_sequence = 0 if after is None else after + 1
        if attachment.sequence_no != expected_sequence:
            raise CollaborationError(
                "live file sequence is stale or unresolved after recovery"
            )
        try:
            persisted = self._store.reconcile_attachment_sync_atomic(
                room_id=self.room_id,
                attachments=(attachment,),
                updates=(),
            )
        except CollaborationStorageError as error:
            raise CollaborationError(
                "remote attachment could not be reconciled"
            ) from error
        return persisted[0]

    def sync_files(self) -> tuple[AttachmentMetadata, ...]:
        self._require_file_mutation_outside_progress_consumer()
        self._require_member(self.local_participant_id)
        # Retry already-durable cleanup before any network dependency. A
        # provider outage after restart must not strand object-store bytes whose
        # tombstone was committed by an earlier authoritative sync.
        self._drain_file_deletions()
        existing = self._store.room_attachments(self.room_id)
        authoritative = tuple(
            item
            for item in existing
            if item.transfer_state in {"stored", "deleted"}
        )
        existing_authoritative_ids = {
            item.attachment_id for item in authoritative
        }
        # Advance only through the locally complete authoritative prefix. A
        # later terminal row must never cause reconnect to skip missing history.
        after: int | None = None
        for attachment in authoritative:
            expected = 0 if after is None else after + 1
            if attachment.sequence_no != expected:
                break
            after = attachment.sequence_no
        page = self._files.history_after(
            room_id=self.room_id,
            after_sequence=after,
            limit=MAX_SYNC_ATTACHMENTS,
        )
        if type(page) is not AttachmentHistoryPage:
            raise CollaborationError("file history response is invalid")
        incoming = page.attachments
        if len(incoming) > MAX_SYNC_ATTACHMENTS:
            raise CollaborationError("file history response is invalid or too large")

        expected_sequence = 0 if after is None else after + 1
        for attachment in incoming:
            self._validate_remote_attachment(
                attachment,
                require_current_sender=False,
                allow_tombstone=True,
            )
            if attachment.sequence_no != expected_sequence:
                raise CollaborationError(
                    "file history has an unresolved sequence gap"
                )
            expected_sequence += 1

        state_after = self._store.attachment_state_revision(self.room_id)
        if state_after is not None and (
            page.snapshot_state_revision is None
            or page.snapshot_state_revision < state_after
        ):
            raise CollaborationError("file history state watermark regressed")
        updates = self._files.state_updates_after(
            room_id=self.room_id,
            after_revision=state_after,
            limit=MAX_SYNC_ATTACHMENTS,
        )
        if type(updates) is not tuple or len(updates) > MAX_SYNC_ATTACHMENTS:
            raise CollaborationError(
                "attachment state response is invalid or too large"
            )
        history_complete = len(incoming) < MAX_SYNC_ATTACHMENTS
        # State updates are not attachment-discovery authority. Only metadata
        # already proven authoritative locally, or metadata present in this
        # authoritative history page, may be targeted. In particular, a stranded
        # local pending/uploading/failed row must never be promoted to stored by
        # the mutable state stream without its immutable server history record.
        known_attachment_ids = {
            item.attachment_id
            for item in authoritative
        }
        known_attachment_ids.update(item.attachment_id for item in incoming)
        state_previous = state_after
        applicable_updates: list[AttachmentStateUpdate] = []
        for update in updates:
            if type(update) is not AttachmentStateUpdate:
                raise CollaborationError(
                    "attachment state response contains invalid update type"
                )
            if update.room_id != self.room_id:
                raise CollaborationError(
                    "attachment state response crossed room boundary"
                )
            expected_revision = (
                0 if state_previous is None else state_previous + 1
            )
            if update.revision != expected_revision:
                raise CollaborationError(
                    "attachment state has an unresolved revision gap"
                )
            if update.attachment_id not in known_attachment_ids:
                if history_complete:
                    raise CollaborationError(
                        "attachment state references unknown room attachment"
                    )
                break
            applicable_updates.append(update)
            state_previous = update.revision

        try:
            persisted = self._store.reconcile_attachment_sync_atomic(
                room_id=self.room_id,
                attachments=incoming,
                updates=tuple(applicable_updates),
                snapshot_state_revision=page.snapshot_state_revision,
            )
        except CollaborationStorageError as error:
            raise CollaborationError(
                "attachment history and state could not be reconciled atomically"
            ) from error

        self._drain_file_deletions()

        if not persisted:
            return ()
        current_by_id = {
            item.attachment_id: item
            for item in self._store.room_attachments(self.room_id)
        }
        return tuple(
            current_by_id[item.attachment_id]
            for item in persisted
            if (
                item.attachment_id not in existing_authoritative_ids
                and current_by_id[item.attachment_id].transfer_state == "stored"
            )
        )

    def _drain_file_deletions(self) -> None:
        if self._file_store is None:
            return
        try:
            pending = self._store.pending_attachment_deletions(self.room_id)
        except CollaborationStorageError as error:
            raise CollaborationError(
                "durable file deletion state is invalid"
            ) from error
        for object_key in pending:
            try:
                self._file_store.delete(object_key=object_key)
            except Exception:
                # Deletion intent remains durable. FileStorePort.delete is
                # idempotent so a crash after remote deletion but before local
                # acknowledgement is safe to retry.
                raise CollaborationError("durable file deletion failed") from None
            try:
                self._store.acknowledge_attachment_deletion(
                    room_id=self.room_id,
                    object_key=object_key,
                )
            except CollaborationStorageError as error:
                raise CollaborationError(
                    "durable file deletion acknowledgement failed"
                ) from error

    def cancel_file(self, attachment_id: str) -> AttachmentMetadata:
        self._require_file_mutation_outside_progress_consumer()
        self._require_member(self.local_participant_id)
        attachment = self._attachment(_id(attachment_id, "attachment id"))
        if attachment.sender_id != self.local_participant_id:
            raise CollaborationError(
                "participant cannot cancel another participant's attachment"
            )
        if attachment.transfer_state not in {"pending", "uploading", "failed"}:
            raise CollaborationError("attachment cannot be cancelled from current state")
        self._files.cancel(attachment_id=attachment.attachment_id)
        try:
            return self._store.discard_provisional_attachment(
                attachment.attachment_id
            )
        except CollaborationStorageError as error:
            raise CollaborationError(
                "cancelled provisional attachment could not be discarded"
            ) from error

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
        if (
            type(token) is not str
            or not token
            or len(token) > MAX_DOWNLOAD_TOKEN_CHARS
            or any(
                ch.isspace() or ord(ch) < 32 or ord(ch) == 127
                for ch in token
            )
        ):
            raise CollaborationError("file store returned invalid short-lived token")
        return token

    def is_current_participant(self, participant_id: str) -> bool:
        participant = _id(participant_id, "participant id")
        return participant in self._participant_ids()

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
        if metadata.transfer_state != "pending" or metadata.scan_state != "pending":
            raise CollaborationError("prepared file must start in pending state")
        path = _existing_regular_file(prepared.local_path)
        display_name = safe_display_filename(path.name)
        if metadata.display_name != display_name:
            raise CollaborationError("prepared file display name does not match selected file")
        mime_type, _encoding = mimetypes.guess_type(display_name)
        if metadata.mime_type != mime_type:
            raise CollaborationError("prepared file MIME type does not match selected file")
        if metadata.object_key != _canonical_object_key(
            self.room_id,
            metadata.attachment_id,
        ):
            raise CollaborationError("prepared file object key is outside canonical namespace")
        if path.stat().st_size != metadata.size_bytes:
            raise CollaborationError("prepared file size changed before upload")
        if _sha256_path(path) != metadata.sha256:
            raise CollaborationError("prepared file content changed before upload")

    def _progress_observers(
        self,
        attachment: AttachmentMetadata,
        consumer: Callable[[FileTransferProgress], None] | None,
    ) -> tuple[
        Callable[[FileTransferProgress], None],
        Callable[[], None],
        Callable[[], None],
    ]:
        if consumer is not None and not callable(consumer):
            raise CollaborationError("file progress consumer must be callable")
        last_transferred = -1
        terminal_emitted = False

        def deliver(sample: FileTransferProgress) -> None:
            if consumer is not None:
                self._file_progress_consumer_depth += 1
                try:
                    consumer(sample)
                except Exception:
                    # Presentation delivery is an observer boundary. A broken UI
                    # consumer must not turn a valid provider transfer into an
                    # ambiguous remote upload.
                    pass
                finally:
                    self._file_progress_consumer_depth -= 1

        def observe_provider(sample: FileTransferProgress) -> None:
            nonlocal last_transferred
            if terminal_emitted:
                # A provider callback is synchronous by contract. Ignore any
                # retained/late callback after controller-authoritative
                # completion so presentation can never regress from terminal.
                return
            if type(sample) is not FileTransferProgress:
                raise CollaborationError(
                    "file transport returned invalid progress metadata"
                )
            if sample.complete:
                raise CollaborationError(
                    "file transport cannot claim authoritative completion"
                )
            if sample.attachment_id != attachment.attachment_id:
                raise CollaborationError(
                    "file transfer progress belongs to another attachment"
                )
            if sample.total_bytes != attachment.size_bytes:
                raise CollaborationError(
                    "file transfer progress changed attachment size"
                )
            if sample.transferred_bytes < last_transferred:
                raise CollaborationError(
                    "file transfer progress moved backwards"
                )
            if sample.transferred_bytes == last_transferred:
                return
            last_transferred = sample.transferred_bytes
            deliver(sample)

        def close() -> None:
            nonlocal terminal_emitted
            terminal_emitted = True

        def complete() -> None:
            nonlocal terminal_emitted
            if terminal_emitted:
                return
            terminal_emitted = True
            deliver(
                FileTransferProgress(
                    attachment.attachment_id,
                    attachment.size_bytes,
                    attachment.size_bytes,
                    complete=True,
                )
            )

        return observe_provider, complete, close

    def _adopt_authoritative_upload(
        self,
        result: AttachmentMetadata,
    ) -> AttachmentMetadata:
        # A successful upload can legitimately receive a later room sequence
        # when other clients published files concurrently. Never publish that
        # later row into a locally gapped history: first reconcile the missing
        # authoritative prefix from the provider.
        authoritative = tuple(
            item
            for item in self._store.room_attachments(self.room_id)
            if item.transfer_state in {"stored", "deleted"}
        )
        after: int | None = None
        for current in authoritative:
            expected = 0 if after is None else after + 1
            if current.sequence_no != expected:
                break
            after = current.sequence_no
        expected_sequence = 0 if after is None else after + 1
        if (
            result.transfer_state == "stored"
            and result.sequence_no > expected_sequence
        ):
            self.sync_files()
            authoritative = tuple(
                item
                for item in self._store.room_attachments(self.room_id)
                if item.transfer_state in {"stored", "deleted"}
            )
            after = None
            for current in authoritative:
                expected = 0 if after is None else after + 1
                if current.sequence_no != expected:
                    break
                after = current.sequence_no
            expected_sequence = 0 if after is None else after + 1
            if result.sequence_no > expected_sequence:
                raise CollaborationError(
                    "file authority sequence prefix remains incomplete after recovery"
                )
        try:
            return self._store.adopt_authoritative_attachment(result)
        except CollaborationStorageError as error:
            raise CollaborationError(
                "file transport authority could not be reconciled"
            ) from error

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
        if (
            result.transfer_state == "failed"
            and result.sequence_no != expected.sequence_no
        ):
            raise CollaborationError(
                "failed file transport result changed provisional sequence"
            )

    def _validate_remote_attachment(
        self,
        attachment: AttachmentMetadata,
        *,
        require_current_sender: bool,
        allow_tombstone: bool,
    ) -> None:
        if type(attachment) is not AttachmentMetadata:
            raise CollaborationError("file history contains invalid attachment type")
        if attachment.room_id != self.room_id:
            raise CollaborationError("file history crossed room boundary")
        if require_current_sender:
            self._require_member(attachment.sender_id)
        else:
            # Durable room history survives participant departure. Live receive
            # still requires current membership, while replay trusts the
            # room-scoped authoritative transport and validates sender identity.
            _id(attachment.sender_id, "sender id")
        canonical_key = (
            f"rooms/{_storage_key_segment(self.room_id)}/"
            f"{_storage_key_segment(attachment.attachment_id)}"
        )
        if attachment.object_key != canonical_key:
            raise CollaborationError(
                "file history crossed canonical attachment namespace"
            )
        allowed_states = {"stored", "deleted"} if allow_tombstone else {"stored"}
        if attachment.transfer_state not in allowed_states:
            raise CollaborationError(
                "file history contains non-durable attachment state"
            )

    @staticmethod
    def _validate_recovered_message(
        draft: ChatDraft,
        message: ChatMessageMetadata,
    ) -> None:
        if (
            type(message) is not ChatMessageMetadata
            or message.message_id != draft.message_id
            or message.room_id != draft.room_id
            or message.sender_id != draft.sender_id
            or (
                not message.redacted
                and message.body != draft.body
            )
            or message.retention != draft.retention
            or message.sent_at_unix_ms is None
        ):
            raise CollaborationError(
                "recovered chat message changed immutable message identity"
            )

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
            or message.redacted
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
    if any(0xD800 <= ord(ch) <= 0xDFFF for ch in value):
        raise CollaborationError("chat body contains invalid Unicode surrogate")
    return value


def _enum(value: object, enum_type: type[Enum], label: str):
    try:
        return enum_type(value)
    except (TypeError, ValueError) as exc:
        raise CollaborationError(f"invalid {label}") from exc


def _nonnegative_int(value: object, label: str) -> int:
    if (
        type(value) is not int
        or not 0 <= value <= MAX_WIRE_INTEGER
    ):
        raise CollaborationError(
            f"{label} must be a bounded non-negative JSON-safe integer"
        )
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


def _canonical_object_key(room_id: str, attachment_id: str) -> str:
    return (
        f"rooms/{_storage_key_segment(room_id)}/"
        f"{_storage_key_segment(attachment_id)}"
    )


def _child_operation_id(root: str, target_id: str) -> str:
    root = _id(root, "operation id")
    target = _id(target_id, "target id")
    digest = hashlib.sha256(
        root.encode("utf-8") + b"\x00" + target.encode("utf-8")
    ).hexdigest()
    return _id(f"batch:{digest}", "operation id")


__all__ = [
    "AttachmentHistoryPage",
    "ChatDraft",
    "ChatModerationAction",
    "ChatModerationCommand",
    "ChatTransportPort",
    "ClassroomCollaborationController",
    "CollaborationError",
    "FileQuotaPolicy",
    "FileTransferPort",
    "FileTransferProgress",
    "PreparedFile",
]
