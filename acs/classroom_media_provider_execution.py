from __future__ import annotations

"""Shared execution lease for desktop/browser classroom media provider calls.

The classroom media product has two intentionally separate transaction owners:

* a secret-bearing session handoff for connect/reconnect/disconnect; and
* a non-secret media-effect transaction owner for source/moderation/device calls.

Those owners must not each believe they can have an independent provider mutation
in flight. This module supplies only the shared serialization/recovery lease needed
by the eventual shipping binder. It owns no media policy, browser bridge, provider
SDK, token, participant identity, chess state, or canonical transaction commit.

The binder reserves one lease before preparing either coordinator, binds the exact
coordinator transaction identity before dispatch, marks the provider boundary only
when invocation is actually dispatched, and releases the lease only after the
coordinator has either committed safely or proved that no provider call occurred.
Ambiguous/partial outcomes move the lease to recovery and block every other media
provider mutation until trusted reconciliation completes.
"""

from dataclasses import dataclass, replace
from enum import Enum
import re
import secrets
from threading import RLock, get_ident


_LEASE_RE = re.compile(r"^execution-[0-9a-f]{32}$")
_TRANSACTION_RE = re.compile(r"^(?:host|session)-[0-9a-f]{32}$")


class MediaProviderExecutionError(RuntimeError):
    """Shared media-provider execution ordering was violated."""


class MediaProviderExecutionRecoveryRequired(MediaProviderExecutionError):
    """A prior provider mutation must be reconciled before another can start."""


class MediaProviderExecutionOwner(str, Enum):
    SESSION = "session"
    EFFECT = "effect"


@dataclass(frozen=True, slots=True)
class MediaProviderExecutionLease:
    """Non-secret diagnostic view of the one active shared provider lease."""

    lease_id: str
    owner: MediaProviderExecutionOwner
    transaction_id: str | None
    provider_boundary_crossed: bool


@dataclass(frozen=True, slots=True)
class MediaProviderExecutionRecoveryStatus:
    """Non-secret recovery state held after an ambiguous or partial mutation."""

    lease: MediaProviderExecutionLease
    provider_outcome_unknown: bool


@dataclass(frozen=True, slots=True)
class _LeaseState:
    lease_id: str
    owner: MediaProviderExecutionOwner
    transaction_id: str | None = None
    provider_boundary_crossed: bool = False

    def public(self) -> MediaProviderExecutionLease:
        return MediaProviderExecutionLease(
            lease_id=self.lease_id,
            owner=self.owner,
            transaction_id=self.transaction_id,
            provider_boundary_crossed=self.provider_boundary_crossed,
        )


@dataclass(frozen=True, slots=True)
class _RecoveryState:
    lease: _LeaseState
    provider_outcome_unknown: bool


