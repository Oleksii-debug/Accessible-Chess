from __future__ import annotations

"""Explicit reliability/resource/permission envelope for Universal Chess Agent runs."""

from dataclasses import dataclass

from .agent_resource_budget import (
    AgentResourceAdmission,
    AgentResourceBudget,
    AgentResourceUsage,
    evaluate_agent_resource_admission,
)
from .agent_tools import ToolExecutor, ToolRisk
from .universal_chess_agent import AgentRunResult, UniversalChessAgentRuntime


class AgentReliabilityError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class AgentPermissionPolicy:
    """Least-authority tool policy for one run family.

    Tool ids are exact; wildcards are intentionally unsupported.  HIGH_IMPACT
    tools require an explicit opt-in in addition to ToolExecutor approval/effect
    guards, so this policy can only narrow the underlying executor authority.
    """

    allowed_tool_ids: frozenset[str] = frozenset()
    allow_high_impact: bool = False

    def __post_init__(self) -> None:
        if type(self.allowed_tool_ids) is not frozenset:
            raise TypeError("allowed_tool_ids must be a frozenset")
        for value in self.allowed_tool_ids:
            if (
                type(value) is not str
                or not value
                or value != value.strip()
                or len(value) > 180
            ):
                raise ValueError("allowed_tool_ids contains invalid text")
        if type(self.allow_high_impact) is not bool:
            raise TypeError("allow_high_impact must be boolean")

    def validate(self, executor: ToolExecutor) -> frozenset[str]:
        if type(executor) is not ToolExecutor:
            raise TypeError("executor must be ToolExecutor")
        specs = {spec.tool_id: spec for spec in executor.specs()}
        for tool_id in self.allowed_tool_ids:
            spec = specs.get(tool_id)
            if spec is None:
                raise AgentReliabilityError(f"unregistered permitted tool: {tool_id}")
            if spec.risk is ToolRisk.HIGH_IMPACT and not self.allow_high_impact:
                raise AgentReliabilityError("high-impact tool requires explicit policy")
        return self.allowed_tool_ids


@dataclass(frozen=True, slots=True)
class AgentResourcePolicy:
    owner_budget: AgentResourceBudget
    plan_budget: AgentResourceBudget

    def __post_init__(self) -> None:
        if type(self.owner_budget) is not AgentResourceBudget:
            raise TypeError("owner_budget must be AgentResourceBudget")
        if type(self.plan_budget) is not AgentResourceBudget:
            raise TypeError("plan_budget must be AgentResourceBudget")

    def admit(
        self,
        *,
        current_usage: AgentResourceUsage,
        requested: AgentResourceUsage,
    ) -> AgentResourceAdmission:
        admission = evaluate_agent_resource_admission(
            owner_budget=self.owner_budget,
            plan_budget=self.plan_budget,
            current_usage=current_usage,
            requested=requested,
        )
        if not admission.allowed:
            raise AgentReliabilityError(admission.reason)
        return admission


class ReliableAgentSession:
    """Narrow a Universal Agent run without creating another runtime authority."""

    def __init__(
        self,
        *,
        runtime: UniversalChessAgentRuntime,
        permissions: AgentPermissionPolicy,
        resources: AgentResourcePolicy,
    ) -> None:
        if type(runtime) is not UniversalChessAgentRuntime:
            raise TypeError("runtime must be UniversalChessAgentRuntime")
        if type(permissions) is not AgentPermissionPolicy:
            raise TypeError("permissions must be AgentPermissionPolicy")
        if type(resources) is not AgentResourcePolicy:
            raise TypeError("resources must be AgentResourcePolicy")
        permissions.validate(runtime.tools)
        self.runtime = runtime
        self.permissions = permissions
        self.resources = resources

    async def run(
        self,
        *,
        run_id: str,
        user_text: str,
        current_usage: AgentResourceUsage,
        requested_usage: AgentResourceUsage,
    ) -> AgentRunResult:
        self.resources.admit(
            current_usage=current_usage,
            requested=requested_usage,
        )
        allowed = self.permissions.validate(self.runtime.tools)
        return await self.runtime.run(
            run_id=run_id,
            user_text=user_text,
            allowed_tool_ids=allowed,
        )

    async def cancel(self, run_id: str) -> bool:
        return await self.runtime.cancel(run_id)


__all__ = [
    "AgentPermissionPolicy",
    "AgentReliabilityError",
    "AgentResourcePolicy",
    "ReliableAgentSession",
]
