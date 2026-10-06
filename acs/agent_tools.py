from __future__ import annotations

"""Fail-closed tool registry/executor for the Universal Chess Agent.

Adapted from Oleksii-debug/Nika-Core@6df8b80b7a248f1559a0ff96f74efa2d2c47ad14
src/nika_core/tools.py.

Accessible Chess owns the actual chess/media tools. External/high-impact side
effects require both exact host authorization and a durable effect guard.
"""

import asyncio
import hashlib
import json
import unicodedata
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field, replace
from enum import Enum
from math import isfinite
from types import MappingProxyType
from typing import Protocol


class ToolRisk(str, Enum):
    READ_ONLY = "read_only"
    LOCAL_WRITE = "local_write"
    EXTERNAL_SIDE_EFFECT = "external_side_effect"
    HIGH_IMPACT = "high_impact"


@dataclass(frozen=True, slots=True)
class ToolSpec:
    tool_id: str
    description: str
    risk: ToolRisk = ToolRisk.READ_ONLY
    timeout_seconds: float = 30.0
    input_schema: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if type(self.tool_id) is not str or not self.tool_id.strip():
            raise ValueError("tool_id must be non-empty text")
        if type(self.description) is not str or not self.description.strip():
            raise ValueError("description must be non-empty text")
        if type(self.risk) is not ToolRisk:
            raise TypeError("risk must be ToolRisk")
        if isinstance(self.timeout_seconds, bool) or not isinstance(self.timeout_seconds, (int, float)):
            raise TypeError("timeout_seconds must be numeric")
        if not isfinite(float(self.timeout_seconds)) or self.timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be finite and positive")
        if not isinstance(self.input_schema, Mapping):
            raise TypeError("input_schema must be a mapping")
        object.__setattr__(self, "input_schema", MappingProxyType(dict(self.input_schema)))


_MAX_TOOL_ARGUMENT_DEPTH = 32
_MAX_TOOL_ARGUMENT_ITEMS = 4096
_MAX_TOOL_ARGUMENT_TEXT_BYTES = 256 * 1024


@dataclass(frozen=True, slots=True)
class ToolAuthorization:
    tool_id: str
    task_id: str
    risk: ToolRisk
    arguments_fingerprint: str
    effect_fingerprint: str
    approval_fingerprint: str

    def __post_init__(self) -> None:
        for name in (
            "tool_id",
            "task_id",
            "arguments_fingerprint",
            "effect_fingerprint",
            "approval_fingerprint",
        ):
            value = getattr(self, name)
            if type(value) is not str or not value or value != value.strip():
                raise ValueError(f"{name} must be non-empty canonical text")
        if type(self.risk) is not ToolRisk:
            raise TypeError("risk must be ToolRisk")


@dataclass(frozen=True, slots=True)
class ToolCall:
    call_id: str
    tool_id: str
    arguments: Mapping[str, object]
    task_id: str | None = None
    authorization: ToolAuthorization | None = field(default=None, repr=False, compare=False)

    def __post_init__(self) -> None:
        for name in ("call_id", "tool_id"):
            value = getattr(self, name)
            if type(value) is not str or not value or value != value.strip():
                raise ValueError(f"{name} must be non-empty canonical text")
        if self.task_id is not None and (
            type(self.task_id) is not str or not self.task_id or self.task_id != self.task_id.strip()
        ):
            raise ValueError("task_id must be non-empty canonical text or None")
        if not isinstance(self.arguments, Mapping):
            raise TypeError("arguments must be a mapping")
        if type(self.arguments) not in (dict, MappingProxyType):
            raise TypeError("arguments must use a passive built-in mapping")
        normalized = _normalize_json(self.arguments)
        if type(normalized) is not dict:
            raise TypeError("arguments must normalize to a built-in mapping")
        object.__setattr__(self, "arguments", MappingProxyType(normalized))


@dataclass(frozen=True, slots=True)
class ToolResult:
    call_id: str
    tool_id: str
    output: object | None = None
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.error is None


