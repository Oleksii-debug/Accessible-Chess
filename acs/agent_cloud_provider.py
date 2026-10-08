"""Fixed-endpoint cloud text models behind the EXISTING Accessible Chess ModelGateway.

Section 49 incremental adapter: no second router, no embedded credentials,
no automatic paid activation, no model-inferred tool authority. Provider
accounts and real LIVE evidence are external to this module.
"""
from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from types import MappingProxyType

from .agent_model_contracts import (
    ModelErrorCode, ModelFailureEffect, ModelGatewayError, ModelRequest,
    ModelResponse, ModelUsage, ProviderCapabilities, ProviderKind, PrivacyClass,
)

# Fixed known origins: never construct an endpoint from a model response,
# untrusted file, prompt, request metadata, or user-controlled hostname.
_PROVIDER_CONFIG = MappingProxyType({
    "mistral": ("https://api.mistral.ai/v1", "MISTRAL_API_KEY"),
    "groq": ("https://api.groq.com/openai/v1", "GROQ_API_KEY"),
    "openrouter": ("https://openrouter.ai/api/v1", "OPENROUTER_API_KEY"),
    "deepseek": ("https://api.deepseek.com/v1", "DEEPSEEK_API_KEY"),
    "nvidia_nim": ("https://integrate.api.nvidia.com/v1", "NVIDIA_NIM_API_KEY"),
})
MAX_RESPONSE_BYTES = 1024 * 1024
MAX_PROMPT_CHARS = 128 * 1024
MAX_JSON_ITEMS = 4096
MAX_JSON_DEPTH = 48


def _identifier(value: object) -> str:
    if type(value) is not str or not value or value != value.strip():
        raise ValueError("model must be canonical non-empty text")
    if len(value) > 256 or any(not x.isprintable() for x in value):
        raise ValueError("model identity is invalid")
    return value


def _unique_json_pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def _reject_nonfinite(_value):
    raise ValueError("nonfinite JSON constant")


def _read_json(data: bytes):
    value = json.loads(
        data, object_pairs_hook=_unique_json_pairs,
        parse_constant=_reject_nonfinite,
    )
    stack = [(value, 0)]
    remaining = MAX_JSON_ITEMS
    while stack:
        item, depth = stack.pop()
        if depth > MAX_JSON_DEPTH:
            raise ValueError("JSON depth limit")
        if type(item) is dict or type(item) is list:
            remaining -= len(item)
            if remaining < 0:
                raise ValueError("JSON size limit")
            if type(item) is dict:
                stack.extend((x, depth + 1) for x in item.values())
            else:
                stack.extend((x, depth + 1) for x in item)
        elif item is not None and type(item) not in (str, int, float, bool):
            raise ValueError("unsupported JSON type")
    return value


def configured_provider_ids() -> tuple[str, ...]:
    """Presence only, never expose credential values or tokens in diagnostics."""
    return tuple(name for name, (_, env) in _PROVIDER_CONFIG.items()
                 if bool(os.environ.get(env)))


@dataclass(frozen=True, slots=True)
class ProviderAvailability:
    provider_id: str
    configured: bool
    mode: str  # CONFIGURED_UNVERIFIED or NOT_CONFIGURED; never a LIVE PASS claim.


def provider_availability() -> tuple[ProviderAvailability, ...]:
    return tuple(
        ProviderAvailability(name, bool(os.environ.get(env)),
                             "CONFIGURED_UNVERIFIED" if os.environ.get(env) else "NOT_CONFIGURED")
        for name, (_, env) in _PROVIDER_CONFIG.items()
    )


