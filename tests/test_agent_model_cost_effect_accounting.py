from __future__ import annotations

import asyncio
import unittest
from decimal import Decimal

from acs.agent_budget import ModelCostBudget
from acs.agent_model_contracts import (
    ModelErrorCode,
    ModelFailureEffect,
    ModelGatewayError,
    ModelRequest,
    ModelResponse,
    ModelUsage,
    ProviderCapabilities,
    ProviderKind,
)
from acs.agent_model_gateway import ModelGateway
from acs.agent_tools import ToolExecutor
from acs.universal_chess_agent import AgentRunPolicy, UniversalChessAgentRuntime


class _Provider:
    def __init__(self, *, failure_effect: ModelFailureEffect | None = None) -> None:
        self.failure_effect = failure_effect
        self.calls = 0

    @property
    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(
            provider_id="fixture",
            kind=ProviderKind.LOCAL,
            supports_private_data=True,
        )

    async def complete(self, request: ModelRequest) -> ModelResponse:
        self.calls += 1
        if self.failure_effect is not None:
            raise ModelGatewayError(
                ModelErrorCode.PROVIDER_ERROR,
                "provider diagnostic must not affect budget semantics",
                provider_id="fixture",
                retryable=False,
                failure_effect=self.failure_effect,
            )
        return ModelResponse(
            request_id=request.request_id,
            text='{"type":"final","text":"done"}',
            provider_id="fixture",
            provider_kind=ProviderKind.LOCAL,
            model=request.model or "fixture-model",
            usage=ModelUsage(total_tokens=3),
        )


class _SelfCancellingProvider(_Provider):
    async def complete(self, _request: ModelRequest) -> ModelResponse:
        self.calls += 1
        raise asyncio.CancelledError()


def _runtime(
    provider: _Provider,
    budget: ModelCostBudget,
    *,
    estimated_cost: Decimal = Decimal("0.40"),
) -> UniversalChessAgentRuntime:
    gateway = ModelGateway()
    gateway.register(provider)
    return UniversalChessAgentRuntime(
        gateway=gateway,
        tools=ToolExecutor(),
        provider_id="fixture",
        product_instruction="Answer through the bounded agent protocol.",
        policy=AgentRunPolicy(
            max_steps=1,
            max_model_calls=1,
            estimated_cost_per_model_call=estimated_cost,
        ),
        budget=budget,
    )


