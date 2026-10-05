from __future__ import annotations

"""Provider-neutral model gateway for the Universal Chess Agent.

Adapted from first-party donor:
Oleksii-debug/Nika-Core@main
src/nika_core/model_gateway/contracts.py blob bafcf6cbb07d5b511979b09d1d920972a00da2c2
src/nika_core/model_gateway/gateway.py blob cff342b529121e73d549f99398c1c333b57524d8

This module deliberately knows nothing about chess legality. The Agent may use
model text for planning/explanation, but all board mutations still pass through
canonical Accessible Chess application services.
"""

import asyncio
from dataclasses import dataclass, field, replace
from enum import StrEnum
from math import isfinite
from types import MappingProxyType
from typing import Mapping, Protocol


class AgentPrivacyClass(StrEnum):
    PUBLIC = "public"
    PRIVATE = "private"
    SENSITIVE = "sensitive"


class AgentProviderKind(StrEnum):
    NO_LLM = "no_llm"
    LOCAL = "local"
    CLOUD = "cloud"


class AgentModelErrorCode(StrEnum):
    INVALID_REQUEST = "invalid_request"
    UNAVAILABLE = "unavailable"
    TIMEOUT = "timeout"
    CANCELLED = "cancelled"
    AUTHENTICATION = "authentication"
    RATE_LIMITED = "rate_limited"
    RESOURCE_LIMIT = "resource_limit"
    PROVIDER_ERROR = "provider_error"


@dataclass(frozen=True, slots=True)
class AgentModelMessage:
    role: str
    content: str

    def __post_init__(self) -> None:
        if self.role not in {"system", "user", "assistant", "tool"}:
            raise ValueError(f"unsupported message role: {self.role}")
        if not isinstance(self.content, str) or not self.content.strip():
            raise ValueError("message content must not be empty")


@dataclass(frozen=True, slots=True)
class AgentModelRequest:
    request_id: str
    messages: tuple[AgentModelMessage, ...]
    model: str | None = None
    provider_id: str | None = None
    provider_kind: AgentProviderKind | None = None
    fallback_provider_ids: tuple[str, ...] = ()
    privacy: AgentPrivacyClass = AgentPrivacyClass.PRIVATE
    timeout_seconds: float = 60.0
    temperature: float | None = None
    metadata: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.request_id, str) or not self.request_id.strip():
            raise ValueError("request_id must not be empty")
        messages = tuple(self.messages)
        if not messages or any(type(m) is not AgentModelMessage for m in messages):
            raise TypeError("messages must contain AgentModelMessage values")
        object.__setattr__(self, "messages", messages)
        if self.provider_kind is not None and not isinstance(self.provider_kind, AgentProviderKind):
            raise TypeError("provider_kind must be AgentProviderKind")
        if not isinstance(self.privacy, AgentPrivacyClass):
            raise TypeError("privacy must be AgentPrivacyClass")
        fallbacks = tuple(self.fallback_provider_ids)
        if len(set(fallbacks)) != len(fallbacks):
            raise ValueError("fallback provider IDs must be unique")
        if self.provider_id is not None and self.provider_id in fallbacks:
            raise ValueError("primary provider cannot also be a fallback")
        object.__setattr__(self, "fallback_provider_ids", fallbacks)
        if isinstance(self.timeout_seconds, bool) or not isinstance(
            self.timeout_seconds, (int, float)
        ):
            raise TypeError("timeout_seconds must be numeric")
        if not isfinite(float(self.timeout_seconds)) or self.timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be finite and positive")
        if self.temperature is not None:
            if isinstance(self.temperature, bool) or not isinstance(
                self.temperature, (int, float)
            ):
                raise TypeError("temperature must be numeric")
            if not isfinite(float(self.temperature)) or not 0 <= self.temperature <= 2:
                raise ValueError("temperature must be between 0 and 2")
            object.__setattr__(self, "temperature", float(self.temperature))
        if not isinstance(self.metadata, Mapping):
            raise TypeError("metadata must be a mapping")
        canonical: dict[str, str] = {}
        for key, value in self.metadata.items():
            if not isinstance(key, str) or not key.strip() or key != key.strip():
                raise ValueError("metadata keys must be canonical non-empty text")
            if not isinstance(value, str) or not value.strip():
                raise ValueError("metadata values must be non-empty text")
            canonical[key] = value
        object.__setattr__(self, "metadata", MappingProxyType(dict(sorted(canonical.items()))))


@dataclass(frozen=True, slots=True)
class AgentModelUsage:
    input_tokens: int | None = None
    output_tokens: int | None = None
    total_tokens: int | None = None


@dataclass(frozen=True, slots=True)
class AgentModelResponse:
    request_id: str
    text: str
    provider_id: str
    provider_kind: AgentProviderKind
    model: str
    usage: AgentModelUsage = field(default_factory=AgentModelUsage)
    latency_ms: float | None = None


@dataclass(frozen=True, slots=True)
class AgentProviderCapabilities:
    provider_id: str
    kind: AgentProviderKind
    supports_private_data: bool
    supports_tools: bool = False
    supports_streaming: bool = False
    supports_hard_cancellation: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.provider_id, str) or not self.provider_id.strip():
            raise ValueError("provider_id must not be empty")


