from __future__ import annotations

"""Shipping host binder for asynchronous classroom LiveKit provider execution.

This module composes the exact transaction authorities supplied by the classroom
media foundation stack:

* ClassroomMediaSessionHostTransactions: secret connect/reconnect/disconnect lifecycle;
* ClassroomMediaHostTransactions: non-secret source/moderation/device effects;
* ClassroomMediaProviderExecutionArbiter: one shared provider-execution owner.

It deliberately does not execute JavaScript itself. The Windows/WebView host asks
the binder for one BrowserMediaInvocation, dispatches that invocation asynchronously
to the packaged AccessibleChessLiveKitMedia adapter, and then reports the exact
provider outcome back to this binder on the owner thread. No host thread blocks on a
browser promise and no second media provider mutation can overlap the first.

The binder retains only non-secret transaction metadata. Secret join credentials
exist only in the one invocation object returned immediately before browser
dispatch; its diagnostic representation intentionally omits arguments.
"""

from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
from datetime import datetime
from threading import RLock, get_ident
from typing import Any

from .classroom_media_host_transactions import (
    ClassroomMediaHostTransactions,
    MediaHostRecoveryRequired,
    MediaProviderEffect,
)
from .classroom_media_provider_execution import (
    ClassroomMediaProviderExecutionArbiter,
    MediaProviderExecutionLease,
    MediaProviderExecutionOwner,
    MediaProviderExecutionRecoveryStatus,
)
from .classroom_media_session_transactions import (
    ClassroomMediaSessionHostTransactions,
    MediaSessionEffectKind,
    MediaSessionProviderEffect,
)
from .classroom_realtime_media import (
    JoinCredential,
    MediaDeviceKind,
    MediaSource,
)


class ClassroomMediaBrowserBinderError(RuntimeError):
    """The trusted host violated the async browser/provider binder contract."""


class ClassroomMediaBrowserRecoveryRequired(ClassroomMediaBrowserBinderError):
    """Provider/canonical media state must be reconciled before further work."""


@dataclass(frozen=True, slots=True)
class PreparedMediaProviderTransaction:
    """Non-secret handle returned after canonical authorization/prepare."""

    lease_id: str
    owner: MediaProviderExecutionOwner
    transaction_id: str


@dataclass(frozen=True, slots=True)
class MediaProviderStepResult:
    """Result of one successful browser provider acknowledgement."""

    completed: bool
    result: Any | None = None


class BrowserMediaInvocation:
    """One exact asynchronous call to the packaged browser LiveKit adapter.

    Arguments are intentionally excluded from repr/str and are not a dataclass
    field, preventing accidental dataclasses.asdict() snapshots of join tokens.
    The host must pass arguments directly to the adapter and discard the object
    after reporting the exact outcome.
    """

    __slots__ = (
        "_lease_id",
        "_owner",
        "_transaction_id",
        "_method",
        "_chunk_index",
        "_arguments",
    )

    def __init__(
        self,
        *,
        lease_id: str,
        owner: MediaProviderExecutionOwner,
        transaction_id: str,
        method: str,
        chunk_index: int,
        arguments: tuple[object, ...],
    ) -> None:
        self._lease_id = lease_id
        self._owner = owner
        self._transaction_id = transaction_id
        self._method = method
        self._chunk_index = chunk_index
        self._arguments = arguments

    @property
    def lease_id(self) -> str:
        return self._lease_id

    @property
    def owner(self) -> MediaProviderExecutionOwner:
        return self._owner

    @property
    def transaction_id(self) -> str:
        return self._transaction_id

    @property
    def method(self) -> str:
        return self._method

    @property
    def chunk_index(self) -> int:
        return self._chunk_index

    @property
    def arguments(self) -> tuple[object, ...]:
        return self._arguments

    def __repr__(self) -> str:
        return (
            "BrowserMediaInvocation("
            f"lease_id={self._lease_id!r}, "
            f"owner={self._owner!r}, "
            f"transaction_id={self._transaction_id!r}, "
            f"method={self._method!r}, "
            f"chunk_index={self._chunk_index!r}, "
            "arguments=<redacted>)"
        )

    __str__ = __repr__


