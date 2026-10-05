from __future__ import annotations

import asyncio
import math
import unittest

from acs.agent_model_contracts import (
    ModelErrorCode,
    ModelFailureEffect,
    ModelGatewayError,
    ModelMessage,
    ModelRequest,
    ModelResponse,
    ModelUsage,
    PrivacyClass,
    ProviderCapabilities,
    ProviderKind,
)
from acs.agent_model_gateway import ModelGateway


class _HostileResponse:
    def __getattribute__(self, _name: str) -> object:
        raise AssertionError("arbitrary provider response attributes must not be probed")


class _HostileStr(str):
    def strip(self, *_args: object, **_kwargs: object) -> str:
        raise AssertionError("hostile text hook must not run")

    def isprintable(self) -> bool:
        raise AssertionError("hostile text hook must not run")


class _HostileUsage(ModelUsage):
    def __getattribute__(self, _name: str) -> object:
        raise AssertionError("hostile usage attributes must not be probed")


class _HostileGatewayError(ModelGatewayError):
    def __getattribute__(self, name: str) -> object:
        if name in {"code", "provider_id", "retryable", "failure_effect"}:
            raise AssertionError("provider error subclass hooks must not be probed")
        return super().__getattribute__(name)


class _Provider:
    def __init__(
        self,
        response: object,
        *,
        provider_id: str = "provider-a",
        kind: ProviderKind = ProviderKind.LOCAL,
        supports_private_data: bool = True,
        supports_hard_cancellation: bool = False,
    ) -> None:
        self.response = response
        self.capability_reads = 0
        self.complete_calls = 0
        self._capabilities = ProviderCapabilities(
            provider_id=provider_id,
            kind=kind,
            supports_private_data=supports_private_data,
            supports_hard_cancellation=supports_hard_cancellation,
        )

    @property
    def capabilities(self) -> ProviderCapabilities:
        self.capability_reads += 1
        if self.capability_reads > 1:
            raise AssertionError("registered provider capabilities must be identity-pinned")
        return self._capabilities

    async def complete(self, _request: ModelRequest) -> object:
        self.complete_calls += 1
        return self.response


class _RequestEchoProvider(_Provider):
    def __init__(self) -> None:
        super().__init__(None)

    async def complete(self, request: ModelRequest) -> ModelResponse:
        self.complete_calls += 1
        return ModelResponse(
            request_id=request.request_id,
            text="ok",
            provider_id="provider-a",
            provider_kind=ProviderKind.LOCAL,
            model=request.model or "provider-default",
            usage=ModelUsage(input_tokens=1, output_tokens=2, total_tokens=3),
            latency_ms=1.5,
        )


class _RaisingProvider(_Provider):
    def __init__(
        self,
        error: BaseException,
        *,
        provider_id: str = "provider-a",
        supports_hard_cancellation: bool = False,
    ) -> None:
        super().__init__(
            None,
            provider_id=provider_id,
            supports_hard_cancellation=supports_hard_cancellation,
        )
        self.error = error

    async def complete(self, _request: ModelRequest) -> object:
        self.complete_calls += 1
        raise self.error


class _SelfCancellingProvider(_Provider):
    async def complete(self, _request: ModelRequest) -> object:
        self.complete_calls += 1
        raise asyncio.CancelledError()


def _request(*, model: str | None = "model-a") -> ModelRequest:
    return ModelRequest(
        request_id="request-a",
        messages=(ModelMessage(role="user", content="fixture"),),
        model=model,
        provider_id="provider-a",
        privacy=PrivacyClass.PRIVATE,
    )


def _response(**overrides: object) -> ModelResponse:
    values: dict[str, object] = {
        "request_id": "request-a",
        "text": "ok",
        "provider_id": "provider-a",
        "provider_kind": ProviderKind.LOCAL,
        "model": "model-a",
        "usage": ModelUsage(input_tokens=1, output_tokens=2, total_tokens=3),
        "latency_ms": 2.0,
    }
    values.update(overrides)
    return ModelResponse(**values)  # type: ignore[arg-type]


