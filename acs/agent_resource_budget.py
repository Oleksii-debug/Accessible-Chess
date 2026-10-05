from __future__ import annotations

"""Agent resource-ceiling narrowing.

Adapted from first-party donor:
Oleksii-debug/ChatGPT-Autopilot-ExtensionChatGPT-Autopilot-Extension@main
src/core/agent-budget-admission.js
blob b6559a49247e89bc7c281b2fe5df25e505ea6bbc

A child/plan budget may only narrow owner authority, never expand it.
"""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class AgentResourceBudget:
    max_model_calls: int = 0
    max_runtime_seconds: int = 0
    max_cost_usd_micros: int = 0

    def __post_init__(self) -> None:
        for label, value, maximum in (
            ("max_model_calls", self.max_model_calls, 1_000_000),
            ("max_runtime_seconds", self.max_runtime_seconds, 31_536_000),
            ("max_cost_usd_micros", self.max_cost_usd_micros, (1 << 63) - 1),
        ):
            if type(value) is not int or value < 0 or value > maximum:
                raise ValueError(f"{label} is invalid")


@dataclass(frozen=True, slots=True)
class AgentResourceUsage:
    model_calls: int = 0
    runtime_seconds: int = 0
    cost_usd_micros: int = 0

    def __post_init__(self) -> None:
        for label, value in (
            ("model_calls", self.model_calls),
            ("runtime_seconds", self.runtime_seconds),
            ("cost_usd_micros", self.cost_usd_micros),
        ):
            if type(value) is not int or value < 0:
                raise ValueError(f"{label} must be a non-negative integer")


@dataclass(frozen=True, slots=True)
class AgentResourceAdmission:
    allowed: bool
    reason: str
    effective_budget: AgentResourceBudget


def narrow_agent_budget(
    owner: AgentResourceBudget,
    plan: AgentResourceBudget,
) -> AgentResourceBudget:
    if type(owner) is not AgentResourceBudget or type(plan) is not AgentResourceBudget:
        raise TypeError("owner and plan must be AgentResourceBudget")
    return AgentResourceBudget(
        max_model_calls=min(owner.max_model_calls, plan.max_model_calls),
        max_runtime_seconds=min(owner.max_runtime_seconds, plan.max_runtime_seconds),
        max_cost_usd_micros=min(owner.max_cost_usd_micros, plan.max_cost_usd_micros),
    )


def evaluate_agent_resource_admission(
    *,
    owner_budget: AgentResourceBudget,
    plan_budget: AgentResourceBudget,
    current_usage: AgentResourceUsage,
    requested: AgentResourceUsage,
) -> AgentResourceAdmission:
    if type(current_usage) is not AgentResourceUsage or type(requested) is not AgentResourceUsage:
        raise TypeError("usage values must be AgentResourceUsage")
    effective = narrow_agent_budget(owner_budget, plan_budget)
    projections = (
        (
            current_usage.model_calls + requested.model_calls,
            effective.max_model_calls,
            "model_call_budget_exceeded",
        ),
        (
            current_usage.runtime_seconds + requested.runtime_seconds,
            effective.max_runtime_seconds,
            "runtime_budget_exceeded",
        ),
        (
            current_usage.cost_usd_micros + requested.cost_usd_micros,
            effective.max_cost_usd_micros,
            "cost_budget_exceeded",
        ),
    )
    for projected, maximum, reason in projections:
        if projected > maximum:
            return AgentResourceAdmission(False, reason, effective)
    return AgentResourceAdmission(True, "admitted", effective)


__all__ = [
    "AgentResourceAdmission",
    "AgentResourceBudget",
    "AgentResourceUsage",
    "evaluate_agent_resource_admission",
    "narrow_agent_budget",
]
