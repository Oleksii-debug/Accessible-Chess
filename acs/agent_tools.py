from __future__ import annotations

"""Universal Chess Agent tool contracts.

Adapted from first-party donor:
Oleksii-debug/Nika-Core@main
src/nika_core/tools.py blob 5df4992ca8645511e7d3fa4e976d884be3b9faa2

Accessible Chess intentionally owns a smaller boundary. Read-only/local tools can
run immediately. External/high-impact tools fail closed unless a trusted host
authorization policy and durable effect guard are supplied.
"""

import asyncio
import hashlib
import json
import unicodedata
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Protocol


class ChessToolRisk(StrEnum):
    READ_ONLY = "read_only"
    LOCAL_WRITE = "local_write"
    EXTERNAL_SIDE_EFFECT = "external_side_effect"
    HIGH_IMPACT = "high_impact"


@dataclass(frozen=True, slots=True)
class ChessToolSpec:
    tool_id: str
    description: str
    risk: ChessToolRisk = ChessToolRisk.READ_ONLY
    timeout_seconds: float = 30.0
    input_schema: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.tool_id, str) or not self.tool_id.strip():
            raise ValueError("tool_id must not be empty")
        if not isinstance(self.description, str) or not self.description.strip():
            raise ValueError("description must not be empty")
        if not isinstance(self.risk, ChessToolRisk):
            raise TypeError("risk must be ChessToolRisk")
        if isinstance(self.timeout_seconds, bool) or not isinstance(
            self.timeout_seconds, (int, float)
        ):
            raise TypeError("timeout_seconds must be numeric")
        if self.timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be greater than zero")


@dataclass(frozen=True, slots=True)
class ChessToolCall:
    call_id: str
    tool_id: str
    arguments: Mapping[str, object]
    task_id: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.call_id, str) or not self.call_id.strip():
            raise ValueError("call_id must not be empty")
        if not isinstance(self.tool_id, str) or not self.tool_id.strip():
            raise ValueError("tool_id must not be empty")
        if not isinstance(self.arguments, Mapping):
            raise TypeError("arguments must be a mapping")


@dataclass(frozen=True, slots=True)
class ChessToolAuthorization:
    tool_id: str
    task_id: str
    risk: ChessToolRisk
    arguments_fingerprint: str
    effect_fingerprint: str
    approval_fingerprint: str

    def __post_init__(self) -> None:
        values = (
            self.tool_id,
            self.task_id,
            self.arguments_fingerprint,
            self.effect_fingerprint,
            self.approval_fingerprint,
        )
        if any(not isinstance(value, str) or not value.strip() for value in values):
            raise ValueError("authorization identity fields must not be empty")

    def matches(self, *, spec: ChessToolSpec, call: ChessToolCall) -> bool:
        return (
            self.tool_id == spec.tool_id == call.tool_id
            and self.task_id == (call.task_id or "")
            and self.risk is spec.risk
            and self.arguments_fingerprint == chess_tool_arguments_fingerprint(call.arguments)
        )


def _normalize_json(value: object, *, path: str = "arguments") -> object:
    if value is None or isinstance(value, (bool, int)):
        return value
    if isinstance(value, float):
        if not (float("-inf") < value < float("inf")):
            raise ValueError(f"{path} must not contain NaN or infinity")
        return value
    if isinstance(value, str):
        return unicodedata.normalize("NFC", value)
    if isinstance(value, (list, tuple)):
        return [_normalize_json(item, path=f"{path}[{index}]") for index, item in enumerate(value)]
    if isinstance(value, Mapping):
        normalized: dict[str, object] = {}
        for raw_key, raw_value in value.items():
            if not isinstance(raw_key, str):
                raise TypeError(f"{path} keys must be strings")
            key = unicodedata.normalize("NFC", raw_key)
            if key in normalized:
                raise ValueError(f"{path} contains duplicate normalized key {key!r}")
            normalized[key] = _normalize_json(raw_value, path=f"{path}.{key}")
        return normalized
    raise ValueError(f"{path} contains unsupported value type {type(value).__name__}")


def chess_tool_arguments_fingerprint(arguments: Mapping[str, object]) -> str:
    normalized = _normalize_json(arguments)
    encoded = json.dumps(
        normalized,
        allow_nan=False,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True, slots=True)
class ChessToolResult:
    call_id: str
    tool_id: str
    output: object | None = None
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.error is None


class ChessToolHandler(Protocol):
    async def __call__(self, arguments: Mapping[str, object]) -> object: ...


ApprovalPolicy = Callable[
    [ChessToolSpec, ChessToolCall],
    Awaitable[ChessToolAuthorization | None],
]


class DurableEffectGuard(Protocol):
    async def execute(
        self,
        *,
        spec: ChessToolSpec,
        call: ChessToolCall,
        authorization: ChessToolAuthorization,
        handler: ChessToolHandler,
    ) -> ChessToolResult: ...


class ChessToolExecutor:
    def __init__(
        self,
        *,
        approval_policy: ApprovalPolicy | None = None,
        durable_effect_guard: DurableEffectGuard | None = None,
    ) -> None:
        self._tools: dict[str, tuple[ChessToolSpec, ChessToolHandler]] = {}
        self._approval_policy = approval_policy
        self._durable_effect_guard = durable_effect_guard

    def register(self, spec: ChessToolSpec, handler: ChessToolHandler) -> None:
        if spec.tool_id in self._tools:
            raise ValueError(f"duplicate tool_id: {spec.tool_id}")
        self._tools[spec.tool_id] = (spec, handler)

    def specs(self) -> tuple[ChessToolSpec, ...]:
        return tuple(spec for spec, _handler in self._tools.values())

    async def execute(self, call: ChessToolCall) -> ChessToolResult:
        registered = self._tools.get(call.tool_id)
        if registered is None:
            return ChessToolResult(call.call_id, call.tool_id, error="unknown tool")
        spec, handler = registered

        if spec.risk in {ChessToolRisk.EXTERNAL_SIDE_EFFECT, ChessToolRisk.HIGH_IMPACT}:
            if self._approval_policy is None or self._durable_effect_guard is None:
                return ChessToolResult(
                    call.call_id,
                    call.tool_id,
                    error="trusted approval and durable effect guard required",
                )
            try:
                authorization = await self._approval_policy(spec, call)
            except asyncio.CancelledError:
                raise
            except Exception:
                return ChessToolResult(call.call_id, call.tool_id, error="approval required")
            if authorization is None or not authorization.matches(spec=spec, call=call):
                return ChessToolResult(call.call_id, call.tool_id, error="approval required")
            return await self._durable_effect_guard.execute(
                spec=spec,
                call=call,
                authorization=authorization,
                handler=handler,
            )

        try:
            output = await asyncio.wait_for(handler(call.arguments), timeout=spec.timeout_seconds)
        except asyncio.CancelledError:
            raise
        except TimeoutError:
            return ChessToolResult(call.call_id, call.tool_id, error="tool timed out")
        except Exception:
            return ChessToolResult(call.call_id, call.tool_id, error="tool failed")
        return ChessToolResult(call.call_id, call.tool_id, output=output)


__all__ = [
    "ApprovalPolicy",
    "ChessToolAuthorization",
    "ChessToolCall",
    "ChessToolExecutor",
    "ChessToolHandler",
    "ChessToolResult",
    "ChessToolRisk",
    "ChessToolSpec",
    "DurableEffectGuard",
    "chess_tool_arguments_fingerprint",
]
