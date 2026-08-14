"""Presentation-neutral commercial security and entitlement contracts.

This module intentionally contains no network, billing-provider, UI, filesystem,
or platform-secret implementation. It defines stable product policy objects that
can later be backed by a server without rewriting chess, data, or presentation
modules.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import FrozenSet, Mapping, Optional, Protocol


class EntitlementState(str, Enum):
    FREE_BETA = "free_beta"
    TRIAL = "trial"
    PAID_MONTHLY = "paid_monthly"
    PAID_YEARLY = "paid_yearly"
    ORGANIZATION = "organization"
    GRACE = "grace"
    EXPIRED = "expired"
    REVOKED = "revoked"
    UPDATE_REQUIRED = "update_required"


class AccessDecision(str, Enum):
    ALLOW = "allow"
    DENY = "deny"
    UPDATE_REQUIRED = "update_required"


@dataclass(frozen=True)
class AccountSession:
    subject_id: str
    session_id: str
    issued_at: datetime
    expires_at: datetime

    def is_valid(self, now: Optional[datetime] = None) -> bool:
        current = now or datetime.now(timezone.utc)
        return bool(self.subject_id and self.session_id and self.issued_at <= current < self.expires_at)


@dataclass(frozen=True)
class RemotePolicy:
    minimum_supported_version: Optional[str] = None
    refresh_after_seconds: int = 3600
    grace_period_seconds: int = 72 * 3600
    metadata: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.refresh_after_seconds <= 0:
            raise ValueError("refresh_after_seconds must be positive")
        if self.grace_period_seconds < 0:
            raise ValueError("grace_period_seconds cannot be negative")


@dataclass(frozen=True)
class Entitlement:
    state: EntitlementState
    feature_ids: FrozenSet[str] = frozenset()
    valid_until: Optional[datetime] = None
    policy: RemotePolicy = field(default_factory=RemotePolicy)

    @property
    def is_revoked(self) -> bool:
        return self.state is EntitlementState.REVOKED

    @property
    def requires_update(self) -> bool:
        return self.state is EntitlementState.UPDATE_REQUIRED

    def is_time_valid(self, now: Optional[datetime] = None) -> bool:
        if self.valid_until is None:
            return True
        current = now or datetime.now(timezone.utc)
        return current < self.valid_until


class EntitlementService(Protocol):
    """Authority-facing port. Concrete implementations may be server-backed."""

    def current_entitlement(self, session: Optional[AccountSession]) -> Entitlement:
        ...


class BillingProvider(Protocol):
    """Billing abstraction only; product code must not depend on Stripe/Paddle APIs."""

    def customer_portal_url(self, session: AccountSession) -> str:
        ...


class LicensePolicy(Protocol):
    def decide(self, entitlement: Entitlement, feature_id: str, *, now: Optional[datetime] = None) -> AccessDecision:
        ...


class DefaultLicensePolicy:
    """Safe default policy for beta and future paid states.

    FREE_BETA intentionally permits declared features so the product can ship
    free during development while retaining a server-switchable path to paid,
    revoked, expired, grace, and update-required states.
    """

    _ACTIVE_STATES = frozenset(
        {
            EntitlementState.FREE_BETA,
            EntitlementState.TRIAL,
            EntitlementState.PAID_MONTHLY,
            EntitlementState.PAID_YEARLY,
            EntitlementState.ORGANIZATION,
            EntitlementState.GRACE,
        }
    )

    def decide(self, entitlement: Entitlement, feature_id: str, *, now: Optional[datetime] = None) -> AccessDecision:
        if entitlement.requires_update:
            return AccessDecision.UPDATE_REQUIRED
        if entitlement.is_revoked or entitlement.state is EntitlementState.EXPIRED:
            return AccessDecision.DENY
        if entitlement.state not in self._ACTIVE_STATES:
            return AccessDecision.DENY
        if not entitlement.is_time_valid(now):
            return AccessDecision.DENY
        if feature_id not in entitlement.feature_ids:
            return AccessDecision.DENY
        return AccessDecision.ALLOW


class FeatureGate:
    """Single application-facing gate for protected capabilities."""

    def __init__(self, policy: Optional[LicensePolicy] = None) -> None:
        self._policy = policy or DefaultLicensePolicy()

    def decision(self, entitlement: Entitlement, feature_id: str, *, now: Optional[datetime] = None) -> AccessDecision:
        if not feature_id or feature_id.strip() != feature_id:
            raise ValueError("feature_id must be a non-empty stable identifier without surrounding whitespace")
        return self._policy.decide(entitlement, feature_id, now=now)

    def allows(self, entitlement: Entitlement, feature_id: str, *, now: Optional[datetime] = None) -> bool:
        return self.decision(entitlement, feature_id, now=now) is AccessDecision.ALLOW


# Stable product identifiers. New premium capabilities should extend this
# registry rather than invent provider-specific flags in UI/data/chess modules.
FEATURE_LOCAL_CHESS = "local_chess"
FEATURE_ENGINE_ANALYSIS = "engine_analysis"
FEATURE_DATABASES = "databases"
FEATURE_BOOK_READER = "book_reader"
FEATURE_ONLINE_PLAY = "online_play"
FEATURE_CLOUD_SYNC = "cloud_sync"

DEFAULT_BETA_FEATURES: FrozenSet[str] = frozenset(
    {
        FEATURE_LOCAL_CHESS,
        FEATURE_ENGINE_ANALYSIS,
        FEATURE_DATABASES,
        FEATURE_BOOK_READER,
    }
)


def permissive_beta_entitlement() -> Entitlement:
    """Development default: free beta without embedding any secret or provider."""

    return Entitlement(
        state=EntitlementState.FREE_BETA,
        feature_ids=DEFAULT_BETA_FEATURES,
    )
