from __future__ import annotations

"""Secret-safe two-phase session transactions for browser classroom media.

This successor complements classroom_media_host_transactions. The canonical
ClassroomMediaController still owns join/reconnect/leave state transitions and
still commits only after its synchronous provider port returns. The session port
captures that provider call before canonical state mutation, hands the short-lived
credential to the trusted browser host exactly once, and consumes the exact same
call only after a validated provider-success snapshot returns to the owner thread.

Join tokens are never placed in public transaction effects, pending browser
payloads, recovery status, repr output, or diagnostics. Once a credential has
crossed into the browser, a failed/unknown transaction is quarantined for explicit
reconciliation rather than being treated as a clean rollback.
"""

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from enum import Enum
import re
import secrets
from threading import RLock, get_ident
from typing import Any

from .classroom_media_host_transactions import (
    ClassroomMediaHostTransactionPort,
    ClassroomMediaHostTransactions,
    MediaHostRecoveryRequired,
    MediaHostTransactionError,
)
from .classroom_realtime_media import (
    ClassroomMediaController,
    JoinCredential,
    MediaDeviceKind,
    MediaSource,
    ModerationCommand,
)


_SESSION_TRANSACTION_RE = re.compile(r"^session-[0-9a-f]{32}$")
_PROVIDER_SNAPSHOT_KEYS = frozenset(
    {
        "connected",
        "cleanup_required",
        "room_id",
        "participant_id",
        "microphone_enabled",
        "camera_enabled",
        "screen_share_enabled",
    }
)


class MediaSessionEffectKind(str, Enum):
    CONNECT = "connect"
    RECONNECT = "reconnect"
    DISCONNECT = "disconnect"


@dataclass(frozen=True, slots=True)
class MediaSessionProviderEffect:
    """Public non-secret description of one exact browser session effect."""

    transaction_id: str
    kind: MediaSessionEffectKind
    enabled_sources: tuple[MediaSource, ...] = ()

    def __post_init__(self) -> None:
        if (
            type(self.transaction_id) is not str
            or _SESSION_TRANSACTION_RE.fullmatch(self.transaction_id) is None
        ):
            raise MediaHostTransactionError("media session transaction id is invalid")
        if not isinstance(self.kind, MediaSessionEffectKind):
            raise MediaHostTransactionError("media session effect kind is invalid")
        if type(self.enabled_sources) is not tuple or any(
            not isinstance(source, MediaSource) for source in self.enabled_sources
        ):
            raise MediaHostTransactionError("media session enabled sources are invalid")
        if len(set(self.enabled_sources)) != len(self.enabled_sources):
            raise MediaHostTransactionError("media session enabled sources contain duplicates")
        if self.kind is MediaSessionEffectKind.DISCONNECT and self.enabled_sources:
            raise MediaHostTransactionError("disconnect cannot carry enabled sources")
        if self.kind is MediaSessionEffectKind.CONNECT and self.enabled_sources:
            raise MediaHostTransactionError("initial join cannot auto-publish media")

    def browser_payload(self) -> Mapping[str, object]:
        return {
            "transaction_id": self.transaction_id,
            "operation": self.kind.value,
            "credential_required": self.kind
            in {MediaSessionEffectKind.CONNECT, MediaSessionEffectKind.RECONNECT},
            "enabled_sources": [source.value for source in self.enabled_sources],
        }


@dataclass(frozen=True, slots=True)
class MediaSessionRecoveryStatus:
    """Secret-free reconciliation state after an uncertain session effect."""

    effect: MediaSessionProviderEffect
    provider_outcome_unknown: bool
    credential_handed_off: bool


@dataclass(frozen=True, slots=True)
class _CapturedSessionCall:
    effect: MediaSessionProviderEffect
    credential: JoinCredential | None = field(repr=False, default=None)


