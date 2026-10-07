from __future__ import annotations

import asyncio
import json
import unittest

import httpx

from acs.agent_model_contracts import (
    ModelErrorCode,
    ModelGatewayError,
    ModelMessage,
    ModelRequest,
)
from acs.agent_model_gateway import ModelGateway
from acs.agent_ollama_provider import OllamaProvider


def _response(text: str = "Вітаю", **extra):
    return {
        "model": "qwen3:8b",
        "done": True,
        "message": {"role": "assistant", "content": text},
        "prompt_eval_count": 10,
        "eval_count": 4,
        **extra,
    }


class Section21OllamaProviderTests(unittest.TestCase):
    def _provider(self, handler):
        self.requests = []

        def wrapped(request):
            self.requests.append(request)
            return handler(request)

        def factory(**kwargs):
            self.assertIs(kwargs["trust_env"], False)
            self.assertIs(kwargs["follow_redirects"], False)
            return httpx.AsyncClient(
                transport=httpx.MockTransport(wrapped),
                **kwargs,
            )

        return OllamaProvider(client_factory=factory)

    @staticmethod
    def _request():
        return ModelRequest(
            "request-1",
            (ModelMessage("user", "Яка позиція?"),),
            model="qwen3:8b",
        )

    def test_local_payload_is_exact_and_gateway_compatible(self):
        provider = self._provider(
            lambda _: httpx.Response(200, json=_response())
        )
        gateway = ModelGateway()
        gateway.register(provider)
        request = self._request()
        result = asyncio.run(
            gateway.complete(
                ModelRequest(
                    request_id=request.request_id,
                    messages=request.messages,
                    provider_id="ollama",
                    model=request.model,
                )
            )
        )
        self.assertEqual(result.text, "Вітаю")
        self.assertEqual(result.usage.total_tokens, 14)
        sent = json.loads(self.requests[0].content)
        self.assertEqual(
            str(self.requests[0].url),
            "http://localhost:11434/api/chat",
        )
        self.assertEqual(sent["model"], "qwen3:8b")
        self.assertIs(sent["stream"], False)
        self.assertIs(sent["think"], False)

    def test_endpoint_and_model_remain_local_only(self):
        for endpoint in (
            "https://example.org",
            "http://localhost:11434/api/chat",
            "http://user:secret@localhost:11434",
        ):
            with self.subTest(endpoint=endpoint), self.assertRaises(ValueError):
                OllamaProvider(base_url=endpoint)
        with self.assertRaises(ValueError):
            OllamaProvider(default_model="model:cloud")

    def test_invalid_or_oversized_provider_response_fails_closed(self):
        provider = self._provider(
            lambda _: httpx.Response(
                200,
                json=_response(done=False),
            )
        )
        with self.assertRaises(ModelGatewayError) as caught:
            asyncio.run(provider.complete(self._request()))
        self.assertIs(caught.exception.code, ModelErrorCode.PROVIDER_ERROR)

    def test_http_failure_does_not_leak_response_body(self):
        provider = self._provider(
            lambda _: httpx.Response(500, text="private provider detail")
        )
        with self.assertRaises(ModelGatewayError) as caught:
            asyncio.run(provider.complete(self._request()))
        self.assertNotIn("private provider detail", str(caught.exception))
        self.assertIs(caught.exception.code, ModelErrorCode.UNAVAILABLE)


if __name__ == "__main__":
    unittest.main()