class _FrozenProviderMapping(dict):
    """JSON-compatible non-secret provider mapping frozen after authorization."""

    @staticmethod
    def _immutable(*_args, **_kwargs):
        raise TypeError("media provider invocation is immutable")

    __setitem__ = _immutable
    __delitem__ = _immutable
    clear = _immutable
    pop = _immutable
    popitem = _immutable
    setdefault = _immutable
    update = _immutable
    __ior__ = _immutable


@dataclass(frozen=True, slots=True)
class _ActiveTransaction:
    prepared: PreparedMediaProviderTransaction
    invocation_claimed: bool = False
    provider_call_dispatched: bool = False
    chunk_index: int = 0


class ClassroomMediaBrowserBinder:
    """Compose both media transaction owners behind one nonblocking provider gate."""

    def __init__(
        self,
        *,
        session: ClassroomMediaSessionHostTransactions,
        effects: ClassroomMediaHostTransactions,
        arbiter: ClassroomMediaProviderExecutionArbiter,
    ) -> None:
        if not isinstance(session, ClassroomMediaSessionHostTransactions):
            raise TypeError(
                "session coordinator must be ClassroomMediaSessionHostTransactions"
            )
        if not isinstance(effects, ClassroomMediaHostTransactions):
            raise TypeError("effect coordinator must be ClassroomMediaHostTransactions")
        if not isinstance(arbiter, ClassroomMediaProviderExecutionArbiter):
            raise TypeError(
                "provider execution arbiter must be ClassroomMediaProviderExecutionArbiter"
            )

        session_controller = getattr(session, "_controller", None)
        effect_controller = getattr(effects, "_controller", None)
        if session_controller is None or session_controller is not effect_controller:
            raise ValueError(
                "session and effect coordinators must share one canonical media controller"
            )
        session_port = getattr(session, "_session_port", None)
        outer_port = getattr(session, "_outer_port", None)
        effect_port = getattr(effects, "_port", None)
        if (
            getattr(session, "_host_transactions", None) is not effects
            or outer_port is not effect_port
            or getattr(effect_port, "_session_port", None) is not session_port
        ):
            raise ValueError(
                "session transactions must share the exact effect transaction owner"
            )
        if arbiter.active_lease is not None or arbiter.recovery_status is not None:
            raise ValueError("provider execution arbiter must be idle when binder is created")

        self._session = session
        self._effects = effects
        self._arbiter = arbiter
        self._owner_thread_id = get_ident()
        self._lock = RLock()
        self._active: _ActiveTransaction | None = None

    @property
    def active_transaction(self) -> PreparedMediaProviderTransaction | None:
        with self._lock:
            return None if self._active is None else self._active.prepared

    @property
    def recovery_status(self) -> MediaProviderExecutionRecoveryStatus | None:
        return self._arbiter.recovery_status

    def prepare_join(
        self,
        credential: JoinCredential,
        *,
        now: datetime,
    ) -> PreparedMediaProviderTransaction | None:
        return self._begin(
            MediaProviderExecutionOwner.SESSION,
            lambda: self._session.prepare_join(credential, now=now),
        )

    def prepare_reconnect(
        self,
        credential: JoinCredential,
        *,
        now: datetime,
    ) -> PreparedMediaProviderTransaction | None:
        return self._begin(
            MediaProviderExecutionOwner.SESSION,
            lambda: self._session.prepare_reconnect(credential, now=now),
        )

    def prepare_disconnect(self) -> PreparedMediaProviderTransaction | None:
        return self._begin(
            MediaProviderExecutionOwner.SESSION,
            self._session.prepare_disconnect,
        )

    def prepare_leave(self) -> PreparedMediaProviderTransaction | None:
        """Compatibility alias for the canonical disconnect preparation."""

        return self.prepare_disconnect()

    def prepare_local_source(
        self,
        source: MediaSource | str,
        enabled: bool,
    ) -> PreparedMediaProviderTransaction | None:
        return self._begin(
            MediaProviderExecutionOwner.EFFECT,
            lambda: self._effects.prepare_local_source(source, enabled),
        )

    def prepare_publish_permission(
        self,
        *,
        actor_id: str,
        target_id: str,
        source: MediaSource | str,
        allowed: bool,
        operation_id: str,
    ) -> PreparedMediaProviderTransaction | None:
        return self._begin(
            MediaProviderExecutionOwner.EFFECT,
            lambda: self._effects.prepare_publish_permission(
                actor_id=actor_id,
                target_id=target_id,
                source=source,
                allowed=allowed,
                operation_id=operation_id,
            ),
        )

    def prepare_soft_mute(
        self,
        *,
        actor_id: str,
        target_id: str,
        muted: bool,
        operation_id: str,
    ) -> PreparedMediaProviderTransaction | None:
        return self._begin(
            MediaProviderExecutionOwner.EFFECT,
            lambda: self._effects.prepare_soft_mute(
                actor_id=actor_id,
                target_id=target_id,
                muted=muted,
                operation_id=operation_id,
            ),
        )

    def prepare_all_students_publish_permission(
        self,
        *,
        actor_id: str,
        source: MediaSource | str,
        allowed: bool,
        operation_id: str,
    ) -> PreparedMediaProviderTransaction | None:
        return self._begin(
            MediaProviderExecutionOwner.EFFECT,
            lambda: self._effects.prepare_all_students_publish_permission(
                actor_id=actor_id,
                source=source,
                allowed=allowed,
                operation_id=operation_id,
            ),
        )

    def prepare_all_students_soft_mute(
        self,
        *,
        actor_id: str,
        muted: bool,
        operation_id: str,
    ) -> PreparedMediaProviderTransaction | None:
        return self._begin(
            MediaProviderExecutionOwner.EFFECT,
            lambda: self._effects.prepare_all_students_soft_mute(
                actor_id=actor_id,
                muted=muted,
                operation_id=operation_id,
            ),
        )

    def prepare_remove_participant(
        self,
        *,
        actor_id: str,
        target_id: str,
        block: bool,
        operation_id: str,
    ) -> PreparedMediaProviderTransaction | None:
        return self._begin(
            MediaProviderExecutionOwner.EFFECT,
            lambda: self._effects.prepare_remove_participant(
                actor_id=actor_id,
                target_id=target_id,
                block=block,
                operation_id=operation_id,
            ),
        )

    def prepare_device_recovery(
        self,
        kind: MediaDeviceKind | str,
        device_id: str,
    ) -> PreparedMediaProviderTransaction | None:
        return self._begin(
            MediaProviderExecutionOwner.EFFECT,
            lambda: self._effects.prepare_device_recovery(kind, device_id),
        )

    def claim_browser_invocation(
        self,
        lease_id: str,
    ) -> BrowserMediaInvocation:
        """Claim exactly one provider call immediately before browser dispatch.

        For connect/reconnect, taking the one-shot credential is itself the
        provider boundary: after the secret leaves the coordinator, a stale
        browser callback could use it even if the host later reports that normal
        dispatch never began. The shared arbiter is therefore crossed before the
        credential-bearing invocation is returned.
        """

        self._assert_owner_thread()
        with self._lock:
            active = self._require_active(lease_id)
            if active.invocation_claimed:
                raise ClassroomMediaBrowserBinderError(
                    "browser media invocation was already claimed"
                )
            prepared = active.prepared
            if prepared.owner is MediaProviderExecutionOwner.SESSION:
                payload = self._session.pending_browser_payload
                if (
                    payload is None
                    or payload.get("transaction_id") != prepared.transaction_id
                ):
                    raise ClassroomMediaBrowserBinderError(
                        "session coordinator has no matching browser payload"
                    )
                credential: Mapping[str, str] | None = None
                if payload.get("credential_required") is True:
                    try:
                        credential = self._session.take_credential(
                            prepared.transaction_id
                        )
                    except Exception:
                        # Expiry at the one-shot disclosure boundary retires the
                        # coordinator transaction before any secret is exposed.
                        if self._session.pending_effect is None:
                            self._arbiter.release_without_provider(
                                prepared.lease_id
                            )
                            self._active = None
                        raise
                    lease = self._arbiter.active_lease
                    if (
                        lease is None
                        or lease.lease_id != prepared.lease_id
                    ):
                        raise ClassroomMediaBrowserBinderError(
                            "shared provider execution lease is inconsistent"
                        )
                    if not lease.provider_boundary_crossed:
                        self._arbiter.mark_provider_boundary_crossed(
                            prepared.lease_id
                        )
                invocation = self._session_invocation(
                    prepared,
                    payload,
                    credential,
                )
            else:
                payload = self._effects.pending_browser_payload
                if payload is None:
                    raise ClassroomMediaBrowserBinderError(
                        "effect coordinator has no pending browser payload"
                    )
                invocation = self._effect_invocation(prepared, payload)

            self._active = replace(
                active,
                invocation_claimed=True,
                provider_call_dispatched=False,
                chunk_index=invocation.chunk_index,
            )
            return invocation

    def mark_provider_started(self, lease_id: str) -> None:
        """Cross the provider boundary immediately before dispatching the JS call."""

        self._assert_owner_thread()
        with self._lock:
            active = self._require_active(lease_id)
            if not active.invocation_claimed:
                raise ClassroomMediaBrowserBinderError(
                    "provider call cannot start before invocation claim"
                )
            if active.provider_call_dispatched:
                raise ClassroomMediaBrowserBinderError(
                    "provider call was already marked started"
                )
            lease = self._arbiter.active_lease
            if lease is None or lease.lease_id != active.prepared.lease_id:
                raise ClassroomMediaBrowserBinderError(
                    "shared provider execution lease is inconsistent"
                )
            if not lease.provider_boundary_crossed:
                self._arbiter.mark_provider_boundary_crossed(lease_id)
            self._active = replace(active, provider_call_dispatched=True)

    def provider_not_started(self, lease_id: str) -> None:
        """Retire a claimed/unclaimed call only when browser dispatch never occurred."""

        self._assert_owner_thread()
        with self._lock:
            active = self._require_active(lease_id)
            if active.provider_call_dispatched:
                raise ClassroomMediaBrowserBinderError(
                    "provider call was already dispatched"
                )
            prepared = active.prepared
            try:
                if prepared.owner is MediaProviderExecutionOwner.SESSION:
                    self._session.provider_not_started(prepared.transaction_id)
                else:
                    self._effects.provider_not_started(prepared.transaction_id)
            except MediaHostRecoveryRequired as exc:
                self._latch_coordinator_recovery(active)
                raise ClassroomMediaBrowserRecoveryRequired(str(exc)) from exc

            self._arbiter.release_without_provider(prepared.lease_id)
            self._active = None

    def provider_failed(self, lease_id: str) -> MediaProviderExecutionRecoveryStatus:
        """Record a dispatched failure whose partial provider outcome is unsafe."""

        self._assert_owner_thread()
        with self._lock:
            active = self._require_dispatched(lease_id)
            prepared = active.prepared
            if prepared.owner is MediaProviderExecutionOwner.SESSION:
                self._session.provider_failed(prepared.transaction_id)
            else:
                self._effects.provider_failed(prepared.transaction_id)
            status = self._latch_coordinator_recovery(active)
            return status

    def session_connection_failed_clean(
        self,
        lease_id: str,
        provider_snapshot: Mapping[str, object],
    ) -> None:
        """Release failed connect/reconnect only after exact clean snapshot proof."""

        self._assert_owner_thread()
        with self._lock:
            active = self._require_dispatched(lease_id)
            if active.prepared.owner is not MediaProviderExecutionOwner.SESSION:
                raise ClassroomMediaBrowserBinderError(
                    "clean connection failure applies only to session transactions"
                )
            self._session.provider_connection_failed_clean(
                active.prepared.transaction_id,
                provider_snapshot,
            )
            self._arbiter.release_after_verified_clean_failure(
                active.prepared.lease_id
            )
            self._active = None

    def acknowledge_provider_success(
        self,
        lease_id: str,
        *,
        provider_snapshot: Mapping[str, object] | None = None,
    ) -> MediaProviderStepResult:
        """Commit exact provider success; retain the lease for later moderation chunks."""

        self._assert_owner_thread()
        with self._lock:
            active = self._require_dispatched(lease_id)
            prepared = active.prepared
            if prepared.owner is MediaProviderExecutionOwner.SESSION:
                if provider_snapshot is None:
                    raise ClassroomMediaBrowserBinderError(
                        "session provider success requires an exact provider snapshot"
                    )
                try:
                    result = self._session.acknowledge_provider_success(
                        prepared.transaction_id,
                        provider_snapshot,
                    )
                except MediaHostRecoveryRequired as exc:
                    self._latch_coordinator_recovery(active)
                    raise ClassroomMediaBrowserRecoveryRequired(str(exc)) from exc
                self._arbiter.complete(prepared.lease_id)
                self._active = None
                return MediaProviderStepResult(completed=True, result=result)

            if provider_snapshot is not None:
                raise ClassroomMediaBrowserBinderError(
                    "effect success does not accept provider snapshot authority"
                )
            try:
                result = self._effects.acknowledge_provider_chunk_success(
                    prepared.transaction_id,
                    active.chunk_index,
                )
            except MediaHostRecoveryRequired as exc:
                self._latch_coordinator_recovery(active)
                raise ClassroomMediaBrowserRecoveryRequired(str(exc)) from exc

            if self._effects.pending_effect is not None:
                self._active = replace(
                    active,
                    invocation_claimed=False,
                    provider_call_dispatched=False,
                    chunk_index=active.chunk_index + 1,
                )
                return MediaProviderStepResult(completed=False, result=None)

            self._arbiter.complete(prepared.lease_id)
            self._active = None
            return MediaProviderStepResult(completed=True, result=result)

    def resolve_recovery(self, lease_id: str) -> None:
        """Release both coordinator and shared provider recovery in safe order."""

        self._assert_owner_thread()
        with self._lock:
            if self._active is not None:
                raise ClassroomMediaBrowserBinderError(
                    "cannot resolve recovery while provider execution is active"
                )
            recovery = self._arbiter.recovery_status
            if recovery is None or recovery.lease.lease_id != lease_id:
                raise ClassroomMediaBrowserBinderError(
                    "browser media recovery lease is unknown"
                )
            transaction_id = recovery.lease.transaction_id
            if transaction_id is None:
                raise ClassroomMediaBrowserBinderError(
                    "browser media recovery has no coordinator transaction"
                )
            if recovery.lease.owner is MediaProviderExecutionOwner.SESSION:
                self._session.resolve_recovery(transaction_id)
            else:
                self._effects.resolve_recovery(transaction_id)
            self._arbiter.resolve_recovery(lease_id)

    def _begin(
        self,
        owner: MediaProviderExecutionOwner,
        prepare: Callable[[], MediaSessionProviderEffect | MediaProviderEffect | None],
    ) -> PreparedMediaProviderTransaction | None:
        self._assert_owner_thread()
        with self._lock:
            if self._active is not None:
                raise ClassroomMediaBrowserBinderError(
                    "browser media transaction is already active"
                )
            lease = self._arbiter.begin(owner)
            try:
                effect = prepare()
            except Exception:
                self._arbiter.release_without_provider(lease.lease_id)
                raise
            if effect is None:
                self._arbiter.release_without_provider(lease.lease_id)
                return None
            prepared = PreparedMediaProviderTransaction(
                lease_id=lease.lease_id,
                owner=owner,
                transaction_id=effect.transaction_id,
            )
            try:
                self._arbiter.bind_transaction(
                    prepared.lease_id,
                    prepared.transaction_id,
                )
            except Exception:
                # No browser payload has been claimed and no provider call can
                # have started; retire the coordinator transaction before
                # releasing the shared execution gate.
                if owner is MediaProviderExecutionOwner.SESSION:
                    self._session.provider_not_started(prepared.transaction_id)
                else:
                    self._effects.provider_not_started(prepared.transaction_id)
                self._arbiter.release_without_provider(prepared.lease_id)
                raise
            self._active = _ActiveTransaction(prepared=prepared)
            return prepared

    def _latch_coordinator_recovery(
        self,
        active: _ActiveTransaction,
    ) -> MediaProviderExecutionRecoveryStatus:
        prepared = active.prepared
        if prepared.owner is MediaProviderExecutionOwner.SESSION:
            coordinator_status = self._session.recovery_status
        else:
            coordinator_status = self._effects.recovery_status
        if coordinator_status is None:
            raise ClassroomMediaBrowserBinderError(
                "coordinator reported recovery without recovery metadata"
            )
        status = self._arbiter.require_recovery(
            prepared.lease_id,
            provider_outcome_unknown=coordinator_status.provider_outcome_unknown,
        )
        self._active = None
        return status

    def _require_active(self, lease_id: str) -> _ActiveTransaction:
        if type(lease_id) is not str:
            raise ClassroomMediaBrowserBinderError(
                "browser media lease id is invalid"
            )
        if (
            self._active is None
            or self._active.prepared.lease_id != lease_id
        ):
            raise ClassroomMediaBrowserBinderError(
                "browser media transaction is unknown or already consumed"
            )
        return self._active

    def _require_dispatched(self, lease_id: str) -> _ActiveTransaction:
        active = self._require_active(lease_id)
        if not active.invocation_claimed or not active.provider_call_dispatched:
            raise ClassroomMediaBrowserBinderError(
                "provider outcome cannot be recorded before exact dispatch"
            )
        return active

    def _assert_owner_thread(self) -> None:
        if get_ident() != self._owner_thread_id:
            raise ClassroomMediaBrowserBinderError(
                "browser media binder mutation requires the owner thread"
            )

    @staticmethod
    def _session_invocation(
        prepared: PreparedMediaProviderTransaction,
        payload: Mapping[str, object],
        credential: Mapping[str, str] | None,
    ) -> BrowserMediaInvocation:
        expected_fields = {
            "transaction_id",
            "operation",
            "credential_required",
            "enabled_sources",
        }
        if (
            set(payload) != expected_fields
            or payload.get("transaction_id") != prepared.transaction_id
        ):
            raise ClassroomMediaBrowserBinderError(
                "session browser payload transaction is inconsistent"
            )
        operation = payload.get("operation")
        enabled_sources = payload.get("enabled_sources")
        if type(enabled_sources) is not list:
            raise ClassroomMediaBrowserBinderError(
                "session browser enabled sources are invalid"
            )
        if operation in {
            MediaSessionEffectKind.CONNECT.value,
            MediaSessionEffectKind.RECONNECT.value,
        }:
            if (
                payload.get("credential_required") is not True
                or not isinstance(credential, Mapping)
            ):
                raise ClassroomMediaBrowserBinderError(
                    "session browser credential shape is inconsistent"
                )
            method = (
                "connect"
                if operation == MediaSessionEffectKind.CONNECT.value
                else "reconnect"
            )
            arguments = (credential, tuple(enabled_sources))
        elif operation == MediaSessionEffectKind.DISCONNECT.value:
            if (
                payload.get("credential_required") is not False
                or credential is not None
                or enabled_sources
            ):
                raise ClassroomMediaBrowserBinderError(
                    "disconnect browser payload shape is inconsistent"
                )
            method = "disconnect"
            arguments = ()
        else:
            raise ClassroomMediaBrowserBinderError(
                "session browser operation is unsupported"
            )
        return BrowserMediaInvocation(
            lease_id=prepared.lease_id,
            owner=prepared.owner,
            transaction_id=prepared.transaction_id,
            method=method,
            chunk_index=0,
            arguments=arguments,
        )

    @staticmethod
    def _effect_invocation(
        prepared: PreparedMediaProviderTransaction,
        payload: Mapping[str, object],
    ) -> BrowserMediaInvocation:
        if payload.get("transaction_id") != prepared.transaction_id:
            raise ClassroomMediaBrowserBinderError(
                "effect browser payload transaction is inconsistent"
            )
        operation = payload.get("operation")
        chunk_index = payload.get("chunk_index", 0)
        if type(chunk_index) is not int or chunk_index < 0:
            raise ClassroomMediaBrowserBinderError(
                "effect browser payload chunk index is invalid"
            )
        if operation == "set_local_source":
            method = "setLocalSource"
            arguments = (payload.get("source"), payload.get("enabled"))
        elif operation == "apply_moderation":
            raw_commands = payload.get("commands")
            if type(raw_commands) is not list:
                raise ClassroomMediaBrowserBinderError(
                    "moderation browser payload commands are invalid"
                )
            commands = tuple(
                _FrozenProviderMapping(command)
                for command in raw_commands
                if type(command) is dict
            )
            if len(commands) != len(raw_commands):
                raise ClassroomMediaBrowserBinderError(
                    "moderation browser payload command is invalid"
                )
            arguments = (commands,)
            method = "applyModeration"
        elif operation == "recover_device":
            method = "recoverDevice"
            arguments = (
                payload.get("kind"),
                payload.get("device_id"),
                payload.get("republish_enabled"),
            )
        else:
            raise ClassroomMediaBrowserBinderError(
                "effect browser operation is unsupported"
            )
        return BrowserMediaInvocation(
            lease_id=prepared.lease_id,
            owner=prepared.owner,
            transaction_id=prepared.transaction_id,
            method=method,
            chunk_index=chunk_index,
            arguments=arguments,
        )


__all__ = [
    "BrowserMediaInvocation",
    "ClassroomMediaBrowserBinder",
    "ClassroomMediaBrowserBinderError",
    "ClassroomMediaBrowserRecoveryRequired",
    "MediaProviderStepResult",
    "PreparedMediaProviderTransaction",
]