class AgentModelGatewayError(RuntimeError):
    def __init__(
        self,
        code: AgentModelErrorCode,
        message: str,
        *,
        provider_id: str | None = None,
        retryable: bool = False,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.provider_id = provider_id
        self.retryable = retryable


class AgentModelProvider(Protocol):
    @property
    def capabilities(self) -> AgentProviderCapabilities: ...

    async def complete(self, request: AgentModelRequest) -> AgentModelResponse: ...


class AgentModelGateway:
    """Small fail-closed provider router with privacy-aware fallback."""

    _SAFE_FALLBACK_CODES = frozenset(
        {
            AgentModelErrorCode.UNAVAILABLE,
            AgentModelErrorCode.RATE_LIMITED,
            AgentModelErrorCode.TIMEOUT,
        }
    )

    def __init__(self) -> None:
        self._providers: dict[str, AgentModelProvider] = {}
        self._defaults: dict[AgentProviderKind, str] = {}

    def register(self, provider: AgentModelProvider, *, default: bool = False) -> None:
        provider_id = provider.capabilities.provider_id
        if provider_id in self._providers:
            raise ValueError(f"duplicate provider_id: {provider_id}")
        self._providers[provider_id] = provider
        if default:
            self._defaults[provider.capabilities.kind] = provider_id

    def providers(self) -> tuple[str, ...]:
        return tuple(sorted(self._providers))

    async def complete(self, request: AgentModelRequest) -> AgentModelResponse:
        providers = self._select_candidates(request)
        self._validate_privacy(request, providers)
        loop = asyncio.get_running_loop()
        deadline = loop.time() + float(request.timeout_seconds)

        last_error: AgentModelGatewayError | None = None
        for index, provider in enumerate(providers):
            remaining = deadline - loop.time()
            if remaining <= 0:
                raise AgentModelGatewayError(
                    AgentModelErrorCode.TIMEOUT,
                    "model request exceeded its deadline",
                    retryable=False,
                )
            attempt = replace(
                request,
                provider_id=provider.capabilities.provider_id,
                provider_kind=None,
                fallback_provider_ids=(),
                timeout_seconds=remaining,
            )
            try:
                return await asyncio.wait_for(provider.complete(attempt), timeout=remaining)
            except asyncio.CancelledError:
                raise
            except TimeoutError:
                last_error = AgentModelGatewayError(
                    AgentModelErrorCode.TIMEOUT,
                    "model provider request timed out",
                    provider_id=provider.capabilities.provider_id,
                    retryable=provider.capabilities.supports_hard_cancellation,
                )
            except AgentModelGatewayError as exc:
                last_error = AgentModelGatewayError(
                    exc.code,
                    "model provider failed",
                    provider_id=provider.capabilities.provider_id,
                    retryable=exc.retryable,
                )
            except Exception:
                last_error = AgentModelGatewayError(
                    AgentModelErrorCode.PROVIDER_ERROR,
                    "model provider failed",
                    provider_id=provider.capabilities.provider_id,
                    retryable=False,
                )

            if index + 1 >= len(providers):
                assert last_error is not None
                raise last_error
            if last_error.code not in self._SAFE_FALLBACK_CODES:
                raise last_error

        raise AgentModelGatewayError(
            AgentModelErrorCode.UNAVAILABLE,
            "model route exhausted",
            retryable=True,
        )

    def _select_candidates(self, request: AgentModelRequest) -> tuple[AgentModelProvider, ...]:
        if request.provider_id is not None:
            primary = self._providers.get(request.provider_id)
            if primary is None:
                raise AgentModelGatewayError(
                    AgentModelErrorCode.UNAVAILABLE, "requested provider is unavailable"
                )
        elif request.provider_kind is not None:
            provider_id = self._defaults.get(request.provider_kind)
            primary = self._providers.get(provider_id or "")
            if primary is None:
                raise AgentModelGatewayError(
                    AgentModelErrorCode.UNAVAILABLE, "default provider is unavailable"
                )
        else:
            local_id = self._defaults.get(AgentProviderKind.LOCAL)
            cloud_id = self._defaults.get(AgentProviderKind.CLOUD)
            primary = self._providers.get(local_id or "") or self._providers.get(cloud_id or "")
            if primary is None:
                raise AgentModelGatewayError(
                    AgentModelErrorCode.UNAVAILABLE, "no model provider is configured"
                )

        candidates = [primary]
        seen = {primary.capabilities.provider_id}
        for provider_id in request.fallback_provider_ids:
            provider = self._providers.get(provider_id)
            if provider is None:
                raise AgentModelGatewayError(
                    AgentModelErrorCode.UNAVAILABLE,
                    "fallback provider is unavailable",
                    provider_id=provider_id,
                )
            if provider_id not in seen:
                candidates.append(provider)
                seen.add(provider_id)
        return tuple(candidates)

    @staticmethod
    def _validate_privacy(
        request: AgentModelRequest, providers: tuple[AgentModelProvider, ...]
    ) -> None:
        if request.privacy is AgentPrivacyClass.PUBLIC:
            return
        for provider in providers:
            if not provider.capabilities.supports_private_data:
                raise AgentModelGatewayError(
                    AgentModelErrorCode.INVALID_REQUEST,
                    "selected model route does not permit private data",
                    provider_id=provider.capabilities.provider_id,
                )


__all__ = [
    "AgentModelErrorCode",
    "AgentModelGateway",
    "AgentModelGatewayError",
    "AgentModelMessage",
    "AgentModelProvider",
    "AgentModelRequest",
    "AgentModelResponse",
    "AgentModelUsage",
    "AgentPrivacyClass",
    "AgentProviderCapabilities",
    "AgentProviderKind",
]
