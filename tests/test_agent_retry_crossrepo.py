from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from acs.agent_retry import (
    RetryCondition,
    RetryDisposition,
    RetryIntent,
    RetryPolicy,
    evaluate_retry,
    plan_retry,
)


NOW = datetime(2026, 10, 5, 10, 0, tzinfo=UTC)


def test_retry_is_disabled_by_default() -> None:
    decision = plan_retry(
        RetryPolicy(),
        operation_id="media-job",
        condition=RetryCondition.RECOVERABLE_NETWORK_FAILURE,
        retries_used=0,
        now=NOW,
        replay_safe=True,
    )
    assert decision.disposition is RetryDisposition.ATTEMPTS_EXHAUSTED


def test_retry_requires_replay_safe_operation() -> None:
    decision = plan_retry(
        RetryPolicy(max_retries=3, base_delay_seconds=1),
        operation_id="media-job",
        condition=RetryCondition.RECOVERABLE_NETWORK_FAILURE,
        retries_used=0,
        now=NOW,
        replay_safe=False,
    )
    assert decision.disposition is RetryDisposition.NOT_RETRYABLE
    assert decision.intent is None


@pytest.mark.parametrize(
    "condition",
    [
        RetryCondition.UNCERTAIN_EXTERNAL_EFFECT,
        RetryCondition.APPROVAL_DENIED,
        RetryCondition.PERMISSION_FAILURE,
        RetryCondition.AMBIGUOUS_MEDIA_STATE,
        RetryCondition.DETERMINISTIC_VALIDATION_ERROR,
    ],
)
def test_semantic_or_uncertain_failures_never_auto_retry(
    condition: RetryCondition,
) -> None:
    decision = plan_retry(
        RetryPolicy(max_retries=5, base_delay_seconds=1),
        operation_id="agent-op",
        condition=condition,
        retries_used=0,
        now=NOW,
        replay_safe=True,
    )
    assert decision.disposition is RetryDisposition.NOT_RETRYABLE


def test_retry_uses_deterministic_bounded_exponential_backoff() -> None:
    policy = RetryPolicy(
        max_retries=5,
        base_delay_seconds=2,
        max_delay_seconds=5,
    )
    first = plan_retry(
        policy,
        operation_id="provider-op",
        condition=RetryCondition.TEMPORARY_BUSY,
        retries_used=0,
        now=NOW,
        replay_safe=True,
    )
    third = plan_retry(
        policy,
        operation_id="provider-op",
        condition=RetryCondition.TEMPORARY_BUSY,
        retries_used=2,
        now=NOW,
        replay_safe=True,
    )
    assert first.intent is not None
    assert third.intent is not None
    assert first.intent.not_before_utc == NOW + timedelta(seconds=2)
    assert third.intent.not_before_utc == NOW + timedelta(seconds=5)


def test_rate_limit_retry_after_cannot_escape_policy_ceiling() -> None:
    decision = plan_retry(
        RetryPolicy(max_retries=2, base_delay_seconds=1, max_delay_seconds=10),
        operation_id="provider-op",
        condition=RetryCondition.EXPLICIT_RATE_LIMIT,
        retries_used=0,
        now=NOW,
        replay_safe=True,
        retry_after_seconds=30,
    )
    assert decision.disposition is RetryDisposition.BACKOFF_LIMIT_EXCEEDED


def test_retry_intent_round_trip_and_restart_evaluation() -> None:
    policy = RetryPolicy(max_retries=2, base_delay_seconds=2)
    planned = plan_retry(
        policy,
        operation_id="recording-preprocess",
        condition=RetryCondition.TEMPORARY_PROVIDER_READINESS,
        retries_used=0,
        now=NOW,
        replay_safe=True,
    )
    assert planned.intent is not None
    restored = RetryIntent.from_payload(planned.intent.to_payload())
    waiting = evaluate_retry(
        restored,
        policy,
        now=NOW + timedelta(seconds=1),
        replay_safe=True,
    )
    ready = evaluate_retry(
        restored,
        policy,
        now=NOW + timedelta(seconds=2),
        replay_safe=True,
    )
    assert waiting.disposition is RetryDisposition.WAITING
    assert ready.disposition is RetryDisposition.READY


def test_cancelled_retry_remains_cancelled_after_restart() -> None:
    intent = RetryIntent(
        operation_id="agent-call",
        condition=RetryCondition.RECOVERABLE_NETWORK_FAILURE,
        retry_number=1,
        not_before_utc=NOW + timedelta(seconds=1),
    )
    decision = evaluate_retry(
        intent,
        RetryPolicy(max_retries=2, base_delay_seconds=1),
        now=NOW,
        replay_safe=True,
        cancelled=True,
    )
    assert decision.disposition is RetryDisposition.CANCELLED
