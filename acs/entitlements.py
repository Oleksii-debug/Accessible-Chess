from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import FrozenSet, Protocol, runtime_checkable


class EntitlementState(str, Enum):
    FREE_BETA = "free_beta"
    TRIAL = "trial"
    PAID_MONTHLY = "paid_monthly"
    PAID_YEARLY = "paid_yearly"
    ORGANIZATION = "organization"
    GRACE_PERIOD = "grace_period"
    EXPIRED = "expired"
    REVOKED = "revoked"
    UPDATE_REQUIRED = "update_required"


class FeatureId(str, Enum):
    """Stable product-facing capability identifiers.

    These values describe product capabilities, never price tiers or billing
    providers. Product code may depend on them while infrastructure adapters map
    future commercial plans and server claims to these stable IDs.

    Accessibility itself is intentionally absent from this catalog: keyboard,
    screen-reader and semantic-document accessibility are product invariants,
    not entitlements that can be sold or revoked.
    """

    PLAY_ENGINE = "play.engine"
    ANALYSIS_ENGINE = "analysis.engine"
    POSITION_EDITOR = "position.editor"
    HISTORY_REVIEW = "history.review"
    DATA_IMPORT = "data.import"
    DATA_EXPORT = "data.export"
    DATA_RECOVERY = "data.recovery"
    PGN_WORKSPACE = "pgn.workspace"
    LIBRARY_SEARCH = "library.search"
    BOOKS_READER = "books.reader"
    TRAINING_LOCAL = "training.local"
    TRAINING_COURSES = "training.courses"
    TEACHER_LOCAL = "teacher.local"
    CLASSROOM_LOCAL = "classroom.local"
    EDUCATION_MANAGEMENT = "education.management"
    SETTINGS_PROFILES = "settings.profiles"


CORE_FEATURE_IDS: FrozenSet[str] = frozenset(feature.value for feature in FeatureId)

# User-owned local data must remain exportable and recoverable even when a
# commercial entitlement is unavailable, expired, revoked or requires an update.
# This is a data-safety invariant, not a paid feature grant. Provider-backed
# premium content/export requires distinct future capability IDs.
LOCAL_DATA_SAFETY_FEATURE_IDS: FrozenSet[str] = frozenset(
    {
        FeatureId.DATA_EXPORT.value,
        FeatureId.DATA_RECOVERY.value,
    }
)


ACTIVE_STATES = frozenset(
    {
        EntitlementState.FREE_BETA,
        EntitlementState.TRIAL,
        EntitlementState.PAID_MONTHLY,
        EntitlementState.PAID_YEARLY,
        EntitlementState.ORGANIZATION,
    }
)


@dataclass(frozen=True, order=True)
class ProductVersion:
    """Small dependency-free comparable product version.

    Accessible Chess currently uses numeric release versions. Keeping comparison
    here avoids coupling entitlement policy to packaging or UI code.
    """

    major: int
    minor: int
    patch: int = 0

    @classmethod
    def parse(cls, value: str) -> "ProductVersion":
        text = str(value).strip()
        parts = text.split(".")
        if not 2 <= len(parts) <= 3 or any(not p.isdigit() for p in parts):
            raise ValueError(f"invalid product version: {value!r}")
        values = [int(p) for p in parts]
        if len(values) == 2:
            values.append(0)
        return cls(*values)

    def __str__(self) -> str:
        return f"{self.major}.{self.minor}.{self.patch}"


@dataclass(frozen=True)
class RemotePolicy:
    """Server-authored policy values consumed by the client.

    `refresh_after` is an enforceable cache TTL boundary, not advisory metadata.
    Once it is passed the pure FeatureGate fails closed unless a bounded
    `grace_until` is still active. Transport code may refresh before evaluation.

    This type deliberately contains no transport, signature, payment-provider,
    or token-storage implementation. Those belong to infrastructure adapters.
    """

    minimum_supported_version: ProductVersion | None = None
    refresh_after: datetime | None = None
    grace_until: datetime | None = None

    def __post_init__(self) -> None:
        _validate_datetime("refresh_after", self.refresh_after)
        _validate_datetime("grace_until", self.grace_until)


