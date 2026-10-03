from __future__ import annotations

"""Authenticated RPC boundary for canonical classroom room chat.

This module adapts the existing provider-neutral ChatTransportPort to a strict
versioned request/response boundary. Membership/role authority and durable or
provider effects remain injected server responsibilities; this module owns no
roster, chess state, persistence database, provider SDK, or credentials.
"""

from collections.abc import Mapping
from typing import Protocol
import re

from .classroom_collaboration import (
    MAX_SYNC_MESSAGES,
    ChatDraft,
    ChatModerationAction,
    ChatModerationCommand,
    ChatTransportPort,
)
from .classroom_collaboration_storage import (
    ChatMessageMetadata,
    ChatMessageStateUpdate,
)
from .classroom_domain import MAX_RECORDS_PER_COLLECTION, MAX_WIRE_INTEGER


RPC_VERSION = 1
MAX_MODERATION_COMMANDS = MAX_RECORDS_PER_COLLECTION
_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")


class ClassroomChatRpcError(ValueError):
    """Safe public failure for malformed, unauthorized, or failed chat RPC."""


class ClassroomChatRpcCallPort(Protocol):
    """Authenticated request transport used by the desktop-side adapter."""

    def call(self, request: Mapping[str, object]) -> Mapping[str, object]:
        ...


class ClassroomChatRpcServerPort(Protocol):
    """Trusted server authority called only with authenticated caller identity.

    This signature intentionally matches ClassroomChatServerService from the
    canonical durable #29 server lineage. Authorization, send locks, durable
    sequencing and moderation replay remain server responsibilities.
    """

    def send_message(
        self,
        *,
        trusted_caller_identity: str,
        draft: ChatDraft,
    ) -> ChatMessageMetadata:
        ...

    def history_after(
        self,
        *,
        trusted_caller_identity: str,
        room_id: str,
        after_sequence: int | None,
        limit: int,
    ) -> tuple[ChatMessageMetadata, ...]:
        ...

    def state_updates_after(
        self,
        *,
        trusted_caller_identity: str,
        room_id: str,
        after_revision: int | None,
        limit: int,
    ) -> tuple[ChatMessageStateUpdate, ...]:
        ...

    def apply_moderation(
        self,
        *,
        trusted_caller_identity: str,
        commands: tuple[ChatModerationCommand, ...],
    ) -> None:
        ...