class CloudChatProvider:
    """Text-only bounded HTTPS adapter. Gateway owns routing, privacy and audit.

    Provider-side execution may have occurred on timeout/429/500, so error
    effect is UNKNOWN and ModelGateway cannot silently duplicate requests.
    """

    def __init__(
        self, *, provider_id: str, default_model: str,
        allow_private_data: bool = False, max_output_tokens: int = 512,
        client_factory=None,
    ) -> None:
        if provider_id not in _PROVIDER_CONFIG:
            raise ValueError("unsupported cloud provider")
        if type(allow_private_data) is not bool:
            raise TypeError("privacy approval must be boolean")
        if type(max_output_tokens) is not int or not 1 <= max_output_tokens <= 4096:
            raise ValueError("invalid bounded output-token limit")
        self._provider_id = provider_id
        self._origin, self._secret_env = _PROVIDER_CONFIG[provider_id]
        self._default_model = _identifier(default_model)
        self._max_output_tokens = max_output_tokens
        self._client_factory = client_factory
        self._capabilities = ProviderCapabilities(
            provider_id=provider_id, kind=ProviderKind.CLOUD,
            supports_private_data=allow_private_data,
            supports_tools=False, supports_streaming=False,
            supports_hard_cancellation=False,
        )

    @property
    def capabilities(self) -> ProviderCapabilities:
        return self._capabilities

    def configured(self) -> bool:
        return bool(os.environ.get(self._secret_env))

    def _error(
        self, code: ModelErrorCode, message: str, *,
        no_effect: bool = False, retryable: bool = False,
    ) -> ModelGatewayError:
        return ModelGatewayError(
            code, message, provider_id=self._provider_id,
            retryable=retryable,
            failure_effect=(
                ModelFailureEffect.NO_EFFECT if no_effect
                else ModelFailureEffect.UNKNOWN
            ),
        )

    async def _exchange(self, method: str, path: str, *, payload=None, timeout: float):
        secret = os.environ.get(self._secret_env)
        if not secret:
            raise self._error(ModelErrorCode.UNAVAILABLE,
                              "cloud provider is not configured", no_effect=True,
                              retryable=True)
        try:
            import httpx
        except ImportError:
            raise self._error(ModelErrorCode.UNAVAILABLE,
                              "optional model HTTP component unavailable",
                              no_effect=True, retryable=True) from None
        factory = self._client_factory or httpx.AsyncClient
        try:
            async with factory(
                timeout=timeout, trust_env=False, follow_redirects=False,
            ) as client:
                async with client.stream(
                    method, self._origin + path,
                    headers={"Authorization": "Bearer " + secret,
                             "Accept": "application/json"},
                    json=payload,
                ) as response:
                    status = response.status_code
                    if status != 200:
                        if status in (401, 403):
                            code = ModelErrorCode.AUTHENTICATION
                        elif status == 429:
                            code = ModelErrorCode.RATE_LIMITED
                        elif status in (400, 404, 422):
                            code = ModelErrorCode.INVALID_REQUEST
                        elif status >= 500:
                            code = ModelErrorCode.UNAVAILABLE
                        else:
                            code = ModelErrorCode.PROVIDER_ERROR
                        raise self._error(code, "cloud provider request failed",
                                          retryable=(code in (
                                              ModelErrorCode.UNAVAILABLE,
                                              ModelErrorCode.RATE_LIMITED)))
                    raw = bytearray()
                    async for chunk in response.aiter_bytes():
                        if len(raw) + len(chunk) > MAX_RESPONSE_BYTES:
                            raise self._error(
                                ModelErrorCode.RESOURCE_LIMIT,
                                "cloud provider response exceeded limit")
                        raw.extend(chunk)
        except httpx.TimeoutException:
            raise self._error(ModelErrorCode.TIMEOUT,
                              "cloud provider request timed out") from None
        except httpx.RequestError:
            raise self._error(ModelErrorCode.UNAVAILABLE,
                              "cloud provider network unavailable") from None
        try:
            return _read_json(bytes(raw))
        except (ValueError, UnicodeDecodeError, TypeError, RecursionError):
            raise self._error(ModelErrorCode.PROVIDER_ERROR,
                              "cloud provider returned invalid JSON") from None

    async def list_models(self, *, timeout: float = 15.0) -> tuple[str, ...]:
        if type(timeout) not in (float, int) or not 0 < timeout <= 60:
            raise ValueError("model list timeout must be bounded")
        value = await self._exchange("GET", "/models", timeout=timeout)
        if type(value) is not dict or type(value.get("data")) is not list:
            raise self._error(ModelErrorCode.PROVIDER_ERROR,
                              "cloud model catalog is malformed")
        models = value["data"]
        if len(models) > 512:
            raise self._error(ModelErrorCode.RESOURCE_LIMIT,
                              "cloud model catalog exceeds limit")
        try:
            return tuple(sorted({_identifier(x["id"]) for x in models
                                 if type(x) is dict}))
        except (ValueError, KeyError, TypeError):
            raise self._error(ModelErrorCode.PROVIDER_ERROR,
                              "cloud model identity is invalid") from None

    async def complete(self, request: ModelRequest) -> ModelResponse:
        if type(request) is not ModelRequest:
            raise TypeError("request must be ModelRequest")
        if request.privacy is not PrivacyClass.PUBLIC and not self._capabilities.supports_private_data:
            raise self._error(ModelErrorCode.INVALID_REQUEST,
                              "private chess data is not approved for cloud",
                              no_effect=True)
        if any(message.role == "tool" for message in request.messages):
            raise self._error(ModelErrorCode.INVALID_REQUEST,
                              "text-only cloud route does not accept tool messages",
                              no_effect=True)
        model = _identifier(request.model or self._default_model)
        if sum(len(message.content) for message in request.messages) > MAX_PROMPT_CHARS:
            raise self._error(ModelErrorCode.RESOURCE_LIMIT,
                              "cloud model request exceeds input limit",
                              no_effect=True)
        payload = {
            "model": model,
            "messages": [{"role": m.role, "content": m.content}
                         for m in request.messages],
            "stream": False,
            "max_tokens": self._max_output_tokens,
        }
        if request.temperature is not None:
            payload["temperature"] = request.temperature
        started = time.perf_counter()
        body = await self._exchange("POST", "/chat/completions",
                                    payload=payload,
                                    timeout=request.timeout_seconds)
        try:
            if type(body) is not dict or type(body["choices"]) is not list:
                raise ValueError("invalid choices")
            if len(body["choices"]) != 1:
                raise ValueError("ambiguous choices")
            choice = body["choices"][0]
            if type(choice) is not dict or type(choice["message"]) is not dict:
                raise ValueError("invalid message")
            if choice["message"].get("role") not in (None, "assistant"):
                raise ValueError("invalid assistant role")
            answer = choice["message"]["content"]
            identity = _identifier(body["model"])
            if identity != model or type(answer) is not str or not answer.strip():
                raise ValueError("invalid model/answer identity")
            usage = body.get("usage") or {}
            if type(usage) is not dict:
                raise ValueError("invalid usage")
            def token(name):
                value = usage.get(name)
                if value is not None and (type(value) is not int or value < 0):
                    raise ValueError("invalid usage number")
                return value
            inp, out, total = token("prompt_tokens"), token("completion_tokens"), token("total_tokens")
            if inp is not None and out is not None and total is not None and inp + out != total:
                raise ValueError("inconsistent token totals")
        except (ValueError, KeyError, TypeError):
            raise self._error(ModelErrorCode.PROVIDER_ERROR,
                              "cloud provider response contract invalid") from None
        return ModelResponse(
            request_id=request.request_id, text=answer,
            provider_id=self._provider_id, provider_kind=ProviderKind.CLOUD,
            model=model, usage=ModelUsage(input_tokens=inp, output_tokens=out,
                                          total_tokens=total),
            latency_ms=(time.perf_counter() - started) * 1000,
        )


def register_configured_cloud_providers(
    gateway, *, models: dict[str, str], allow_private_data: bool = False,
    max_output_tokens: int = 512,
) -> tuple[str, ...]:
    """Register into the existing ModelGateway, never instantiate a router #2.

    Models are explicit and must come from an authenticated /models lookup or
    an operator-reviewed account configuration. No payment/setup is triggered.
    """
    if type(models) is not dict:
        raise TypeError("models must be explicit provider-to-model mapping")
    registered = []
    for provider in _PROVIDER_CONFIG:
        if provider not in models or not os.environ.get(_PROVIDER_CONFIG[provider][1]):
            continue
        instance = CloudChatProvider(
            provider_id=provider, default_model=models[provider],
            allow_private_data=allow_private_data,
            max_output_tokens=max_output_tokens,
        )
        gateway.register(instance, default=(not registered))
        registered.append(provider)
    return tuple(registered)