class _SecretCredentialPayload(dict[str, str]):
    """JSON-compatible one-shot credential mapping with redacted formatting."""

    def __repr__(self) -> str:
        return (
            "{'room_id': '<redacted>', 'participant_id': '<redacted>', "
            "'token': '<redacted>'}"
        )

    __str__ = __repr__


class _PreparedSessionEffect(Exception):
    def __init__(self, captured: _CapturedSessionCall) -> None:
        super().__init__("session provider effect prepared")
        self.captured = captured


class ClassroomMediaSessionTransactionPort:
    """Inner session port captured by the existing non-secret host port."""

    def __init__(self) -> None:
        self._lock = RLock()
        self._phase = "idle"
        self._transaction_id: str | None = None
        self._expected: _CapturedSessionCall | None = None
        self._consumed = False
        self._coordinator_bound = False

    def _bind_coordinator(self) -> None:
        with self._lock:
            if self._coordinator_bound:
                raise MediaHostTransactionError(
                    "media session transaction port already has a coordinator"
                )
            if self._phase != "idle":
                raise MediaHostTransactionError("media session transaction port is busy")
            self._coordinator_bound = True

    def connect(
        self,
        credential: JoinCredential,
        *,
        enabled_sources: tuple[MediaSource, ...],
    ) -> None:
        self._emit(
            _CapturedSessionCall(
                MediaSessionProviderEffect(
                    transaction_id=self._active_transaction_id(),
                    kind=MediaSessionEffectKind.CONNECT,
                    enabled_sources=enabled_sources,
                ),
                credential,
            )
        )

    def reconnect(
        self,
        credential: JoinCredential,
        *,
        enabled_sources: tuple[MediaSource, ...],
    ) -> None:
        self._emit(
            _CapturedSessionCall(
                MediaSessionProviderEffect(
                    transaction_id=self._active_transaction_id(),
                    kind=MediaSessionEffectKind.RECONNECT,
                    enabled_sources=enabled_sources,
                ),
                credential,
            )
        )

    def disconnect(self) -> None:
        self._emit(
            _CapturedSessionCall(
                MediaSessionProviderEffect(
                    transaction_id=self._active_transaction_id(),
                    kind=MediaSessionEffectKind.DISCONNECT,
                ),
                None,
            )
        )

    def set_local_source(self, source: MediaSource, enabled: bool) -> None:
        raise MediaHostTransactionError("local source effect belongs to media host port")

    def apply_moderation(self, commands: tuple[ModerationCommand, ...]) -> None:
        raise MediaHostTransactionError("moderation effect belongs to media host port")

    def recover_device(
        self,
        kind: MediaDeviceKind,
        device_id: str,
        *,
        republish_enabled: bool,
    ) -> None:
        raise MediaHostTransactionError("device recovery belongs to media host port")

    def _active_transaction_id(self) -> str:
        if self._transaction_id is None:
            raise MediaHostTransactionError(
                "session provider effect requires an active host transaction"
            )
        return self._transaction_id

    def _emit(self, captured: _CapturedSessionCall) -> None:
        with self._lock:
            if self._phase == "prepare":
                raise _PreparedSessionEffect(captured)
            if self._phase == "commit":
                if self._expected is None or captured != self._expected:
                    raise MediaHostTransactionError(
                        "committed session effect does not match prepared effect"
                    )
                if self._consumed:
                    raise MediaHostTransactionError(
                        "prepared session effect was consumed more than once"
                    )
                self._consumed = True
                return
            raise MediaHostTransactionError(
                "session provider effect requires prepare/commit host transaction"
            )

    def _prepare(
        self,
        transaction_id: str,
        replay: Callable[[], Any],
    ) -> tuple[_CapturedSessionCall | None, Any]:
        with self._lock:
            if self._phase != "idle":
                raise MediaHostTransactionError("media session transaction port is busy")
            self._phase = "prepare"
            self._transaction_id = transaction_id
            try:
                result = replay()
            except _PreparedSessionEffect as prepared:
                return prepared.captured, None
            finally:
                self._phase = "idle"
                self._transaction_id = None
            return None, result

    def _commit(
        self,
        captured: _CapturedSessionCall,
        replay: Callable[[], Any],
    ) -> Any:
        with self._lock:
            if self._phase != "idle":
                raise MediaHostTransactionError("media session transaction port is busy")
            self._phase = "commit"
            self._transaction_id = captured.effect.transaction_id
            self._expected = captured
            self._consumed = False
            try:
                result = replay()
                if not self._consumed:
                    raise MediaHostTransactionError(
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
    captured: _CapturedSessionCall
    base_revision: int
    replay: Callable[[], Any] = field(repr=False)
    credential_handed_off: bool = False


@dataclass(frozen=True, slots=True)
class _SessionRecovery:
    effect: MediaSessionProviderEffect
    provider_outcome_unknown: bool
    credential_handed_off: bool


SessionTransactionIdFactory = Callable[[], str]


class ClassroomMediaSessionHostTransactions:
    """Owner-thread coordinator for join/reconnect/disconnect provider effects."""

    def __init__(
        self,
        controller: ClassroomMediaController,
        outer_port: ClassroomMediaHostTransactionPort,
        session_port: ClassroomMediaSessionTransactionPort,
        host_transactions: ClassroomMediaHostTransactions,
        *,
        transaction_id_factory: SessionTransactionIdFactory | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        if not isinstance(controller, ClassroomMediaController):
            raise TypeError("controller must be ClassroomMediaController")
        if not isinstance(outer_port, ClassroomMediaHostTransactionPort):
            raise TypeError("outer port must be ClassroomMediaHostTransactionPort")
        if not isinstance(session_port, ClassroomMediaSessionTransactionPort):
            raise TypeError("session port must be ClassroomMediaSessionTransactionPort")
        if not isinstance(host_transactions, ClassroomMediaHostTransactions):
            raise TypeError("host transactions must be ClassroomMediaHostTransactions")
        if getattr(controller, "_media", None) is not outer_port:
            raise ValueError("controller must use the supplied outer media port")
        if getattr(outer_port, "_session_port", None) is not session_port:
            raise ValueError("outer media port must delegate to the supplied session port")
        if (
            getattr(host_transactions, "_controller", None) is not controller
            or getattr(host_transactions, "_port", None) is not outer_port
        ):
            raise ValueError(
                "session transactions must share the exact non-secret host owner"
            )
        if transaction_id_factory is not None and not callable(transaction_id_factory):
            raise TypeError("session transaction id factory must be callable")
        if clock is not None and not callable(clock):
            raise TypeError("session transaction clock must be callable")

        nonce = secrets.token_hex(8) if transaction_id_factory is None else ""
        self._controller = controller
        self._outer_port = outer_port
        self._session_port = session_port
        self._host_transactions = host_transactions
        self._activity_gate = host_transactions.activity_gate
        self._transaction_id_factory = transaction_id_factory
        self._now = clock or (lambda: datetime.now(timezone.utc))
        self._transaction_nonce = nonce
        self._transaction_counter = 0
        self._injected_transaction_ids: set[str] = set()
        self._lock = RLock()
        self._owner_thread_id = get_ident()
        self._pending: _PendingSessionTransaction | None = None
        self._recovery: _SessionRecovery | None = None
        session_port._bind_coordinator()

    @property
    def pending_effect(self) -> MediaSessionProviderEffect | None:
        with self._lock:
            return None if self._pending is None else self._pending.captured.effect

    @property
    def pending_browser_payload(self) -> Mapping[str, object] | None:
        with self._lock:
            return (
                None
                if self._pending is None
                else self._pending.captured.effect.browser_payload()
            )

    @property
    def recovery_status(self) -> MediaSessionRecoveryStatus | None:
        with self._lock:
            if self._recovery is None:
                return None
            return MediaSessionRecoveryStatus(
                effect=self._recovery.effect,
                provider_outcome_unknown=self._recovery.provider_outcome_unknown,
                credential_handed_off=self._recovery.credential_handed_off,
            )

    def __repr__(self) -> str:
        with self._lock:
            if self._recovery is not None:
                state = "recovery"
            elif self._pending is not None:
                state = "pending"
            else:
                state = "idle"
        return f"ClassroomMediaSessionHostTransactions(state={state!r}, credential=<redacted>)"

    def _assert_owner_thread(self) -> None:
        if get_ident() != self._owner_thread_id:
            raise MediaHostTransactionError(
                "media session transaction mutation requires the owner thread"
            )

    def _transaction_id(self) -> str:
        if self._transaction_id_factory is None:
            if self._transaction_counter >= (1 << 64) - 1:
                raise MediaHostTransactionError(
                    "media session transaction identity space is exhausted"
                )
            self._transaction_counter += 1
            return (
                "session-"
                + self._transaction_nonce
                + f"{self._transaction_counter:016x}"
            )
        value = self._transaction_id_factory()
        if (
            type(value) is not str
            or _SESSION_TRANSACTION_RE.fullmatch(value) is None
        ):
            raise MediaHostTransactionError(
                "session transaction id factory returned invalid identity"
            )
        if value in self._injected_transaction_ids:
            raise MediaHostTransactionError(
                "session transaction id factory reused an identity"
            )
        self._injected_transaction_ids.add(value)
        return value

    def _release_unexposed_transaction_id(self, transaction_id: str) -> None:
        if self._transaction_id_factory is not None:
            self._injected_transaction_ids.discard(transaction_id)

    def _prepare(self, replay: Callable[[], Any]) -> MediaSessionProviderEffect | None:
        self._assert_owner_thread()
        with self._lock:
            if self._pending is not None:
                raise MediaHostTransactionError(
                    "a media session provider effect is already pending"
                )
            if self._recovery is not None:
                raise MediaHostRecoveryRequired(
                    "media session provider state requires recovery"
                )
            self._activity_gate.claim(self)
            transaction_id: str | None = None
            try:
                transaction_id = self._transaction_id()
                base_revision = self._controller.state.revision
                captured, _result = self._session_port._prepare(transaction_id, replay)
                if captured is None:
                    self._release_unexposed_transaction_id(transaction_id)
                    self._activity_gate.release(self)
                    return None
                self._pending = _PendingSessionTransaction(
                    captured=captured,
                    base_revision=base_revision,
                    replay=replay,
                )
                return captured.effect
            except Exception:
                if transaction_id is not None:
                    self._release_unexposed_transaction_id(transaction_id)
                self._activity_gate.release(self)
                raise

    def prepare_join(
        self,
        credential: JoinCredential,
        *,
        now: datetime,
    ) -> MediaSessionProviderEffect | None:
        return self._prepare(lambda: self._controller.join(credential, now=now))

    def prepare_reconnect(
        self,
        credential: JoinCredential,
        *,
        now: datetime,
    ) -> MediaSessionProviderEffect | None:
        return self._prepare(lambda: self._controller.reconnect(credential, now=now))

    def prepare_disconnect(self) -> MediaSessionProviderEffect | None:
        return self._prepare(self._controller.leave)

    def take_credential(self, transaction_id: str) -> Mapping[str, str]:
        """Return the exact short-lived credential once, only to the trusted host."""

        self._assert_owner_thread()
        with self._lock:
            pending = self._require_pending(transaction_id)
            if pending.captured.effect.kind not in {
                MediaSessionEffectKind.CONNECT,
                MediaSessionEffectKind.RECONNECT,
            }:
                raise MediaHostTransactionError(
                    "disconnect session transaction has no credential"
                )
            if pending.credential_handed_off:
                raise MediaHostTransactionError(
                    "media session credential was already handed off"
                )
            credential = pending.captured.credential
            if credential is None:
                raise MediaHostTransactionError(
                    "media session credential is unavailable"
                )
            try:
                current = self._now()
            except Exception:
                self._pending = None
                self._activity_gate.release(self)
                raise MediaHostTransactionError(
                    "media session credential clock failed"
                ) from None
            try:
                credential.assert_usable(current)
            except Exception:
                # No secret has crossed the provider boundary yet. Drop the
                # private credential and do not retain its traceback/cause.
                self._pending = None
                self._activity_gate.release(self)
                raise MediaHostTransactionError(
                    "media session credential expired before browser handoff"
                ) from None
            self._pending = replace(pending, credential_handed_off=True)
            return _SecretCredentialPayload(
                room_id=credential.room_id,
                participant_id=credential.participant_id,
                token=credential.token,
            )

    def provider_not_started(self, transaction_id: str) -> None:
        """Discard only before a secret has crossed into the browser provider host."""

        self._assert_owner_thread()
        with self._lock:
            pending = self._require_pending(transaction_id)
            if pending.credential_handed_off:
                self._enter_recovery(
                    pending,
                    provider_outcome_unknown=True,
                )
                raise MediaHostRecoveryRequired(
                    "media session credential already crossed the provider boundary"
                )
            self._pending = None
            self._activity_gate.release(self)

    def provider_connection_failed_clean(
        self,
        transaction_id: str,
        provider_snapshot: Mapping[str, object],
    ) -> None:
        """Retire failed connect/reconnect only after exact clean teardown proof."""

        self._assert_owner_thread()
        with self._lock:
            pending = self._require_pending(transaction_id)
            if pending.captured.effect.kind not in {
                MediaSessionEffectKind.CONNECT,
                MediaSessionEffectKind.RECONNECT,
            }:
                raise MediaHostTransactionError(
                    "verified clean failure applies only to connect or reconnect"
                )
            if not pending.credential_handed_off:
                raise MediaHostTransactionError(
                    "verified clean failure requires credential handoff"
                )
            try:
                self._validate_clean_disconnected_snapshot(provider_snapshot)
            except Exception:
                self._enter_recovery(pending, provider_outcome_unknown=True)
                raise MediaHostRecoveryRequired(
                    "media session adapter has not proven clean teardown"
                ) from None
            self._pending = None
            self._activity_gate.release(self)

    def provider_failed(self, transaction_id: str) -> None:
        self.provider_outcome_unknown(transaction_id)

    def provider_outcome_unknown(self, transaction_id: str) -> None:
        self._assert_owner_thread()
        with self._lock:
            pending = self._require_pending(transaction_id)
            self._enter_recovery(pending, provider_outcome_unknown=True)

    def acknowledge_provider_success(
        self,
        transaction_id: str,
        provider_snapshot: Mapping[str, object],
    ) -> Any:
        """Validate exact provider state, then replay canonical commit once."""

        self._assert_owner_thread()
        with self._lock:
            pending = self._require_pending(transaction_id)
            effect = pending.captured.effect
            if (
                effect.kind
                in {MediaSessionEffectKind.CONNECT, MediaSessionEffectKind.RECONNECT}
                and not pending.credential_handed_off
            ):
                self._enter_recovery(pending, provider_outcome_unknown=True)
                raise MediaHostRecoveryRequired(
                    "provider success arrived before credential handoff"
                )
            try:
                self._validate_provider_snapshot(pending, provider_snapshot)
            except Exception:
                self._enter_recovery(pending, provider_outcome_unknown=True)
                raise MediaHostRecoveryRequired(
                    "media session provider result requires recovery"
                ) from None
            if self._controller.state.revision != pending.base_revision:
                self._enter_recovery(pending, provider_outcome_unknown=False)
                raise MediaHostRecoveryRequired(
                    "canonical media state changed before session acknowledgement"
                )
            try:
                result = self._session_port._commit(
                    pending.captured,
                    pending.replay,
                )
            except Exception:
                self._enter_recovery(pending, provider_outcome_unknown=False)
                raise MediaHostRecoveryRequired(
                    "provider session succeeded but canonical commit requires recovery"
                ) from None
            self._pending = None
            self._activity_gate.release(self)
            return result

    def resolve_recovery(self, transaction_id: str) -> None:
        self._assert_owner_thread()
        with self._lock:
            if (
                self._recovery is None
                or self._recovery.effect.transaction_id != transaction_id
            ):
                raise MediaHostTransactionError(
                    "media session recovery transaction is unknown"
                )
            self._recovery = None
            self._activity_gate.release(self)

    def _enter_recovery(
        self,
        pending: _PendingSessionTransaction,
        *,
        provider_outcome_unknown: bool,
    ) -> None:
        self._pending = None
        self._recovery = _SessionRecovery(
            effect=pending.captured.effect,
            provider_outcome_unknown=provider_outcome_unknown,
            credential_handed_off=pending.credential_handed_off,
        )

    def _validate_clean_disconnected_snapshot(
        self,
        value: Mapping[str, object],
    ) -> None:
        if type(value) is not dict or set(value) != _PROVIDER_SNAPSHOT_KEYS:
            raise MediaHostTransactionError("media session provider snapshot is invalid")
        expected = {
            "connected": False,
            "cleanup_required": False,
            "room_id": None,
            "participant_id": None,
            "microphone_enabled": False,
            "camera_enabled": False,
            "screen_share_enabled": False,
        }
        if value != expected:
            raise MediaHostTransactionError(
                "media session provider snapshot does not confirm clean teardown"
            )

    def _validate_provider_snapshot(
        self,
        pending: _PendingSessionTransaction,
        value: Mapping[str, object],
    ) -> None:
        if type(value) is not dict or set(value) != _PROVIDER_SNAPSHOT_KEYS:
            raise MediaHostTransactionError("media session provider snapshot is invalid")
        for key in (
            "connected",
            "cleanup_required",
            "microphone_enabled",
            "camera_enabled",
            "screen_share_enabled",
        ):
            if type(value[key]) is not bool:
                raise MediaHostTransactionError(
                    "media session provider snapshot flags are invalid"
                )

        effect = pending.captured.effect
        credential = pending.captured.credential
        if effect.kind is MediaSessionEffectKind.DISCONNECT:
            self._validate_clean_disconnected_snapshot(value)
            return

        if credential is None:
            raise MediaHostTransactionError("media session credential is unavailable")
        enabled = set(effect.enabled_sources)
        expected = {
            "connected": True,
            "cleanup_required": False,
            "room_id": credential.room_id,
            "participant_id": credential.participant_id,
            "microphone_enabled": MediaSource.MICROPHONE in enabled,
            "camera_enabled": MediaSource.CAMERA in enabled,
            "screen_share_enabled": MediaSource.SCREEN_SHARE in enabled,
        }
        if value != expected:
            raise MediaHostTransactionError(
                "media session provider snapshot does not match prepared effect"
            )

    def _require_pending(self, transaction_id: str) -> _PendingSessionTransaction:
        if (
            type(transaction_id) is not str
            or _SESSION_TRANSACTION_RE.fullmatch(transaction_id) is None
        ):
            raise MediaHostTransactionError("media session transaction id is invalid")
        if (
            self._pending is None
            or self._pending.captured.effect.transaction_id != transaction_id
        ):
            raise MediaHostTransactionError(
                "media session transaction is unknown or already consumed"
            )
        return self._pending


__all__ = [
    "ClassroomMediaSessionHostTransactions",
    "ClassroomMediaSessionTransactionPort",
    "MediaSessionEffectKind",
    "MediaSessionProviderEffect",
    "MediaSessionRecoveryStatus",
]
