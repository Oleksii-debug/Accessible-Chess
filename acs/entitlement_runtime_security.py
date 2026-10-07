from __future__ import annotations

"""Rollback-resistant entitlement timing and safe-expiry shell policy.

Security Section 13 consumes a verified time-bounded lease from the earlier
security workline. It does not verify signatures, mint leases, bind devices or
store secrets itself. The injected ProtectedRollbackStateStore is the
device/protected-storage boundary and MUST maintain a monotonic generation
anchor independently from the sealed state payload.

Security Section 14 composes that clock decision with the canonical FeatureGate.
Premium capability failure is fail-closed, while account recovery, update/help
and user-owned local data recovery/export stay reachable. Nothing in this
module deletes, encrypts, corrupts or otherwise modifies user data.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import Enum
import re
from typing import Protocol, runtime_checkable

from .entitlements import (
    AccessDecision,
    EntitlementSnapshot,
    EntitlementState,
    FeatureGate,
    FeatureId,
    LOCAL_DATA_SAFETY_FEATURE_IDS,
    ProductVersion,
)


_IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
DEFAULT_CLOCK_ROLLBACK_TOLERANCE = timedelta(minutes=5)


class SafeShellAction(str, Enum):
    ACCOUNT_LOGIN = "account.login"
    ACCOUNT_RECOVERY = "account.recovery"
    ENTITLEMENT_REFRESH = "entitlement.refresh"
    APP_UPDATE = "app.update"
    HELP = "help.open"
    DATA_EXPORT = "data.export"
    DATA_RECOVERY = "data.recovery"
    SECURITY_STATUS = "security.status"


SAFE_LOCKED_ACTION_IDS: tuple[str, ...] = tuple(action.value for action in SafeShellAction)


@dataclass(frozen=True)
class LeaseObservation:
    """Verified lease facts required by rollback resistance."""

    installation_id: str
    lease_id: str
    issued_at: datetime
    snapshot: EntitlementSnapshot

    def __post_init__(self) -> None:
        _validate_identifier("installation_id", self.installation_id)
        _validate_identifier("lease_id", self.lease_id)
        issued = _utc("issued_at", self.issued_at)
        server = self.snapshot.server_time
        expiry = self.snapshot.expires_at
        if server is None:
            raise ValueError("verified lease must include server_time")
        if expiry is None:
            raise ValueError("verified lease must include expires_at")
        server = _utc("server_time", server)
        _utc("expires_at", expiry)
        if issued > server:
            raise ValueError("issued_at cannot be later than server_time")


@dataclass(frozen=True)
class ProtectedRollbackState:
    """Sealed state whose generation is anchored outside the payload."""

    installation_id: str
    generation: int
    lease_id: str
    lease_issued_at: datetime
    server_time_floor: datetime
    effective_time_floor: datetime

    def __post_init__(self) -> None:
        _validate_identifier("installation_id", self.installation_id)
        _validate_identifier("lease_id", self.lease_id)
        if type(self.generation) is not int or self.generation < 1:
            raise ValueError("generation must be a positive integer")
        _utc("lease_issued_at", self.lease_issued_at)
        _utc("server_time_floor", self.server_time_floor)
        _utc("effective_time_floor", self.effective_time_floor)
        if self.lease_issued_at > self.server_time_floor:
            raise ValueError("lease issuance cannot exceed server-time floor")
        if self.server_time_floor > self.effective_time_floor:
            raise ValueError("server-time floor cannot exceed effective-time floor")


@runtime_checkable
class ProtectedRollbackStateStore(Protocol):
    """Protected storage contract supplied by earlier security sections.

    generation_floor MUST be an integrity-protected monotonic anchor that is not
    derived solely from the replayable state payload. compare_and_swap MUST
    atomically advance that anchor together with the sealed payload.
    """

    def load(self, installation_id: str) -> ProtectedRollbackState | None:
        ...

    def generation_floor(self, installation_id: str) -> int:
        ...

    def compare_and_swap(
        self,
        installation_id: str,
        *,
        expected_generation: int,
        new_state: ProtectedRollbackState,
    ) -> bool:
        ...


@dataclass(frozen=True)
class ClockSecurityDecision:
    allowed: bool
    reason: str
    effective_time: datetime | None
    generation: int

    @property
    def requires_online_refresh(self) -> bool:
        return not self.allowed


class RollbackResistantLeaseGuard:
    """Durable monotonic time/lease gate for Security Section 13."""

    def __init__(
        self,
        store: ProtectedRollbackStateStore,
        *,
        rollback_tolerance: timedelta = DEFAULT_CLOCK_ROLLBACK_TOLERANCE,
    ) -> None:
        if not isinstance(rollback_tolerance, timedelta):
            raise TypeError("rollback_tolerance must be timedelta")
        if rollback_tolerance < timedelta(0) or rollback_tolerance > timedelta(hours=1):
            raise ValueError("rollback_tolerance must be between zero and one hour")
        self._store = store
        self._rollback_tolerance = rollback_tolerance

    def observe(
        self,
        observation: LeaseObservation,
        *,
        wall_time: datetime | None = None,
    ) -> ClockSecurityDecision:
        wall = _utc_now(wall_time)
        server = _utc("server_time", observation.snapshot.server_time)
        issued = _utc("issued_at", observation.issued_at)

        try:
            floor = self._store.generation_floor(observation.installation_id)
            state = self._store.load(observation.installation_id)
        except Exception:
            return _deny("protected_state_unavailable")

        if type(floor) is not int or floor < 0:
            return _deny("protected_state_invalid")

        if state is None:
            if floor != 0:
                return _deny("protected_state_replay")
        else:
            if type(state) is not ProtectedRollbackState:
                return _deny("protected_state_invalid")
            if state.installation_id != observation.installation_id:
                return _deny("installation_mismatch")
            if state.generation != floor:
                return _deny("protected_state_replay")

            if issued < state.lease_issued_at:
                return _deny("stale_lease_replay", floor)
            if (
                issued == state.lease_issued_at
                and server == state.server_time_floor
                and observation.lease_id != state.lease_id
            ):
                return _deny("conflicting_lease_generation", floor)
            if server < state.server_time_floor:
                return _deny("stale_server_time_replay", floor)

        prior_time = state.effective_time_floor if state is not None else server
        trusted_floor = max(server, prior_time)
        if wall + self._rollback_tolerance < trusted_floor:
            return _deny("clock_rollback", floor)

        effective = max(wall, trusted_floor)
        next_generation = floor + 1
        next_state = ProtectedRollbackState(
            installation_id=observation.installation_id,
            generation=next_generation,
            lease_id=observation.lease_id,
            lease_issued_at=max(issued, state.lease_issued_at) if state is not None else issued,
            server_time_floor=max(server, state.server_time_floor) if state is not None else server,
            effective_time_floor=effective,
        )

        try:
            committed = self._store.compare_and_swap(
                observation.installation_id,
                expected_generation=floor,
                new_state=next_state,
            )
        except Exception:
            return _deny("protected_state_commit_failed", floor)
        if committed is not True:
            return _deny("protected_state_conflict", floor)

        try:
            observed_floor = self._store.generation_floor(observation.installation_id)
            observed_state = self._store.load(observation.installation_id)
        except Exception:
            return _deny("protected_state_commit_unverified", floor)
        if (
            observed_floor != next_generation
            or type(observed_state) is not ProtectedRollbackState
            or observed_state != next_state
        ):
            return _deny("protected_state_commit_unverified", floor)

        return ClockSecurityDecision(
            allowed=True,
            reason="trusted_time_advanced",
            effective_time=effective,
            generation=next_generation,
        )


@dataclass(frozen=True)
class LockedShellDecision:
    capability_allowed: bool
    premium_locked: bool
    reason: str
    access: AccessDecision
    safe_action_ids: tuple[str, ...] = SAFE_LOCKED_ACTION_IDS
    preserve_user_data: bool = True
    destructive_action: bool = False

    def as_dict(self) -> dict[str, object]:
        return {
            "capabilityAllowed": self.capability_allowed,
            "premiumLocked": self.premium_locked,
            "reason": self.reason,
            "featureId": self.access.feature_id,
            "entitlementState": self.access.state.value,
            "requiresUpdate": self.access.requires_update,
            "usingGrace": self.access.using_grace,
            "safeActionIds": list(self.safe_action_ids),
            "preserveUserData": self.preserve_user_data,
            "destructiveAction": self.destructive_action,
        }


class LockedShellPolicy:
    """Security Section 14 fail-closed premium / fail-safe recovery policy."""

    def __init__(self, *, current_version: ProductVersion | str) -> None:
        self._gate = FeatureGate(current_version=current_version)

    def evaluate(
        self,
        feature_id: str | FeatureId,
        snapshot: EntitlementSnapshot | None,
        clock: ClockSecurityDecision,
    ) -> LockedShellDecision:
        feature = (
            feature_id.value
            if isinstance(feature_id, FeatureId)
            else str(feature_id).strip().lower()
        )

        if feature in LOCAL_DATA_SAFETY_FEATURE_IDS:
            access = self._gate.evaluate(feature, snapshot, now=clock.effective_time)
            return LockedShellDecision(
                capability_allowed=access.allowed,
                premium_locked=_premium_globally_locked(snapshot, clock),
                reason=access.reason,
                access=access,
            )

        if not clock.allowed or clock.effective_time is None:
            state = snapshot.state if snapshot is not None else EntitlementState.EXPIRED
            access = AccessDecision(
                allowed=False,
                state=state,
                reason=clock.reason,
                feature_id=feature,
            )
            return LockedShellDecision(
                capability_allowed=False,
                premium_locked=True,
                reason=clock.reason,
                access=access,
            )

        access = self._gate.evaluate(feature, snapshot, now=clock.effective_time)
        return LockedShellDecision(
            capability_allowed=access.allowed,
            premium_locked=not access.allowed,
            reason=access.reason,
            access=access,
        )


def _premium_globally_locked(
    snapshot: EntitlementSnapshot | None,
    clock: ClockSecurityDecision,
) -> bool:
    if not clock.allowed:
        return True
    if snapshot is None:
        return True
    return snapshot.state in {
        EntitlementState.EXPIRED,
        EntitlementState.REVOKED,
        EntitlementState.UPDATE_REQUIRED,
    }


def _deny(reason: str, generation: int = 0) -> ClockSecurityDecision:
    return ClockSecurityDecision(False, reason, None, generation)


def _validate_identifier(name: str, value: object) -> None:
    if type(value) is not str or not _IDENTIFIER_RE.fullmatch(value):
        raise ValueError(f"{name} is not a canonical bounded identifier")


def _utc(name: str, value: datetime | None) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise ValueError(f"{name} must be timezone-aware")
    return value.astimezone(timezone.utc)


def _utc_now(value: datetime | None) -> datetime:
    return _utc("wall_time", datetime.now(timezone.utc) if value is None else value)