class AgentModelCostEffectAccountingTests(unittest.TestCase):
    def test_success_keeps_conservative_cost_as_estimated_unbilled(self) -> None:
        budget = ModelCostBudget("1.00")
        result = asyncio.run(_runtime(_Provider(), budget).run(run_id="success", user_text="go"))

        self.assertEqual(result.text, "done")
        snapshot = budget.snapshot()
        self.assertEqual(snapshot.reserved, Decimal("0"))
        self.assertEqual(snapshot.incurred, Decimal("0"))
        self.assertEqual(snapshot.estimated_unbilled, Decimal("0.40"))
        self.assertEqual(snapshot.available, Decimal("0.60"))

    def test_successful_estimate_is_not_double_counted_when_bill_arrives(self) -> None:
        budget = ModelCostBudget("1.00")
        asyncio.run(_runtime(_Provider(), budget).run(run_id="bill", user_text="go"))

        budget.reconcile_unbilled(
            billing_id="provider-bill-1",
            request_id="bill:model:1",
            billed=Decimal("0.25"),
        )

        snapshot = budget.snapshot()
        self.assertEqual(snapshot.incurred, Decimal("0.25"))
        self.assertEqual(snapshot.estimated_unbilled, Decimal("0.15"))
        self.assertEqual(snapshot.available, Decimal("0.60"))

    def test_unknown_provider_effect_quarantines_full_reservation(self) -> None:
        budget = ModelCostBudget("1.00")
        runtime = _runtime(_Provider(failure_effect=ModelFailureEffect.UNKNOWN), budget)

        with self.assertRaises(ModelGatewayError):
            asyncio.run(runtime.run(run_id="unknown", user_text="go"))

        snapshot = budget.snapshot()
        self.assertEqual(snapshot.reserved, Decimal("0"))
        self.assertEqual(snapshot.incurred, Decimal("0"))
        self.assertEqual(snapshot.estimated_unbilled, Decimal("0.40"))
        self.assertEqual(snapshot.available, Decimal("0.60"))
        with self.assertRaisesRegex(ValueError, "budget exhausted"):
            budget.reserve("must-not-fit", Decimal("0.70"))

    def test_proven_no_effect_releases_reservation_for_reuse(self) -> None:
        budget = ModelCostBudget("1.00")
        runtime = _runtime(_Provider(failure_effect=ModelFailureEffect.NO_EFFECT), budget)

        with self.assertRaises(ModelGatewayError):
            asyncio.run(runtime.run(run_id="no-effect", user_text="go"))

        snapshot = budget.snapshot()
        self.assertEqual(snapshot.reserved, Decimal("0"))
        self.assertEqual(snapshot.incurred, Decimal("0"))
        self.assertEqual(snapshot.estimated_unbilled, Decimal("0"))
        self.assertEqual(snapshot.available, Decimal("1.00"))
        budget.reserve("reusable", Decimal("0.70"))
        self.assertEqual(budget.snapshot().reserved, Decimal("0.70"))

    def test_cancellation_without_effect_proof_quarantines_reservation(self) -> None:
        budget = ModelCostBudget("1.00")
        runtime = _runtime(_SelfCancellingProvider(), budget)

        with self.assertRaises(ModelGatewayError) as caught:
            asyncio.run(runtime.run(run_id="cancelled", user_text="go"))
        self.assertEqual(caught.exception.code, ModelErrorCode.CANCELLED)
        self.assertIs(caught.exception.failure_effect, ModelFailureEffect.UNKNOWN)

        snapshot = budget.snapshot()
        self.assertEqual(snapshot.reserved, Decimal("0"))
        self.assertEqual(snapshot.incurred, Decimal("0"))
        self.assertEqual(snapshot.estimated_unbilled, Decimal("0.40"))
        self.assertEqual(snapshot.available, Decimal("0.60"))

    def test_zero_estimate_success_still_accepts_later_provider_bill(self) -> None:
        budget = ModelCostBudget("1.00")
        asyncio.run(
            _runtime(
                _Provider(),
                budget,
                estimated_cost=Decimal("0"),
            ).run(run_id="zero-success", user_text="go")
        )

        before_bill = budget.snapshot()
        self.assertEqual(before_bill.reserved, Decimal("0"))
        self.assertEqual(before_bill.incurred, Decimal("0"))
        self.assertEqual(before_bill.estimated_unbilled, Decimal("0"))
        self.assertEqual(before_bill.available, Decimal("1.00"))

        budget.reconcile_unbilled(
            billing_id="provider-bill-zero-success",
            request_id="zero-success:model:1",
            billed=Decimal("0.25"),
        )
        after_bill = budget.snapshot()
        self.assertEqual(after_bill.incurred, Decimal("0.25"))
        self.assertEqual(after_bill.estimated_unbilled, Decimal("0"))
        self.assertEqual(after_bill.available, Decimal("0.75"))

    def test_zero_estimate_unknown_effect_still_accepts_later_provider_bill(self) -> None:
        budget = ModelCostBudget("1.00")
        runtime = _runtime(
            _Provider(failure_effect=ModelFailureEffect.UNKNOWN),
            budget,
            estimated_cost=Decimal("0"),
        )

        with self.assertRaises(ModelGatewayError):
            asyncio.run(runtime.run(run_id="zero-unknown", user_text="go"))

        budget.reconcile_unbilled(
            billing_id="provider-bill-zero-unknown",
            request_id="zero-unknown:model:1",
            billed=Decimal("0.30"),
        )
        snapshot = budget.snapshot()
        self.assertEqual(snapshot.reserved, Decimal("0"))
        self.assertEqual(snapshot.incurred, Decimal("0.30"))
        self.assertEqual(snapshot.estimated_unbilled, Decimal("0"))
        self.assertEqual(snapshot.available, Decimal("0.70"))

    def test_observed_bill_above_estimate_closes_available_budget_fail_closed(self) -> None:
        budget = ModelCostBudget("1.00")
        asyncio.run(_runtime(_Provider(), budget).run(run_id="over", user_text="go"))

        budget.reconcile_unbilled(
            billing_id="provider-bill-over",
            request_id="over:model:1",
            billed=Decimal("1.20"),
        )

        snapshot = budget.snapshot()
        self.assertEqual(snapshot.incurred, Decimal("1.20"))
        self.assertEqual(snapshot.estimated_unbilled, Decimal("0"))
        self.assertEqual(snapshot.available, Decimal("0"))
        with self.assertRaisesRegex(ValueError, "budget exhausted"):
            budget.reserve("blocked-after-overrun", Decimal("0.01"))


if __name__ == "__main__":
    unittest.main()
