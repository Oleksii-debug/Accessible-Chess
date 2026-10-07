from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from types import MappingProxyType
from typing import FrozenSet, Mapping, Protocol, runtime_checkable

from .entitlements import FeatureId, LOCAL_DATA_SAFETY_FEATURE_IDS


class PlanId(str, Enum):
    FREE = "free"
    BASIC = "basic"
    PRO = "pro"
    TEACHER = "teacher"
    ORGANIZATION = "organization"
    SOCIAL_LICENSE = "social_license"


class BillingCadence(str, Enum):
    NONE = "none"
    MONTHLY = "monthly"
    YEARLY = "yearly"
    ORGANIZATION = "organization"
    LICENSE = "license"


class SubscriptionActionKind(str, Enum):
    REGISTER = "register"
    SELECT_PLAN = "select_plan"
    BEGIN_CHECKOUT = "begin_checkout"
    REFRESH_CONFIRMATION = "refresh_confirmation"
    OPEN_MANAGE = "open_manage"
    CANCEL = "cancel"


@dataclass(frozen=True)
class PlanDefinition:
    plan_id: PlanId
    label: str
    feature_ids: FrozenSet[str]
    cadences: tuple[BillingCadence, ...]
    organization: bool = False
    sponsored: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.plan_id, PlanId):
            raise TypeError("plan_id must be PlanId")
        if type(self.label) is not str or not self.label.strip():
            raise ValueError("plan label is required")
        if type(self.feature_ids) is not frozenset:
            raise TypeError("feature_ids must be a frozenset")
        if type(self.cadences) is not tuple or not self.cadences:
            raise ValueError("cadences must be a non-empty tuple")
        if any(not isinstance(value, BillingCadence) for value in self.cadences):
            raise TypeError("cadences contain an invalid value")
        if len(set(self.cadences)) != len(self.cadences):
            raise ValueError("duplicate billing cadence")

    @property
    def requires_billing(self) -> bool:
        return self.cadences != (BillingCadence.NONE,)


_FREE = frozenset({
    FeatureId.PLAY_ENGINE.value,
    FeatureId.POSITION_EDITOR.value,
    FeatureId.HISTORY_REVIEW.value,
    FeatureId.DATA_IMPORT.value,
    FeatureId.DATA_EXPORT.value,
    FeatureId.DATA_RECOVERY.value,
    FeatureId.PGN_WORKSPACE.value,
    FeatureId.TRAINING_LOCAL.value,
    FeatureId.SETTINGS_PROFILES.value,
})
_BASIC = _FREE | frozenset({
    FeatureId.LIBRARY_SEARCH.value,
    FeatureId.BOOKS_READER.value,
})
_PRO = _BASIC | frozenset({
    FeatureId.ANALYSIS_ENGINE.value,
    FeatureId.TRAINING_COURSES.value,
})
_TEACHER = _PRO | frozenset({
    FeatureId.TEACHER_LOCAL.value,
    FeatureId.CLASSROOM_LOCAL.value,
    FeatureId.EDUCATION_MANAGEMENT.value,
})


DEFAULT_PLAN_CATALOG: Mapping[PlanId, PlanDefinition] = MappingProxyType({
    PlanId.FREE: PlanDefinition(PlanId.FREE, "Free", _FREE, (BillingCadence.NONE,)),
    PlanId.BASIC: PlanDefinition(PlanId.BASIC, "Basic", _BASIC, (BillingCadence.MONTHLY, BillingCadence.YEARLY)),
    PlanId.PRO: PlanDefinition(PlanId.PRO, "Pro", _PRO, (BillingCadence.MONTHLY, BillingCadence.YEARLY)),
    PlanId.TEACHER: PlanDefinition(PlanId.TEACHER, "Teacher", _TEACHER, (BillingCadence.MONTHLY, BillingCadence.YEARLY)),
    PlanId.ORGANIZATION: PlanDefinition(PlanId.ORGANIZATION, "Organization", _TEACHER, (BillingCadence.ORGANIZATION,), organization=True),
    PlanId.SOCIAL_LICENSE: PlanDefinition(PlanId.SOCIAL_LICENSE, "Social license", _PRO, (BillingCadence.LICENSE,), sponsored=True),
})


def plan(value: str | PlanId) -> PlanDefinition:
    try:
        plan_id = value if isinstance(value, PlanId) else PlanId(str(value))
    except ValueError as exc:
        raise ValueError("unsupported plan") from exc
    return DEFAULT_PLAN_CATALOG[plan_id]


@dataclass(frozen=True)
class SubscriptionActionIntent:
    kind: SubscriptionActionKind
    plan_id: PlanId | None = None
    cadence: BillingCadence | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.kind, SubscriptionActionKind):
            raise TypeError("kind must be SubscriptionActionKind")
        if self.plan_id is not None and not isinstance(self.plan_id, PlanId):
            raise TypeError("plan_id must be PlanId or None")
        if self.cadence is not None and not isinstance(self.cadence, BillingCadence):
            raise TypeError("cadence must be BillingCadence or None")
        if self.kind in {SubscriptionActionKind.SELECT_PLAN, SubscriptionActionKind.BEGIN_CHECKOUT}:
            if self.plan_id is None:
                raise ValueError("selected plan is required")
        if self.kind is SubscriptionActionKind.BEGIN_CHECKOUT:
            definition = plan(self.plan_id)
            if not definition.requires_billing:
                raise ValueError("free plan does not use checkout")
            if self.cadence not in definition.cadences:
                raise ValueError("billing cadence is not valid for selected plan")
        elif self.cadence is not None:
            raise ValueError("cadence is only valid for checkout")

    def to_payload(self) -> dict[str, str]:
        payload = {"action": self.kind.value}
        if self.plan_id is not None:
            payload["plan_id"] = self.plan_id.value
        if self.cadence is not None:
            payload["cadence"] = self.cadence.value
        return payload


@runtime_checkable
class SubscriptionBillingProvider(Protocol):
    """Provider-neutral server port. Card/payment credentials never enter product domain code."""

    def begin_checkout(self, account_id: str, plan_id: PlanId, cadence: BillingCadence) -> str:
        ...

    def customer_portal_url(self, account_id: str) -> str:
        ...

    def request_cancellation(self, account_id: str) -> None:
        ...


def public_plan_catalog() -> tuple[dict[str, object], ...]:
    result: list[dict[str, object]] = []
    for definition in DEFAULT_PLAN_CATALOG.values():
        result.append({
            "plan_id": definition.plan_id.value,
            "label": definition.label,
            "feature_ids": sorted(definition.feature_ids),
            "cadences": [value.value for value in definition.cadences],
            "organization": definition.organization,
            "sponsored": definition.sponsored,
            "requires_billing": definition.requires_billing,
        })
    return tuple(result)


def data_safety_features() -> tuple[str, ...]:
    return tuple(sorted(LOCAL_DATA_SAFETY_FEATURE_IDS))