@dataclass(frozen=True)
class EntitlementSnapshot:
    """Authoritative-or-cached entitlement claims in presentation-neutral form."""

    state: EntitlementState
    feature_ids: FrozenSet[str] = field(default_factory=frozenset)
    expires_at: datetime | None = None
    server_time: datetime | None = None
    policy: RemotePolicy = field(default_factory=RemotePolicy)
    account_id: str | None = None
    organization_id: str | None = None
    source: str = "server"

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "feature_ids",
            frozenset(_normalize_feature_id(v) for v in self.feature_ids),
        )
        _validate_datetime("expires_at", self.expires_at)
        _validate_datetime("server_time", self.server_time)


@dataclass(frozen=True)
class AccessDecision:
    allowed: bool
    state: EntitlementState
    reason: str
    feature_id: str
    requires_update: bool = False
    using_grace: bool = False


@dataclass(frozen=True)
class AccountSession:
    """Non-secret account/session metadata exposed to application code."""

    account_id: str
    signed_in: bool
    organization_id: str | None = None


@runtime_checkable
class EntitlementService(Protocol):
    """Infrastructure port for obtaining entitlement snapshots."""

    def current(self) -> EntitlementSnapshot | None:
        ...

    def refresh(self) -> EntitlementSnapshot:
        ...


@runtime_checkable
class BillingProvider(Protocol):
    """Server-side/payment-facing port; domain code must not know provider APIs."""

    def customer_portal_url(self, account_id: str) -> str:
        ...


@runtime_checkable
class LicensePolicy(Protocol):
    """Application policy port that produces provider-neutral entitlements.

    Implementations may represent the current free beta, a cached signed-in
    account, an organization deployment, or a future commercial policy. Chess,
    UI and data code consume only the resulting EntitlementSnapshot.
    """

    def entitlement_for(self, session: AccountSession | None = None) -> EntitlementSnapshot:
        ...


@dataclass(frozen=True)
class FreeBetaLicensePolicy:
    """Current development policy: all known local product features are enabled.

    This is deliberately local and deterministic. Replacing it with a commercial
    policy later does not require edits to chess rules, UI actions or data models.
    """

    feature_ids: FrozenSet[str] = CORE_FEATURE_IDS

    def __post_init__(self) -> None:
        normalized = frozenset(_normalize_feature_id(value) for value in self.feature_ids)
        object.__setattr__(self, "feature_ids", normalized)

    def entitlement_for(self, session: AccountSession | None = None) -> EntitlementSnapshot:
        return EntitlementSnapshot(
            state=EntitlementState.FREE_BETA,
            feature_ids=self.feature_ids,
            account_id=session.account_id if session and session.signed_in else None,
            organization_id=session.organization_id if session and session.signed_in else None,
            source="local_free_beta",
        )


