from __future__ import annotations

"""One-shot desktop/browser handoff for realtime classroom session credentials.

ClassroomMediaController is intentionally synchronous: it commits canonical local
session state only after RealtimeMediaPort reports provider success. The browser
LiveKit client is asynchronous and join/reconnect credentials contain a short-lived
secret token. This module bridges only that session lifecycle boundary.

The credential is retained in process memory only while one transaction is
pending. It is never included in repr, summaries, recovery metadata, snapshots or
durable state. The browser payload containing the token can be claimed exactly once.
Provider effects other than connect/reconnect/disconnect remain owned by the
separate media-effect transaction boundary. The eventual shipping binder must
serialize this coordinator with that media-effect coordinator behind one shared
provider-execution owner; two independent pending provider calls are not safe.
"""

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field, replace
from datetime import datetime
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
)


_TRANSACTION_RE = re.compile(r"^session-[0-9a-f]{32}$")


class MediaSessionHandoffError(RuntimeError):
    """Raised when the one-shot session handoff contract is violated."""


class MediaSessionRecoveryRequired(MediaSessionHandoffError):
    """Provider/browser session state must be reconciled before another effect."""


class MediaSessionOperation(str, Enum):
    CONNECT = "connect"
    RECONNECT = "reconnect"
    DISCONNECT = "disconnect"


@dataclass(frozen=True, slots=True)
class MediaSessionEffectSummary:
    """Non-secret status safe for diagnostics and product recovery UI."""

    transaction_id: str
    operation: MediaSessionOperation
    enabled_sources: tuple[MediaSource, ...]
    credential_exposed: bool


@dataclass(frozen=True, slots=True)
class MediaSessionRecoveryStatus:
    """Non-secret recovery metadata for a trusted host."""

    effect: MediaSessionEffectSummary
    provider_outcome_unknown: bool


@dataclass(frozen=True, slots=True)
class _SessionProviderEffect:
    transaction_id: str
    operation: MediaSessionOperation
    credential: JoinCredential | None = field(default=None, repr=False)
    enabled_sources: tuple[MediaSource, ...] = ()

    def __post_init__(self) -> None:
        if (
            type(self.transaction_id) is not str
            or _TRANSACTION_RE.fullmatch(self.transaction_id) is None
        ):
            raise MediaSessionHandoffError("media session transaction id is invalid")
        if not isinstance(self.operation, MediaSessionOperation):
            raise MediaSessionHandoffError("media session operation is invalid")
        if type(self.enabled_sources) is not tuple or any(
            not isinstance(source, MediaSource) for source in self.enabled_sources
        ):
            raise MediaSessionHandoffError("media session enabled sources are invalid")
        if len(set(self.enabled_sources)) != len(self.enabled_sources):
            raise MediaSessionHandoffError("media session enabled sources contain duplicates")

        if self.operation is MediaSessionOperation.DISCONNECT:
            if self.credential is not None or self.enabled_sources:
                raise MediaSessionHandoffError("disconnect session effect shape is invalid")
            return

        if type(self.credential) is not JoinCredential:
            raise MediaSessionHandoffError("session credential is invalid")


class _SecretCredentialPayload(dict[str, str]):
    """JSON-compatible credential mapping with fail-safe diagnostic formatting."""

    def __repr__(self) -> str:
        return (
            "{'room_id': '<redacted>', 'participant_id': '<redacted>', "
            "'token': '<redacted>'}"
        )

    __str__ = __repr__


class _SecretBrowserPayload(dict[str, object]):
    """JSON-compatible one-shot payload whose nested credential repr is redacted."""


class _PreparedSessionEffect(Exception):
    def __init__(self, effect: _SessionProviderEffect) -> None:
        super().__init__("session provider effect prepared")
        self.effect = effect


