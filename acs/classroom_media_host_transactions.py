from __future__ import annotations

"""Two-phase host transaction seam for asynchronous classroom media providers.

The canonical ClassroomMediaController intentionally calls a synchronous provider
port and commits canonical state only after that call succeeds. Browser providers
such as LiveKit are asynchronous, so blocking the native owner thread until
JavaScript completes is unsafe.

During prepare_* the port captures the exact provider effect and deliberately
interrupts controller execution before canonical state is mutated. After exact
provider success, commit_provider_success replays the same controller operation.
The port consumes only the exact captured effect and then permits the controller's
existing post-provider commit path.

Only non-secret, already-authorized media effects are represented here. Session
join/reconnect credentials remain outside this slice because their token payload is
secret and requires a dedicated one-shot handoff.
"""

from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
from enum import Enum
import re
import secrets
from threading import RLock, get_ident
from typing import Any

from .classroom_realtime_media import (
    ClassroomMediaController,
    JoinCredential,
    MediaDeviceKind,
    MediaSource,
    ModerationCommand,
    RealtimeMediaPort,
)


_TRANSACTION_RE = re.compile(r"^host-[0-9a-f]{32}$")
# The current LiveKit moderation adapter accepts at most 256 commands and a
# 15-KiB JSON RPC body. Twenty-four worst-case canonical commands (three
# 128-character identifiers each) leave deterministic headroom for room identity
# and JSON framing, so large classroom actions are planned as bounded calls.
MAX_BROWSER_MODERATION_COMMANDS_PER_CHUNK = 24


class MediaHostTransactionError(RuntimeError):
    """Raised when a host/provider transaction violates the two-phase contract."""


class MediaHostRecoveryRequired(MediaHostTransactionError):
    """Provider may have changed while canonical state could not be committed."""


class MediaProviderEffectKind(str, Enum):
    LOCAL_SOURCE = "set_local_source"
    MODERATION = "apply_moderation"
    RECOVER_DEVICE = "recover_device"