def _normalize_json(
    value: object,
    *,
    path: str = "arguments",
    depth: int = 0,
    budget: list[int] | None = None,
    text_budget: list[int] | None = None,
) -> object:
    """Clone only bounded passive JSON-like argument values.

    Tool calls are an authority boundary: direct callers must not be able to
    inject active Mapping/list subclasses or unbounded nested graphs into a
    handler or the argument fingerprint. The same canonicalizer is reused for
    fingerprinting so approval identity and handler-visible arguments share one
    exact representation.
    """

    if budget is None:
        budget = [_MAX_TOOL_ARGUMENT_ITEMS]
    if text_budget is None:
        text_budget = [_MAX_TOOL_ARGUMENT_TEXT_BYTES]
    if depth > _MAX_TOOL_ARGUMENT_DEPTH:
        raise ValueError(f"{path} exceeds the maximum tool argument depth")

    if value is None or type(value) in (bool, int):
        return value
    if type(value) is float:
        if not isfinite(value):
            raise ValueError(f"{path} must not contain NaN/infinity")
        return value
    if type(value) is str:
        canonical = unicodedata.normalize("NFC", value)
        try:
            encoded_size = len(canonical.encode("utf-8"))
        except UnicodeEncodeError as exc:
            raise ValueError(f"{path} contains invalid Unicode text") from exc
        text_budget[0] -= encoded_size
        if text_budget[0] < 0:
            raise ValueError(f"{path} contains too much text")
        return canonical

    if type(value) in (list, tuple):
        budget[0] -= len(value)
        if budget[0] < 0:
            raise ValueError(f"{path} contains too many aggregate items")
        return [
            _normalize_json(
                item,
                path=f"{path}[{i}]",
                depth=depth + 1,
                budget=budget,
                text_budget=text_budget,
            )
            for i, item in enumerate(value)
        ]

    if type(value) in (dict, MappingProxyType):
        size = len(value)
        budget[0] -= size
        if budget[0] < 0:
            raise ValueError(f"{path} contains too many aggregate items")
        result: dict[str, object] = {}
        for raw_key, raw_value in value.items():
            if type(raw_key) is not str:
                raise TypeError(f"{path} keys must be strings")
            key = unicodedata.normalize("NFC", raw_key)
            try:
                key_size = len(key.encode("utf-8"))
            except UnicodeEncodeError as exc:
                raise ValueError(f"{path} contains invalid Unicode key") from exc
            text_budget[0] -= key_size
            if text_budget[0] < 0:
                raise ValueError(f"{path} contains too much text")
            if key in result:
                raise ValueError(
                    f"{path} contains duplicate normalized key {key!r}"
                )
            result[key] = _normalize_json(
                raw_value,
                path=f"{path}.{key}",
                depth=depth + 1,
                budget=budget,
                text_budget=text_budget,
            )
        return result

    raise TypeError(f"{path} contains unsupported active value type")