class ClassroomMediaSessionHandoffPort:
    """Session-only RealtimeMediaPort component for asynchronous browser providers.

    This object can be used directly for session-only controller tests or injected
    as session_port into the non-secret media-effect transaction port. It does not
    implement local-source/moderation/device provider effects.
    """

    def __init__(self) -> None:
        self._lock = RLock()
        self._phase = "idle"
        self._transaction_id: str | None = None
        self._expected: _SessionProviderEffect | None = None
        self._consumed = False
        self._coordinator_bound = False

    def _bind_coordinator(self) -> None:
        with self._lock:
            if self._coordinator_bound:
                raise MediaSessionHandoffError(
                    "media session handoff port already has a coordinator"
                )
            if self._phase != "idle":
                raise MediaSessionHandoffError("media session handoff port is busy")
            self._coordinator_bound = True

    def connect(
        self,
        credential: JoinCredential,
        *,
        enabled_sources: tuple[MediaSource, ...],
    ) -> None:
        self._emit(
            _SessionProviderEffect(
                transaction_id=self._active_transaction_id(),
                operation=MediaSessionOperation.CONNECT,
                credential=credential,
                enabled_sources=enabled_sources,
            )
        )

    def reconnect(
        self,
        credential: JoinCredential,
        *,
        enabled_sources: tuple[MediaSource, ...],
    ) -> None:
        self._emit(
            _SessionProviderEffect(
                transaction_id=self._active_transaction_id(),
                operation=MediaSessionOperation.RECONNECT,
                credential=credential,
                enabled_sources=enabled_sources,
            )
        )

    def disconnect(self) -> None:
        self._emit(
            _SessionProviderEffect(
                transaction_id=self._active_transaction_id(),
                operation=MediaSessionOperation.DISCONNECT,
            )
        )

    def set_local_source(self, source: MediaSource, enabled: bool) -> None:
        raise MediaSessionHandoffError(
            "local-source effect requires the separate media-effect provider port"
        )

    def apply_moderation(self, commands: tuple[ModerationCommand, ...]) -> None:
        raise MediaSessionHandoffError(
            "moderation effect requires the separate media-effect provider port"
        )

    def recover_device(
        self,
        kind: MediaDeviceKind,
        device_id: str,
        *,
        republish_enabled: bool,
    ) -> None:
        raise MediaSessionHandoffError(
            "device recovery requires the separate media-effect provider port"
        )

    def _active_transaction_id(self) -> str:
        if self._transaction_id is None:
            raise MediaSessionHandoffError(
                "session provider effect requires an active host transaction"
            )
        return self._transaction_id

    def _emit(self, effect: _SessionProviderEffect) -> None:
        with self._lock:
            if self._phase == "prepare":
                raise _PreparedSessionEffect(effect)
            if self._phase == "commit":
                if self._expected is None or effect != self._expected:
                    raise MediaSessionHandoffError(
                        "committed session effect does not match prepared effect"
                    )
                if self._consumed:
                    raise MediaSessionHandoffError(
                        "prepared session effect was consumed more than once"
                    )
                self._consumed = True
                return
            raise MediaSessionHandoffError(
                "session provider effect requires prepare/commit host transaction"
            )

    def _prepare(
        self,
        transaction_id: str,
        replay: Callable[[], Any],
    ) -> tuple[_SessionProviderEffect | None, Any]:
        with self._lock:
            if self._phase != "idle":
                raise MediaSessionHandoffError("media session handoff port is busy")
            self._phase = "prepare"
            self._transaction_id = transaction_id
            try:
                result = replay()
            except _PreparedSessionEffect as prepared:
                return prepared.effect, None
            finally:
                self._phase = "idle"
                self._transaction_id = None
            return None, result

    def _commit(
        self,
        effect: _SessionProviderEffect,
        replay: Callable[[], Any],
    ) -> Any:
        with self._lock:
            if self._phase != "idle":
                raise MediaSessionHandoffError("media session handoff port is busy")
            self._phase = "commit"
            self._transaction_id = effect.transaction_id
            self._expected = effect
            self._consumed = False
            try:
                result = replay()
                if not self._consumed:
                    raise MediaSessionHandoffError(
                        "prepared session effect was not consumed during replay"
                    )
                return result
            finally:
                self._phase = "idle"
                self._transaction_id = None
                self._expected = None
                self._consumed = False