@dataclass(frozen=True, slots=True)
class MediaProviderEffect:
    """Exact non-secret provider effect authorized by the canonical controller."""

    transaction_id: str
    kind: MediaProviderEffectKind
    source: MediaSource | None = None
    enabled: bool | None = None
    commands: tuple[ModerationCommand, ...] = ()
    device_kind: MediaDeviceKind | None = None
    device_id: str | None = None
    republish_enabled: bool | None = None

    def __post_init__(self) -> None:
        if (
            type(self.transaction_id) is not str
            or _TRANSACTION_RE.fullmatch(self.transaction_id) is None
        ):
            raise MediaHostTransactionError("media transaction id is invalid")
        if not isinstance(self.kind, MediaProviderEffectKind):
            raise MediaHostTransactionError("media provider effect kind is invalid")
        if type(self.commands) is not tuple or any(
            type(command) is not ModerationCommand for command in self.commands
        ):
            raise MediaHostTransactionError("media moderation effect is invalid")

        if self.kind is MediaProviderEffectKind.LOCAL_SOURCE:
            if (
                not isinstance(self.source, MediaSource)
                or type(self.enabled) is not bool
                or self.commands
                or self.device_kind is not None
                or self.device_id is not None
                or self.republish_enabled is not None
            ):
                raise MediaHostTransactionError("local-source effect shape is invalid")
            return

        if self.kind is MediaProviderEffectKind.MODERATION:
            if (
                not self.commands
                or self.source is not None
                or self.enabled is not None
                or self.device_kind is not None
                or self.device_id is not None
                or self.republish_enabled is not None
            ):
                raise MediaHostTransactionError("moderation effect shape is invalid")
            return

        if (
            not isinstance(self.device_kind, MediaDeviceKind)
            or type(self.device_id) is not str
            or not self.device_id
            or type(self.republish_enabled) is not bool
            or self.source is not None
            or self.enabled is not None
            or self.commands
        ):
            raise MediaHostTransactionError("device-recovery effect shape is invalid")

    @staticmethod
    def _moderation_command_payload(
        command: ModerationCommand,
    ) -> Mapping[str, object]:
        return {
            "operation_id": command.operation_id,
            "actor_id": command.actor_id,
            "target_id": command.target_id,
            "action": command.action.value,
            "source": None if command.source is None else command.source.value,
            "value": command.value,
        }

    def browser_payloads(self) -> tuple[Mapping[str, object], ...]:
        """Return an ordered, bounded browser execution plan.

        A moderation effect remains one canonical transaction even when its
        provider execution needs multiple RPC-sized chunks. The host must execute
        every chunk in order and call commit_provider_success only after all
        chunks have exact provider success. Any partial/unknown outcome is
        recovery-required.
        """

        if self.kind is MediaProviderEffectKind.LOCAL_SOURCE:
            return (
                {
                    "transaction_id": self.transaction_id,
                    "operation": self.kind.value,
                    "source": self.source.value,
                    "enabled": self.enabled,
                },
            )
        if self.kind is MediaProviderEffectKind.MODERATION:
            chunks = tuple(
                self.commands[index:index + MAX_BROWSER_MODERATION_COMMANDS_PER_CHUNK]
                for index in range(
                    0,
                    len(self.commands),
                    MAX_BROWSER_MODERATION_COMMANDS_PER_CHUNK,
                )
            )
            chunk_count = len(chunks)
            return tuple(
                {
                    "transaction_id": self.transaction_id,
                    "operation": self.kind.value,
                    "chunk_index": index,
                    "chunk_count": chunk_count,
                    "commands": [
                        self._moderation_command_payload(command)
                        for command in chunk
                    ],
                }
                for index, chunk in enumerate(chunks)
            )
        return (
            {
                "transaction_id": self.transaction_id,
                "operation": self.kind.value,
                "kind": self.device_kind.value,
                "device_id": self.device_id,
                "republish_enabled": self.republish_enabled,
            },
        )

    def browser_payload(self) -> Mapping[str, object]:
        """Return one browser payload only when the effect needs one provider call."""

        payloads = self.browser_payloads()
        if len(payloads) != 1:
            raise MediaHostTransactionError(
                "media effect requires multiple ordered browser payload chunks"
            )
        return payloads[0]


class _PreparedProviderEffect(Exception):
    def __init__(self, effect: MediaProviderEffect) -> None:
        super().__init__("provider effect prepared")
        self.effect = effect


