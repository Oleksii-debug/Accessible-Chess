"""Section 49 offline qualification. All provider HTTP is mocked, never live."""
from __future__ import annotations

import asyncio
import json
import os
import unittest
from unittest.mock import patch

from acs.agent_cloud_provider import (
    CloudChatProvider, MAX_RESPONSE_BYTES, configured_provider_ids,
    provider_availability, register_configured_cloud_providers,
)
from acs.agent_model_contracts import (
    ModelErrorCode, ModelGatewayError, ModelMessage, ModelRequest,
    PrivacyClass, ProviderKind,
)
from acs.agent_model_gateway import ModelGateway

try:
    import httpx
except ImportError:
    httpx = None


def request(*, provider_id="mistral", private=False, fallbacks=(), model="test-model"):
    return ModelRequest(
        request_id="section49-fixture-1",
        provider_id=provider_id,
        provider_kind=ProviderKind.CLOUD,
        model=model,
        messages=(ModelMessage("system", "Do not invent chess moves."),
                  ModelMessage("user", "Explain the position: startpos.")),
        fallback_provider_ids=fallbacks,
        privacy=PrivacyClass.PRIVATE if private else PrivacyClass.PUBLIC,
        timeout_seconds=3.0,
    )


def success_json(model="test-model", answer='{"type":"final","text":"Legal moves need chess core verification."}'):
    return {
        "model": model,
        "choices": [{"index": 0, "message": {"role": "assistant", "content": answer},
                     "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 7, "completion_tokens": 9, "total_tokens": 16},
    }


@unittest.skipIf(httpx is None, "httpx is an optional provider dependency")
class CloudProviderTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.env = patch.dict(os.environ, {
            "MISTRAL_API_KEY": "unit-test-secret-do-not-log",
            "GROQ_API_KEY": "other-fixture-secret",
        })
        self.env.start()
        self.addCleanup(self.env.stop)
        self.seen = []

    def provider(self, *, name="mistral", handler=None, approved=False):
        def default_handler(req):
            self.seen.append(req)
            self.assertEqual(req.method, "POST")
            self.assertEqual(req.headers["Authorization"],
                             "Bearer " + ("unit-test-secret-do-not-log"
                                          if name == "mistral" else "other-fixture-secret"))
            self.assertEqual(req.url.scheme, "https")
            return httpx.Response(200, json=success_json())
        transport = httpx.MockTransport(handler or default_handler)
        return CloudChatProvider(
            provider_id=name, default_model="test-model",
            allow_private_data=approved,
            client_factory=lambda **kwargs: httpx.AsyncClient(
                transport=transport, **kwargs),
        )

    async def test_real_gateway_text_path_and_canonical_authority(self):
        gateway = ModelGateway()
        provider = self.provider()
        gateway.register(provider, default=True)
        output = await gateway.complete(request())
        self.assertEqual(output.provider_id, "mistral")
        self.assertEqual(output.model, "test-model")
        self.assertIn("chess core", output.text)
        self.assertEqual(output.usage.total_tokens, 16)
        self.assertEqual(len(self.seen), 1)
        self.assertFalse(provider.capabilities.supports_tools)
        self.assertFalse(provider.capabilities.supports_private_data)
        self.assertFalse(provider.capabilities.supports_hard_cancellation)

    async def test_missing_key_preflight_fallback_to_other_provider(self):
        with patch.dict(os.environ, {"MISTRAL_API_KEY": ""}):
            gateway = ModelGateway()
            gateway.register(self.provider())
            gateway.register(self.provider(name="groq"))
            value = await gateway.complete(request(fallbacks=("groq",)))
            self.assertEqual(value.provider_id, "groq")
            self.assertEqual(len(self.seen), 1)

    async def test_private_content_never_leaves_process_without_opt_in(self):
        gateway = ModelGateway()
        gateway.register(self.provider())
        with self.assertRaises(ModelGatewayError) as context:
            await gateway.complete(request(private=True))
        self.assertEqual(context.exception.code, ModelErrorCode.INVALID_REQUEST)
        self.assertFalse(self.seen)

    async def test_private_content_allowed_only_by_explicit_configuration(self):
        gateway = ModelGateway()
        gateway.register(self.provider(approved=True))
        result = await gateway.complete(request(private=True))
        self.assertEqual(result.provider_id, "mistral")

    async def test_auth_status_never_leaks_upstream_body(self):
        secret_echo = "unit-test-secret-do-not-log"
        p = self.provider(handler=lambda _r: httpx.Response(401, text=secret_echo))
        with self.assertRaises(ModelGatewayError) as context:
            await p.complete(request())
        self.assertEqual(context.exception.code, ModelErrorCode.AUTHENTICATION)
        self.assertNotIn(secret_echo, str(context.exception))

    async def test_429_does_not_duplicate_inference_via_fallback(self):
        first_calls = []
        def throttled(req):
            first_calls.append(req)
            return httpx.Response(429, json={"error": "throttled"})
        gateway = ModelGateway()
        gateway.register(self.provider(handler=throttled))
        gateway.register(self.provider(name="groq"))
        with self.assertRaises(ModelGatewayError) as context:
            await gateway.complete(request(fallbacks=("groq",)))
        self.assertEqual(context.exception.code, ModelErrorCode.RATE_LIMITED)
        self.assertEqual(len(first_calls), 1)
        self.assertFalse(self.seen, "UNKNOWN-effect 429 must not auto-retry")

    async def test_timeout_not_retried_or_claimed_success(self):
        def timeout(_req):
            raise httpx.ReadTimeout("unsafe upstream diagnostic")
        p = self.provider(handler=timeout)
        with self.assertRaises(ModelGatewayError) as context:
            await p.complete(request())
        self.assertEqual(context.exception.code, ModelErrorCode.TIMEOUT)
        self.assertNotIn("unsafe", str(context.exception))

    async def test_reject_mismatched_model_identity(self):
        p = self.provider(handler=lambda _req: httpx.Response(
            200, json=success_json(model="other-model")))
        with self.assertRaises(ModelGatewayError) as context:
            await p.complete(request())
        self.assertEqual(context.exception.code, ModelErrorCode.PROVIDER_ERROR)

    async def test_malformed_duplicate_key_json_denied(self):
        raw = b'{"model":"test-model","model":"other-model","choices":[]}'
        p = self.provider(handler=lambda _req: httpx.Response(200, content=raw))
        with self.assertRaises(ModelGatewayError):
            await p.complete(request())

    async def test_response_over_limit(self):
        p = self.provider(handler=lambda _req: httpx.Response(
            200, content=b"x" * (MAX_RESPONSE_BYTES + 1)))
        with self.assertRaises(ModelGatewayError) as context:
            await p.complete(request())
        self.assertEqual(context.exception.code, ModelErrorCode.RESOURCE_LIMIT)

    async def test_model_catalog_authenticated_listing(self):
        def handler(req):
            self.assertEqual(req.method, "GET")
            self.assertEqual(req.url.path, "/v1/models")
            return httpx.Response(200, json={"data": [{"id": "z"}, {"id": "a"}]})
        self.assertEqual(await self.provider(handler=handler).list_models(),
                         ("a", "z"))

    async def test_invalid_model_catalog_does_not_claim_usable(self):
        p = self.provider(handler=lambda _req: httpx.Response(
            200, json={"data": [{"id": ""}]}))
        with self.assertRaises(ModelGatewayError):
            await p.list_models()

    def test_environment_inventory_has_no_secret_values(self):
        status = provider_availability()
        self.assertEqual(status[0].provider_id, "mistral")
        self.assertEqual(status[0].mode, "CONFIGURED_UNVERIFIED")
        self.assertEqual(status[1].provider_id, "groq")
        self.assertIn("mistral", configured_provider_ids())
        self.assertNotIn("unit-test-secret-do-not-log", str(status))

    def test_unsupported_endpoint_or_paid_mode_not_inferable(self):
        with self.assertRaises(ValueError):
            CloudChatProvider(provider_id="https://evil.example",
                              default_model="x")
        with self.assertRaises(ValueError):
            CloudChatProvider(provider_id="mistral",
                              default_model="bad\nname")
        with self.assertRaises(ValueError):
            CloudChatProvider(provider_id="mistral",
                              default_model="x", max_output_tokens=100000)

    def test_explicit_registration_into_canonical_gateway(self):
        gateway = ModelGateway()
        chosen = register_configured_cloud_providers(
            gateway, models={"mistral": "test-model", "groq": "test-model"})
        self.assertEqual(chosen, ("mistral", "groq"))
        self.assertEqual(gateway.providers(), ("groq", "mistral"))


if __name__ == "__main__":
    unittest.main()
