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
import uuid
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


class ClassroomModerationProviderStateVerifierPort(Protocol):
    """Trusted read-only provider-state authority used only for crash recovery."""

    async def moderation_effect_matches(
        self,
        *,
        room_id: str,
        command: ModerationCommand,
    ) -> bool:
        """Return exact True only when the command's state assignment already holds."""


@dataclass(frozen=True, slots=True)
class ModerationOperationState:
    """One ledger record, including pre-effect reservation ownership."""

    fingerprint: str
    committed: bool
    reservation_owner: str | None = None


class ClassroomModerationOperationLedgerPort(Protocol):
    """Atomic reservation ledger for duplicate/replay suppression.

    reserve must never replace an existing fingerprint. This pre-effect
    reservation prevents two service participants from applying conflicting
    semantics for the same room-scoped operation id.
    """

    def operation_state(
        self,
        *,
        room_id: str,
        operation_id: str,
    ) -> ModerationOperationState | None:
        ...

    def reserve(
        self,
        *,
        room_id: str,
        operation_id: str,
        fingerprint: str,
        reservation_owner: str,
    ) -> ModerationOperationState:
        """Atomically create a pending reservation or return the existing record.

        A newly-created pending reservation must retain reservation_owner.
        An existing pending reservation must retain its original owner.
        """

    def commit(
        self,
        *,
        room_id: str,
        operation_id: str,
        fingerprint: str,
        reservation_owner: str,
    ) -> None:
        """Commit only the exact reservation owned by reservation_owner."""


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


def _strict_json_object(
    pairs: list[tuple[str, object]],
) -> dict[str, object]:
    """Reject ambiguous JSON objects instead of accepting last-key-wins input."""

    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ClassroomModerationRpcError(
                "moderation RPC JSON contains duplicate object fields"
            )
        result[key] = value
    return result


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
        raise ClassroomModerationRpcError("moderation operation is invalid") from None


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
    try:
        encoded = payload.encode("utf-8")
    except UnicodeEncodeError:
        raise ClassroomModerationRpcError("moderation RPC payload is not valid UTF-8 text") from None
    if not encoded or len(encoded) > MAX_RPC_PAYLOAD_BYTES:
        raise ClassroomModerationRpcError("moderation RPC payload size is invalid")
    try:
        decoded = json.loads(payload, object_pairs_hook=_strict_json_object)
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


def _validated_ledger_state(
    value: object,
    *,
    expected_fingerprint: str,
) -> ModerationOperationState:
    if (
        type(value) is not ModerationOperationState
        or type(value.fingerprint) is not str
        or len(value.fingerprint) != 64
        or re.fullmatch(r"[0-9a-f]{64}", value.fingerprint) is None
        or type(value.committed) is not bool
        or (
            value.committed
            and value.reservation_owner is not None
        )
        or (
            not value.committed
            and (
                type(value.reservation_owner) is not str
                or _IDENTIFIER_RE.fullmatch(value.reservation_owner) is None
            )
        )
    ):
        raise ClassroomModerationRpcError(
            "moderation replay ledger returned invalid state"
        )
    if value.fingerprint != expected_fingerprint:
        raise ClassroomModerationRpcError(
            "moderation operation id was reused with different semantics"
        )
    return value


