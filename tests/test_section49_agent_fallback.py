"""Section 49: prove explicit provider failover reuses canonical Universal Agent and ModelGateway."""
from __future__ import annotations

import json
import unittest

from acs.agent_model_contracts import (
    ModelErrorCode, ModelFailureEffect, ModelGatewayError, ModelResponse,
    ModelUsage, PrivacyClass, ProviderCapabilities, ProviderKind,
)
from acs.agent_model_gateway import ModelGateway
from acs.agent_tools import ToolExecutor
from acs.universal_chess_agent import (
    AgentRunPolicy, UniversalChessAgentRuntime,
)


class FixtureProvider:
    def __init__(self, name: str, *, effect=ModelFailureEffect.NO_EFFECT,
                 code=None, private=False):
        self.capabilities = ProviderCapabilities(
            provider_id=name, kind=ProviderKind.CLOUD,
            supports_private_data=private, supports_hard_cancellation=False,
        )
        self.calls = 0
        self.effect = effect
        self.code = code

    async def complete(self, request):
        self.calls += 1
        if self.code is not None:
            raise ModelGatewayError(
                self.code, "fixture route unavailable",
                provider_id=self.capabilities.provider_id,
                retryable=True, failure_effect=self.effect,
            )
        return ModelResponse(
            request_id=request.request_id,
            text=json.dumps({"type": "final",
                             "text": "The agent used a registered provider."}),
            provider_id=self.capabilities.provider_id,
            provider_kind=ProviderKind.CLOUD,
            model=self.capabilities.provider_id + "-fixture-model",
            usage=ModelUsage(input_tokens=3, output_tokens=6, total_tokens=9),
            latency_ms=0.2,
        )


class AgentFallbackIntegration(unittest.IsolatedAsyncioTestCase):
    def make_agent(self, primary, backup, *, private=False):
        gateway = ModelGateway()
        gateway.register(primary)
        gateway.register(backup)
        policy = AgentRunPolicy(
            privacy=(PrivacyClass.PRIVATE if private else PrivacyClass.PUBLIC),
            fallback_provider_ids=(backup.capabilities.provider_id,),
            max_steps=2, max_model_calls=2,
        )
        return UniversalChessAgentRuntime(
            gateway=gateway, tools=ToolExecutor(),
            provider_id=primary.capabilities.provider_id,
            product_instruction="Explain only verified chess facts.",
            policy=policy,
        )

    async def test_missing_primary_route_safe_fallback_to_secondary(self):
        first = FixtureProvider("mistral", code=ModelErrorCode.UNAVAILABLE)
        second = FixtureProvider("groq")
        agent = self.make_agent(first, second)
        result = await agent.run(run_id="s49-fallback", user_text="Explain FEN.")
        self.assertIn("registered provider", result.text)
        self.assertEqual(first.calls, 1)
        self.assertEqual(second.calls, 1)
        self.assertEqual(result.model_calls, 1)
        self.assertEqual(result.tool_calls, 0)

    async def test_unknown_effect_does_not_duplicate_request(self):
        first = FixtureProvider(
            "mistral", code=ModelErrorCode.RATE_LIMITED,
            effect=ModelFailureEffect.UNKNOWN,
        )
        second = FixtureProvider("groq")
        agent = self.make_agent(first, second)
        with self.assertRaises(ModelGatewayError) as raised:
            await agent.run(run_id="s49-no-duplicate", user_text="Verify PGN.")
        self.assertEqual(raised.exception.code, ModelErrorCode.RATE_LIMITED)
        self.assertEqual(first.calls, 1)
        self.assertEqual(second.calls, 0)

    async def test_private_prompt_denied_on_all_unapproved_routes(self):
        first = FixtureProvider("mistral")
        second = FixtureProvider("groq")
        agent = self.make_agent(first, second, private=True)
        with self.assertRaises(ModelGatewayError) as raised:
            await agent.run(run_id="s49-privacy", user_text="Private PGN.")
        self.assertEqual(raised.exception.code, ModelErrorCode.INVALID_REQUEST)
        self.assertEqual(first.calls, 0)
        self.assertEqual(second.calls, 0)

    def test_invalid_or_ambiguous_routes_are_rejected_at_policy_boundary(self):
        for routes in (("groq", "groq"), ("",), ("has\nlinebreak",), tuple("x" for _ in range(9))):
            with self.assertRaises((ValueError, TypeError)):
                AgentRunPolicy(fallback_provider_ids=routes)
        first = FixtureProvider("mistral")
        backup = FixtureProvider("groq")
        gateway = ModelGateway()
        gateway.register(first)
        gateway.register(backup)
        with self.assertRaises(ValueError):
            UniversalChessAgentRuntime(
                gateway=gateway, tools=ToolExecutor(),
                provider_id="mistral",
                product_instruction="Safe chess text",
                model="mistral-specific-model",
                policy=AgentRunPolicy(fallback_provider_ids=("groq",)),
            )
        with self.assertRaises(ValueError):
            UniversalChessAgentRuntime(
                gateway=gateway, tools=ToolExecutor(),
                provider_id="mistral",
                product_instruction="Safe chess text",
                policy=AgentRunPolicy(fallback_provider_ids=("mistral",)),
            )


if __name__ == "__main__":
    unittest.main()
