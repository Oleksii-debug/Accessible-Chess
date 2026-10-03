from __future__ import annotations

"""Encrypted durable recovery state for ambiguous classroom chat sends.

The outbox owns no transport or server authority. It stores only exact pending
chat drafts behind the canonical SecretStore boundary so a desktop restart can
reuse the same server-authoritative message identity instead of minting a
duplicate logical message. Plaintext persistence is delegated exclusively to a
SecretStore implementation such as the current-user Windows DPAPI adapter.
"""

from dataclasses import dataclass
import hashlib
import json
from typing import Any

from .classroom_collaboration import ChatDraft, CollaborationError
from .secret_store import SecretStore, SecretStoreError


_MAX_PENDING_CHAT_DRAFTS = 32
_MAX_OUTBOX_BYTES = 60 * 1024
_SCHEMA_VERSION = 1


class ChatOutboxError(RuntimeError):
    """Raised when durable pending-chat recovery state is unsafe or unavailable."""


def _strict_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if type(key) is not str or key in result:
            raise ChatOutboxError("chat outbox JSON object is invalid")
        result[key] = value
    return result


@dataclass(frozen=True, slots=True)
class SecretStoreChatOutbox:
    """Bounded pending-chat document protected by one injected SecretStore."""

    secret_store: SecretStore
    room_id: str
    participant_id: str

    def __post_init__(self) -> None:
        # Reuse the canonical collaboration validators instead of creating a
        # second room/participant identifier grammar.
        try:
            probe = ChatDraft(
                message_id="outbox-probe",
                room_id=self.room_id,
                sender_id=self.participant_id,
                body="outbox probe",
            )
        except CollaborationError as exc:
            raise ChatOutboxError("chat outbox identity is invalid") from exc
        object.__setattr__(self, "room_id", probe.room_id)
        object.__setattr__(self, "participant_id", probe.sender_id)
        if not (
            callable(getattr(self.secret_store, "read", None))
            and callable(getattr(self.secret_store, "write", None))
            and callable(getattr(self.secret_store, "delete", None))
        ):
            raise TypeError("secret_store must implement SecretStore")

    @property
    def slot_name(self) -> str:
        digest = hashlib.sha256(
            (self.room_id + "\0" + self.participant_id).encode("utf-8")
        ).hexdigest()
        return "classroom-chat-outbox-" + digest[:40]

    def __repr__(self) -> str:
        return "SecretStoreChatOutbox(<bound>)"

    def _decode(self, raw: bytes | None) -> tuple[ChatDraft, ...]:
        if raw is None:
            return ()
        if type(raw) is not bytes or not raw or len(raw) > _MAX_OUTBOX_BYTES:
            raise ChatOutboxError("chat outbox ciphertext payload is invalid")
        try:
            value = json.loads(
                raw.decode("utf-8"),
                object_pairs_hook=_strict_object,
                parse_constant=lambda _value: (_ for _ in ()).throw(
                    ChatOutboxError("chat outbox JSON number is invalid")
                ),
            )
        except ChatOutboxError:
            raise
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ChatOutboxError("chat outbox document is malformed") from exc
        if type(value) is not dict or set(value) != {
            "v",
            "room_id",
            "participant_id",
            "entries",
        }:
            raise ChatOutboxError("chat outbox document shape is invalid")
        if value["v"] != _SCHEMA_VERSION:
            raise ChatOutboxError("chat outbox schema is unsupported")
        if value["room_id"] != self.room_id or value["participant_id"] != self.participant_id:
            raise ChatOutboxError("chat outbox identity binding is invalid")
        entries = value["entries"]
        if type(entries) is not list or len(entries) > _MAX_PENDING_CHAT_DRAFTS:
            raise ChatOutboxError("chat outbox entry count is invalid")
        result: list[ChatDraft] = []
        message_ids: set[str] = set()
        payloads: set[tuple[str, str]] = set()
        for item in entries:
            if type(item) is not dict or set(item) != {
                "message_id",
                "body",
                "retention",
            }:
                raise ChatOutboxError("chat outbox entry shape is invalid")
            try:
                draft = ChatDraft(
                    message_id=item["message_id"],
                    room_id=self.room_id,
                    sender_id=self.participant_id,
                    body=item["body"],
                    retention=item["retention"],
                )
            except (CollaborationError, TypeError) as exc:
                raise ChatOutboxError("chat outbox entry is invalid") from exc
            payload_key = (draft.body, draft.retention)
            if draft.message_id in message_ids or payload_key in payloads:
                raise ChatOutboxError("chat outbox contains duplicate recovery identity")
            message_ids.add(draft.message_id)
            payloads.add(payload_key)
            result.append(draft)
        return tuple(result)

    def _read(self) -> tuple[ChatDraft, ...]:
        try:
            raw = self.secret_store.read(self.slot_name)
        except Exception as exc:
            if isinstance(exc, ChatOutboxError):
                raise
            raise ChatOutboxError("chat outbox cannot be read safely") from exc
        return self._decode(raw)

    def _write(self, entries: tuple[ChatDraft, ...]) -> None:
        if len(entries) > _MAX_PENDING_CHAT_DRAFTS:
            raise ChatOutboxError("chat outbox is full")
        if not entries:
            try:
                self.secret_store.delete(self.slot_name)
            except Exception as exc:
                raise ChatOutboxError("chat outbox cannot be cleared safely") from exc
            return
        document = {
            "v": _SCHEMA_VERSION,
            "room_id": self.room_id,
            "participant_id": self.participant_id,
            "entries": [
                {
                    "message_id": item.message_id,
                    "body": item.body,
                    "retention": item.retention,
                }
                for item in entries
            ],
        }
        raw = json.dumps(
            document,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
        if not raw or len(raw) > _MAX_OUTBOX_BYTES:
            raise ChatOutboxError("chat outbox document exceeds size limit")
        try:
            self.secret_store.write(self.slot_name, raw)
        except SecretStoreError as exc:
            raise ChatOutboxError("chat outbox cannot be persisted safely") from exc
        except Exception as exc:
            raise ChatOutboxError("chat outbox cannot be persisted safely") from exc

    def entries(self) -> tuple[ChatDraft, ...]:
        return self._read()

    def find(self, *, body: str, retention: str) -> ChatDraft | None:
        try:
            probe = ChatDraft(
                message_id="outbox-probe",
                room_id=self.room_id,
                sender_id=self.participant_id,
                body=body,
                retention=retention,
            )
        except CollaborationError as exc:
            raise ChatOutboxError("pending chat payload is invalid") from exc
        matches = tuple(
            item
            for item in self._read()
            if item.body == probe.body and item.retention == probe.retention
        )
        if len(matches) > 1:
            raise ChatOutboxError("chat outbox recovery identity is ambiguous")
        return matches[0] if matches else None

    def reserve(
        self,
        *,
        message_id: str,
        body: str,
        retention: str,
    ) -> ChatDraft:
        try:
            candidate = ChatDraft(
                message_id=message_id,
                room_id=self.room_id,
                sender_id=self.participant_id,
                body=body,
                retention=retention,
            )
        except CollaborationError as exc:
            raise ChatOutboxError("pending chat draft is invalid") from exc
        entries = self._read()
        for item in entries:
            if item.body == candidate.body and item.retention == candidate.retention:
                return item
            if item.message_id == candidate.message_id:
                raise ChatOutboxError("message identity conflicts with pending chat draft")
        if len(entries) >= _MAX_PENDING_CHAT_DRAFTS:
            raise ChatOutboxError("chat outbox is full")
        self._write(entries + (candidate,))
        return candidate

    def discard(
        self,
        *,
        message_id: str,
        body: str,
        retention: str,
    ) -> bool:
        try:
            expected = ChatDraft(
                message_id=message_id,
                room_id=self.room_id,
                sender_id=self.participant_id,
                body=body,
                retention=retention,
            )
        except CollaborationError as exc:
            raise ChatOutboxError("pending chat draft is invalid") from exc
        entries = self._read()
        found = tuple(item for item in entries if item.message_id == expected.message_id)
        if not found:
            return False
        if len(found) != 1:
            raise ChatOutboxError("chat outbox recovery identity is ambiguous")
        current = found[0]
        if current.body != expected.body or current.retention != expected.retention:
            raise ChatOutboxError("pending chat identity changed unexpectedly")
        self._write(tuple(item for item in entries if item.message_id != expected.message_id))
        return True


__all__ = [
    "ChatOutboxError",
    "SecretStoreChatOutbox",
]