def tool_arguments_fingerprint(arguments: Mapping[str, object]) -> str:
    if type(arguments) not in (dict, MappingProxyType):
        raise TypeError("arguments must use a passive built-in mapping")
    encoded = json.dumps(
        _normalize_json(arguments),
        allow_nan=False,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


_MAX_TOOL_RESULT_DEPTH = 32
_MAX_TOOL_RESULT_ITEMS = 4096
_MAX_TOOL_RESULT_TEXT_BYTES = 256 * 1024


def _snapshot_tool_output(
    value: object,
    *,
    path: str = "tool output",
    depth: int = 0,
    remaining_items: list[int] | None = None,
    remaining_text_bytes: list[int] | None = None,
) -> object:
    """Detach and bound passive handler output before it crosses Agent authority.

    Exact built-in types prevent custom scalar/container subclasses from carrying
    executable hooks into later serialization, persistence or model turns.
    """

    if depth > _MAX_TOOL_RESULT_DEPTH:
        raise ValueError("tool output nesting is too deep")
    budget = remaining_items if remaining_items is not None else [_MAX_TOOL_RESULT_ITEMS]
    text_budget = (
        remaining_text_bytes
        if remaining_text_bytes is not None
        else [_MAX_TOOL_RESULT_TEXT_BYTES]
    )

    if value is None or type(value) in (bool, int):
        return value
    if type(value) is str:
        canonical = unicodedata.normalize("NFC", value)
        text_budget[0] -= len(canonical.encode("utf-8"))
        if text_budget[0] < 0:
            raise ValueError("tool output text is too large")
        return canonical
    if type(value) is float:
        if not isfinite(value):
            raise ValueError(f"{path} must not contain NaN/infinity")
        return value
    if type(value) is list:
        budget[0] -= len(value)
        if budget[0] < 0:
            raise ValueError("tool output has too many items")
        return [
            _snapshot_tool_output(
                item,
                path=f"{path}[{index}]",
                depth=depth + 1,
                remaining_items=budget,
                remaining_text_bytes=text_budget,
            )
            for index, item in enumerate(value)
        ]
    if type(value) is tuple:
        budget[0] -= len(value)
        if budget[0] < 0:
            raise ValueError("tool output has too many items")
        return tuple(
            _snapshot_tool_output(
                item,
                path=f"{path}[{index}]",
                depth=depth + 1,
                remaining_items=budget,
                remaining_text_bytes=text_budget,
            )
            for index, item in enumerate(value)
        )
    if type(value) is dict:
        budget[0] -= len(value)
        if budget[0] < 0:
            raise ValueError("tool output has too many items")
        snapshot: dict[str, object] = {}
        for key, item in value.items():
            if type(key) is not str:
                raise TypeError(f"{path} keys must be exact text")
            canonical_key = unicodedata.normalize("NFC", key)
            text_budget[0] -= len(canonical_key.encode("utf-8"))
            if text_budget[0] < 0:
                raise ValueError("tool output text is too large")
            if canonical_key in snapshot:
                raise ValueError(
                    f"{path} contains duplicate normalized key {canonical_key!r}"
                )
            snapshot[canonical_key] = _snapshot_tool_output(
                item,
                path=f"{path}.{canonical_key}",
                depth=depth + 1,
                remaining_items=budget,
                remaining_text_bytes=text_budget,
            )
        return snapshot
    raise TypeError(f"{path} contains unsupported value type {type(value).__name__}")


class ToolHandler(Protocol):
    async def __call__(self, arguments: Mapping[str, object]) -> object: ...


ApprovalPolicy = Callable[[ToolSpec, ToolCall], Awaitable[ToolAuthorization | None]]


class ToolEffectGuard(Protocol):
    """Durable reserve/act/finalize boundary supplied by the host layer."""

    def reserve(self, *, spec: ToolSpec, call: ToolCall) -> object: ...
    def completed_output(self, reservation: object) -> tuple[bool, object | None]: ...
    def complete(self, reservation: object, output: object) -> None: ...
    def mark_uncertain(self, reservation: object) -> None: ...


class ToolExecutor:
    def __init__(
        self,
        *,
        approval_policy: ApprovalPolicy | None = None,
        effect_guard: ToolEffectGuard | None = None,
    ) -> None:
        self._tools: dict[str, tuple[ToolSpec, ToolHandler]] = {}
        self._approval_policy = approval_policy
        self._effect_guard = effect_guard

    def register(self, spec: ToolSpec, handler: ToolHandler) -> None:
        if type(spec) is not ToolSpec:
            raise TypeError("spec must be ToolSpec")
        if not callable(handler):
            raise TypeError("handler must be callable")
        if spec.tool_id in self._tools:
            raise ValueError(f"duplicate tool_id: {spec.tool_id}")
        self._tools[spec.tool_id] = (spec, handler)

    def specs(self) -> tuple[ToolSpec, ...]:
        return tuple(
            spec
            for spec, _handler in sorted(
                self._tools.values(), key=lambda item: item[0].tool_id
            )
        )

    async def execute(self, call: ToolCall) -> ToolResult:
        if type(call) is not ToolCall:
            raise TypeError("call must be ToolCall")
        registered = self._tools.get(call.tool_id)
        if registered is None:
            return ToolResult(call.call_id, call.tool_id, error="unknown tool")
        spec, handler = registered
        external = spec.risk in {
            ToolRisk.EXTERNAL_SIDE_EFFECT,
            ToolRisk.HIGH_IMPACT,
        }
        reservation: object | None = None
        effective_call = call

        if external:
            if self._approval_policy is None or self._effect_guard is None:
                return ToolResult(
                    call.call_id,
                    call.tool_id,
                    error="approval and durable effect guard required",
                )
            try:
                authorization = await self._approval_policy(spec, call)
            except asyncio.CancelledError:
                raise
            except Exception:
                return ToolResult(call.call_id, call.tool_id, error="approval required")
            if authorization is None or not self._authorization_matches(
                authorization, spec, call
            ):
                return ToolResult(call.call_id, call.tool_id, error="approval required")
            effective_call = replace(call, authorization=authorization)
            try:
                reservation = self._effect_guard.reserve(
                    spec=spec, call=effective_call
                )
                completed, output = self._effect_guard.completed_output(reservation)
                if completed:
                    try:
                        output = _snapshot_tool_output(output)
                    except (TypeError, ValueError):
                        return ToolResult(
                            call.call_id,
                            call.tool_id,
                            error="tool result not safe",
                        )
                    return ToolResult(call.call_id, call.tool_id, output=output)
            except Exception:
                return ToolResult(
                    call.call_id,
                    call.tool_id,
                    error="tool effect not safe to execute",
                )

        try:
            output = await asyncio.wait_for(
                handler(effective_call.arguments),
                timeout=spec.timeout_seconds,
            )
        except asyncio.CancelledError:
            self._mark_uncertain(reservation)
            raise
        except TimeoutError:
            self._mark_uncertain(reservation)
            return ToolResult(call.call_id, call.tool_id, error="tool timed out")
        except Exception:
            self._mark_uncertain(reservation)
            return ToolResult(call.call_id, call.tool_id, error="tool failed")

        try:
            output = _snapshot_tool_output(output)
        except (TypeError, ValueError):
            self._mark_uncertain(reservation)
            return ToolResult(call.call_id, call.tool_id, error="tool result not safe")

        if reservation is not None:
            try:
                assert self._effect_guard is not None
                json.dumps(
                    output,
                    allow_nan=False,
                    ensure_ascii=False,
                    sort_keys=True,
                )
                self._effect_guard.complete(reservation, output)
            except Exception:
                self._mark_uncertain(reservation)
                return ToolResult(
                    call.call_id,
                    call.tool_id,
                    error="tool result durability failed",
                )
        return ToolResult(call.call_id, call.tool_id, output=output)

    def _mark_uncertain(self, reservation: object | None) -> None:
        if reservation is None or self._effect_guard is None:
            return
        try:
            self._effect_guard.mark_uncertain(reservation)
        except Exception:
            pass

    @staticmethod
    def _authorization_matches(
        authorization: ToolAuthorization,
        spec: ToolSpec,
        call: ToolCall,
    ) -> bool:
        return (
            authorization.tool_id == spec.tool_id == call.tool_id
            and authorization.task_id == call.task_id
            and authorization.risk is spec.risk
            and authorization.arguments_fingerprint
            == tool_arguments_fingerprint(call.arguments)
        )