@dataclass(frozen=True, slots=True)
class _PendingSessionTransaction:
    effect: _SessionProviderEffect
    base_revision: int
    replay: Callable[[], Any]
    credential_exposed: bool = False


@dataclass(frozen=True, slots=True)
class _RecoverySessionTransaction:
    pending: _PendingSessionTransaction
    provider_outcome_unknown: bool


TransactionIdFactory = Callable[[], str]


class ClassroomMediaSessionHandoffs:
    """Serialize one secret-bearing browser session effect around the controller."""

    def __init__(
        self,
        controller: ClassroomMediaController,
        port: ClassroomMediaSessionHandoffPort,
        *,
        transaction_id_factory: TransactionIdFactory | None = None,
    ) -> None:
        if not isinstance(controller, ClassroomMediaController):
            raise TypeError("controller must be ClassroomMediaController")
        if not isinstance(port, ClassroomMediaSessionHandoffPort):
            raise TypeError("port must be ClassroomMediaSessionHandoffPort")
        if transaction_id_factory is not None and not callable(transaction_id_factory):
            raise TypeError("transaction id factory must be callable")

        root_port = getattr(controller, "_media", None)
        if (
            root_port is not port
            and getattr(root_port, "_session_port", None) is not port
        ):
            raise ValueError(
                "controller media path must route session lifecycle through supplied port"
            )

        transaction_nonce = (
            secrets.token_hex(8) if transaction_id_factory is None else ""
        )
        lock = RLock()
        owner_thread_id = get_ident()

        self._controller = controller
        self._port = port
        self._transaction_id_factory = transaction_id_factory
        self._transaction_nonce = transaction_nonce
        self._transaction_counter = 0
        self._injected_transaction_ids: set[str] = set()
        self._lock = lock
        self._owner_thread_id = owner_thread_id
        self._pending: _PendingSessionTransaction | None = None
        self._recovery: _RecoverySessionTransaction | None = None
        port._bind_coordinator()

    @property
    def pending_effect(self) -> MediaSessionEffectSummary | None:
        with self._lock:
            if self._pending is None:
                return None
            return self._summary(self._pending)

    @property
    def recovery_status(self) -> MediaSessionRecoveryStatus | None:
        with self._lock:
            if self._recovery is None:
                return None
            return MediaSessionRecoveryStatus(
                effect=self._summary(self._recovery.pending),
                provider_outcome_unknown=self._recovery.provider_outcome_unknown,
            )

    def _summary(
        self,
        pending: _PendingSessionTransaction,
    ) -> MediaSessionEffectSummary:
        return MediaSessionEffectSummary(
            transaction_id=pending.effect.transaction_id,
            operation=pending.effect.operation,
            enabled_sources=pending.effect.enabled_sources,
            credential_exposed=(
                pending.credential_exposed and pending.effect.credential is not None
            ),
        )

    def _assert_owner_thread(self) -> None:
        if get_ident() != self._owner_thread_id:
            raise MediaSessionHandoffError(
                "media session handoff mutation requires the owner thread"
            )

    def _transaction_id(self) -> str:
        if self._transaction_id_factory is None:
            if self._transaction_counter >= (1 << 64) - 1:
                raise MediaSessionHandoffError(
                    "media session transaction identity space is exhausted"
                )
            self._transaction_counter += 1
            return (
                "session-"
                + self._transaction_nonce
                + f"{self._transaction_counter:016x}"
            )

        value = self._transaction_id_factory()
        if type(value) is not str or _TRANSACTION_RE.fullmatch(value) is None:
            raise MediaSessionHandoffError(
                "transaction id factory returned invalid session identity"
            )
        if value in self._injected_transaction_ids:
            raise MediaSessionHandoffError(
                "transaction id factory reused a session transaction identity"
            )
        self._injected_transaction_ids.add(value)
        return value

    def _release_unexposed_transaction_id(self, transaction_id: str) -> None:
        if self._transaction_id_factory is not None:
            self._injected_transaction_ids.discard(transaction_id)

    def _prepare(self, replay: Callable[[], Any]) -> MediaSessionEffectSummary | None:
        self._assert_owner_thread()
        with self._lock:
            if self._pending is not None:
                raise MediaSessionHandoffError(
                    "a media session provider effect is already pending"
                )
            if self._recovery is not None:
                raise MediaSessionRecoveryRequired(
                    "media session provider state requires recovery"
                )
            transaction_id = self._transaction_id()
            base_revision = self._controller.state.revision
            try:
                effect, _result = self._port._prepare(transaction_id, replay)
            except Exception:
                self._release_unexposed_transaction_id(transaction_id)
                raise
            if effect is None:
                self._release_unexposed_transaction_id(transaction_id)
                return None
            self._pending = _PendingSessionTransaction(
                effect=effect,
                base_revision=base_revision,
                replay=replay,
            )
            return self._summary(self._pending)

    def prepare_join(
        self,
        credential: JoinCredential,
        *,
        now,
    ) -> MediaSessionEffectSummary | None:
        return self._prepare(lambda: self._controller.join(credential, now=now))

    def prepare_reconnect(
        self,
        credential: JoinCredential,
        *,
        now,
    ) -> MediaSessionEffectSummary | None:
        return self._prepare(lambda: self._controller.reconnect(credential, now=now))

    def prepare_leave(self) -> MediaSessionEffectSummary | None:
        return self._prepare(self._controller.leave)

    def claim_browser_payload(
        self,
        transaction_id: str,
        *,
        now: datetime | None = None,
    ) -> Mapping[str, object]:
        """Return the browser session payload exactly once.

        Connect/reconnect returns the short-lived token. Callers must pass this
        object directly to the trusted packaged provider adapter and must not log,
        cache, persist, announce or include it in a product snapshot.
        """

        self._assert_owner_thread()
        with self._lock:
            pending = self._require_pending(transaction_id)
            if pending.credential_exposed:
                raise MediaSessionHandoffError(
                    "media session browser payload was already claimed"
                )
            effect = pending.effect
            if effect.credential is not None:
                if (
                    type(now) is not datetime
                    or now.tzinfo is None
                    or now.utcoffset() is None
                ):
                    raise MediaSessionHandoffError(
                        "timezone-aware current time is required for credential handoff"
                    )
                try:
                    effect.credential.assert_usable(now)
                except Exception as exc:
                    # The credential has not crossed the browser boundary yet.
                    # Retire this exposed transaction identity and force the host
                    # to obtain a fresh short-lived credential rather than
                    # disclosing a stale token to JavaScript.
                    self._pending = None
                    raise MediaSessionHandoffError(
                        "media session credential expired before browser handoff"
                    ) from exc

            payload: _SecretBrowserPayload = _SecretBrowserPayload(
                transaction_id=effect.transaction_id,
                operation=effect.operation.value,
            )
            if effect.credential is not None:
                payload["credential"] = _SecretCredentialPayload(
                    room_id=effect.credential.room_id,
                    participant_id=effect.credential.participant_id,
                    token=effect.credential.token,
                )
                payload["enabled_sources"] = [
                    source.value for source in effect.enabled_sources
                ]
            self._pending = replace(pending, credential_exposed=True)
            return payload

    def provider_not_started(self, transaction_id: str) -> None:
        """Discard only when no provider call occurred and no credential can race."""

        self._assert_owner_thread()
        with self._lock:
            pending = self._require_pending(transaction_id)
            if pending.credential_exposed and pending.effect.credential is not None:
                self._pending = None
                self._recovery = _RecoverySessionTransaction(
                    pending=pending,
                    provider_outcome_unknown=False,
                )
                raise MediaSessionRecoveryRequired(
                    "claimed session credential requires recovery before reuse"
                )
            self._pending = None

    def provider_connection_failed_clean(
        self,
        transaction_id: str,
        *,
        connected: bool,
        cleanup_required: bool,
    ) -> None:
        """Retire a failed connect/reconnect after the adapter proves clean teardown.

        This is intentionally narrower than provider_failed(). The shipping binder
        may call it only after the awaited LiveKit connect/reconnect promise has
        settled and adapter.snapshot() reports connected=false and
        cleanup_required=false. A disconnect failure cannot use this shortcut,
        because canonical state still says connected until exact disconnect
        success is committed.
        """

        self._assert_owner_thread()
        if type(connected) is not bool or type(cleanup_required) is not bool:
            raise MediaSessionHandoffError(
                "media session adapter cleanup flags must be boolean"
            )
        with self._lock:
            pending = self._require_pending(transaction_id)
            if pending.effect.operation not in {
                MediaSessionOperation.CONNECT,
                MediaSessionOperation.RECONNECT,
            }:
                raise MediaSessionHandoffError(
                    "verified clean failure applies only to connect or reconnect"
                )
            if not pending.credential_exposed:
                raise MediaSessionHandoffError(
                    "verified clean failure requires a claimed browser credential"
                )
            if connected or cleanup_required:
                raise MediaSessionHandoffError(
                    "media session adapter has not proven clean teardown"
                )
            self._pending = None

    def provider_failed(self, transaction_id: str) -> None:
        """Latch recovery because browser/provider failures may leave cleanup state."""

        self.provider_outcome_unknown(transaction_id)

    def provider_outcome_unknown(self, transaction_id: str) -> None:
        self._assert_owner_thread()
        with self._lock:
            pending = self._require_pending(transaction_id)
            self._pending = None
            self._recovery = _RecoverySessionTransaction(
                pending=pending,
                provider_outcome_unknown=True,
            )

    def acknowledge_provider_success(self, transaction_id: str) -> Any:
        """Commit canonical session state only after exact browser provider success."""

        self._assert_owner_thread()
        with self._lock:
            pending = self._require_pending(transaction_id)
            if not pending.credential_exposed:
                self._pending = None
                self._recovery = _RecoverySessionTransaction(
                    pending=pending,
                    provider_outcome_unknown=True,
                )
                raise MediaSessionRecoveryRequired(
                    "provider success without a claimed browser payload is inconsistent"
                )
            if self._controller.state.revision != pending.base_revision:
                self._pending = None
                self._recovery = _RecoverySessionTransaction(
                    pending=pending,
                    provider_outcome_unknown=False,
                )
                raise MediaSessionRecoveryRequired(
                    "canonical media state changed before session acknowledgement"
                )
            try:
                result = self._port._commit(pending.effect, pending.replay)
            except Exception as exc:
                self._pending = None
                self._recovery = _RecoverySessionTransaction(
                    pending=pending,
                    provider_outcome_unknown=False,
                )
                raise MediaSessionRecoveryRequired(
                    "provider succeeded but canonical session commit requires recovery"
                ) from exc
            self._pending = None
            return result

    def resolve_recovery(self, transaction_id: str) -> None:
        """Clear recovery only after trusted host reconciliation/credential disposal."""

        self._assert_owner_thread()
        with self._lock:
            self._require_recovery(transaction_id)
            self._recovery = None

    def _require_pending(
        self,
        transaction_id: str,
    ) -> _PendingSessionTransaction:
        if type(transaction_id) is not str or _TRANSACTION_RE.fullmatch(transaction_id) is None:
            raise MediaSessionHandoffError("media session transaction id is invalid")
        if (
            self._pending is None
            or self._pending.effect.transaction_id != transaction_id
        ):
            raise MediaSessionHandoffError(
                "media session transaction is unknown or already consumed"
            )
        return self._pending

    def _require_recovery(
        self,
        transaction_id: str,
    ) -> _RecoverySessionTransaction:
        if type(transaction_id) is not str or _TRANSACTION_RE.fullmatch(transaction_id) is None:
            raise MediaSessionHandoffError("media session transaction id is invalid")
        if (
            self._recovery is None
            or self._recovery.pending.effect.transaction_id != transaction_id
        ):
            raise MediaSessionHandoffError("media session recovery transaction is unknown")
        return self._recovery


__all__ = [
    "ClassroomMediaSessionHandoffPort",
    "ClassroomMediaSessionHandoffs",
    "MediaSessionEffectSummary",
    "MediaSessionHandoffError",
    "MediaSessionOperation",
    "MediaSessionRecoveryRequired",
    "MediaSessionRecoveryStatus",
]
