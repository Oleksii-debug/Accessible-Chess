# Adapted from Oleksii-debug/Nika-Core@6df8b80b7a248f1559a0ff96f74efa2d2c47ad14
# Donor path: src/nika_core/model_gateway/gateway.py
# First-party cross-repository reuse for Accessible Chess.

from __future__ import annotations

import asyncio
import hashlib
from dataclasses import replace
from math import isfinite
from typing import Protocol

from .agent_model_contracts import (
    ModelErrorCode,
    ModelFailureEffect,
    ModelGatewayError,
    ModelProvider,
    ModelRequest,
    ModelResponse,
    ModelUsage,
    PrivacyClass,
    ProviderCapabilities,
    ProviderKind,
)


class _AuditLogPort(Protocol):
    def append(
        self,
        *,
        event_type: str,
        entity_type: str,
        entity_id: str,
        payload: dict[str, object] | None = None,
    ) -> int: ...


_SAFE_FALLBACK_CODES = frozenset(
    {
        ModelErrorCode.UNAVAILABLE,
        ModelErrorCode.RATE_LIMITED,
        ModelErrorCode.TIMEOUT,
    }
)
_SAFE_PROVIDER_MESSAGES = {
    ModelErrorCode.INVALID_REQUEST: "model provider rejected the request",
    ModelErrorCode.UNAVAILABLE: "model provider is unavailable",
    ModelErrorCode.TIMEOUT: "model provider request timed out",
    ModelErrorCode.CANCELLED: "model provider request was cancelled",
    ModelErrorCode.AUTHENTICATION: "model provider authentication failed",
    ModelErrorCode.RATE_LIMITED: "model provider rate limit was reached",
    ModelErrorCode.RESOURCE_LIMIT: "model provider resource limit was reached",
    ModelErrorCode.PROVIDER_ERROR: "model provider failed",
}


