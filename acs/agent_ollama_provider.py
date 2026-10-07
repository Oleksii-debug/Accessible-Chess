"""Native local Ollama provider for the existing Universal Chess Agent.

Adapted from Oleksii-debug/Nika-Core@6df8b80b7a248f1559a0ff96f74efa2d2c47ad14
src/nika_core/model_gateway/providers.py (OllamaProvider and usage mapping).
HTTPX is optional; importing or using deterministic chess needs no model/HTTP.
"""
from __future__ import annotations

import json
import time
from urllib.parse import urlsplit

from .agent_model_contracts import (
    ModelErrorCode, ModelFailureEffect, ModelGatewayError, ModelRequest,
    ModelResponse, ModelUsage, ProviderCapabilities, ProviderKind,
)

MAX_OLLAMA_RESPONSE_BYTES = 1024 * 1024
MAX_OLLAMA_REQUEST_CHARS = 256 * 1024


def _identifier(value: object) -> str:
    if type(value) is not str or not value or value != value.strip():
        raise ValueError("model must be non-empty canonical text")
    if len(value) > 256 or any(not char.isprintable() for char in value):
        raise ValueError("model name is invalid")
    # Local privacy policy must not silently route through Ollama cloud models.
    if "cloud" in value.casefold():
        raise ValueError("this adapter supports local models only")
    return value


def _optional_int(value: object) -> int | None:
    if value is None:
        return None
    if type(value) is not int or value < 0:
        raise ValueError("token count must be a non-negative integer")
    return value


def _json_pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate response field")
        result[key] = value
    return result


class OllamaProvider:
    """Local /api/chat; stream=false, think=false; no model acquisition.

    Configuration belongs to the host. A local Ollama server must be configured
    with cloud disabled (OLLAMA_NO_CLOUD=1). Closing HTTP is not evidence that
    server inference stopped, so hard cancellation and automatic retry are not
    advertised. The existing ModelGateway owns routing/privacy/error handling.
    """

    def __init__(self, *, default_model: str = "qwen3:8b",
                 base_url: str = "http://localhost:11434", client_factory=None):
        self._default_model = _identifier(default_model)
        if type(base_url) is not str:
            raise TypeError("base_url must be text")
        parsed = urlsplit(base_url)
        if (parsed.scheme != "http" or parsed.hostname not in
                {"localhost", "127.0.0.1", "::1"} or parsed.username is not None
                or parsed.password is not None or parsed.path not in {"", "/"}
                or parsed.query or parsed.fragment):
            raise ValueError("Ollama endpoint must be a local HTTP origin")
        if parsed.port is not None and not 1 <= parsed.port <= 65535:
            raise ValueError("Ollama port is invalid")
        self._base_url = base_url.rstrip("/")
        self._client_factory = client_factory
        self._capabilities = ProviderCapabilities(
            provider_id="ollama", kind=ProviderKind.LOCAL,
            supports_private_data=True, supports_hard_cancellation=False,
        )

    @property
    def capabilities(self) -> ProviderCapabilities:
        return self._capabilities

    async def complete(self, request: ModelRequest) -> ModelResponse:
        if type(request) is not ModelRequest:
            raise TypeError("request must be ModelRequest")
        model = _identifier(request.model or self._default_model)
        if sum(len(message.content) for message in request.messages) > MAX_OLLAMA_REQUEST_CHARS:
            raise ModelGatewayError(ModelErrorCode.RESOURCE_LIMIT,
                "local model input exceeds the configured limit", provider_id="ollama",
                failure_effect=ModelFailureEffect.NO_EFFECT)
        try:
            import httpx
        except ImportError:
            raise ModelGatewayError(ModelErrorCode.UNAVAILABLE,
                "optional local model HTTP component is not installed", provider_id="ollama",
                failure_effect=ModelFailureEffect.NO_EFFECT) from None
        payload = {
            "model": model,
            "messages": [{"role": message.role, "content": message.content}
                         for message in request.messages],
            "stream": False, "think": False,
        }
        if request.temperature is not None:
            payload["options"] = {"temperature": request.temperature}
        factory = self._client_factory or httpx.AsyncClient
        started = time.perf_counter()
        try:
            async with factory(timeout=request.timeout_seconds, trust_env=False,
                               follow_redirects=False) as client:
                async with client.stream("POST", self._base_url + "/api/chat", json=payload) as response:
                    response.raise_for_status()
                    raw = bytearray()
                    async for chunk in response.aiter_bytes():
                        if len(raw) + len(chunk) > MAX_OLLAMA_RESPONSE_BYTES:
                            raise ModelGatewayError(ModelErrorCode.RESOURCE_LIMIT,
                                "local model response exceeded the configured limit",
                                provider_id="ollama")
                        raw.extend(chunk)
            body = json.loads(raw, object_pairs_hook=_json_pairs)
            if type(body) is not dict or body.get("done") is not True:
                raise ValueError("incomplete model response")
            message = body["message"]
            if type(message) is not dict or message.get("role") != "assistant":
                raise ValueError("missing assistant response")
            text = message["content"]
            response_model = body["model"]
            if type(text) is not str or not text.strip() or response_model != model:
                raise ValueError("invalid model response identity")
            inputs = _optional_int(body.get("prompt_eval_count"))
            outputs = _optional_int(body.get("eval_count"))
        except httpx.TimeoutException:
            raise ModelGatewayError(ModelErrorCode.TIMEOUT,
                "local model request timed out", provider_id="ollama") from None
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code
            code = (ModelErrorCode.AUTHENTICATION if status in {401, 403} else
                    ModelErrorCode.RATE_LIMITED if status == 429 else
                    ModelErrorCode.UNAVAILABLE if status >= 500 or status == 404 else
                    ModelErrorCode.PROVIDER_ERROR)
            raise ModelGatewayError(code, "local model request failed",
                                    provider_id="ollama") from None
        except httpx.ConnectError:
            raise ModelGatewayError(ModelErrorCode.UNAVAILABLE,
                "local model service is unavailable", provider_id="ollama") from None
        except (httpx.HTTPError, ValueError, KeyError, TypeError, RecursionError):
            raise ModelGatewayError(ModelErrorCode.PROVIDER_ERROR,
                "local model returned an invalid response", provider_id="ollama") from None
        return ModelResponse(
            request_id=request.request_id, text=text, provider_id="ollama",
            provider_kind=ProviderKind.LOCAL, model=response_model,
            usage=ModelUsage(input_tokens=inputs, output_tokens=outputs,
                total_tokens=None if inputs is None or outputs is None else inputs + outputs),
            latency_ms=(time.perf_counter() - started) * 1000,
        )
