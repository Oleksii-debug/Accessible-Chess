from __future__ import annotations

"""Shipping binder for serialized desktop/browser classroom media provider work.

This module composes existing authorities only:

* ClassroomMediaHostTransactions owns non-secret media-effect preparation/commit.
* ClassroomMediaSessionHostTransactions owns secret-bearing session preparation/commit.
* ClassroomMediaProviderExecutionArbiter owns the one process-local provider lease.

The binder acquires the global lease before either coordinator prepares work and
holds it through the exact provider/canonical completion or recovery boundary.
It owns no chess rules, roster/lesson policy, media authorization, provider SDK,
credential issuance, or browser presentation semantics.
"""

from collections.abc import Callable, Mapping
from datetime import datetime
from typing import Any

from .classroom_media_host_transactions import (
    ClassroomMediaHostTransactions,
    MediaHostRecoveryRequired,
    MediaProviderEffect,
)
from .classroom_media_provider_execution import (
    ClassroomMediaProviderExecutionArbiter,
    MediaProviderExecutionError,
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


class _FrozenSecretCredential(dict[str, str]):
    """JSON-compatible credential copy that cannot be mutated or rendered."""

    @staticmethod
    def _immutable(*_args, **_kwargs):
        raise TypeError("media session credential handoff is immutable")

    __setitem__ = _immutable
    __delitem__ = _immutable
    clear = _immutable
    pop = _immutable
    popitem = _immutable
    setdefault = _immutable
    update = _immutable
    __ior__ = _immutable

    def __repr__(self) -> str:
        return "<redacted media session credential>"

    __str__ = __repr__


class ClassroomMediaProviderBinder:
    """Bind both media coordinators to one exact provider-execution authority."""

    def __init__(
        self,
        host_transactions: ClassroomMediaHostTransactions,
        session_transactions: ClassroomMediaSessionHostTransactions,
        *,
        arbiter: ClassroomMediaProviderExecutionArbiter | None = None,
    ) -> None:
        if not isinstance(host_transactions, ClassroomMediaHostTransactions):
            raise TypeError("host transactions must be ClassroomMediaHostTransactions")
        if not isinstance(
            session_transactions,
            ClassroomMediaSessionHostTransactions,
        ):
            raise TypeError(
                "session transactions must be ClassroomMediaSessionHostTransactions"
            )
        if (
            getattr(session_transactions, "_host_transactions", None)
            is not host_transactions
        ):
            raise ValueError(
                "media provider binder coordinators must share one host owner"
            )
        if arbiter is not None and not isinstance(
            arbiter,
            ClassroomMediaProviderExecutionArbiter,
        ):
            raise TypeError("media provider execution arbiter is invalid")

        self._host = host_transactions
        self._sessions = session_transactions
        self._arbiter = arbiter or ClassroomMediaProviderExecutionArbiter()
        self._session_credential_handed_off = False

    @property
    def active_lease(self) -> MediaProviderExecutionLease | None:
        return self._arbiter.active_lease

    @property
    def recovery_status(self) -> MediaProviderExecutionRecoveryStatus | None:
        return self._arbiter.recovery_status

    def __repr__(self) -> str:
        if self.recovery_status is not None:
            state = "recovery"
        elif self.active_lease is not None:
            state = "active"
        else:
            state = "idle"
        return f"ClassroomMediaProviderBinder(state={state!r}, credential=<redacted>)"

    def _prepare(
        self,
        owner: MediaProviderExecutionOwner,
        prepare: Callable[[], MediaProviderEffect | MediaSessionProviderEffect | None],
    ) -> MediaProviderExecutionLease | None:
        lease = self._arbiter.begin(owner)
        try:
            effect = prepare()
        except Exception:
            self._arbiter.release_without_provider(lease.lease_id)
            raise

        if effect is None:
            self._session_credential_handed_off = False
            self._arbiter.release_without_provider(lease.lease_id)
            return None

        if owner is MediaProviderExecutionOwner.EFFECT:
            if not isinstance(effect, MediaProviderEffect):
                self._arbiter.release_without_provider(lease.lease_id)
                raise MediaProviderExecutionError(
                    "effect coordinator returned an invalid provider effect"
                )
        else:
            if not isinstance(effect, MediaSessionProviderEffect):
                self._arbiter.release_without_provider(lease.lease_id)
                raise MediaProviderExecutionError(
                    "session coordinator returned an invalid provider effect"
                )

        try:
            bound = self._arbiter.bind_transaction(
                lease.lease_id,
                effect.transaction_id,
            )
        except Exception:
            # No provider boundary has been crossed. Retire the exact local
            # transaction before releasing the global lease.
            if owner is MediaProviderExecutionOwner.EFFECT:
                self._host.provider_not_started(effect.transaction_id)
            else:
                self._sessions.provider_not_started(effect.transaction_id)
            self._arbiter.release_without_provider(lease.lease_id)
            raise

        pending = (
            self._host.pending_effect
            if owner is MediaProviderExecutionOwner.EFFECT
            else self._sessions.pending_effect
        )
        if pending is None or pending.transaction_id != effect.transaction_id:
            # The coordinator published no stable pending transaction after the
            # exact id was bound. Keep the global lease fail-closed in known
            # recovery rather than accidentally allowing a second provider call.
            self._arbiter.require_recovery(
                lease.lease_id,
                provider_outcome_unknown=False,
            )
            raise MediaProviderExecutionError(
                "media coordinator pending transaction does not match prepared effect"
            )

        self._session_credential_handed_off = False
        return bound

    def prepare_local_source(
        self,
        source: MediaSource | str,
        enabled: bool,
    ) -> MediaProviderExecutionLease | None:
        return self._prepare(
            MediaProviderExecutionOwner.EFFECT,
            lambda: self._host.prepare_local_source(source, enabled),
        )

    def prepare_publish_permission(
        self,
        *,
        actor_id: str,
        target_id: str,
        source: MediaSource | str,
        allowed: bool,
        operation_id: str,
    ) -> MediaProviderExecutionLease | None:
        return self._prepare(
            MediaProviderExecutionOwner.EFFECT,
            lambda: self._host.prepare_publish_permission(
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
    ) -> MediaProviderExecutionLease | None:
        return self._prepare(
            MediaProviderExecutionOwner.EFFECT,
            lambda: self._host.prepare_soft_mute(
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
    ) -> MediaProviderExecutionLease | None:
        return self._prepare(
            MediaProviderExecutionOwner.EFFECT,
            lambda: self._host.prepare_all_students_publish_permission(
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
    ) -> MediaProviderExecutionLease | None:
        return self._prepare(
            MediaProviderExecutionOwner.EFFECT,
            lambda: self._host.prepare_all_students_soft_mute(
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
    ) -> MediaProviderExecutionLease | None:
        return self._prepare(
            MediaProviderExecutionOwner.EFFECT,
            lambda: self._host.prepare_remove_participant(
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
    ) -> MediaProviderExecutionLease | None:
        return self._prepare(
            MediaProviderExecutionOwner.EFFECT,
            lambda: self._host.prepare_device_recovery(kind, device_id),
        )

    def prepare_join(
        self,
        credential: JoinCredential,
        *,
        now: datetime,
    ) -> MediaProviderExecutionLease | None:
        return self._prepare(
            MediaProviderExecutionOwner.SESSION,
            lambda: self._sessions.prepare_join(credential, now=now),
        )

    def prepare_reconnect(
        self,
        credential: JoinCredential,
        *,
        now: datetime,
    ) -> MediaProviderExecutionLease | None:
        return self._prepare(
            MediaProviderExecutionOwner.SESSION,
            lambda: self._sessions.prepare_reconnect(credential, now=now),
        )

    def prepare_disconnect(self) -> MediaProviderExecutionLease | None:
        return self._prepare(
            MediaProviderExecutionOwner.SESSION,
            self._sessions.prepare_disconnect,
        )

    def pending_browser_payload(
        self,
        transaction_id: str,
    ) -> Mapping[str, object]:
        lease = self._require_active(transaction_id)
        if lease.owner is MediaProviderExecutionOwner.EFFECT:
            effect = self._host.pending_effect
            payload = self._host.pending_browser_payload
        else:
            effect = self._sessions.pending_effect
            payload = self._sessions.pending_browser_payload
        if (
            effect is None
            or effect.transaction_id != transaction_id
            or payload is None
        ):
            raise MediaProviderExecutionError(
                "media provider payload is unavailable for active transaction"
            )
        return dict(payload)

    def take_session_credential(
        self,
        transaction_id: str,
    ) -> Mapping[str, str]:
        lease = self._require_active(
            transaction_id,
            owner=MediaProviderExecutionOwner.SESSION,
        )
        if lease.provider_boundary_crossed:
            raise MediaProviderExecutionError(
                "media session credential cannot be handed off after provider dispatch"
            )
        try:
            value = self._sessions.take_credential(transaction_id)
        except Exception:
            if (
                self._sessions.pending_effect is None
                and self._sessions.recovery_status is None
            ):
                self._arbiter.release_without_provider(lease.lease_id)
                self._session_credential_handed_off = False
            raise
        # Taking the one-shot credential is already a provider-capability
        # boundary. A stale browser callback may use the credential even if the
        # normal executor later reports that dispatch never started, so the
        # global serialization gate must become fail-closed before the secret is
        # returned to the browser host.
        self._arbiter.mark_provider_boundary_crossed(lease.lease_id)
        self._session_credential_handed_off = True
        return _FrozenSecretCredential(value)

    def mark_provider_dispatched(
        self,
        transaction_id: str,
    ) -> MediaProviderExecutionLease:
        lease = self._require_active(transaction_id)
        if lease.owner is MediaProviderExecutionOwner.SESSION:
            effect = self._sessions.pending_effect
            if effect is None or effect.transaction_id != transaction_id:
                raise MediaProviderExecutionError(
                    "media session transaction is not pending for provider dispatch"
                )
            if (
                effect.kind
                in {MediaSessionEffectKind.CONNECT, MediaSessionEffectKind.RECONNECT}
                and not self._session_credential_handed_off
            ):
                raise MediaProviderExecutionError(
                    "media session provider dispatch requires credential handoff"
                )
        else:
            effect = self._host.pending_effect
            if effect is None or effect.transaction_id != transaction_id:
                raise MediaProviderExecutionError(
                    "media effect transaction is not pending for provider dispatch"
                )
        # Connect/reconnect crossed the provider-capability boundary when the
        # one-shot credential was handed to the browser. The later executor
        # dispatch acknowledgement is therefore intentionally idempotent for
        # that exact session transaction; non-secret effects and disconnect
        # still cross here immediately before provider invocation.
        if (
            lease.owner is MediaProviderExecutionOwner.SESSION
            and self._session_credential_handed_off
            and lease.provider_boundary_crossed
        ):
            return lease
        return self._arbiter.mark_provider_boundary_crossed(lease.lease_id)

    def provider_not_started(self, transaction_id: str) -> None:
        lease = self._require_active(transaction_id)
        credential_exposed = (
            lease.owner is MediaProviderExecutionOwner.SESSION
            and self._session_credential_handed_off
        )
        if lease.provider_boundary_crossed and not credential_exposed:
            raise MediaProviderExecutionError(
                "provider-not-started cannot follow provider dispatch"
            )
        try:
            if lease.owner is MediaProviderExecutionOwner.EFFECT:
                self._host.provider_not_started(transaction_id)
            else:
                self._sessions.provider_not_started(transaction_id)
        except MediaHostRecoveryRequired:
            # A handed-off session credential is an ambiguous provider
            # capability even when the normal executor says it never invoked
            # LiveKit: a stale callback may still use that token. Preserve the
            # session coordinator's exact uncertainty in the shared recovery
            # latch so neither transaction owner can proceed.
            status = self._sessions.recovery_status
            self._arbiter.require_recovery(
                lease.lease_id,
                provider_outcome_unknown=(
                    True if status is None else status.provider_outcome_unknown
                ),
            )
            self._session_credential_handed_off = False
            raise
        self._arbiter.release_without_provider(lease.lease_id)
        self._session_credential_handed_off = False

    def provider_failed(self, transaction_id: str) -> None:
        self._latch_provider_recovery(transaction_id, outcome_unknown=True)

    def provider_outcome_unknown(self, transaction_id: str) -> None:
        self._latch_provider_recovery(transaction_id, outcome_unknown=True)

    def _latch_provider_recovery(
        self,
        transaction_id: str,
        *,
        outcome_unknown: bool,
    ) -> None:
        lease = self._require_active(transaction_id)
        if not lease.provider_boundary_crossed:
            raise MediaProviderExecutionError(
                "provider recovery requires a dispatched provider invocation"
            )
        if lease.owner is MediaProviderExecutionOwner.EFFECT:
            self._host.provider_outcome_unknown(transaction_id)
        else:
            self._sessions.provider_outcome_unknown(transaction_id)
        self._arbiter.require_recovery(
            lease.lease_id,
            provider_outcome_unknown=outcome_unknown,
        )
        self._session_credential_handed_off = False

    def provider_connection_failed_clean(
        self,
        transaction_id: str,
        provider_snapshot: Mapping[str, object],
    ) -> None:
        lease = self._require_active(
            transaction_id,
            owner=MediaProviderExecutionOwner.SESSION,
        )
        if not lease.provider_boundary_crossed:
            raise MediaProviderExecutionError(
                "verified clean session failure requires provider dispatch"
            )
        try:
            self._sessions.provider_connection_failed_clean(
                transaction_id,
                provider_snapshot,
            )
        except MediaHostRecoveryRequired:
            self._arbiter.require_recovery(
                lease.lease_id,
                provider_outcome_unknown=True,
            )
            self._session_credential_handed_off = False
            raise
        self._arbiter.release_after_verified_clean_failure(lease.lease_id)
        self._session_credential_handed_off = False

    def acknowledge_session_success(
        self,
        transaction_id: str,
        provider_snapshot: Mapping[str, object],
    ) -> Any:
        lease = self._require_active(
            transaction_id,
            owner=MediaProviderExecutionOwner.SESSION,
        )
        if not lease.provider_boundary_crossed:
            raise MediaProviderExecutionError(
                "media session success requires provider dispatch"
            )
        try:
            result = self._sessions.acknowledge_provider_success(
                transaction_id,
                provider_snapshot,
            )
        except MediaHostRecoveryRequired:
            status = self._sessions.recovery_status
            self._arbiter.require_recovery(
                lease.lease_id,
                provider_outcome_unknown=(
                    True if status is None else status.provider_outcome_unknown
                ),
            )
            self._session_credential_handed_off = False
            raise
        self._arbiter.complete(lease.lease_id)
        self._session_credential_handed_off = False
        return result

    def acknowledge_effect_chunk_success(
        self,
        transaction_id: str,
        chunk_index: int,
    ) -> Any | None:
        lease = self._require_active(
            transaction_id,
            owner=MediaProviderExecutionOwner.EFFECT,
        )
        if not lease.provider_boundary_crossed:
            raise MediaProviderExecutionError(
                "media effect success requires provider dispatch"
            )
        try:
            result = self._host.acknowledge_provider_chunk_success(
                transaction_id,
                chunk_index,
            )
        except MediaHostRecoveryRequired:
            status = self._host.recovery_status
            self._arbiter.require_recovery(
                lease.lease_id,
                provider_outcome_unknown=(
                    True if status is None else status.provider_outcome_unknown
                ),
            )
            raise
        if self._host.pending_effect is None:
            self._arbiter.complete(lease.lease_id)
        return result

    def commit_effect_success(self, transaction_id: str) -> Any:
        self._require_active(
            transaction_id,
            owner=MediaProviderExecutionOwner.EFFECT,
        )
        effect = self._host.pending_effect
        if (
            effect is None
            or effect.transaction_id != transaction_id
            or effect.browser_payload_count() != 1
        ):
            raise MediaProviderExecutionError(
                "multi-chunk media effect requires per-chunk acknowledgement"
            )
        return self.acknowledge_effect_chunk_success(transaction_id, 0)

    def resolve_recovery(self, transaction_id: str) -> None:
        status = self._arbiter.recovery_status
        if (
            status is None
            or status.lease.transaction_id != transaction_id
        ):
            raise MediaProviderExecutionError(
                "media provider recovery transaction is unknown"
            )
        if status.lease.owner is MediaProviderExecutionOwner.EFFECT:
            self._host.resolve_recovery(transaction_id)
        else:
            self._sessions.resolve_recovery(transaction_id)
        self._arbiter.resolve_recovery(status.lease.lease_id)
        self._session_credential_handed_off = False

    def _require_active(
        self,
        transaction_id: str,
        *,
        owner: MediaProviderExecutionOwner | None = None,
    ) -> MediaProviderExecutionLease:
        if type(transaction_id) is not str:
            raise MediaProviderExecutionError(
                "media provider transaction id is invalid"
            )
        lease = self._arbiter.active_lease
        if lease is None or lease.transaction_id != transaction_id:
            raise MediaProviderExecutionError(
                "media provider transaction is not the active execution"
            )
        if owner is not None and lease.owner is not owner:
            raise MediaProviderExecutionError(
                "media provider transaction owner mismatch"
            )
        return lease


__all__ = ["ClassroomMediaProviderBinder"]