class ClassroomChatRpcClient(ChatTransportPort):
    """Desktop adapter implementing the existing canonical ChatTransportPort."""

    def __init__(
        self,
        *,
        room_id: str,
        participant_id: str,
        transport: ClassroomChatRpcCallPort,
    ) -> None:
        self.room_id = _opaque_id(room_id, "room id")
        self.participant_id = _opaque_id(participant_id, "participant id")
        self._transport = transport

    def send_message(self, draft: ChatDraft) -> ChatMessageMetadata:
        if type(draft) is not ChatDraft:
            raise ClassroomChatRpcError("chat send requires ChatDraft")
        self._require_bound_identity(draft.room_id, draft.sender_id)
        response = self._call(
            {
                "v": RPC_VERSION,
                "op": "send",
                "room_id": self.room_id,
                "participant_id": self.participant_id,
                "message": {
                    "message_id": draft.message_id,
                    "body": draft.body,
                    "retention": draft.retention,
                },
            }
        )
        _exact_keys(response, {"v", "ok", "message"}, "send response")
        _version_ok(response)
        if response["ok"] is not True:
            raise ClassroomChatRpcError("chat send failed")
        message = _message_from_wire(response["message"])
        _require_delivered_identity(draft, message)
        return message

    def history_after(
        self,
        *,
        room_id: str,
        after_sequence: int | None,
        limit: int,
    ) -> tuple[ChatMessageMetadata, ...]:
        room = _opaque_id(room_id, "room id")
        if room != self.room_id:
            raise ClassroomChatRpcError("chat history crossed bound room")
        after = _optional_sequence(after_sequence)
        bounded_limit = _history_limit(limit)
        response = self._call(
            {
                "v": RPC_VERSION,
                "op": "history",
                "room_id": self.room_id,
                "participant_id": self.participant_id,
                "after_sequence": after,
                "limit": bounded_limit,
            }
        )
        _exact_keys(response, {"v", "ok", "messages"}, "history response")
        _version_ok(response)
        if response["ok"] is not True:
            raise ClassroomChatRpcError("chat history failed")
        raw = response["messages"]
        if type(raw) is not list or len(raw) > bounded_limit:
            raise ClassroomChatRpcError("chat history response is invalid")
        result = tuple(_message_from_wire(item) for item in raw)
        _validate_history(
            result,
            room_id=self.room_id,
            after_sequence=after,
            limit=bounded_limit,
        )
        return result

    def state_updates_after(
        self,
        *,
        room_id: str,
        after_revision: int | None,
        limit: int,
    ) -> tuple[ChatMessageStateUpdate, ...]:
        room = _opaque_id(room_id, "room id")
        if room != self.room_id:
            raise ClassroomChatRpcError("chat state crossed bound room")
        after = _optional_revision(after_revision)
        bounded_limit = _state_limit(limit)
        response = self._call(
            {
                "v": RPC_VERSION,
                "op": "state",
                "room_id": self.room_id,
                "participant_id": self.participant_id,
                "after_revision": after,
                "limit": bounded_limit,
            }
        )
        _exact_keys(response, {"v", "ok", "updates"}, "state response")
        _version_ok(response)
        if response["ok"] is not True:
            raise ClassroomChatRpcError("chat state sync failed")
        raw = response["updates"]
        if type(raw) is not list or len(raw) > bounded_limit:
            raise ClassroomChatRpcError("chat state response is invalid")
        result = tuple(_state_update_from_wire(item) for item in raw)
        _validate_state_updates(
            result,
            room_id=self.room_id,
            after_revision=after,
            limit=bounded_limit,
        )
        return result

    def apply_moderation(self, commands: tuple[ChatModerationCommand, ...]) -> None:
        if type(commands) is not tuple or not commands:
            raise ClassroomChatRpcError("moderation batch must be a non-empty tuple")
        if len(commands) > MAX_MODERATION_COMMANDS:
            raise ClassroomChatRpcError("moderation batch is too large")
        for command in commands:
            if type(command) is not ChatModerationCommand:
                raise ClassroomChatRpcError("moderation batch contains invalid command")
            self._require_bound_identity(command.room_id, command.actor_id)
        response = self._call(
            {
                "v": RPC_VERSION,
                "op": "moderate",
                "room_id": self.room_id,
                "participant_id": self.participant_id,
                "commands": [_command_to_wire(item) for item in commands],
            }
        )
        _exact_keys(response, {"v", "ok"}, "moderation response")
        _version_ok(response)
        if response["ok"] is not True:
            raise ClassroomChatRpcError("chat moderation failed")

    def _call(self, request: Mapping[str, object]) -> dict[str, object]:
        try:
            response = self._transport.call(request)
        except ClassroomChatRpcError as exc:
            # Preserve canonical protocol/response-validation failures used by
            # the trusted in-process transport, but never expose backend/service
            # implementation failures to the desktop client.
            if str(exc).startswith("classroom chat backend"):
                raise ClassroomChatRpcError(
                    "classroom chat service unavailable"
                ) from None
            raise
        except Exception:
            raise ClassroomChatRpcError("classroom chat service unavailable") from None
        if type(response) is not dict:
            raise ClassroomChatRpcError("classroom chat response is invalid")
        return response

    def _require_bound_identity(self, room_id: str, participant_id: str) -> None:
        if room_id != self.room_id or participant_id != self.participant_id:
            raise ClassroomChatRpcError("chat operation crossed bound identity")


