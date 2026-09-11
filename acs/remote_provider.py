"""Remote provider orchestration for the post-freeze Accessible Chess lane.

The provider boundary keeps transport/authentication replaceable while Product
identity and durable teaching state remain canonical elsewhere.  Production can
use :class:`acs.remote_connectivity.TlsRelayClient`; deterministic CI can use
:class:`InProcessRemoteProvider` without Internet access or real credentials.
"""
from __future__ import annotations

from dataclasses import dataclass
import time
from typing import Callable, Protocol

from .remote_connectivity import (
    AuthenticatedPrincipal,
    RemoteConnectionContext,
    RemoteConnectivityError,
    RemoteEndpointProfile,
    RemoteEnvelope,
    RemoteRetryPolicy,
    SecretProvider,
    require_runtime_secret,
)


class RemoteProvider(Protocol):
    def connect(
        self,
        principal: AuthenticatedPrincipal,
        secret: str,
    ) -> RemoteConnectionContext:
        """Authenticate and establish one remote connection."""

    def exchange(self, envelope: RemoteEnvelope) -> RemoteEnvelope:
        """Exchange one bounded protocol envelope."""

    def close(self) -> None:
        """Close the provider connection idempotently."""


ProviderFactory = Callable[[RemoteEndpointProfile, RemoteRetryPolicy], RemoteProvider]
SleepFunction = Callable[[float], None]


@dataclass(frozen=True, slots=True)
class ConnectedRemoteProvider:
    provider: RemoteProvider
    context: RemoteConnectionContext
    attempts: int


class RemoteConnector:
    """Acquire credentials and connect with bounded deterministic retry policy.

    No secret is retained on this object.  Each attempt obtains the credential
    through the injected secret provider, and every failed provider instance is
    closed before retrying.  Final failure remains explicit; there is no local,
    plaintext, or simulated-success fallback.
    """

    def __init__(
        self,
        profile: RemoteEndpointProfile,
        secret_provider: SecretProvider,
        provider_factory: ProviderFactory,
        policy: RemoteRetryPolicy | None = None,
        sleep: SleepFunction = time.sleep,
    ) -> None:
        if not isinstance(profile, RemoteEndpointProfile):
            raise RemoteConnectivityError("remote endpoint profile is invalid")
        if secret_provider is None or not callable(getattr(secret_provider, "get_secret", None)):
            raise RemoteConnectivityError("remote credentials are unavailable")
        if not callable(provider_factory):
            raise RemoteConnectivityError("remote provider factory is unavailable")
        if not callable(sleep):
            raise RemoteConnectivityError("remote retry timer is unavailable")
        self._profile = profile
        self._secret_provider = secret_provider
        self._provider_factory = provider_factory
        self._policy = policy or RemoteRetryPolicy()
        self._sleep = sleep

    def connect(self, principal: AuthenticatedPrincipal) -> ConnectedRemoteProvider:
        if not isinstance(principal, AuthenticatedPrincipal):
            raise RemoteConnectivityError("remote principal is invalid")
        last_error: RemoteConnectivityError | None = None
        for attempt in range(1, self._policy.max_attempts + 1):
            secret = require_runtime_secret(
                self._secret_provider,
                self._profile.credential_key,
            )
            try:
                provider = self._provider_factory(self._profile, self._policy)
            except Exception as exc:
                raise RemoteConnectivityError("remote provider is unavailable") from exc
            if provider is None or not all(
                callable(getattr(provider, name, None))
                for name in ("connect", "exchange", "close")
            ):
                raise RemoteConnectivityError("remote provider is unavailable")
            try:
                context = provider.connect(principal, secret)
                if (
                    not isinstance(context, RemoteConnectionContext)
                    or context.principal != principal
                ):
                    raise RemoteConnectivityError("remote authenticated identity mismatch")
                return ConnectedRemoteProvider(provider, context, attempt)
            except RemoteConnectivityError as exc:
                last_error = exc
                try:
                    provider.close()
                except Exception:
                    pass
                if attempt >= self._policy.max_attempts:
                    break
                delay = min(
                    self._policy.initial_backoff_seconds * (2 ** (attempt - 1)),
                    self._policy.max_backoff_seconds,
                )
                self._sleep(delay)
            finally:
                secret = ""
        raise RemoteConnectivityError("remote endpoint is unavailable") from last_error


Authenticator = Callable[[AuthenticatedPrincipal, str], AuthenticatedPrincipal | None]
ExchangeHandler = Callable[[RemoteEnvelope], RemoteEnvelope]


class InProcessRemoteProvider:
    """Deterministic provider for CI and fault-injection tests only.

    It uses the same authenticated-principal and envelope contracts as network
    transports but performs no socket or Internet access.  The credential is
    passed to the injected authenticator and is never stored.
    """

    def __init__(
        self,
        authenticator: Authenticator,
        exchange_handler: ExchangeHandler,
    ) -> None:
        if not callable(authenticator) or not callable(exchange_handler):
            raise RemoteConnectivityError("in-process remote provider is invalid")
        self._authenticator = authenticator
        self._exchange_handler = exchange_handler
        self._context: RemoteConnectionContext | None = None

    @property
    def connected(self) -> bool:
        return self._context is not None

    def connect(
        self,
        principal: AuthenticatedPrincipal,
        secret: str,
    ) -> RemoteConnectionContext:
        if self._context is not None:
            raise RemoteConnectivityError("remote connection is already active")
        if not isinstance(principal, AuthenticatedPrincipal):
            raise RemoteConnectivityError("remote principal is invalid")
        if type(secret) is not str or not secret or secret != secret.strip():
            raise RemoteConnectivityError("remote credentials are unavailable")
        try:
            verified = self._authenticator(principal, secret)
        except RemoteConnectivityError:
            raise
        except Exception as exc:
            raise RemoteConnectivityError("remote authentication failed") from exc
        if not isinstance(verified, AuthenticatedPrincipal) or verified != principal:
            raise RemoteConnectivityError("remote authentication failed")
        context = RemoteConnectionContext(verified)
        self._context = context
        return context

    def exchange(self, envelope: RemoteEnvelope) -> RemoteEnvelope:
        if self._context is None:
            raise RemoteConnectivityError("remote connection is unavailable")
        if not isinstance(envelope, RemoteEnvelope):
            raise RemoteConnectivityError("remote envelope is invalid")
        try:
            response = self._exchange_handler(envelope)
        except RemoteConnectivityError:
            raise
        except Exception as exc:
            raise RemoteConnectivityError("remote provider exchange failed") from exc
        if not isinstance(response, RemoteEnvelope):
            raise RemoteConnectivityError("remote provider response is invalid")
        return response

    def close(self) -> None:
        self._context = None
