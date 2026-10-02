from __future__ import annotations

"""Trusted provider-neutral moderation RPC core for classroom media.

This module is deliberately a transport/service boundary, not a second classroom
policy engine. Caller identity and room identity come from the trusted realtime
transport. Role/membership authorization is delegated to the server's canonical
classroom authority before any provider effect. Provider administration and the
operation ledger are also injected ports so LiveKit credentials never enter the
desktop/browser model.
"""

import asyncio
from dataclasses import dataclass
import hashlib
import json
import re
from typing import Protocol

from .classroom_realtime_media import ModerationAction, ModerationCommand, MediaSource


RPC_VERSION = 1
MAX_RPC_PAYLOAD_BYTES = 15 * 1024
MAX_RPC_OPERATIONS = 256
MAX_IDENTIFIER_LENGTH = 128
_IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_OPERATION_FIELDS = frozenset(
    {"operation_id", "actor_id", "target_id", "action", "source", "value"}
)
_ENVELOPE_FIELDS = frozenset({"version", "room_id", "operations"})


class ClassroomModerationRpcError(ValueError):
    """Fail-closed moderation RPC error safe for transport-level handling."""


class ClassroomModerationAuthorizationPort(Protocol):
    """Canonical server-side classroom membership/role authority."""

    def authorize_moderation_batch(
        self,
        *,
        room_id: str,
        caller_identity: str,
        commands: tuple[ModerationCommand, ...],
    ) -> None:
        """Raise if any command is not authorized in the canonical classroom."""


class ClassroomModerationProviderAdminPort(Protocol):
    """Trusted provider administration boundary.

    Implementations must apply each command as an idempotent state assignment.
    If this method raises, callers may retry the same operation id.
    """

    async def apply_moderation_command(
        self,
        *,
        room_id: str,
        command: ModerationCommand,
    ) -> None:
        ...


class ClassroomModerationOperationLedgerPort(Protocol):
    """Committed-operation ledger for duplicate/replay suppression."""

    def committed_fingerprint(
        self,
        *,
        room_id: str,
        operation_id: str,
    ) -> str | None:
        ...

    def commit(
        self,
        *,
        room_id: str,
        operation_id: str,
        fingerprint: str,
    ) -> None:
        """Persist one committed operation or raise on a conflicting value."""


@dataclass(frozen=True, slots=True)
class ParsedModerationRpc:
    room_id: str
    commands: tuple[ModerationCommand, ...]
    fingerprints: tuple[str, ...]


def _identifier(value: object, name: str) -> str:
    if (
        type(value) is not str
        or not value
        or len(value) > MAX_IDENTIFIER_LENGTH
        or _IDENTIFIER_RE.fullmatch(value) is None
    ):
        raise ClassroomModerationRpcError(f"{name} is invalid")
    return value


def _strict_bool(value: object, name: str) -> bool:
    if type(value) is not bool:
        raise ClassroomModerationRpcError(f"{name} must be boolean")
    return value


def _canonical_command_dict(command: ModerationCommand) -> dict[str, object]:
    return {
        "operation_id": command.operation_id,
        "actor_id": command.actor_id,
        "target_id": command.target_id,
        "action": command.action.value,
        "source": None if command.source is None else command.source.value,
        "value": command.value,
    }