class ClassroomModerationRpcService:
    """Validate, authorize, apply, and acknowledge moderation operations.

    Calls are serialized within one service participant. Across service
    participants, the shared ledger must atomically reserve an operation
    fingerprint and preserve reservation ownership before the first provider
    effect. Exact pending retries are accepted only by the same live service
    participant; another participant fails closed until explicit reconciliation.
    """

    def __init__(
        self,
        *,
        authorization: ClassroomModerationAuthorizationPort,
        provider_admin: ClassroomModerationProviderAdminPort,
        ledger: ClassroomModerationOperationLedgerPort,
        provider_state_verifier: (
            ClassroomModerationProviderStateVerifierPort | None
        ) = None,
    ) -> None:
        if authorization is None or provider_admin is None or ledger is None:
            raise TypeError("moderation RPC service ports are required")
        if provider_state_verifier is not None and not callable(
            getattr(provider_state_verifier, "moderation_effect_matches", None)
        ):
            raise TypeError("moderation provider state verifier is invalid")
        self._authorization = authorization
        self._provider_admin = provider_admin
        self._ledger = ledger
        self._provider_state_verifier = provider_state_verifier
        self._reservation_owner = uuid.uuid4().hex
        self._lock = asyncio.Lock()

    async def reconcile_verified_pending(
        self,
        *,
        room_id: str,
        command: ModerationCommand,
    ) -> None:
        """Commit an ambiguous pending operation only after provider-state proof.

        Recovery never reapplies a provider effect and never steals reservation
        ownership. The durable owner recorded before the crash is reused solely
        as the compare-and-set token for the existing ledger commit after a
        trusted verifier proves the exact state assignment already holds.
        """

        room = _identifier(room_id, "room id")
        if type(command) is not ModerationCommand:
            raise ClassroomModerationRpcError(
                "moderation recovery command is invalid"
            )
        fingerprint = _fingerprint(command)

        async with self._lock:
            try:
                state = self._ledger.operation_state(
                    room_id=room,
                    operation_id=command.operation_id,
                )
            except Exception:
                raise ClassroomModerationRpcError(
                    "moderation replay ledger read failed"
                ) from None
            if state is None:
                raise ClassroomModerationRpcError(
                    "moderation operation is not pending recovery"
                )
            state = _validated_ledger_state(
                state,
                expected_fingerprint=fingerprint,
            )
            await self._reconcile_verified_pending_locked(
                room_id=room,
                command=command,
                fingerprint=fingerprint,
                state=state,
            )

    async def _reconcile_verified_pending_locked(
        self,
        *,
        room_id: str,
        command: ModerationCommand,
        fingerprint: str,
        state: ModerationOperationState,
    ) -> None:
        if state.committed:
            return
        verifier = self._provider_state_verifier
        if verifier is None:
            raise ClassroomModerationRpcError(
                "moderation provider state verification is unavailable"
            )
        reservation_owner = state.reservation_owner
        assert reservation_owner is not None

        try:
            matches = await verifier.moderation_effect_matches(
                room_id=room_id,
                command=command,
            )
        except Exception:
            raise ClassroomModerationRpcError(
                "moderation provider state verification failed"
            ) from None
        if type(matches) is not bool:
            raise ClassroomModerationRpcError(
                "moderation provider state verifier returned invalid result"
            )
        if not matches:
            raise ClassroomModerationRpcError(
                "moderation provider state does not confirm pending operation"
            )

        try:
            self._ledger.commit(
                room_id=room_id,
                operation_id=command.operation_id,
                fingerprint=fingerprint,
                reservation_owner=reservation_owner,
            )
        except Exception:
            raise ClassroomModerationRpcError(
                "moderation replay ledger reconciliation commit failed"
            ) from None

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
            pending_commands: list[tuple[ModerationCommand, str]] = []
            for command, fingerprint in zip(
                parsed.commands,
                parsed.fingerprints,
                strict=True,
            ):
                try:
                    state = self._ledger.operation_state(
                        room_id=parsed.room_id,
                        operation_id=command.operation_id,
                    )
                except Exception as error:
                    raise ClassroomModerationRpcError(
                        "moderation replay ledger read failed"
                    ) from None
                if state is None:
                    pending_commands.append((command, fingerprint))
                    continue
                state = _validated_ledger_state(
                    state,
                    expected_fingerprint=fingerprint,
                )
                if not state.committed:
                    if state.reservation_owner != self._reservation_owner:
                        if self._provider_state_verifier is None:
                            raise ClassroomModerationRpcError(
                                "moderation operation is pending in another service participant"
                            )
                        await self._reconcile_verified_pending_locked(
                            room_id=parsed.room_id,
                            command=command,
                            fingerprint=fingerprint,
                            state=state,
                        )
                        continue
                    pending_commands.append((command, fingerprint))

            if pending_commands:
                # Authorize the complete set of effects before reserving or
                # mutating provider state. Authorization failure therefore
                # cannot poison operation ids in the shared ledger.
                try:
                    self._authorization.authorize_moderation_batch(
                        room_id=parsed.room_id,
                        caller_identity=trusted_caller_identity,
                        commands=tuple(command for command, _ in pending_commands),
                    )
                except Exception as error:
                    raise ClassroomModerationRpcError(
                        "moderation request is not authorized"
                    ) from None

                # Reserve every effect before the first provider mutation.
                # A cross-instance conflicting fingerprint therefore fails
                # before either this request or a later command can change the
                # provider. Exact pending reservations are retriable.
                effects: list[tuple[ModerationCommand, str]] = []
                for command, fingerprint in pending_commands:
                    try:
                        state = self._ledger.reserve(
                            room_id=parsed.room_id,
                            operation_id=command.operation_id,
                            fingerprint=fingerprint,
                            reservation_owner=self._reservation_owner,
                        )
                    except Exception as error:
                        raise ClassroomModerationRpcError(
                            "moderation replay ledger reservation failed"
                        ) from None
                    state = _validated_ledger_state(
                        state,
                        expected_fingerprint=fingerprint,
                    )
                    if not state.committed:
                        if state.reservation_owner != self._reservation_owner:
                            raise ClassroomModerationRpcError(
                                "moderation operation is pending in another service participant"
                            )
                        effects.append((command, fingerprint))

                for command, fingerprint in effects:
                    try:
                        await self._provider_admin.apply_moderation_command(
                            room_id=parsed.room_id,
                            command=command,
                        )
                    except Exception as error:
                        raise ClassroomModerationRpcError(
                            "moderation provider operation failed"
                        ) from None
                    try:
                        self._ledger.commit(
                            room_id=parsed.room_id,
                            operation_id=command.operation_id,
                            fingerprint=fingerprint,
                            reservation_owner=self._reservation_owner,
                        )
                    except Exception as error:
                        raise ClassroomModerationRpcError(
                            "moderation replay ledger commit failed"
                        ) from None

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
    "ClassroomModerationProviderStateVerifierPort",
    "ClassroomModerationRpcError",
    "ClassroomModerationRpcService",
    "ModerationOperationState",
    "MAX_RPC_OPERATIONS",
    "MAX_RPC_PAYLOAD_BYTES",
    "ParsedModerationRpc",
    "RPC_VERSION",
    "parse_moderation_rpc",
]