class ModelGateway:
    def __init__(self, *, audit_log: _AuditLogPort | None = None) -> None:
        self._providers: dict[str, ModelProvider] = {}
        # Capabilities are authority metadata. Capture and validate them once at
        # registration so a provider cannot change identity/privacy/cancellation
        # semantics between selection, execution and audit.
        self._capabilities: dict[str, ProviderCapabilities] = {}
        self._defaults: dict[ProviderKind, str] = {}
        self._audit_log = audit_log

    def register(self, provider: ModelProvider, *, default: bool = False) -> None:
        if type(default) is not bool:
            raise TypeError("default must be boolean")
        capabilities = self._validate_capabilities(provider.capabilities)
        provider_id = capabilities.provider_id
        if provider_id in self._providers:
            raise ValueError(f"duplicate provider_id: {provider_id}")
        self._providers[provider_id] = provider
        self._capabilities[provider_id] = capabilities
        if default:
            self._defaults[capabilities.kind] = provider_id

    def providers(self) -> tuple[str, ...]:
        return tuple(sorted(self._providers))

    async def complete(self, request: ModelRequest) -> ModelResponse:
        # ModelRequest is a frozen, canonicalized boundary value. Reject
        # subclasses/arbitrary lookalikes before probing any provider route.
        if type(request) is not ModelRequest:
            raise TypeError("request must be ModelRequest")
        providers = self._select_candidates(request)
        self._validate_privacy_route(request, providers)
        loop = asyncio.get_running_loop()
        deadline = loop.time() + request.timeout_seconds

        for index, (provider, capabilities) in enumerate(providers):
            remaining = deadline - loop.time()
            if remaining <= 0:
                error = ModelGatewayError(
                    ModelErrorCode.TIMEOUT,
                    "model request exceeded its deadline",
                    provider_id=capabilities.provider_id,
                    retryable=False,
                )
                self._audit_failure(request, capabilities.provider_id, error)
                raise error

            attempt_request = replace(
                request,
                provider_id=capabilities.provider_id,
                provider_kind=None,
                fallback_provider_ids=(),
                timeout_seconds=remaining,
            )
            self._audit(
                event_type="model.requested",
                request=request,
                payload={
                    "provider_id": capabilities.provider_id,
                    "provider_kind": capabilities.kind.value,
                    "privacy": request.privacy.value,
                    "model_fingerprint": model_identity_fingerprint(request.model),
                    "attempt": index + 1,
                },
            )

            response: ModelResponse | None = None
            terminal_error: ModelGatewayError | None = None
            cancelled = False
            try:
                response = await asyncio.wait_for(
                    provider.complete(attempt_request), timeout=remaining
                )
            except TimeoutError:
                # This is the gateway's total-route deadline, so no budget is
                # left for a fallback attempt. Preserve UNKNOWN effect state;
                # provider-origin typed TIMEOUT + NO_EFFECT may still fall back
                # before this outer deadline when hard cancellation is pinned.
                error = ModelGatewayError(
                    ModelErrorCode.TIMEOUT,
                    "model request exceeded its deadline",
                    provider_id=capabilities.provider_id,
                    retryable=False,
                    failure_effect=ModelFailureEffect.UNKNOWN,
                )
                self._audit_failure(request, capabilities.provider_id, error)
                terminal_error = error
            except asyncio.CancelledError:
                # A provider coroutine may itself raise CancelledError. That is
                # not equivalent to cancellation of this gateway task. Only
                # propagate task cancellation when the current task has a real
                # pending cancellation request; otherwise sanitize the provider
                # failure and preserve UNKNOWN effect state.
                current_task = asyncio.current_task()
                if current_task is not None and current_task.cancelling():
                    self._audit(
                        event_type="model.cancelled",
                        request=request,
                        payload={"provider_id": capabilities.provider_id},
                    )
                    cancelled = True
                else:
                    error = ModelGatewayError(
                        ModelErrorCode.CANCELLED,
                        "model provider cancelled without caller cancellation",
                        provider_id=capabilities.provider_id,
                        retryable=False,
                        failure_effect=ModelFailureEffect.UNKNOWN,
                    )
                    self._audit_failure(request, capabilities.provider_id, error)
                    terminal_error = error
            except ModelGatewayError as raw_error:
                error = self._normalize_provider_error(
                    raw_error, capabilities.provider_id
                )
                self._audit_failure(request, capabilities.provider_id, error)
                if self._can_fallback(error=error, index=index, providers=providers):
                    self._audit_fallback(
                        request,
                        capabilities,
                        providers[index + 1][1],
                        error,
                    )
                    continue
                terminal_error = error
            except Exception:  # noqa: BLE001 - provider implementations are untrusted
                error = ModelGatewayError(
                    ModelErrorCode.PROVIDER_ERROR,
                    "model provider failed without a typed Nika error",
                    provider_id=capabilities.provider_id,
                    retryable=False,
                )
                self._audit_failure(request, capabilities.provider_id, error)
                terminal_error = error

            # Raise after the provider exception handler so provider-controlled
            # diagnostics are not retained as public cause/context chains.
            if cancelled:
                raise asyncio.CancelledError()
            if terminal_error is not None:
                raise terminal_error
            if response is None:
                error = ModelGatewayError(
                    ModelErrorCode.PROVIDER_ERROR,
                    "model provider completed without a response",
                    provider_id=capabilities.provider_id,
                    retryable=False,
                )
                self._audit_failure(request, capabilities.provider_id, error)
                raise error

            try:
                response = self._validate_provider_response(
                    response,
                    request=attempt_request,
                    capabilities=capabilities,
                )
            except ModelGatewayError as error:
                self._audit_failure(request, capabilities.provider_id, error)
                raise error

            self._audit(
                event_type="model.completed",
                request=request,
                payload={
                    "provider_id": response.provider_id,
                    "model_fingerprint": model_identity_fingerprint(response.model),
                    "input_tokens": response.usage.input_tokens,
                    "output_tokens": response.usage.output_tokens,
                    "total_tokens": response.usage.total_tokens,
                    "latency_ms": response.latency_ms,
                    "attempt": index + 1,
                },
            )
            return response

        raise ModelGatewayError(
            ModelErrorCode.UNAVAILABLE,
            "model fallback route was exhausted",
            retryable=True,
        )

    def _select_candidates(
        self, request: ModelRequest
    ) -> tuple[tuple[ModelProvider, ProviderCapabilities], ...]:
        primary = self._select(request)
        candidates = [primary]
        seen = {primary[1].provider_id}
        for provider_id in request.fallback_provider_ids:
            if provider_id in seen:
                raise ModelGatewayError(
                    ModelErrorCode.INVALID_REQUEST,
                    f"fallback route repeats provider: {provider_id}",
                    provider_id=provider_id,
                )
            provider = self._providers.get(provider_id)
            if provider is None:
                raise ModelGatewayError(
                    ModelErrorCode.UNAVAILABLE,
                    f"unknown fallback model provider: {provider_id}",
                    provider_id=provider_id,
                )
            capabilities = self._capabilities[provider_id]
            candidates.append((provider, capabilities))
            seen.add(provider_id)
        return tuple(candidates)

    def _validate_privacy_route(
        self,
        request: ModelRequest,
        providers: tuple[tuple[ModelProvider, ProviderCapabilities], ...],
    ) -> None:
        if request.privacy is PrivacyClass.PUBLIC:
            return
        for _provider, capabilities in providers:
            if not capabilities.supports_private_data:
                raise ModelGatewayError(
                    ModelErrorCode.INVALID_REQUEST,
                    "private data cannot be routed to this provider",
                    provider_id=capabilities.provider_id,
                )

    @staticmethod
    def _validate_capabilities(value: object) -> ProviderCapabilities:
        if type(value) is not ProviderCapabilities:
            raise TypeError("provider capabilities must be ProviderCapabilities")
        if (
            type(value.provider_id) is not str
            or not value.provider_id
            or value.provider_id != value.provider_id.strip()
            or any(not char.isprintable() for char in value.provider_id)
        ):
            raise ValueError("provider_id must be non-empty canonical text")
        if not any(value.kind is member for member in ProviderKind):
            raise TypeError("provider kind must be ProviderKind")
        for name in (
            "supports_private_data",
            "supports_tools",
            "supports_streaming",
            "supports_hard_cancellation",
        ):
            if type(getattr(value, name)) is not bool:
                raise TypeError(f"{name} must be boolean")
        # Rebuild the frozen value so registration retains a stable copy even if
        # future contract implementations become mutable.
        return ProviderCapabilities(
            provider_id=value.provider_id,
            kind=value.kind,
            supports_private_data=value.supports_private_data,
            supports_tools=value.supports_tools,
            supports_streaming=value.supports_streaming,
            supports_hard_cancellation=value.supports_hard_cancellation,
        )

    @staticmethod
    def _validate_provider_response(
        response: object,
        *,
        request: ModelRequest,
        capabilities: ProviderCapabilities,
    ) -> ModelResponse:
        def invalid() -> ModelGatewayError:
            return ModelGatewayError(
                ModelErrorCode.PROVIDER_ERROR,
                "model provider returned an invalid response contract",
                provider_id=capabilities.provider_id,
                retryable=False,
                failure_effect=ModelFailureEffect.UNKNOWN,
            )

        # Do not probe attributes on arbitrary provider-controlled objects.
        if type(response) is not ModelResponse:
            raise invalid()
        if type(response.request_id) is not str or response.request_id != request.request_id:
            raise invalid()
        if type(response.provider_id) is not str or response.provider_id != capabilities.provider_id:
            raise invalid()
        if response.provider_kind is not capabilities.kind:
            raise invalid()
        if (
            type(response.model) is not str
            or not response.model
            or response.model != response.model.strip()
            or any(not char.isprintable() for char in response.model)
        ):
            raise invalid()
        if request.model is not None and response.model != request.model:
            raise invalid()
        if type(response.text) is not str:
            raise invalid()
        if type(response.usage) is not ModelUsage:
            raise invalid()
        for value in (
            response.usage.input_tokens,
            response.usage.output_tokens,
            response.usage.total_tokens,
        ):
            if value is not None and (type(value) is not int or value < 0):
                raise invalid()
        if response.latency_ms is not None:
            if type(response.latency_ms) not in (int, float):
                raise invalid()
            try:
                finite_latency = isfinite(float(response.latency_ms))
            except OverflowError:
                finite_latency = False
            if not finite_latency or response.latency_ms < 0:
                raise invalid()
        return response

    @staticmethod
    def _normalize_provider_error(
        error: ModelGatewayError, provider_id: str
    ) -> ModelGatewayError:
        def invalid(message: str) -> ModelGatewayError:
            return ModelGatewayError(
                ModelErrorCode.PROVIDER_ERROR,
                message,
                provider_id=provider_id,
                retryable=False,
                failure_effect=ModelFailureEffect.UNKNOWN,
            )

        # Provider exceptions are untrusted boundary objects too. Reject a
        # subclass before touching provider-controlled attributes/hooks.
        if type(error) is not ModelGatewayError:
            return invalid("model provider returned an invalid error contract")
        if type(error.code) is not ModelErrorCode:
            return invalid("model provider returned an invalid error code")
        if type(error.retryable) is not bool:
            return invalid("model provider returned an invalid retryable flag")
        if type(error.failure_effect) is not ModelFailureEffect:
            return invalid("model provider returned an invalid failure effect state")
        if error.provider_id is not None and type(error.provider_id) is not str:
            return invalid("model provider returned an invalid provider identity")
        if error.provider_id is not None and error.provider_id != provider_id:
            return invalid("model provider returned an error for another provider identity")
        safe_message = _SAFE_PROVIDER_MESSAGES[error.code]
        if provider_id == "foundry-local" and error.code is ModelErrorCode.UNAVAILABLE:
            safe_message = (
                "Foundry Local model is unavailable; use the explicit model download "
                "action before inference if the model is not cached"
            )
        return ModelGatewayError(
            error.code,
            safe_message,
            provider_id=provider_id,
            retryable=error.retryable,
            failure_effect=error.failure_effect,
        )

    @staticmethod
    def _can_fallback(
        *,
        error: ModelGatewayError,
        index: int,
        providers: tuple[tuple[ModelProvider, ProviderCapabilities], ...],
    ) -> bool:
        if index + 1 >= len(providers):
            return False
        if error.code not in _SAFE_FALLBACK_CODES:
            return False
        if not error.retryable:
            return False
        if error.failure_effect is not ModelFailureEffect.NO_EFFECT:
            return False
        return not (
            error.code is ModelErrorCode.TIMEOUT
            and not providers[index][1].supports_hard_cancellation
        )

    def _audit_failure(
        self, request: ModelRequest, provider_id: str, error: ModelGatewayError
    ) -> None:
        self._audit(
            event_type="model.failed",
            request=request,
            payload={
                "provider_id": provider_id,
                "model_fingerprint": model_identity_fingerprint(request.model),
                "code": error.code.value,
                "failure_effect": error.failure_effect.value,
            },
        )

    def _audit_fallback(
        self,
        request: ModelRequest,
        current: ProviderCapabilities,
        fallback: ProviderCapabilities,
        error: ModelGatewayError,
    ) -> None:
        self._audit(
            event_type="model.fallback",
            request=request,
            payload={
                "from_provider_id": current.provider_id,
                "to_provider_id": fallback.provider_id,
                "reason": error.code.value,
                "failure_effect": error.failure_effect.value,
            },
        )

    def _select(
        self, request: ModelRequest
    ) -> tuple[ModelProvider, ProviderCapabilities]:
        if request.provider_id:
            provider = self._providers.get(request.provider_id)
            if provider is None:
                raise ModelGatewayError(
                    ModelErrorCode.UNAVAILABLE,
                    f"unknown model provider: {request.provider_id}",
                    provider_id=request.provider_id,
                )
            capabilities = self._capabilities[request.provider_id]
            if (
                request.provider_kind is not None
                and capabilities.kind is not request.provider_kind
            ):
                raise ModelGatewayError(
                    ModelErrorCode.INVALID_REQUEST,
                    "selected model provider kind does not match the requested boundary",
                    provider_id=request.provider_id,
                    retryable=False,
                    failure_effect=ModelFailureEffect.NO_EFFECT,
                )
            return provider, capabilities
        if request.provider_kind:
            provider_id = self._defaults.get(request.provider_kind)
            if provider_id is None:
                raise ModelGatewayError(
                    ModelErrorCode.UNAVAILABLE,
                    f"no default provider for kind: {request.provider_kind.value}",
                )
            return self._providers[provider_id], self._capabilities[provider_id]
        if len(self._providers) == 1:
            provider_id, provider = next(iter(self._providers.items()))
            return provider, self._capabilities[provider_id]
        raise ModelGatewayError(
            ModelErrorCode.INVALID_REQUEST,
            "provider_id or provider_kind is required when several providers are registered",
        )

    def _audit(
        self,
        *,
        event_type: str,
        request: ModelRequest,
        payload: dict[str, object],
    ) -> None:
        if self._audit_log is None:
            return
        self._audit_log.append(
            event_type=event_type,
            entity_type="model_request",
            entity_id=request.request_id,
            payload=payload,
        )


def model_identity_fingerprint(model: str | None) -> str:
    """Return a stable content-free projection for untrusted model identity metadata."""

    value = model if model is not None else "<provider-default>"
    digest = hashlib.sha256(value.encode("utf-8", errors="surrogatepass")).hexdigest()
    return f"sha256:{digest}"