class ClassroomChatRpcService:
    """Authenticated endpoint over one canonical trusted room-chat server."""

    def __init__(
        self,
        *,
        backend: ClassroomChatRpcServerPort,
    ) -> None:
        if backend is None:
            raise TypeError("trusted classroom chat server backend is required")
        self._backend = backend

    def handle(
        self,
        request: Mapping[str, object],
        *,
        authenticated_room_id: str,
        authenticated_participant_id: str,
    ) -> dict[str, object]:
        if type(request) is not dict:
            raise ClassroomChatRpcError("chat request must be an object")
        room = _opaque_id(authenticated_room_id, "authenticated room id")
        participant = _opaque_id(
            authenticated_participant_id,
            "authenticated participant id",
        )
        _version_ok(request)
        op = request.get("op")
        if op == "send":
            return self._handle_send(request, room=room, participant=participant)
        if op == "history":
            return self._handle_history(request, room=room, participant=participant)
        if op == "state":
            return self._handle_state(request, room=room, participant=participant)
        if op == "moderate":
            return self._handle_moderation(request, room=room, participant=participant)
        raise ClassroomChatRpcError("unsupported chat RPC operation")

    def _handle_send(
        self,
        request: dict[str, object],
        *,
        room: str,
        participant: str,
    ) -> dict[str, object]:
        _exact_keys(
            request,
            {"v", "op", "room_id", "participant_id", "message"},
            "send request",
        )
        _require_authenticated_identity(request, room=room, participant=participant)
        raw = request["message"]
        if type(raw) is not dict:
            raise ClassroomChatRpcError("send message must be an object")
        _exact_keys(raw, {"message_id", "body", "retention"}, "send message")
        try:
            draft = ChatDraft(
                message_id=raw["message_id"],
                room_id=room,
                sender_id=participant,
                body=raw["body"],
                retention=raw["retention"],
            )
        except Exception:
            raise ClassroomChatRpcError("send message is invalid") from None
        try:
            delivered = self._backend.send_message(
                trusted_caller_identity=participant,
                draft=draft,
            )
        except Exception:
            raise ClassroomChatRpcError("classroom chat backend failed") from None
        if type(delivered) is not ChatMessageMetadata:
            raise ClassroomChatRpcError("classroom chat backend returned invalid message")
        _require_delivered_identity(draft, delivered)
        return {"v": RPC_VERSION, "ok": True, "message": _message_to_wire(delivered)}

    def _handle_history(
        self,
        request: dict[str, object],
        *,
        room: str,
        participant: str,
    ) -> dict[str, object]:
        _exact_keys(
            request,
            {
                "v",
                "op",
                "room_id",
                "participant_id",
                "after_sequence",
                "limit",
            },
            "history request",
        )
        _require_authenticated_identity(request, room=room, participant=participant)
        after = _optional_sequence(request["after_sequence"])
        limit = _history_limit(request["limit"])
        try:
            messages = self._backend.history_after(
                trusted_caller_identity=participant,
                room_id=room,
                after_sequence=after,
                limit=limit,
            )
        except Exception:
            raise ClassroomChatRpcError("classroom chat backend failed") from None
        if type(messages) is not tuple:
            raise ClassroomChatRpcError("classroom chat backend returned invalid history")
        _validate_history(messages, room_id=room, after_sequence=after, limit=limit)
        return {
            "v": RPC_VERSION,
            "ok": True,
            "messages": [_message_to_wire(item) for item in messages],
        }

    def _handle_state(
        self,
        request: dict[str, object],
        *,
        room: str,
        participant: str,
    ) -> dict[str, object]:
        _exact_keys(
            request,
            {
                "v",
                "op",
                "room_id",
                "participant_id",
                "after_revision",
                "limit",
            },
            "state request",
        )
        _require_authenticated_identity(request, room=room, participant=participant)
        after = _optional_revision(request["after_revision"])
        limit = _state_limit(request["limit"])
        try:
            updates = self._backend.state_updates_after(
                trusted_caller_identity=participant,
                room_id=room,
                after_revision=after,
                limit=limit,
            )
        except Exception:
            raise ClassroomChatRpcError("classroom chat backend failed") from None
        if type(updates) is not tuple:
            raise ClassroomChatRpcError(
                "classroom chat backend returned invalid state history"
            )
        _validate_state_updates(
            updates,
            room_id=room,
            after_revision=after,
            limit=limit,
        )
        return {
            "v": RPC_VERSION,
            "ok": True,
            "updates": [_state_update_to_wire(item) for item in updates],
        }

    def _handle_moderation(
        self,
        request: dict[str, object],
        *,
        room: str,
        participant: str,
    ) -> dict[str, object]:
        _exact_keys(
            request,
            {"v", "op", "room_id", "participant_id", "commands"},
            "moderation request",
        )
        _require_authenticated_identity(request, room=room, participant=participant)
        raw = request["commands"]
        if type(raw) is not list or not raw or len(raw) > MAX_MODERATION_COMMANDS:
            raise ClassroomChatRpcError("moderation command batch is invalid")
        commands = tuple(
            _command_from_wire(item, room_id=room, actor_id=participant)
            for item in raw
        )
        try:
            self._backend.apply_moderation(
                trusted_caller_identity=participant,
                commands=commands,
            )
        except Exception:
            raise ClassroomChatRpcError("classroom chat backend failed") from None
        return {"v": RPC_VERSION, "ok": True}


