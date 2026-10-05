from __future__ import annotations

"""Fail-closed retry planning for Accessible Chess Agent/Media work.

Adapted from Oleksii-debug/Nika-Core@6df8b80b7a248f1559a0ff96f74efa2d2c47ad14
src/nika_core/runtime/retry.py.

This module intentionally keeps only the generic deterministic retry semantics.
It does not import Nika runtime outcomes or create a second scheduler.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from math import isfinite, ldexp


class RetryCondition(StrEnum):
    TEMPORARY_BUSY = "temporary_busy"
    EXPLICIT_RATE_LIMIT = "explicit_rate_limit"
    RECOVERABLE_NETWORK_FAILURE = "recoverable_network_failure"
    TEMPORARY_PROVIDER_READINESS = "temporary_provider_readiness"
    UNCERTAIN_EXTERNAL_EFFECT = "uncertain_external_effect"
    APPROVAL_DENIED = "approval_denied"
    PERMISSION_FAILURE = "permission_failure"
    AMBIGUOUS_MEDIA_STATE = "ambiguous_media_state"
    DETERMINISTIC_VALIDATION_ERROR = "deterministic_validation_error"


_SAFE_RETRY_CONDITIONS = frozenset(
    {
        RetryCondition.TEMPORARY_BUSY,
        RetryCondition.EXPLICIT_RATE_LIMIT,
        RetryCondition.RECOVERABLE_NETWORK_FAILURE,
        RetryCondition.TEMPORARY_PROVIDER_READINESS,
    }
)
_INTENT_VERSION = 1
_MIN_AUTOMATIC_RETRY_DELAY_SECONDS = 1.0


class RetryDisposition(StrEnum):
    SCHEDULED = "scheduled"
    WAITING = "waiting"
    READY = "ready"
    PAUSED = "paused"
    CANCELLED = "cancelled"
    NOT_RETRYABLE = "not_retryable"
    ATTEMPTS_EXHAUSTED = "attempts_exhausted"
    BACKOFF_LIMIT_EXCEEDED = "backoff_limit_exceeded"
    DEADLINE_EXCEEDED = "deadline_exceeded"


def _require_bool(value: object, *, name: str) -> bool:
    if type(value) is not bool:
        raise TypeError(f"{name} must be boolean")
    return value


def _retry_count(value: object, *, name: str, minimum: int) -> int:
    if type(value) is not int or value < minimum:
        qualifier = "positive" if minimum == 1 else "non-negative"
        raise ValueError(f"{name} must be a {qualifier} integer")
    return value


def _delay(value: object, *, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"{name} must be a finite non-negative number")
    try:
        result = float(value)
    except OverflowError as exc:
        raise ValueError(f"{name} must be finite and non-negative") from exc
    if not isfinite(result) or result < 0:
        raise ValueError(f"{name} must be finite and non-negative")
    return result


def _utc(value: object, *, name: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must be timezone-aware")
    return value.astimezone(UTC)


def _format_utc(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _parse_utc(value: object, *, name: str) -> datetime:
    if type(value) is not str or not value:
        raise ValueError(f"{name} must be a timezone-aware ISO timestamp")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{name} must be a timezone-aware ISO timestamp") from exc
    return _utc(parsed, name=name)


@dataclass(frozen=True, slots=True)
class RetryPolicy:
    max_retries: int = 0
    base_delay_seconds: float = 0.0
    max_delay_seconds: float = 30.0

    def __post_init__(self) -> None:
        _retry_count(self.max_retries, name="max_retries", minimum=0)
        base = _delay(self.base_delay_seconds, name="base_delay_seconds")
        maximum = _delay(self.max_delay_seconds, name="max_delay_seconds")
        if base > maximum:
            raise ValueError("base_delay_seconds must not exceed max_delay_seconds")
        object.__setattr__(self, "base_delay_seconds", base)
        object.__setattr__(self, "max_delay_seconds", maximum)

    def delay_seconds(self, *, retry_number: int) -> float:
        number = _retry_count(retry_number, name="retry_number", minimum=1)
        if self.base_delay_seconds == 0:
            return 0.0
        try:
            value = ldexp(self.base_delay_seconds, number - 1)
        except OverflowError:
            return self.max_delay_seconds
        return min(value, self.max_delay_seconds)


@dataclass(frozen=True, slots=True)
class RetryIntent:
    operation_id: str
    condition: RetryCondition
    retry_number: int
    not_before_utc: datetime
    deadline_utc: datetime | None = None

    def __post_init__(self) -> None:
        if type(self.operation_id) is not str or not self.operation_id or self.operation_id != self.operation_id.strip():
            raise ValueError("operation_id must be non-empty canonical text")
        if type(self.condition) is not RetryCondition:
            raise TypeError("condition must be RetryCondition")
        _retry_count(self.retry_number, name="retry_number", minimum=1)
        not_before = _utc(self.not_before_utc, name="not_before_utc")
        deadline = None if self.deadline_utc is None else _utc(self.deadline_utc, name="deadline_utc")
        if deadline is not None and not_before >= deadline:
            raise ValueError("not_before_utc must be earlier than deadline_utc")
        object.__setattr__(self, "not_before_utc", not_before)
        object.__setattr__(self, "deadline_utc", deadline)

    def to_payload(self) -> dict[str, object]:
        return {
            "version": _INTENT_VERSION,
            "operation_id": self.operation_id,
            "condition": self.condition.value,
            "retry_number": self.retry_number,
            "not_before_utc": _format_utc(self.not_before_utc),
            "deadline_utc": None if self.deadline_utc is None else _format_utc(self.deadline_utc),
        }

    @classmethod
    def from_payload(cls, payload: Mapping[str, object]) -> "RetryIntent":
        if not isinstance(payload, Mapping):
            raise TypeError("retry intent payload must be a mapping")
        expected = {
            "version",
            "operation_id",
            "condition",
            "retry_number",
            "not_before_utc",
            "deadline_utc",
        }
        if set(payload) != expected:
            raise ValueError("retry intent payload fields are invalid")
        if type(payload["version"]) is not int or payload["version"] != _INTENT_VERSION:
            raise ValueError("retry intent payload version is unsupported")
        operation_id = payload["operation_id"]
        condition_value = payload["condition"]
        retry_number = payload["retry_number"]
        if type(operation_id) is not str:
            raise TypeError("operation_id must be text")
        if type(condition_value) is not str:
            raise TypeError("condition must be text")
        if type(retry_number) is not int:
            raise TypeError("retry_number must be integer")
        try:
            condition = RetryCondition(condition_value)
        except ValueError as exc:
            raise ValueError("retry condition is unsupported") from exc
        deadline_raw = payload["deadline_utc"]
        return cls(
            operation_id=operation_id,
            condition=condition,
            retry_number=retry_number,
            not_before_utc=_parse_utc(payload["not_before_utc"], name="not_before_utc"),
            deadline_utc=None if deadline_raw is None else _parse_utc(deadline_raw, name="deadline_utc"),
        )


@dataclass(frozen=True, slots=True)
class RetryDecision:
    disposition: RetryDisposition
    condition: RetryCondition
    intent: RetryIntent | None = None


def plan_retry(
    policy: RetryPolicy,
    *,
    operation_id: str,
    condition: RetryCondition,
    retries_used: int,
    now: datetime,
    replay_safe: bool,
    deadline: datetime | None = None,
    retry_after_seconds: float | None = None,
    paused: bool = False,
    cancelled: bool = False,
) -> RetryDecision:
    if type(policy) is not RetryPolicy:
        raise TypeError("policy must be RetryPolicy")
    _retry_count(retries_used, name="retries_used", minimum=0)
    if type(condition) is not RetryCondition:
        raise TypeError("condition must be RetryCondition")
    _require_bool(replay_safe, name="replay_safe")
    _require_bool(paused, name="paused")
    _require_bool(cancelled, name="cancelled")
    current = _utc(now, name="now")
    deadline_utc = None if deadline is None else _utc(deadline, name="deadline")
    retry_after = None if retry_after_seconds is None else _delay(retry_after_seconds, name="retry_after_seconds")

    if retry_after is not None and condition is not RetryCondition.EXPLICIT_RATE_LIMIT:
        raise ValueError("retry_after_seconds is only valid for explicit rate limits")
    if cancelled:
        return RetryDecision(RetryDisposition.CANCELLED, condition)
    if condition not in _SAFE_RETRY_CONDITIONS or not replay_safe:
        return RetryDecision(RetryDisposition.NOT_RETRYABLE, condition)
    if retries_used >= policy.max_retries:
        return RetryDecision(RetryDisposition.ATTEMPTS_EXHAUSTED, condition)
    if deadline_utc is not None and current >= deadline_utc:
        return RetryDecision(RetryDisposition.DEADLINE_EXCEEDED, condition)

    retry_number = retries_used + 1
    value = policy.delay_seconds(retry_number=retry_number)
    if retry_after is not None:
        if retry_after > policy.max_delay_seconds:
            return RetryDecision(RetryDisposition.BACKOFF_LIMIT_EXCEEDED, condition)
        value = max(value, retry_after)
    if value == 0.0:
        if policy.max_delay_seconds < _MIN_AUTOMATIC_RETRY_DELAY_SECONDS:
            return RetryDecision(RetryDisposition.BACKOFF_LIMIT_EXCEEDED, condition)
        value = _MIN_AUTOMATIC_RETRY_DELAY_SECONDS
    try:
        not_before = current + timedelta(seconds=value)
    except OverflowError:
        return RetryDecision(RetryDisposition.BACKOFF_LIMIT_EXCEEDED, condition)
    if deadline_utc is not None and not_before >= deadline_utc:
        return RetryDecision(RetryDisposition.DEADLINE_EXCEEDED, condition)

    intent = RetryIntent(
        operation_id=operation_id,
        condition=condition,
        retry_number=retry_number,
        not_before_utc=not_before,
        deadline_utc=deadline_utc,
    )
    return RetryDecision(
        RetryDisposition.PAUSED if paused else RetryDisposition.SCHEDULED,
        condition,
        intent,
    )


def evaluate_retry(
    intent: RetryIntent,
    policy: RetryPolicy,
    *,
    now: datetime,
    replay_safe: bool,
    paused: bool = False,
    cancelled: bool = False,
) -> RetryDecision:
    if type(intent) is not RetryIntent or type(policy) is not RetryPolicy:
        raise TypeError("intent and policy must use exact retry contract types")
    _require_bool(replay_safe, name="replay_safe")
    _require_bool(paused, name="paused")
    _require_bool(cancelled, name="cancelled")
    current = _utc(now, name="now")
    if cancelled:
        return RetryDecision(RetryDisposition.CANCELLED, intent.condition)
    if intent.condition not in _SAFE_RETRY_CONDITIONS or not replay_safe:
        return RetryDecision(RetryDisposition.NOT_RETRYABLE, intent.condition)
    if intent.retry_number > policy.max_retries:
        return RetryDecision(RetryDisposition.ATTEMPTS_EXHAUSTED, intent.condition)
    if intent.deadline_utc is not None and current >= intent.deadline_utc:
        return RetryDecision(RetryDisposition.DEADLINE_EXCEEDED, intent.condition)
    remaining = (intent.not_before_utc - current).total_seconds()
    if remaining > policy.max_delay_seconds:
        return RetryDecision(RetryDisposition.BACKOFF_LIMIT_EXCEEDED, intent.condition)
    if paused:
        return RetryDecision(RetryDisposition.PAUSED, intent.condition, intent)
    if current < intent.not_before_utc:
        return RetryDecision(RetryDisposition.WAITING, intent.condition, intent)
    return RetryDecision(RetryDisposition.READY, intent.condition, intent)
