from __future__ import annotations

"""Universal Chess Agent runtime over the Accessible Chess application-tool boundary.

Cross-repository design intake:
- Nika-Core ModelGateway + ToolExecutor contracts.
- ChatGPT Autopilot observe/reason/tool/verify orchestration and least-authority
  envelope principle.
- AutoTrade exact model-cost budget.

The runtime never exposes chain-of-thought and never gives the model direct
access to Board/SQLite/processes. The model may only request registered tools.
"""

import asyncio
import json
from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum
from math import isfinite
from typing import Mapping

from .agent_budget import ModelCostBudget
from .agent_model_contracts import (
    ModelFailureEffect,
    ModelGatewayError,
    ModelMessage,
    ModelRequest,
    PrivacyClass,
)
from .agent_model_gateway import ModelGateway
from .agent_tools import ToolCall, ToolExecutor


class AgentProtocolError(ValueError):
    pass


class AgentStepKind(StrEnum):
    TOOL = "tool"
    FINAL = "final"


@dataclass(frozen=True, slots=True)
class AgentRunPolicy:
    max_steps: int = 12
    max_model_calls: int = 12
    max_response_chars: int = 32_000
    model_timeout_seconds: float = 90.0
    privacy: PrivacyClass = PrivacyClass.PRIVATE
    estimated_cost_per_model_call: Decimal = Decimal("0")

    def __post_init__(self) -> None:
        for name in ("max_steps", "max_model_calls", "max_response_chars"):
            value = getattr(self, name)
            if type(value) is not int or value <= 0:
                raise ValueError(f"{name} must be a positive integer")
        if type(self.model_timeout_seconds) not in (int, float):
            raise ValueError("model_timeout_seconds must be finite and positive")
        try:
            finite_timeout = isfinite(float(self.model_timeout_seconds))
        except OverflowError:
            finite_timeout = False
        if not finite_timeout or self.model_timeout_seconds <= 0:
            raise ValueError("model_timeout_seconds must be finite and positive")
        if not isinstance(self.privacy, PrivacyClass):
            raise TypeError("privacy must be PrivacyClass")
        cost = (
            self.estimated_cost_per_model_call
            if isinstance(self.estimated_cost_per_model_call, Decimal)
            else Decimal(str(self.estimated_cost_per_model_call))
        )
        if not cost.is_finite() or cost < 0:
            raise ValueError("estimated_cost_per_model_call must be finite and non-negative")
        object.__setattr__(self, "estimated_cost_per_model_call", cost)


@dataclass(frozen=True, slots=True)
class AgentRunResult:
    text: str
    model_calls: int
    tool_calls: int
    steps: int
    stopped: bool = False


