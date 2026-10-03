from __future__ import annotations

"""Crash-safe encrypted chat-draft outbox for Windows classroom collaboration.

The canonical collaboration controller remains the authority for membership,
transport semantics, ordering and SQLite metadata.  This module only preserves
the exact logical chat draft across a full desktop-process restart until the
canonical controller can prove that exact message durable.

Draft plaintext is stored only through SecretStore.  Slot names depend on
room/participant identity and a fixed numeric slot, never on draft text, so the
filesystem does not become a dictionary-friendly fingerprint oracle.
"""

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import stat

if os.name == "nt":
    import msvcrt
else:
    import fcntl

from .classroom_collaboration import ChatDraft, ClassroomCollaborationController
from .classroom_collaboration_storage import ChatMessageMetadata
from .secret_store import SecretStore


_MAX_PENDING_DRAFTS = 32
_RECORD_VERSION = 1
_MAX_RECORD_BYTES = 32 * 1024


class DurableChatOutboxError(RuntimeError):
    """Raised when durable draft recovery cannot be proven safely."""


class DurableChatOutboxBusyError(DurableChatOutboxError):
    """Raised when another process owns the outbox mutation transaction."""


def _is_reparse(info: os.stat_result) -> bool:
    flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    return bool(getattr(info, "st_file_attributes", 0) & flag)


def _same_file_identity(left: os.stat_result, right: os.stat_result) -> bool:
    left_ino = getattr(left, "st_ino", 0)
    right_ino = getattr(right, "st_ino", 0)
    if left_ino and right_ino:
        return (getattr(left, "st_dev", None), left_ino) == (
            getattr(right, "st_dev", None),
            right_ino,
        )
    return True


def _unsafe_lock_file(info: os.stat_result) -> bool:
    return (
        not stat.S_ISREG(info.st_mode)
        or stat.S_ISLNK(info.st_mode)
        or _is_reparse(info)
        or getattr(info, "st_nlink", 1) != 1
    )


def _open_peer_lock_file(path: Path):
    """Open one stable regular lock inode without following replacement links."""

    try:
        parent = path.parent.lstat()
    except OSError as exc:
        raise DurableChatOutboxError(
            "chat outbox lock parent cannot be inspected safely"
        ) from exc
    if not stat.S_ISDIR(parent.st_mode) or stat.S_ISLNK(parent.st_mode) or _is_reparse(parent):
        raise DurableChatOutboxError(
            "chat outbox lock parent must be a regular directory"
        )

    for _attempt in range(8):
        try:
            before = path.lstat()
        except FileNotFoundError:
            before = None
        except OSError as exc:
            raise DurableChatOutboxError(
                "chat outbox peer lock cannot be inspected safely"
            ) from exc

        if before is not None and _unsafe_lock_file(before):
            raise DurableChatOutboxError(
                "chat outbox peer lock must be one regular unlinked file"
            )

        flags = os.O_RDWR
        if hasattr(os, "O_BINARY"):
            flags |= os.O_BINARY
        if before is None:
            flags |= os.O_CREAT | os.O_EXCL
        elif hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW

        try:
            fd = os.open(os.fspath(path), flags, 0o600)
        except (FileExistsError, FileNotFoundError):
            continue
        except OSError as exc:
            raise DurableChatOutboxError(
                "chat outbox peer lock cannot be opened safely"
            ) from exc

        try:
            opened = os.fstat(fd)
            try:
                current = path.lstat()
            except FileNotFoundError as exc:
                raise DurableChatOutboxError(
                    "chat outbox peer lock changed while opening"
                ) from exc
            if (
                _unsafe_lock_file(opened)
                or _unsafe_lock_file(current)
                or not _same_file_identity(opened, current)
                or (
                    before is not None
                    and not _same_file_identity(before, opened)
                )
            ):
                raise DurableChatOutboxError(
                    "chat outbox peer lock changed while opening"
                )
            return os.fdopen(fd, "r+b")
        except Exception:
            os.close(fd)
            raise

    raise DurableChatOutboxBusyError(
        "chat outbox peer lock changed while acquiring"
    )


@dataclass(frozen=True, slots=True)
class ChatOutboxResolution:
    draft: ChatDraft
    persisted_message: ChatMessageMetadata | None = None