class FeatureGate:
    """Pure policy evaluator for stable feature IDs.

    The gate never deletes data and never performs network or billing calls.
    User-owned local data export/recovery are narrow safety invariants and stay
    available independently of commercial entitlement state. Other features
    remain fail-closed unless explicitly entitled.

    When a server-authored snapshot supplies `server_time`, evaluation never
    reasons about a time earlier than that trusted floor. This blocks the trivial
    local-clock rollback where a user sets Windows time before a server-observed
    expiry/refresh boundary. A transport/cache layer remains responsible for
    persistence and cryptographic authenticity of server-issued policy.
    """

    def __init__(self, *, current_version: ProductVersion | str) -> None:
        self.current_version = (
            current_version
            if isinstance(current_version, ProductVersion)
            else ProductVersion.parse(current_version)
        )

    def evaluate(
        self,
        feature_id: str | FeatureId,
        snapshot: EntitlementSnapshot | None,
        *,
        now: datetime | None = None,
    ) -> AccessDecision:
        feature = _normalize_feature_id(feature_id)
        local_time = _utc_now(now)

        if feature in LOCAL_DATA_SAFETY_FEATURE_IDS:
            return AccessDecision(
                True,
                snapshot.state if snapshot is not None else EntitlementState.EXPIRED,
                "local_data_safety",
                feature,
            )

        if snapshot is None:
            return AccessDecision(
                False,
                EntitlementState.EXPIRED,
                "entitlement_unavailable",
                feature,
            )

        current_time = _effective_time(local_time, snapshot.server_time)

        minimum = snapshot.policy.minimum_supported_version
        if minimum is not None and self.current_version < minimum:
            return AccessDecision(
                False,
                EntitlementState.UPDATE_REQUIRED,
                "minimum_supported_version",
                feature,
                requires_update=True,
            )

        if snapshot.state is EntitlementState.UPDATE_REQUIRED:
            return AccessDecision(
                False,
                snapshot.state,
                "update_required",
                feature,
                requires_update=True,
            )

        if snapshot.state is EntitlementState.REVOKED:
            return AccessDecision(False, snapshot.state, "revoked", feature)

        entitled = feature in snapshot.feature_ids or "*" in snapshot.feature_ids
        if not entitled:
            return AccessDecision(False, snapshot.state, "feature_not_entitled", feature)

        if snapshot.state is EntitlementState.EXPIRED:
            return AccessDecision(False, snapshot.state, "expired", feature)

        if snapshot.expires_at is not None and current_time > snapshot.expires_at:
            grace_until = snapshot.policy.grace_until
            if grace_until is not None and current_time <= grace_until:
                return AccessDecision(
                    True,
                    EntitlementState.GRACE_PERIOD,
                    "cached_entitlement_grace",
                    feature,
                    using_grace=True,
                )
            return AccessDecision(False, EntitlementState.EXPIRED, "expired", feature)

        if snapshot.state is EntitlementState.GRACE_PERIOD:
            grace_until = snapshot.policy.grace_until
            if grace_until is None or current_time > grace_until:
                return AccessDecision(False, EntitlementState.EXPIRED, "grace_expired", feature)
            return AccessDecision(
                True,
                snapshot.state,
                "grace_period",
                feature,
                using_grace=True,
            )

        refresh_after = snapshot.policy.refresh_after
        if refresh_after is not None and current_time > refresh_after:
            grace_until = snapshot.policy.grace_until
            if grace_until is not None and current_time <= grace_until:
                return AccessDecision(
                    True,
                    EntitlementState.GRACE_PERIOD,
                    "refresh_overdue_grace",
                    feature,
                    using_grace=True,
                )
            return AccessDecision(
                False,
                EntitlementState.EXPIRED,
                "refresh_required",
                feature,
            )

        if snapshot.state in ACTIVE_STATES:
            return AccessDecision(True, snapshot.state, "entitled", feature)

        return AccessDecision(False, snapshot.state, "not_active", feature)


def _normalize_feature_id(value: str | FeatureId) -> str:
    text = value.value if isinstance(value, FeatureId) else str(value).strip().lower()
    if not text:
        raise ValueError("feature ID must not be empty")
    if any(ch.isspace() for ch in text):
        raise ValueError("feature ID must not contain whitespace")
    return text


def _validate_datetime(name: str, value: datetime | None) -> None:
    if value is not None and value.tzinfo is None:
        raise ValueError(f"{name} must be timezone-aware")


def _utc_now(value: datetime | None) -> datetime:
    if value is None:
        return datetime.now(timezone.utc)
    if value.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    return value.astimezone(timezone.utc)


def _effective_time(local_time: datetime, server_time: datetime | None) -> datetime:
    """Return a time that never predates a known server-authored time floor."""

    if server_time is None:
        return local_time
    server_utc = server_time.astimezone(timezone.utc)
    return max(local_time, server_utc)