def _tool_catalog(executor: ToolExecutor) -> str:
    items = [
        {
            "tool_id": spec.tool_id,
            "description": spec.description,
            "risk": spec.risk.value,
            "input_schema": dict(spec.input_schema),
        }
        for spec in executor.specs()
    ]
    return json.dumps(items, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _system_prompt(executor: ToolExecutor, product_instruction: str) -> str:
    if type(product_instruction) is not str:
        raise TypeError("product_instruction must be text")
    base = product_instruction.strip()
    if not base:
        raise ValueError("product_instruction must not be empty")
    return (
        base
        + "\n\nYou are the Accessible Chess Universal Chess Agent. "
        "Canonical chess state belongs to Accessible Chess tools, never to you. "
        "Do not invent board state. When a tool is needed, request exactly one "
        "registered tool. Return ONLY one JSON object with no markdown. "
        "Allowed response shapes:\n"
        '{"type":"tool","tool_id":"registered.id","arguments":{...}}\n'
        '{"type":"final","text":"user-visible answer"}\n'
        "Never include hidden reasoning, chain-of-thought, credentials or "
        "unregistered fields. Registered tools:\n"
        + _tool_catalog(executor)
    )


def _strict_json_object_pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
    value: dict[str, object] = {}
    for key, item in pairs:
        if key in value:
            raise AgentProtocolError("model response contains duplicate JSON object keys")
        value[key] = item
    return value


def _reject_json_constant(_value: str) -> object:
    raise AgentProtocolError("model response contains a non-finite JSON number")


_MAX_AGENT_JSON_DEPTH = 64
_MAX_AGENT_JSON_ITEMS = 4096


def _validate_json_structure(value: object) -> None:
    stack: list[tuple[object, int]] = [(value, 0)]
    remaining_items = _MAX_AGENT_JSON_ITEMS
    while stack:
        current, depth = stack.pop()
        if depth > _MAX_AGENT_JSON_DEPTH:
            raise AgentProtocolError("model response JSON nesting is too deep")
        if type(current) is dict:
            remaining_items -= len(current)
            if remaining_items < 0:
                raise AgentProtocolError("model response JSON has too many items")
            stack.extend((item, depth + 1) for item in current.values())
        elif type(current) is list:
            remaining_items -= len(current)
            if remaining_items < 0:
                raise AgentProtocolError("model response JSON has too many items")
            stack.extend((item, depth + 1) for item in current)
        elif current is None or type(current) in (bool, int, float, str):
            continue
        else:  # pragma: no cover - stdlib JSON cannot produce other values
            raise AgentProtocolError("model response JSON contains unsupported data")


def _strict_step(raw: str, *, max_chars: int) -> tuple[AgentStepKind, str, Mapping[str, object] | None]:
    if type(raw) is not str:
        raise AgentProtocolError("model response must be text")
    if len(raw) > max_chars:
        raise AgentProtocolError("model response exceeded the bounded protocol size")
    try:
        value = json.loads(
            raw,
            object_pairs_hook=_strict_json_object_pairs,
            parse_constant=_reject_json_constant,
        )
    except AgentProtocolError:
        raise
    except (json.JSONDecodeError, RecursionError, ValueError) as exc:
        raise AgentProtocolError("model response is not valid agent JSON") from exc
    _validate_json_structure(value)
    if type(value) is not dict:
        raise AgentProtocolError("agent response must be a JSON object")
    kind = value.get("type")
    if kind == AgentStepKind.FINAL.value:
        if set(value) != {"type", "text"}:
            raise AgentProtocolError("final response contains unknown fields")
        text = value.get("text")
        if type(text) is not str or not text.strip():
            raise AgentProtocolError("final response text must be non-empty")
        return AgentStepKind.FINAL, text.strip(), None
    if kind == AgentStepKind.TOOL.value:
        if set(value) != {"type", "tool_id", "arguments"}:
            raise AgentProtocolError("tool response contains unknown fields")
        tool_id = value.get("tool_id")
        arguments = value.get("arguments")
        if type(tool_id) is not str or not tool_id or tool_id != tool_id.strip():
            raise AgentProtocolError("tool_id must be canonical text")
        if type(arguments) is not dict:
            raise AgentProtocolError("tool arguments must be a JSON object")
        return AgentStepKind.TOOL, tool_id, arguments
    raise AgentProtocolError("agent response type is unsupported")


class UniversalChessAgentRuntime:
    """One bounded cancellable model/tool loop for the full chess platform."""

    def __init__(
        self,
        *,
        gateway: ModelGateway,
        tools: ToolExecutor,
        provider_id: str,
        product_instruction: str,
        model: str | None = None,
        policy: AgentRunPolicy | None = None,
        budget: ModelCostBudget | None = None,
    ) -> None:
        if type(gateway) is not ModelGateway:
            raise TypeError("gateway must be ModelGateway")
        if type(tools) is not ToolExecutor:
            raise TypeError("tools must be ToolExecutor")
        if type(provider_id) is not str or not provider_id or provider_id != provider_id.strip():
            raise ValueError("provider_id must be non-empty canonical text")
        if model is not None and (type(model) is not str or not model or model != model.strip()):
            raise ValueError("model must be canonical text or None")
        self.gateway = gateway
        self.tools = tools
        self.provider_id = provider_id
        self.model = model
        self.policy = policy or AgentRunPolicy()
        self.budget = budget
        self.system_prompt = _system_prompt(tools, product_instruction)
        self._active: dict[str, asyncio.Task[AgentRunResult]] = {}
        self._active_lock = asyncio.Lock()

    async def run(
        self,
        *,
        run_id: str,
        user_text: str,
        allowed_tool_ids: frozenset[str] | None = None,
    ) -> AgentRunResult:
        if type(run_id) is not str or not run_id or run_id != run_id.strip():
            raise ValueError("run_id must be non-empty canonical text")
        if type(user_text) is not str or not user_text.strip():
            raise ValueError("user_text must be non-empty")
        if allowed_tool_ids is not None:
            if type(allowed_tool_ids) is not frozenset:
                raise TypeError("allowed_tool_ids must be a frozenset or None")
            registered = {spec.tool_id for spec in self.tools.specs()}
            for tool_id in allowed_tool_ids:
                if (
                    type(tool_id) is not str
                    or not tool_id
                    or tool_id != tool_id.strip()
                ):
                    raise ValueError("allowed_tool_ids contains an invalid tool id")
                if tool_id not in registered:
                    raise ValueError("allowed_tool_ids contains an unregistered tool")
        async with self._active_lock:
            existing = self._active.get(run_id)
            if existing is not None and not existing.done():
                raise RuntimeError("an agent run with this identity is already active")
            task = asyncio.create_task(
                self._run_loop(
                    run_id=run_id,
                    user_text=user_text.strip(),
                    allowed_tool_ids=allowed_tool_ids,
                )
            )
            self._active[run_id] = task
        try:
            return await task
        finally:
            async with self._active_lock:
                if self._active.get(run_id) is task:
                    self._active.pop(run_id, None)

    async def cancel(self, run_id: str) -> bool:
        async with self._active_lock:
            task = self._active.get(run_id)
            if task is None or task.done():
                return False
            task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        return True

    def _release_or_quarantine_reservation(
        self,
        *,
        request_id: str,
        reservation: Decimal,
        failure_effect: ModelFailureEffect | None,
    ) -> None:
        if self.budget is None:
            return
        if failure_effect is ModelFailureEffect.NO_EFFECT:
            self.budget.release(request_id)
            return
        self.budget.settle(
            request_id,
            incurred=Decimal("0"),
            estimated_unbilled=reservation,
        )

    async def _run_loop(
        self,
        *,
        run_id: str,
        user_text: str,
        allowed_tool_ids: frozenset[str] | None,
    ) -> AgentRunResult:
        messages: list[ModelMessage] = [
            ModelMessage(role="system", content=self.system_prompt),
            ModelMessage(role="user", content=user_text),
        ]
        model_calls = 0
        tool_calls = 0

        for step_number in range(1, self.policy.max_steps + 1):
            if model_calls >= self.policy.max_model_calls:
                raise RuntimeError("agent model-call limit reached")
            request_id = f"{run_id}:model:{model_calls + 1}"
            reservation = self.policy.estimated_cost_per_model_call
            if self.budget is not None:
                # A zero estimate still needs a request lifecycle so a later
                # provider bill can be reconciled instead of becoming orphaned.
                self.budget.reserve(request_id, reservation)
            try:
                response = await self.gateway.complete(
                    ModelRequest(
                        request_id=request_id,
                        messages=tuple(messages),
                        provider_id=self.provider_id,
                        model=self.model,
                        privacy=self.policy.privacy,
                        timeout_seconds=self.policy.model_timeout_seconds,
                        temperature=0.0,
                    )
                )
            except ModelGatewayError as exc:
                self._release_or_quarantine_reservation(
                    request_id=request_id,
                    reservation=reservation,
                    failure_effect=exc.failure_effect,
                )
                raise
            except BaseException:
                self._release_or_quarantine_reservation(
                    request_id=request_id,
                    reservation=reservation,
                    failure_effect=None,
                )
                raise
            else:
                if self.budget is not None:
                    self.budget.settle(
                        request_id,
                        incurred=Decimal("0"),
                        estimated_unbilled=reservation,
                    )
            model_calls += 1

            kind, value, arguments = _strict_step(
                response.text,
                max_chars=self.policy.max_response_chars,
            )
            if kind is AgentStepKind.FINAL:
                return AgentRunResult(
                    text=value,
                    model_calls=model_calls,
                    tool_calls=tool_calls,
                    steps=step_number,
                )

            assert arguments is not None
            if allowed_tool_ids is not None and value not in allowed_tool_ids:
                raise AgentProtocolError("tool is not permitted for this run")
            tool_calls += 1
            call_id = f"{run_id}:tool:{tool_calls}"
            result = await self.tools.execute(
                ToolCall(
                    call_id=call_id,
                    tool_id=value,
                    arguments=arguments,
                    task_id=run_id,
                )
            )
            tool_payload = {
                "call_id": result.call_id,
                "tool_id": result.tool_id,
                "ok": result.ok,
                "output": result.output if result.ok else None,
                "error": result.error,
            }
            try:
                tool_text = json.dumps(
                    tool_payload,
                    allow_nan=False,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                )
            except (TypeError, ValueError) as exc:
                raise RuntimeError("tool result is not JSON-safe") from exc

            messages.append(ModelMessage(role="assistant", content=response.text))
            messages.append(ModelMessage(role="tool", content=tool_text))

        raise RuntimeError("agent step limit reached")