class ClassroomMediaHostTransactionPort:
    """RealtimeMediaPort gate for nonblocking provider effects."""

    def __init__(self, *, session_port: RealtimeMediaPort | None = None) -> None:
        self._session_port = session_port
        self._lock = RLock()
        self._phase = "idle"
        self._transaction_id: str | None = None
        self._expected: MediaProviderEffect | None = None
        self._consumed = False

    def connect(
        self,
        credential: JoinCredential,
        *,
        enabled_sources: tuple[MediaSource, ...],
    ) -> None:
        if self._session_port is None:
            raise MediaHostTransactionError(
                "media session connect requires a dedicated session transport"
            )
        self._session_port.connect(credential, enabled_sources=enabled_sources)

    def reconnect(
        self,
        credential: JoinCredential,
        *,
        enabled_sources: tuple[MediaSource, ...],
    ) -> None:
        if self._session_port is None:
            raise MediaHostTransactionError(
                "media session reconnect requires a dedicated session transport"
            )
        self._session_port.reconnect(credential, enabled_sources=enabled_sources)

    def disconnect(self) -> None:
        if self._session_port is None:
            raise MediaHostTransactionError(
                "media session disconnect requires a dedicated session transport"
            )
        self._session_port.disconnect()

    def set_local_source(self, source: MediaSource, enabled: bool) -> None:
        self._emit(
            MediaProviderEffect(
                transaction_id=self._active_transaction_id(),
                kind=MediaProviderEffectKind.LOCAL_SOURCE,
                source=source,
                enabled=enabled,
            )
        )

    def apply_moderation(self, commands: tuple[ModerationCommand, ...]) -> None:
        self._emit(
            MediaProviderEffect(
                transaction_id=self._active_transaction_id(),
                kind=MediaProviderEffectKind.MODERATION,
                commands=commands,
            )
        )

    def recover_device(
        self,
        kind: MediaDeviceKind,
        device_id: str,
        *,
        republish_enabled: bool,
    ) -> None:
        self._emit(
            MediaProviderEffect(
                transaction_id=self._active_transaction_id(),
                kind=MediaProviderEffectKind.RECOVER_DEVICE,
                device_kind=kind,
                device_id=device_id,
                republish_enabled=republish_enabled,
            )
        )

    def _active_transaction_id(self) -> str:
        if self._transaction_id is None:
            raise MediaHostTransactionError(
                "provider effect requires an active host transaction"
            )
        return self._transaction_id

    def _emit(self, effect: MediaProviderEffect) -> None:
        with self._lock:
            if self._phase == "prepare":
                raise _PreparedProviderEffect(effect)
            if self._phase == "commit":
                if self._expected is None or effect != self._expected:
                    raise MediaHostTransactionError(
                        "committed provider effect does not match prepared effect"
                    )
                if self._consumed:
                    raise MediaHostTransactionError(
                        "prepared provider effect was consumed more than once"
                    )
                self._consumed = True
                return
            raise MediaHostTransactionError(
                "provider effect requires prepare/commit host transaction"
            )

    def _prepare(
        self,
        transaction_id: str,
        replay: Callable[[], Any],
    ) -> tuple[MediaProviderEffect | None, Any]:
        with self._lock:
            if self._phase != "idle":
                raise MediaHostTransactionError("media transaction port is busy")
            self._phase = "prepare"
            self._transaction_id = transaction_id
            try:
                result = replay()
            except _PreparedProviderEffect as prepared:
                return prepared.effect, None
            finally:
                self._phase = "idle"
                self._transaction_id = None
            return None, result

    def _commit(self, effect: MediaProviderEffect, replay: Callable[[], Any]) -> Any:
        with self._lock:
            if self._phase != "idle":
                raise MediaHostTransactionError("media transaction port is busy")
            self._phase = "commit"
            self._transaction_id = effect.transaction_id
            self._expected = effect
            self._consumed = False
            try:
                result = replay()
                if not self._consumed:
                    raise MediaHostTransactionError(
                        "prepared provider effect was not consumed during replay"
                    )
                return result
            finally:
                self._phase = "idle"
                self._transaction_id = None
                self._expected = None
                self._consumed = False


@dataclass(frozen=True, slots=True)
class _PendingTransaction:
    effect: MediaProviderEffect
    base_revision: int
    replay: Callable[[], Any]
    next_chunk_index: int = 0


TransactionIdFactory = Callable[[], str]