def _fingerprint(command: ModerationCommand) -> str:
    payload = json.dumps(
        _canonical_command_dict(command),
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _parse_command(value: object) -> ModerationCommand:
    if type(value) is not dict or set(value) != _OPERATION_FIELDS:
        raise ClassroomModerationRpcError("moderation operation fields are invalid")
    try:
        action = ModerationAction(value["action"])
    except (TypeError, ValueError):
        raise ClassroomModerationRpcError("moderation action is invalid") from None

    source_value = value["source"]
    source: MediaSource | None
    if source_value is None:
        source = None
    else:
        try:
            source = MediaSource(source_value)
        except (TypeError, ValueError):
            raise ClassroomModerationRpcError("media source is invalid") from None

    operation_id = _identifier(value["operation_id"], "operation id")
    actor_id = _identifier(value["actor_id"], "actor id")
    target_id = _identifier(value["target_id"], "target id")
    command_value = _strict_bool(value["value"], "moderation value")

    try:
        return ModerationCommand(
            operation_id=operation_id,
            actor_id=actor_id,
            target_id=target_id,
            action=action,
            source=source,
            value=command_value,
        )
    except (TypeError, ValueError) as error:
        raise ClassroomModerationRpcError("moderation operation is invalid") from error


def parse_moderation_rpc(
    payload: object,
    *,
    trusted_room_id: str,
    trusted_caller_identity: str,
) -> ParsedModerationRpc:
    """Parse one LiveKit-style RPC payload against trusted transport context."""

    room_id = _identifier(trusted_room_id, "trusted room id")
    caller = _identifier(trusted_caller_identity, "trusted caller identity")
    if type(payload) is not str:
        raise ClassroomModerationRpcError("moderation RPC payload must be text")
    encoded = payload.encode("utf-8")
    if not encoded or len(encoded) > MAX_RPC_PAYLOAD_BYTES:
        raise ClassroomModerationRpcError("moderation RPC payload size is invalid")
    try:
        decoded = json.loads(payload)
    except (TypeError, ValueError, json.JSONDecodeError):
        raise ClassroomModerationRpcError("moderation RPC payload is invalid JSON") from None
    if type(decoded) is not dict or set(decoded) != _ENVELOPE_FIELDS:
        raise ClassroomModerationRpcError("moderation RPC envelope fields are invalid")
    if decoded["version"] != RPC_VERSION or type(decoded["version"]) is not int:
        raise ClassroomModerationRpcError("moderation RPC version is invalid")
    payload_room = _identifier(decoded["room_id"], "payload room id")
    if payload_room != room_id:
        raise ClassroomModerationRpcError("moderation RPC room identity mismatch")
    operations = decoded["operations"]
    if (
        type(operations) is not list
        or not operations
        or len(operations) > MAX_RPC_OPERATIONS
    ):
        raise ClassroomModerationRpcError("moderation operation batch is invalid")

    commands = tuple(_parse_command(item) for item in operations)
    operation_ids = tuple(item.operation_id for item in commands)
    if len(set(operation_ids)) != len(operation_ids):
        raise ClassroomModerationRpcError("moderation operation ids must be unique")
    if any(item.actor_id != caller for item in commands):
        raise ClassroomModerationRpcError("moderation actor does not match trusted caller")

    return ParsedModerationRpc(
        room_id=room_id,
        commands=commands,
        fingerprints=tuple(_fingerprint(item) for item in commands),
    )


class ClassroomModerationRpcService:
    """Validate, authorize, apply, and acknowledge moderation operations.

    Calls are serialized within one service participant so an operation id cannot
    race itself. A deployment with multiple service participants must provide a
    ledger whose commit operation is conflict-safe across those participants.
    """

    def __init__(
        self,
        *,
        authorization: ClassroomModerationAuthorizationPort,
        provider_admin: ClassroomModerationProviderAdminPort,
        ledger: ClassroomModerationOperationLedgerPort,
    ) -> None:
        if authorization is None or provider_admin is None or ledger is None:
            raise TypeError("moderation RPC service ports are required")
        self._authorization = authorization
        self._provider_admin = provider_admin
        self._ledger = ledger
        self._lock = asyncio.Lock()

    async def handle_rpc(
        self,
        *,
        trusted_room_id: str,
        trusted_caller_identity: str,
        payload: object,
    ) -> str:
        parsed = parse_moderation_rpc(
            payload,
            trusted_room_id=trusted_room_id,
            trusted_caller_identity=trusted_caller_identity,
        )

        async with self._lock:
            new_commands: list[tuple[ModerationCommand, str]] = []
            for command, fingerprint in zip(
                parsed.commands,
                parsed.fingerprints,
                strict=True,
            ):
                try:
                    committed = self._ledger.committed_fingerprint(
                        room_id=parsed.room_id,
                        operation_id=command.operation_id,
                    )
                except Exception as error:
                    raise ClassroomModerationRpcError(
                        "moderation replay ledger read failed"
                    ) from error
                if committed is None:
                    new_commands.append((command, fingerprint))
                    continue
                if committed != fingerprint:
                    raise ClassroomModerationRpcError(
                        "moderation operation id was reused with different semantics"
                    )

            if new_commands:
                # Authorize the complete set of new effects before the first
                # provider mutation so a later unauthorized command cannot leave
                # an earlier command partially applied.
                try:
                    self._authorization.authorize_moderation_batch(
                        room_id=parsed.room_id,
                        caller_identity=trusted_caller_identity,
                        commands=tuple(command for command, _ in new_commands),
                    )
                except Exception as error:
                    raise ClassroomModerationRpcError(
                        "moderation request is not authorized"
                    ) from error
                for command, fingerprint in new_commands:
                    try:
                        await self._provider_admin.apply_moderation_command(
                            room_id=parsed.room_id,
                            command=command,
                        )
                    except Exception as error:
                        raise ClassroomModerationRpcError(
                            "moderation provider operation failed"
                        ) from error
                    try:
                        self._ledger.commit(
                            room_id=parsed.room_id,
                            operation_id=command.operation_id,
                            fingerprint=fingerprint,
                        )
                    except Exception as error:
                        raise ClassroomModerationRpcError(
                            "moderation replay ledger commit failed"
                        ) from error

            response = json.dumps(
                {
                    "version": RPC_VERSION,
                    "status": "ok",
                    "accepted_operation_ids": [
                        command.operation_id for command in parsed.commands
                    ],
                },
                ensure_ascii=False,
                separators=(",", ":"),
            )
            if len(response.encode("utf-8")) > MAX_RPC_PAYLOAD_BYTES:
                raise ClassroomModerationRpcError(
                    "moderation acknowledgement exceeds RPC size limit"
                )
            return response


__all__ = [
    "ClassroomModerationAuthorizationPort",
    "ClassroomModerationOperationLedgerPort",
    "ClassroomModerationProviderAdminPort",
    "ClassroomModerationRpcError",
    "ClassroomModerationRpcService",
    "MAX_RPC_OPERATIONS",
    "MAX_RPC_PAYLOAD_BYTES",
    "ParsedModerationRpc",
    "RPC_VERSION",
    "parse_moderation_rpc",
]