def _command_to_wire(command: ChatModerationCommand) -> dict[str, object]:
    if command.action is ChatModerationAction.SET_SEND_PERMISSION:
        return {
            "operation_id": command.operation_id,
            "action": command.action.value,
            "target_id": command.target_id,
            "allowed": command.allowed,
        }
    if command.action is ChatModerationAction.HIDE_MESSAGE:
        return {
            "operation_id": command.operation_id,
            "action": command.action.value,
            "message_id": command.message_id,
        }
    raise ClassroomChatRpcError("unsupported moderation action")


def _command_from_wire(
    value: object,
    *,
    room_id: str,
    actor_id: str,
) -> ChatModerationCommand:
    if type(value) is not dict:
        raise ClassroomChatRpcError("moderation command must be an object")
    action = value.get("action")
    try:
        if action == ChatModerationAction.SET_SEND_PERMISSION.value:
            _exact_keys(
                value,
                {"operation_id", "action", "target_id", "allowed"},
                "send-permission command",
            )
            return ChatModerationCommand(
                operation_id=value["operation_id"],
                room_id=room_id,
                actor_id=actor_id,
                target_id=value["target_id"],
                action=ChatModerationAction.SET_SEND_PERMISSION,
                allowed=value["allowed"],
            )
        if action == ChatModerationAction.HIDE_MESSAGE.value:
            _exact_keys(
                value,
                {"operation_id", "action", "message_id"},
                "hide-message command",
            )
            return ChatModerationCommand(
                operation_id=value["operation_id"],
                room_id=room_id,
                actor_id=actor_id,
                target_id=None,
                action=ChatModerationAction.HIDE_MESSAGE,
                message_id=value["message_id"],
            )
    except Exception:
        raise ClassroomChatRpcError("moderation command is invalid") from None
    raise ClassroomChatRpcError("unsupported moderation action")


def _message_to_wire(message: ChatMessageMetadata) -> dict[str, object]:
    if type(message) is not ChatMessageMetadata or message.sent_at_unix_ms is None:
        raise ClassroomChatRpcError("live chat message lacks authoritative timestamp")
    return {
        "message_id": message.message_id,
        "room_id": message.room_id,
        "sender_id": message.sender_id,
        "sequence_no": message.sequence_no,
        "body": message.body,
        "retention": message.retention,
        "hidden": message.hidden,
        "redacted": message.redacted,
        "sent_at_unix_ms": message.sent_at_unix_ms,
    }


def _message_from_wire(value: object) -> ChatMessageMetadata:
    if type(value) is not dict:
        raise ClassroomChatRpcError("chat message response must be an object")
    _exact_keys(
        value,
        {
            "message_id",
            "room_id",
            "sender_id",
            "sequence_no",
            "body",
            "retention",
            "hidden",
            "redacted",
            "sent_at_unix_ms",
        },
        "chat message response",
    )
    if type(value["hidden"]) is not bool:
        raise ClassroomChatRpcError("chat hidden flag must be boolean")
    if type(value["redacted"]) is not bool:
        raise ClassroomChatRpcError("chat redacted flag must be boolean")
    try:
        message = ChatMessageMetadata(
            message_id=value["message_id"],
            room_id=value["room_id"],
            sender_id=value["sender_id"],
            sequence_no=value["sequence_no"],
            body=value["body"],
            retention=value["retention"],
            hidden=value["hidden"],
            sent_at_unix_ms=value["sent_at_unix_ms"],
            redacted=value["redacted"],
        )
    except Exception:
        raise ClassroomChatRpcError("chat message response is invalid") from None
    if message.sent_at_unix_ms is None:
        raise ClassroomChatRpcError("live chat message lacks authoritative timestamp")
    return message


def _state_update_to_wire(update: ChatMessageStateUpdate) -> dict[str, object]:
    if type(update) is not ChatMessageStateUpdate:
        raise ClassroomChatRpcError("chat state update is invalid")
    return {
        "room_id": update.room_id,
        "message_id": update.message_id,
        "revision": update.revision,
        "hidden": update.hidden,
        "redacted": update.redacted,
    }


def _state_update_from_wire(value: object) -> ChatMessageStateUpdate:
    if type(value) is not dict:
        raise ClassroomChatRpcError("chat state update must be an object")
    _exact_keys(
        value,
        {"room_id", "message_id", "revision", "hidden", "redacted"},
        "chat state update",
    )
    try:
        return ChatMessageStateUpdate(
            room_id=value["room_id"],
            message_id=value["message_id"],
            revision=value["revision"],
            hidden=value["hidden"],
            redacted=value["redacted"],
        )
    except Exception:
        raise ClassroomChatRpcError("chat state update is invalid") from None