class ClassroomMediaHostTransactions:
    """Serialize one authorized async provider effect around the controller."""

    def __init__(
        self,
        controller: ClassroomMediaController,
        port: ClassroomMediaHostTransactionPort,
        *,
        transaction_id_factory: TransactionIdFactory | None = None,
    ) -> None:
        if not isinstance(controller, ClassroomMediaController):
            raise TypeError("controller must be ClassroomMediaController")
        if not isinstance(port, ClassroomMediaHostTransactionPort):
            raise TypeError("port must be ClassroomMediaHostTransactionPort")
        if getattr(controller, "_media", None) is not port:
            raise ValueError("controller must use the supplied media transaction port")
        if transaction_id_factory is not None and not callable(transaction_id_factory):
            raise TypeError("transaction id factory must be callable")
        self._controller = controller
        self._port = port
        self._transaction_id_factory = transaction_id_factory or (
            lambda: "host-" + secrets.token_hex(16)
        )
        self._lock = RLock()
        self._owner_thread_id = get_ident()
        self._pending: _PendingTransaction | None = None
        self._recovery: _PendingTransaction | None = None
        self._used_transaction_ids: set[str] = set()

    @property
    def pending_effect(self) -> MediaProviderEffect | None:
        with self._lock:
            return None if self._pending is None else self._pending.effect

    @property
    def recovery_effect(self) -> MediaProviderEffect | None:
        with self._lock:
            return None if self._recovery is None else self._recovery.effect

    @property
    def pending_browser_payload(self) -> Mapping[str, object] | None:
        """Return only the next provider call allowed for the pending transaction."""

        with self._lock:
            if self._pending is None:
                return None
            payloads = self._pending.effect.browser_payloads()
            if self._pending.next_chunk_index >= len(payloads):
                raise MediaHostTransactionError(
                    "media transaction provider plan is internally inconsistent"
                )
            return payloads[self._pending.next_chunk_index]

    def _assert_owner_thread(self) -> None:
        if get_ident() != self._owner_thread_id:
            raise MediaHostTransactionError(
                "media host transaction mutation requires the owner thread"
            )

    def _transaction_id(self) -> str:
        value = self._transaction_id_factory()
        if type(value) is not str or _TRANSACTION_RE.fullmatch(value) is None:
            raise MediaHostTransactionError(
                "transaction id factory returned invalid identity"
            )
        if value in self._used_transaction_ids:
            raise MediaHostTransactionError(
                "transaction id factory reused a media transaction identity"
            )
        self._used_transaction_ids.add(value)
        return value

    def _prepare(self, replay: Callable[[], Any]) -> MediaProviderEffect | None:
        self._assert_owner_thread()
        with self._lock:
            if self._pending is not None:
                raise MediaHostTransactionError("a media provider effect is already pending")
            if self._recovery is not None:
                raise MediaHostRecoveryRequired(
                    "media provider state requires recovery before another effect"
                )
            transaction_id = self._transaction_id()
            base_revision = self._controller.state.revision
            effect, _result = self._port._prepare(transaction_id, replay)
            if effect is None:
                return None
            self._pending = _PendingTransaction(
                effect=effect,
                base_revision=base_revision,
                replay=replay,
            )
            return effect

    def prepare_local_source(
        self,
        source: MediaSource | str,
        enabled: bool,
    ) -> MediaProviderEffect | None:
        return self._prepare(
            lambda: self._controller.set_local_source(source, enabled)
        )

    def prepare_publish_permission(
        self,
        *,
        actor_id: str,
        target_id: str,
        source: MediaSource | str,
        allowed: bool,
        operation_id: str,
    ) -> MediaProviderEffect | None:
        return self._prepare(
            lambda: self._controller.set_publish_permission(
                actor_id=actor_id,
                target_id=target_id,
                source=source,
                allowed=allowed,
                operation_id=operation_id,
            )
        )

    def prepare_soft_mute(
        self,
        *,
        actor_id: str,
        target_id: str,
        muted: bool,
        operation_id: str,
    ) -> MediaProviderEffect | None:
        return self._prepare(
            lambda: self._controller.set_soft_mute(
                actor_id=actor_id,
                target_id=target_id,
                muted=muted,
                operation_id=operation_id,
            )
        )

    def prepare_all_students_publish_permission(
        self,
        *,
        actor_id: str,
        source: MediaSource | str,
        allowed: bool,
        operation_id: str,
    ) -> MediaProviderEffect | None:
        return self._prepare(
            lambda: self._controller.set_all_students_publish_permission(
                actor_id=actor_id,
                source=source,
                allowed=allowed,
                operation_id=operation_id,
            )
        )

    def prepare_all_students_soft_mute(
        self,
        *,
        actor_id: str,
        muted: bool,
        operation_id: str,
    ) -> MediaProviderEffect | None:
        return self._prepare(
            lambda: self._controller.set_all_students_soft_mute(
                actor_id=actor_id,
                muted=muted,
                operation_id=operation_id,
            )
        )

    def prepare_remove_participant(
        self,
        *,
        actor_id: str,
        target_id: str,
        block: bool,
        operation_id: str,
    ) -> MediaProviderEffect | None:
        return self._prepare(
            lambda: self._controller.remove_participant(
                actor_id=actor_id,
                target_id=target_id,
                block=block,
                operation_id=operation_id,
            )
        )

    def prepare_device_recovery(
        self,
        kind: MediaDeviceKind | str,
        device_id: str,
    ) -> MediaProviderEffect | None:
        return self._prepare(lambda: self._controller.recover_device(kind, device_id))

    def provider_not_started(self, transaction_id: str) -> None:
        """Discard an effect only when the provider was provably never invoked."""

        self._assert_owner_thread()
        with self._lock:
            pending = self._require_pending(transaction_id)
            if pending.next_chunk_index != 0:
                self._pending = None
                self._recovery = pending
                raise MediaHostRecoveryRequired(
                    "media provider transaction is already partially applied"
                )
            self._pending = None

    def provider_failed(self, transaction_id: str) -> None:
        """Latch recovery after a provider failure with potentially partial effects."""

        self.provider_outcome_unknown(transaction_id)

    def provider_outcome_unknown(self, transaction_id: str) -> None:
        """Latch recovery when provider success/failure cannot be established."""

        self._assert_owner_thread()
        with self._lock:
            pending = self._require_pending(transaction_id)
            self._pending = None
            self._recovery = pending

    def acknowledge_provider_chunk_success(
        self,
        transaction_id: str,
        chunk_index: int,
    ) -> Any | None:
        """Advance one exact provider chunk and commit only after the final chunk."""

        self._assert_owner_thread()
        if type(chunk_index) is not int or chunk_index < 0:
            raise MediaHostTransactionError("media provider chunk index is invalid")
        with self._lock:
            pending = self._require_pending(transaction_id)
            payloads = pending.effect.browser_payloads()
            if chunk_index != pending.next_chunk_index:
                if chunk_index < pending.next_chunk_index:
                    raise MediaHostTransactionError(
                        "media provider chunk acknowledgement is duplicate or stale"
                    )
                self._pending = None
                self._recovery = pending
                raise MediaHostRecoveryRequired(
                    "media provider chunks completed out of order"
                )

            next_chunk = chunk_index + 1
            if next_chunk < len(payloads):
                self._pending = replace(
                    pending,
                    next_chunk_index=next_chunk,
                )
                return None

            if self._controller.state.revision != pending.base_revision:
                self._pending = None
                self._recovery = pending
                raise MediaHostRecoveryRequired(
                    "canonical media state changed before provider acknowledgement"
                )
            try:
                result = self._port._commit(pending.effect, pending.replay)
            except Exception as exc:
                self._pending = None
                self._recovery = pending
                raise MediaHostRecoveryRequired(
                    "provider succeeded but canonical media commit requires recovery"
                ) from exc
            self._pending = None
            return result

    def commit_provider_success(self, transaction_id: str) -> Any:
        """Compatibility helper for effects that require exactly one provider call."""

        self._assert_owner_thread()
        with self._lock:
            pending = self._require_pending(transaction_id)
            if len(pending.effect.browser_payloads()) != 1:
                raise MediaHostTransactionError(
                    "multi-chunk media effect requires per-chunk provider acknowledgement"
                )
        return self.acknowledge_provider_chunk_success(transaction_id, 0)

    def resolve_recovery(self, transaction_id: str) -> None:
        """Clear recovery only after the host has reconciled provider state."""

        self._assert_owner_thread()
        with self._lock:
            if (
                self._recovery is None
                or self._recovery.effect.transaction_id != transaction_id
            ):
                raise MediaHostTransactionError("media recovery transaction is unknown")
            self._recovery = None

    def _require_pending(self, transaction_id: str) -> _PendingTransaction:
        if type(transaction_id) is not str or _TRANSACTION_RE.fullmatch(transaction_id) is None:
            raise MediaHostTransactionError("media transaction id is invalid")
        if self._pending is None or self._pending.effect.transaction_id != transaction_id:
            raise MediaHostTransactionError("media transaction is unknown or already consumed")
        return self._pending


__all__ = [
    "ClassroomMediaHostTransactionPort",
    "ClassroomMediaHostTransactions",
    "MediaHostRecoveryRequired",
    "MediaHostTransactionError",
    "MediaProviderEffect",
    "MAX_BROWSER_MODERATION_COMMANDS_PER_CHUNK",
    "MediaProviderEffectKind",
]