class ModelProviderResponseAuthorityTests(unittest.TestCase):
    def _complete_error(self, response: object) -> ModelGatewayError:
        gateway = ModelGateway()
        gateway.register(_Provider(response))
        with self.assertRaises(ModelGatewayError) as caught:
            asyncio.run(gateway.complete(_request()))
        self.assertEqual(caught.exception.code, ModelErrorCode.PROVIDER_ERROR)
        self.assertEqual(caught.exception.provider_id, "provider-a")
        self.assertFalse(caught.exception.retryable)
        return caught.exception

    def test_success_response_remains_accepted_and_capabilities_are_pinned(self) -> None:
        provider = _RequestEchoProvider()
        gateway = ModelGateway()
        gateway.register(provider)

        response = asyncio.run(gateway.complete(_request()))

        self.assertEqual(response.request_id, "request-a")
        self.assertEqual(response.provider_id, "provider-a")
        self.assertEqual(response.model, "model-a")
        self.assertEqual(response.usage.total_tokens, 3)
        self.assertEqual(provider.capability_reads, 1)
        self.assertEqual(provider.complete_calls, 1)

    def test_arbitrary_request_object_is_rejected_without_attribute_probes(self) -> None:
        gateway = ModelGateway()
        gateway.register(_RequestEchoProvider())

        with self.assertRaisesRegex(TypeError, "request must be ModelRequest"):
            asyncio.run(gateway.complete(_HostileResponse()))  # type: ignore[arg-type]

    def test_arbitrary_response_object_is_rejected_without_attribute_probes(self) -> None:
        error = self._complete_error(_HostileResponse())
        self.assertEqual(
            str(error),
            "model provider returned an invalid response contract",
        )

    def test_response_request_identity_must_match_attempt(self) -> None:
        self._complete_error(_response(request_id="request-b"))

    def test_response_provider_identity_must_match_registered_authority(self) -> None:
        self._complete_error(_response(provider_id="provider-b"))

    def test_response_provider_kind_must_match_registered_authority(self) -> None:
        self._complete_error(_response(provider_kind=ProviderKind.CLOUD))

    def test_explicit_model_identity_cannot_silently_change(self) -> None:
        self._complete_error(_response(model="different-model"))

    def test_provider_default_model_may_report_its_resolved_identity(self) -> None:
        provider = _Provider(
            ModelResponse(
                request_id="request-a",
                text="ok",
                provider_id="provider-a",
                provider_kind=ProviderKind.LOCAL,
                model="resolved-default",
                usage=ModelUsage(total_tokens=1),
            )
        )
        gateway = ModelGateway()
        gateway.register(provider)

        response = asyncio.run(gateway.complete(_request(model=None)))

        self.assertEqual(response.model, "resolved-default")

    def test_usage_must_be_exact_model_usage_before_field_reads(self) -> None:
        hostile = _HostileUsage(total_tokens=1)
        self._complete_error(_response(usage=hostile))

    def test_usage_token_counts_are_strict_non_negative_integers(self) -> None:
        for value in (-1, True, 1.5, "1"):
            with self.subTest(value=value):
                self._complete_error(
                    _response(usage=ModelUsage(total_tokens=value))  # type: ignore[arg-type]
                )

    def test_latency_is_finite_non_negative_builtin_numeric(self) -> None:
        for value in (-1, math.nan, math.inf, True, "1"):
            with self.subTest(value=value):
                self._complete_error(_response(latency_ms=value))

    def test_capability_identity_rejects_text_subclasses_before_hooks(self) -> None:
        class BadCapabilitiesProvider:
            @property
            def capabilities(self) -> ProviderCapabilities:
                return ProviderCapabilities(
                    provider_id=_HostileStr("provider-a"),
                    kind=ProviderKind.LOCAL,
                    supports_private_data=True,
                )

        with self.assertRaises(ValueError):
            ModelGateway().register(BadCapabilitiesProvider())

    def test_capability_flags_require_exact_booleans(self) -> None:
        class BadCapabilitiesProvider:
            @property
            def capabilities(self) -> ProviderCapabilities:
                return ProviderCapabilities(
                    provider_id="provider-a",
                    kind=ProviderKind.LOCAL,
                    supports_private_data=1,  # type: ignore[arg-type]
                )

        with self.assertRaises(TypeError):
            ModelGateway().register(BadCapabilitiesProvider())

    def test_register_default_flag_requires_exact_boolean(self) -> None:
        provider = _RequestEchoProvider()
        with self.assertRaisesRegex(TypeError, "default must be boolean"):
            ModelGateway().register(provider, default=1)  # type: ignore[arg-type]
        self.assertEqual(provider.capability_reads, 0)

    def test_provider_error_subclass_is_rejected_before_attribute_hooks(self) -> None:
        raw = _HostileGatewayError(
            ModelErrorCode.UNAVAILABLE,
            "secret provider detail",
            provider_id="provider-a",
            retryable=True,
            failure_effect=ModelFailureEffect.NO_EFFECT,
        )
        gateway = ModelGateway()
        gateway.register(_RaisingProvider(raw))

        with self.assertRaises(ModelGatewayError) as caught:
            asyncio.run(gateway.complete(_request()))

        self.assertEqual(caught.exception.code, ModelErrorCode.PROVIDER_ERROR)
        self.assertEqual(
            str(caught.exception),
            "model provider returned an invalid error contract",
        )
        self.assertEqual(caught.exception.failure_effect, ModelFailureEffect.UNKNOWN)

    def test_provider_self_cancellation_is_not_reported_as_caller_cancellation(self) -> None:
        gateway = ModelGateway()
        gateway.register(_SelfCancellingProvider(None))

        with self.assertRaises(ModelGatewayError) as caught:
            asyncio.run(gateway.complete(_request()))

        self.assertEqual(caught.exception.code, ModelErrorCode.CANCELLED)
        self.assertEqual(caught.exception.failure_effect, ModelFailureEffect.UNKNOWN)
        self.assertFalse(caught.exception.retryable)

    def test_typed_timeout_can_fallback_only_with_pinned_hard_cancellation(self) -> None:
        primary = _RaisingProvider(
            ModelGatewayError(
                ModelErrorCode.TIMEOUT,
                "private provider timeout detail",
                provider_id="provider-a",
                retryable=True,
                failure_effect=ModelFailureEffect.NO_EFFECT,
            ),
            supports_hard_cancellation=True,
        )
        fallback = _Provider(
            ModelResponse(
                request_id="request-a",
                text="fallback-ok",
                provider_id="provider-b",
                provider_kind=ProviderKind.LOCAL,
                model="model-a",
                usage=ModelUsage(total_tokens=1),
            ),
            provider_id="provider-b",
        )
        gateway = ModelGateway()
        gateway.register(primary)
        gateway.register(fallback)
        request = ModelRequest(
            request_id="request-a",
            messages=(ModelMessage(role="user", content="fixture"),),
            model="model-a",
            provider_id="provider-a",
            fallback_provider_ids=("provider-b",),
            privacy=PrivacyClass.PRIVATE,
        )

        response = asyncio.run(gateway.complete(request))

        self.assertEqual(response.provider_id, "provider-b")
        self.assertEqual(primary.complete_calls, 1)
        self.assertEqual(fallback.complete_calls, 1)

    def test_typed_timeout_does_not_fallback_without_hard_cancellation(self) -> None:
        primary = _RaisingProvider(
            ModelGatewayError(
                ModelErrorCode.TIMEOUT,
                "private provider timeout detail",
                provider_id="provider-a",
                retryable=True,
                failure_effect=ModelFailureEffect.NO_EFFECT,
            ),
            supports_hard_cancellation=False,
        )
        fallback = _Provider(
            ModelResponse(
                request_id="request-a",
                text="must-not-run",
                provider_id="provider-b",
                provider_kind=ProviderKind.LOCAL,
                model="model-a",
                usage=ModelUsage(total_tokens=1),
            ),
            provider_id="provider-b",
        )
        gateway = ModelGateway()
        gateway.register(primary)
        gateway.register(fallback)
        request = ModelRequest(
            request_id="request-a",
            messages=(ModelMessage(role="user", content="fixture"),),
            model="model-a",
            provider_id="provider-a",
            fallback_provider_ids=("provider-b",),
            privacy=PrivacyClass.PRIVATE,
        )

        with self.assertRaises(ModelGatewayError) as caught:
            asyncio.run(gateway.complete(request))

        self.assertEqual(caught.exception.code, ModelErrorCode.TIMEOUT)
        self.assertEqual(caught.exception.failure_effect, ModelFailureEffect.NO_EFFECT)
        self.assertEqual(fallback.complete_calls, 0)


if __name__ == "__main__":
    unittest.main()
