from __future__ import annotations

"""Safe public bridge for R19-R22 online entitlement lifecycle.

The desktop UI never supplies account/device/build identifiers, access tokens,
refresh tokens, credential identifiers, lease payloads, signing inputs, or
revocation subjects.  Those remain private-runtime/server authority.
"""

from dataclasses import dataclass
from typing import Iterable

from .protection_boundary import (
    ENTITLEMENT_RUNTIME_API_VERSION,
    ProtectionBoundaryError,
    ProtectionRuntimeClient,
)

_ALLOWED_STATES = frozenset({
    "authorized",
    "renewal_due",
    "network_grace",
    "reauth_required",
    "revoked",
    "quarantined",
    "recovery_required",
    "device_limit",
    "consent_required",
})
_ALLOWED_ACTIONS = frozenset({
    "retry",
    "login",
    "recover",
    "repair",
    "transfer_device",
    "review_privacy",
})
_ALLOWED_LIVE_REGIONS = frozenset({"none", "polite", "assertive"})
_MAX_REASON = 256
_MAX_ACTIONS = 5
_MAX_RETRY_SECONDS = 86400
_MAX_LEASE_SECONDS = 31 * 24 * 60 * 60


class ProtectionLifecycleError(ProtectionBoundaryError):
    pass


@dataclass(frozen=True)
class EntitlementLifecycleSnapshot:
    state: str
    reason: str
    actions: tuple[str, ...]
    live_region: str
    retry_after_seconds: int
    lease_remaining_seconds: int | None

    @property
    def premium_allowed(self) -> bool:
        return self.state in {"authorized", "renewal_due", "network_grace"}


def _validate_actions(value: object) -> tuple[str, ...]:
    if not isinstance(value, list) or len(value) > _MAX_ACTIONS:
        raise ProtectionLifecycleError("private lifecycle actions are invalid")
    if any(not isinstance(item, str) or item not in _ALLOWED_ACTIONS for item in value):
        raise ProtectionLifecycleError("private lifecycle action is invalid")
    if len(value) != len(set(value)):
        raise ProtectionLifecycleError("private lifecycle actions contain duplicates")
    return tuple(value)


def _validate_snapshot(value: object) -> EntitlementLifecycleSnapshot:
    if not isinstance(value, dict) or set(value) != {
        "api_version",
        "state",
        "reason",
        "actions",
        "live_region",
        "retry_after_seconds",
        "lease_remaining_seconds",
    }:
        raise ProtectionLifecycleError("private lifecycle schema is invalid")
    if value.get("api_version") != ENTITLEMENT_RUNTIME_API_VERSION:
        raise ProtectionLifecycleError("private lifecycle API version is unsupported")

    state = value.get("state")
    reason = value.get("reason")
    live_region = value.get("live_region")
    retry_after = value.get("retry_after_seconds")
    lease_remaining = value.get("lease_remaining_seconds")

    if state not in _ALLOWED_STATES:
        raise ProtectionLifecycleError("private lifecycle state is invalid")
    if not isinstance(reason, str) or not reason or len(reason) > _MAX_REASON:
        raise ProtectionLifecycleError("private lifecycle reason is invalid")
    if live_region not in _ALLOWED_LIVE_REGIONS:
        raise ProtectionLifecycleError("private lifecycle live region is invalid")
    if (
        not isinstance(retry_after, int)
        or isinstance(retry_after, bool)
        or not 0 <= retry_after <= _MAX_RETRY_SECONDS
    ):
        raise ProtectionLifecycleError("private lifecycle retry interval is invalid")
    if lease_remaining is not None and (
        not isinstance(lease_remaining, int)
        or isinstance(lease_remaining, bool)
        or not -_MAX_LEASE_SECONDS <= lease_remaining <= _MAX_LEASE_SECONDS
    ):
        raise ProtectionLifecycleError("private lifecycle lease interval is invalid")

    actions = _validate_actions(value.get("actions"))

    if state == "authorized":
        if reason != "none" or lease_remaining is None or lease_remaining <= 0:
            raise ProtectionLifecycleError("authorized lifecycle result is inconsistent")
    elif state == "renewal_due":
        if reason != "renewal_due" or lease_remaining is None or lease_remaining <= 0:
            raise ProtectionLifecycleError("renewal-due lifecycle result is inconsistent")
    elif state == "network_grace":
        if reason != "network_failure" or lease_remaining is None:
            raise ProtectionLifecycleError("network-grace lifecycle result is inconsistent")
    else:
        if reason == "none":
            raise ProtectionLifecycleError("denied lifecycle result is inconsistent")

    if state in {"revoked", "quarantined", "recovery_required", "device_limit", "reauth_required", "consent_required"}:
        if live_region != "assertive":
            raise ProtectionLifecycleError("blocked lifecycle result must be assertive")

    return EntitlementLifecycleSnapshot(
        state=state,
        reason=reason,
        actions=actions,
        live_region=live_region,
        retry_after_seconds=retry_after,
        lease_remaining_seconds=lease_remaining,
    )


class ProtectionEntitlementLifecycle:
    """Opaque R19-R22 orchestration entry point owned by the private runtime."""

    def __init__(self, client: ProtectionRuntimeClient) -> None:
        if not isinstance(client, ProtectionRuntimeClient):
            raise TypeError("client must be a ProtectionRuntimeClient")
        self.client = client

    def synchronize(self) -> EntitlementLifecycleSnapshot:
        try:
            runtime = self.client.runtime_extension(
                minimum_api_version=ENTITLEMENT_RUNTIME_API_VERSION
            )
        except ProtectionBoundaryError as exc:
            raise ProtectionLifecycleError(str(exc)) from exc

        operation = getattr(runtime, "synchronize_online_entitlement", None)
        if not callable(operation):
            raise ProtectionLifecycleError(
                "private online entitlement lifecycle operation is unavailable"
            )
        try:
            value = operation(
                package_root=self.client.application_dir,
                state_root=self.client.state_root,
            )
        except Exception as exc:
            raise ProtectionLifecycleError(
                "private online entitlement lifecycle synchronization failed"
            ) from exc
        return _validate_snapshot(value)


__all__ = [
    "EntitlementLifecycleSnapshot",
    "ProtectionEntitlementLifecycle",
    "ProtectionLifecycleError",
]