class DurableChatDraftOutbox:
    """One encrypted fixed-slot outbox for one room participant.

    Each draft occupies a fixed numbered SecretStore slot.  The slot path is
    independent of the message body and message ID.  A slot is deleted only
    after the exact canonical message is known durable, or when a later send
    proves that a previously pending slot is already durable locally.
    """

    def __init__(
        self,
        *,
        secret_store: SecretStore,
        room_id: str,
        participant_id: str,
        storage_scope: str,
        lock_path: str | Path,
        message_lookup: Callable[[str], ChatMessageMetadata | None],
    ) -> None:
        for method in ("read", "write", "delete"):
            if not callable(getattr(secret_store, method, None)):
                raise TypeError("secret_store must implement SecretStore")
        if type(room_id) is not str or not room_id:
            raise TypeError("room_id must be non-empty text")
        if type(participant_id) is not str or not participant_id:
            raise TypeError("participant_id must be non-empty text")
        if type(storage_scope) is not str or not storage_scope:
            raise TypeError("storage_scope must be non-empty text")
        if not isinstance(lock_path, (str, Path)):
            raise TypeError("lock_path must be a filesystem path")
        lock = Path(lock_path)
        if not lock.is_absolute() or not lock.name:
            raise ValueError("lock_path must be an absolute file path")
        if not callable(message_lookup):
            raise TypeError("message_lookup must be callable")
        # Reuse ChatDraft's canonical opaque-ID validation without inventing a
        # second identity parser.
        ChatDraft(
            message_id="validation-message",
            room_id=room_id,
            sender_id=participant_id,
            body="validation",
        )
        self._secret_store = secret_store
        self._room_id = room_id
        self._participant_id = participant_id
        self._message_lookup = message_lookup
        self._lock_path = lock
        identity = hashlib.sha256(
            (
                storage_scope
                + "\0"
                + room_id
                + "\0"
                + participant_id
            ).encode("utf-8")
        ).hexdigest()
        self._slot_prefix = f"classroom-chat-outbox-{identity}"

    def _slot(self, index: int) -> str:
        if type(index) is not int or not 0 <= index < _MAX_PENDING_DRAFTS:
            raise DurableChatOutboxError("chat outbox slot index is invalid")
        return f"{self._slot_prefix}-{index:02d}"

    @contextmanager
    def _peer_lock(self) -> Iterator[None]:
        """Serialize one read/reconcile/slot-mutation transaction across processes."""

        handle = _open_peer_lock_file(self._lock_path)
        acquired = False
        try:
            if os.name == "nt":
                handle.seek(0, os.SEEK_END)
                if handle.tell() == 0:
                    handle.write(b"\0")
                    handle.flush()
                handle.seek(0)
                try:
                    msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                except OSError as exc:
                    raise DurableChatOutboxBusyError(
                        "chat outbox is busy in another process"
                    ) from exc
            else:
                try:
                    fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                except OSError as exc:
                    raise DurableChatOutboxBusyError(
                        "chat outbox is busy in another process"
                    ) from exc
            acquired = True
            yield
        finally:
            if acquired:
                try:
                    if os.name == "nt":
                        handle.seek(0)
                        msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
                    else:
                        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
                except OSError:
                    # Closing the descriptor releases the process-owned lock
                    # even if explicit cleanup reports an error.
                    pass
            handle.close()

    @staticmethod
    def _loads_no_duplicates(raw: str) -> object:
        def pairs(items: list[tuple[str, object]]) -> dict[str, object]:
            result: dict[str, object] = {}
            for key, value in items:
                if key in result:
                    raise DurableChatOutboxError(
                        "chat outbox record contains duplicate JSON members"
                    )
                result[key] = value
            return result

        try:
            return json.loads(raw, object_pairs_hook=pairs)
        except DurableChatOutboxError:
            raise
        except Exception as exc:
            raise DurableChatOutboxError("chat outbox record is not valid JSON") from exc

    def _encode(self, draft: ChatDraft) -> bytes:
        payload = {
            "v": _RECORD_VERSION,
            "message_id": draft.message_id,
            "room_id": draft.room_id,
            "sender_id": draft.sender_id,
            "body": draft.body,
            "retention": draft.retention,
        }
        raw = json.dumps(
            payload,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
        if not raw or len(raw) > _MAX_RECORD_BYTES:
            raise DurableChatOutboxError("chat outbox record exceeds size limit")
        return raw

    def _decode(self, raw: bytes) -> ChatDraft:
        if type(raw) is not bytes or not raw or len(raw) > _MAX_RECORD_BYTES:
            raise DurableChatOutboxError("chat outbox record has invalid size")
        try:
            text = raw.decode("utf-8", errors="strict")
        except UnicodeDecodeError as exc:
            raise DurableChatOutboxError("chat outbox record is not UTF-8") from exc
        payload = self._loads_no_duplicates(text)
        if type(payload) is not dict or set(payload) != {
            "v",
            "message_id",
            "room_id",
            "sender_id",
            "body",
            "retention",
        }:
            raise DurableChatOutboxError("chat outbox record shape is invalid")
        if payload["v"] != _RECORD_VERSION or type(payload["v"]) is not int:
            raise DurableChatOutboxError("chat outbox record version is unsupported")
        try:
            draft = ChatDraft(
                message_id=payload["message_id"],
                room_id=payload["room_id"],
                sender_id=payload["sender_id"],
                body=payload["body"],
                retention=payload["retention"],
            )
        except Exception as exc:
            raise DurableChatOutboxError("chat outbox draft is invalid") from exc
        if (
            draft.room_id != self._room_id
            or draft.sender_id != self._participant_id
        ):
            raise DurableChatOutboxError("chat outbox record crossed identity boundary")
        return draft

    def _read_slot(self, index: int) -> ChatDraft | None:
        try:
            raw = self._secret_store.read(self._slot(index))
        except Exception as exc:
            raise DurableChatOutboxError("chat outbox secret cannot be read") from exc
        if raw is None:
            return None
        return self._decode(raw)

    def _delete_slot(self, index: int) -> None:
        try:
            self._secret_store.delete(self._slot(index))
        except Exception as exc:
            raise DurableChatOutboxError("chat outbox secret cannot be deleted") from exc

    def _lookup_persisted(self, draft: ChatDraft) -> ChatMessageMetadata | None:
        try:
            message = self._message_lookup(draft.message_id)
        except Exception as exc:
            raise DurableChatOutboxError(
                "chat outbox durable-message lookup failed"
            ) from exc
        if message is None:
            return None
        if type(message) is not ChatMessageMetadata:
            raise DurableChatOutboxError(
                "chat outbox durable-message lookup returned invalid type"
            )
        if (
            message.message_id != draft.message_id
            or message.room_id != draft.room_id
            or message.sender_id != draft.sender_id
            or message.body != draft.body
            or message.retention != draft.retention
        ):
            raise DurableChatOutboxError(
                "chat outbox identity conflicts with durable chat metadata"
            )
        return message

    def prepare(self, candidate: ChatDraft) -> ChatOutboxResolution:
        with self._peer_lock():
            return self._prepare_locked(candidate)

    def _prepare_locked(self, candidate: ChatDraft) -> ChatOutboxResolution:
        if type(candidate) is not ChatDraft:
            raise TypeError("candidate must be ChatDraft")
        if (
            candidate.room_id != self._room_id
            or candidate.sender_id != self._participant_id
        ):
            raise DurableChatOutboxError("chat draft crossed outbox identity boundary")

        empty_slot: int | None = None
        matching: tuple[int, ChatDraft, ChatMessageMetadata | None] | None = None
        seen_message_ids: set[str] = set()

        for index in range(_MAX_PENDING_DRAFTS):
            stored = self._read_slot(index)
            if stored is None:
                if empty_slot is None:
                    empty_slot = index
                continue
            if stored.message_id in seen_message_ids:
                raise DurableChatOutboxError(
                    "chat outbox contains duplicate message identity"
                )
            seen_message_ids.add(stored.message_id)
            persisted = self._lookup_persisted(stored)

            # Mirror the existing WebView pending-draft identity: body text is
            # the logical retry key.  If retention changed while an ambiguous
            # send was unresolved, retry the exact stored draft (including its
            # original retention) rather than minting a second message.
            same_logical_draft = stored.body == candidate.body
            if same_logical_draft:
                if matching is not None:
                    raise DurableChatOutboxError(
                        "chat outbox contains duplicate logical draft"
                    )
                matching = (index, stored, persisted)
                continue

            if persisted is not None:
                # A previous send was canonical and durable but cleanup did not
                # finish.  Retire that stale slot before accepting unrelated new
                # work; failure here blocks the new network effect safely.
                self._delete_slot(index)
                if empty_slot is None:
                    empty_slot = index

        if matching is not None:
            index, stored, persisted = matching
            if persisted is not None:
                # Recovery is already complete.  Best-effort cleanup must not
                # turn a proven successful send into a user-visible failure.
                try:
                    self._delete_slot(index)
                except DurableChatOutboxError:
                    pass
            return ChatOutboxResolution(stored, persisted)

        if candidate.message_id in seen_message_ids:
            raise DurableChatOutboxError(
                "new chat message identity collides with pending outbox state"
            )
        if empty_slot is None:
            raise DurableChatOutboxError("chat outbox is full")

        encoded = self._encode(candidate)
        try:
            self._secret_store.write(self._slot(empty_slot), encoded)
        except Exception as exc:
            raise DurableChatOutboxError("chat outbox secret cannot be written") from exc
        return ChatOutboxResolution(candidate, None)

    def acknowledge(self, draft: ChatDraft) -> None:
        with self._peer_lock():
            self._acknowledge_locked(draft)

    def _acknowledge_locked(self, draft: ChatDraft) -> None:
        if type(draft) is not ChatDraft:
            raise TypeError("draft must be ChatDraft")
        for index in range(_MAX_PENDING_DRAFTS):
            stored = self._read_slot(index)
            if stored is None or stored.message_id != draft.message_id:
                continue
            if (
                stored.room_id != draft.room_id
                or stored.sender_id != draft.sender_id
                or stored.body != draft.body
                or stored.retention != draft.retention
            ):
                raise DurableChatOutboxError(
                    "chat outbox acknowledgement conflicts with stored draft"
                )
            self._delete_slot(index)
            return


class DurableOutboxClassroomCollaborationController(
    ClassroomCollaborationController
):
    """Canonical controller plus encrypted restart-safe chat draft identity."""

    def __init__(
        self,
        *,
        chat_outbox: DurableChatDraftOutbox | None = None,
        **kwargs: object,
    ) -> None:
        if chat_outbox is not None and not isinstance(
            chat_outbox, DurableChatDraftOutbox
        ):
            raise TypeError("chat_outbox must be DurableChatDraftOutbox")
        super().__init__(**kwargs)
        self._chat_outbox = chat_outbox

    def send_chat(
        self,
        *,
        message_id: str,
        body: str,
        retention: str = "session",
    ) -> ChatMessageMetadata:
        outbox = self._chat_outbox
        if outbox is None:
            return super().send_chat(
                message_id=message_id,
                body=body,
                retention=retention,
            )

        # Do not persist a draft for a participant that the canonical roster has
        # already removed.  The base implementation repeats this check before
        # any transport effect.
        self._require_member(self.local_participant_id)
        candidate = ChatDraft(
            message_id=message_id,
            room_id=self.room_id,
            sender_id=self.local_participant_id,
            body=body,
            retention=retention,
        )
        resolution = outbox.prepare(candidate)

        if resolution.persisted_message is not None:
            return resolution.persisted_message

        delivered = super().send_chat(
            message_id=resolution.draft.message_id,
            body=resolution.draft.body,
            retention=resolution.draft.retention,
        )
        try:
            outbox.acknowledge(resolution.draft)
        except DurableChatOutboxError:
            # Delivery is already canonical and durable in the collaboration
            # SQLite.  A stale encrypted slot cannot cause a duplicate: the next
            # prepare resolves it against that exact durable metadata first.
            pass
        return delivered


__all__ = [
    "ChatOutboxResolution",
    "DurableChatDraftOutbox",
    "DurableChatOutboxBusyError",
    "DurableChatOutboxError",
    "DurableOutboxClassroomCollaborationController",
]