def _require_delivered_identity(
    draft: ChatDraft,
    message: ChatMessageMetadata,
) -> None:
    if (
        message.message_id != draft.message_id
        or message.room_id != draft.room_id
        or message.sender_id != draft.sender_id
        or message.body != draft.body
        or message.retention != draft.retention
        or message.sent_at_unix_ms is None
    ):
        raise ClassroomChatRpcError("chat backend changed immutable message identity")


def _validate_history(
    messages: tuple[ChatMessageMetadata, ...],
    *,
    room_id: str,
    after_sequence: int | None,
    limit: int,
) -> None:
    if len(messages) > limit:
        raise ClassroomChatRpcError("chat history exceeds requested limit")
    previous = after_sequence
    seen: set[str] = set()
    for message in messages:
        if type(message) is not ChatMessageMetadata:
            raise ClassroomChatRpcError("chat history contains invalid message")
        if message.room_id != room_id or message.sent_at_unix_ms is None:
            raise ClassroomChatRpcError("chat history crossed room or timestamp boundary")
        expected = 0 if previous is None else previous + 1
        if message.sequence_no != expected:
            raise ClassroomChatRpcError("chat history has an unresolved sequence gap")
        if message.message_id in seen:
            raise ClassroomChatRpcError("chat history contains duplicate message id")
        seen.add(message.message_id)
        previous = message.sequence_no


def _validate_state_updates(
    updates: tuple[ChatMessageStateUpdate, ...],
    *,
    room_id: str,
    after_revision: int | None,
    limit: int,
) -> None:
    if len(updates) > limit:
        raise ClassroomChatRpcError("chat state history exceeds requested limit")
    previous = after_revision
    for update in updates:
        if type(update) is not ChatMessageStateUpdate:
            raise ClassroomChatRpcError("chat state history contains invalid update")
        if update.room_id != room_id:
            raise ClassroomChatRpcError("chat state history crossed room boundary")
        expected = 0 if previous is None else previous + 1
        if update.revision != expected:
            raise ClassroomChatRpcError(
                "chat state history has an unresolved revision gap"
            )
        previous = update.revision


def _version_ok(value: Mapping[str, object]) -> None:
    if value.get("v") != RPC_VERSION or type(value.get("v")) is not int:
        raise ClassroomChatRpcError("unsupported chat RPC version")


def _require_authenticated_identity(
    request: Mapping[str, object],
    *,
    room: str,
    participant: str,
) -> None:
    try:
        requested_room = _opaque_id(request["room_id"], "room id")
        requested_participant = _opaque_id(request["participant_id"], "participant id")
    except KeyError:
        raise ClassroomChatRpcError("chat request identity is missing") from None
    if requested_room != room or requested_participant != participant:
        raise ClassroomChatRpcError("chat request identity does not match authenticated transport")


def _exact_keys(
    value: Mapping[str, object],
    expected: set[str],
    label: str,
) -> None:
    if type(value) is not dict or set(value) != expected:
        raise ClassroomChatRpcError(f"{label} fields are invalid")


def _opaque_id(value: object, label: str) -> str:
    if type(value) is not str or _ID_RE.fullmatch(value) is None:
        raise ClassroomChatRpcError(f"{label} must be a canonical opaque identifier")
    return value


def _optional_sequence(value: object) -> int | None:
    if value is None:
        return None
    if type(value) is not int or not 0 <= value <= MAX_WIRE_INTEGER:
        raise ClassroomChatRpcError(
            "after_sequence must be null or bounded non-negative integer"
        )
    return value


def _history_limit(value: object) -> int:
    if type(value) is not int or not 1 <= value <= MAX_SYNC_MESSAGES:
        raise ClassroomChatRpcError("history limit is invalid")
    return value


def _optional_revision(value: object) -> int | None:
    if value is None:
        return None
    if type(value) is not int or not 0 <= value <= MAX_WIRE_INTEGER:
        raise ClassroomChatRpcError(
            "after_revision must be null or bounded non-negative integer"
        )
    return value


def _state_limit(value: object) -> int:
    if type(value) is not int or not 1 <= value <= MAX_SYNC_MESSAGES:
        raise ClassroomChatRpcError("state history limit is invalid")
    return value


__all__ = [
    "ClassroomChatRpcCallPort",
    "ClassroomChatRpcServerPort",
    "ClassroomChatRpcClient",
    "ClassroomChatRpcError",
    "ClassroomChatRpcService",
    "MAX_MODERATION_COMMANDS",
    "RPC_VERSION",
]