class ClassroomMediaProviderExecutionArbiter:
    """Serialize every browser/provider mutation for one classroom media runtime."""

    def __init__(self) -> None:
        nonce = secrets.token_hex(8)
        self._nonce = nonce
        self._counter = 0
        self._owner_thread_id = get_ident()
        self._lock = RLock()
        self._active: _LeaseState | None = None
        self._recovery: _RecoveryState | None = None

    @property
    def active_lease(self) -> MediaProviderExecutionLease | None:
        with self._lock:
            return None if self._active is None else self._active.public()

    @property
    def recovery_status(self) -> MediaProviderExecutionRecoveryStatus | None:
        with self._lock:
            if self._recovery is None:
                return None
            return MediaProviderExecutionRecoveryStatus(
                lease=self._recovery.lease.public(),
                provider_outcome_unknown=self._recovery.provider_outcome_unknown,
            )

    def begin(
        self,
        owner: MediaProviderExecutionOwner,
    ) -> MediaProviderExecutionLease:
        """Reserve the sole provider-execution slot before coordinator prepare."""

        self._assert_owner_thread()
        if not isinstance(owner, MediaProviderExecutionOwner):
            raise TypeError("media provider execution owner must be canonical")
        with self._lock:
            if self._recovery is not None:
                raise MediaProviderExecutionRecoveryRequired(
                    "media provider execution requires recovery"
                )
            if self._active is not None:
                raise MediaProviderExecutionError(
                    "another media provider execution lease is already active"
                )
            lease = _LeaseState(
                lease_id=self._next_lease_id(),
                owner=owner,
            )
            self._active = lease
            return lease.public()

    def bind_transaction(
        self,
        lease_id: str,
        transaction_id: str,
    ) -> MediaProviderExecutionLease:
        """Bind the exact #1142/#1160 transaction before browser dispatch."""

        self._assert_owner_thread()
        transaction = self._transaction_id(transaction_id)
        with self._lock:
            active = self._require_active(lease_id)
            expected_prefix = (
                "session-"
                if active.owner is MediaProviderExecutionOwner.SESSION
                else "host-"
            )
            if not transaction.startswith(expected_prefix):
                raise MediaProviderExecutionError(
                    "provider transaction identity does not match lease owner"
                )
            if active.transaction_id is not None:
                raise MediaProviderExecutionError(
                    "media provider execution lease already has a transaction"
                )
            active = replace(active, transaction_id=transaction)
            self._active = active
            return active.public()

    def mark_provider_boundary_crossed(
        self,
        lease_id: str,
    ) -> MediaProviderExecutionLease:
        """Record that the browser/provider invocation may now have side effects."""

        self._assert_owner_thread()
        with self._lock:
            active = self._require_active(lease_id)
            if active.transaction_id is None:
                raise MediaProviderExecutionError(
                    "provider execution requires a bound transaction"
                )
            if active.provider_boundary_crossed:
                raise MediaProviderExecutionError(
                    "provider execution boundary was already crossed"
                )
            active = replace(active, provider_boundary_crossed=True)
            self._active = active
            return active.public()

    def release_without_provider(
        self,
        lease_id: str,
    ) -> None:
        """Release only when the binder can prove no provider invocation occurred."""

        self._assert_owner_thread()
        with self._lock:
            active = self._require_active(lease_id)
            if active.provider_boundary_crossed:
                raise MediaProviderExecutionError(
                    "provider execution lease crossed the provider boundary"
                )
            self._active = None

    def release_after_verified_clean_failure(
        self,
        lease_id: str,
    ) -> None:
        """Release after the owning coordinator proves a dispatched effect left no provider state.

        This is not a provider-success path and performs no canonical commit. The
        shipping binder may use it only after the owning transaction coordinator
        has accepted its own stronger clean-failure proof (for example #1160's
        connect/reconnect adapter snapshot with connected=false and
        cleanup_required=false).
        """

        self._assert_owner_thread()
        with self._lock:
            active = self._require_active(lease_id)
            if active.owner is not MediaProviderExecutionOwner.SESSION:
                raise MediaProviderExecutionError(
                    "verified clean failure is not valid for media-effect transactions"
                )
            if active.transaction_id is None or not active.provider_boundary_crossed:
                raise MediaProviderExecutionError(
                    "verified clean failure requires an exact dispatched transaction"
                )
            self._active = None

    def complete(
        self,
        lease_id: str,
    ) -> None:
        """Release after provider success and exact canonical coordinator commit."""

        self._assert_owner_thread()
        with self._lock:
            active = self._require_active(lease_id)
            if active.transaction_id is None or not active.provider_boundary_crossed:
                raise MediaProviderExecutionError(
                    "provider execution cannot complete before exact dispatch"
                )
            self._active = None

    def require_recovery(
        self,
        lease_id: str,
        *,
        provider_outcome_unknown: bool,
    ) -> MediaProviderExecutionRecoveryStatus:
        """Move the sole active lease into a process-local recovery latch."""

        self._assert_owner_thread()
        if type(provider_outcome_unknown) is not bool:
            raise TypeError("provider outcome unknown flag must be boolean")
        with self._lock:
            active = self._require_active(lease_id)
            if active.transaction_id is None:
                raise MediaProviderExecutionError(
                    "media provider recovery requires a bound transaction"
                )
            if provider_outcome_unknown and not active.provider_boundary_crossed:
                raise MediaProviderExecutionError(
                    "unknown provider outcome requires a crossed provider boundary"
                )
            self._active = None
            recovery = _RecoveryState(
                lease=active,
                provider_outcome_unknown=provider_outcome_unknown,
            )
            self._recovery = recovery
            return MediaProviderExecutionRecoveryStatus(
                lease=recovery.lease.public(),
                provider_outcome_unknown=recovery.provider_outcome_unknown,
            )

    def resolve_recovery(
        self,
        lease_id: str,
    ) -> None:
        """Release the global media gate only after trusted provider reconciliation."""

        self._assert_owner_thread()
        lease = self._lease_id(lease_id)
        with self._lock:
            if self._recovery is None or self._recovery.lease.lease_id != lease:
                raise MediaProviderExecutionError(
                    "media provider recovery lease is unknown"
                )
            self._recovery = None

    def _next_lease_id(self) -> str:
        if self._counter >= (1 << 64) - 1:
            raise MediaProviderExecutionError(
                "media provider execution lease identity space is exhausted"
            )
        self._counter += 1
        return "execution-" + self._nonce + f"{self._counter:016x}"

    def _require_active(self, lease_id: str) -> _LeaseState:
        lease = self._lease_id(lease_id)
        if self._active is None or self._active.lease_id != lease:
            raise MediaProviderExecutionError(
                "media provider execution lease is unknown or already consumed"
            )
        return self._active

    def _assert_owner_thread(self) -> None:
        if get_ident() != self._owner_thread_id:
            raise MediaProviderExecutionError(
                "media provider execution mutation requires the owner thread"
            )

    @staticmethod
    def _lease_id(value: str) -> str:
        if type(value) is not str or _LEASE_RE.fullmatch(value) is None:
            raise MediaProviderExecutionError(
                "media provider execution lease id is invalid"
            )
        return value

    @staticmethod
    def _transaction_id(value: str) -> str:
        if type(value) is not str or _TRANSACTION_RE.fullmatch(value) is None:
            raise MediaProviderExecutionError(
                "media provider transaction id is invalid"
            )
        return value


__all__ = [
    "ClassroomMediaProviderExecutionArbiter",
    "MediaProviderExecutionError",
    "MediaProviderExecutionLease",
    "MediaProviderExecutionOwner",
    "MediaProviderExecutionRecoveryRequired",
    "MediaProviderExecutionRecoveryStatus",
]
