from __future__ import annotations

"""Reusable agent runtime contracts for Accessible Chess.

Adapted from first-party donor:
Oleksii-debug/Nika-Core@main
src/nika_core/runtime/contracts.py blob 03191b2ef23eabd9274aee98c9c02c1b6e784aac
src/nika_core/runtime/retry.py blob 64da65c4f96c2a4cb8e0e3f63e8af92054c81193

The chess product owns this API. It intentionally contains no Nika imports and no
chess rules. Canonical board mutations still go through Accessible Chess
application services.
"""

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from math import isfinite, ldexp
from typing import Any, Protocol, runtime_checkable


class AgentCapability(StrEnum):
    DETERMINISTIC_NO_LLM = "deterministic_no_llm"
    DURABLE_RESUME = "durable_resume"
    CANCELLATION = "cancellation"
    TOOL_CALLS = "tool_calls"
    LOCAL_MODELS = "local_models"
    CLOUD_MODELS = "cloud_models"


class AgentOutcome(StrEnum):
    COMPLETED = "completed"
    PAUSED = "paused"
    CANCELLED = "cancelled"
    FAILED = "failed"


class AgentErrorCode(StrEnum):
    TIMEOUT = "timeout"
    TRANSIENT = "transient"
    INVALID_RESUME = "invalid_resume"
    RESUME_UNAVAILABLE = "resume_unavailable"
    DUPLICATE_ACTIVE = "duplicate_active"
    INVALID_TOOL_RESULT = "invalid_tool_result"
    INTERNAL = "internal"


@dataclass(frozen=True, slots=True)
class AgentRequest:
    task_id: str
    thread_id: str
    payload: Mapping[str, Any] = field(default_factory=dict)
    max_steps: int = 64
    timeout_seconds: float | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.task_id, str) or not self.task_id.strip():
            raise ValueError("task_id must not be empty")
        if not isinstance(self.thread_id, str) or not self.thread_id.strip():
            raise ValueError("thread_id must not be empty")
        if type(self.max_steps) is not int or self.max_steps < 1:
            raise ValueError("max_steps must be a positive integer")
        if self.timeout_seconds is not None:
            if isinstance(self.timeout_seconds, bool) or not isinstance(
                self.timeout_seconds, (int, float)
            ):
                raise TypeError("timeout_seconds must be numeric")
            if not isfinite(float(self.timeout_seconds)) or self.timeout_seconds <= 0:
                raise ValueError("timeout_seconds must be finite and positive")


@dataclass(frozen=True, slots=True)
class AgentResumeRequest:
    task_id: str
    thread_id: str
    resume_token: str
    value: Any = None
    max_steps: int = 64

    def __post_init__(self) -> None:
        for label, value in (
            ("task_id", self.task_id),
            ("thread_id", self.thread_id),
            ("resume_token", self.resume_token),
        ):
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{label} must not be empty")
        if type(self.max_steps) is not int or self.max_steps < 1:
            raise ValueError("max_steps must be a positive integer")


@dataclass(frozen=True, slots=True)
class AgentEvent:
    sequence: int
    event_type: str
    payload: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if type(self.sequence) is not int or self.sequence < 0:
            raise ValueError("sequence must be a non-negative integer")
        if not isinstance(self.event_type, str) or not self.event_type.strip():
            raise ValueError("event_type must not be empty")


@dataclass(frozen=True, slots=True)
class AgentResult:
    outcome: AgentOutcome
    events: tuple[AgentEvent, ...] = ()
    output: Mapping[str, Any] = field(default_factory=dict)
    resume_token: str | None = None
    error: str | None = None
    error_code: AgentErrorCode | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.outcome, AgentOutcome):
            raise TypeError("outcome must be AgentOutcome")
        if self.outcome is AgentOutcome.PAUSED:
            if not isinstance(self.resume_token, str) or not self.resume_token.strip():
                raise ValueError("paused outcome requires a resume token")
        if self.outcome is AgentOutcome.FAILED and not self.error:
            raise ValueError("failed outcome requires an error")
        if self.error_code is not None and not isinstance(self.error_code, AgentErrorCode):
            raise TypeError("error_code must be AgentErrorCode")
        if self.outcome is not AgentOutcome.FAILED and self.error_code is not None:
            raise ValueError("error_code is valid only for failed outcomes")


@runtime_checkable
class ChessAgentRuntimePort(Protocol):
    @property
    def runtime_id(self) -> str: ...

    @property
    def capabilities(self) -> frozenset[AgentCapability]: ...

    async def run(self, request: AgentRequest) -> AgentResult: ...

    async def resume(self, request: AgentResumeRequest) -> AgentResult: ...

    async def cancel(self, *, task_id: str, thread_id: str) -> bool: ...


@dataclass(frozen=True, slots=True)
class AgentRetryPolicy:
    """Fail-closed retry policy adapted from Nika-Core.

    Retries are disabled by default. A caller must explicitly opt into exact
    error classes. Blind replay is not permitted unless allow_fresh_retry=True.
    """

    max_retries: int = 0
    retryable_error_codes: frozenset[AgentErrorCode] = field(default_factory=frozenset)
    base_delay_seconds: float = 0.0
    max_delay_seconds: float = 30.0
    allow_fresh_retry: bool = False

    def __post_init__(self) -> None:
        if type(self.max_retries) is not int or self.max_retries < 0:
            raise ValueError("max_retries must be a non-negative integer")
        if not isinstance(self.retryable_error_codes, frozenset):
            raise TypeError("retryable_error_codes must be a frozenset")
        if any(not isinstance(code, AgentErrorCode) for code in self.retryable_error_codes):
            raise TypeError("retryable_error_codes contains an invalid value")
        for name, value in (
            ("base_delay_seconds", self.base_delay_seconds),
            ("max_delay_seconds", self.max_delay_seconds),
        ):
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise TypeError(f"{name} must be numeric")
            if not isfinite(float(value)) or value < 0:
                raise ValueError(f"{name} must be finite and non-negative")
        if self.base_delay_seconds > self.max_delay_seconds:
            raise ValueError("base_delay_seconds must not exceed max_delay_seconds")
        if type(self.allow_fresh_retry) is not bool:
            raise TypeError("allow_fresh_retry must be boolean")

    def should_retry(self, result: AgentResult, *, retries_used: int) -> bool:
        if type(retries_used) is not int or retries_used < 0:
            raise ValueError("retries_used must be a non-negative integer")
        if retries_used >= self.max_retries:
            return False
        if result.outcome is not AgentOutcome.FAILED or result.error_code is None:
            return False
        if result.error_code not in self.retryable_error_codes:
            return False
        has_resume = isinstance(result.resume_token, str) and bool(result.resume_token.strip())
        return has_resume or self.allow_fresh_retry

    def delay_seconds(self, *, retry_number: int) -> float:
        if type(retry_number) is not int or retry_number < 1:
            raise ValueError("retry_number must be a positive integer")
        if self.base_delay_seconds == 0:
            return 0.0
        try:
            delay = ldexp(float(self.base_delay_seconds), retry_number - 1)
        except OverflowError:
            return float(self.max_delay_seconds)
        return min(delay, float(self.max_delay_seconds))


__all__ = [
    "AgentCapability",
    "AgentErrorCode",
    "AgentEvent",
    "AgentOutcome",
    "AgentRequest",
    "AgentResult",
    "AgentResumeRequest",
    "AgentRetryPolicy",
    "ChessAgentRuntimePort",
]
