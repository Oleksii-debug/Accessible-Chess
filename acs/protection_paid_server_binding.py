"""R63/R64 -> R65 trusted server composition, never client payment authority.

This module connects the ONE canonical neutral subscription/billing readers and
premium operation admission to the existing Chess ServerApplicationBoundary.
No payment SDK, provider signature verifier, token issuer, database or second
entitlement engine lives here. Production provider and durable stores are
separately required before enabling paid operations.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Callable

from continuum_runtime.billing_adapter import (
    AtomicBillingStore, BillingAdapter, TrustedBillingVerifier,
)
from continuum_runtime.server_premium import OperationAdmission, ServerPremiumGuard
from continuum_runtime.subscription_policy import (
    SubscriptionPlan, SubscriptionPolicyBackend,
)
from acs.server_application_boundary import (
    ApiRequest, AuthenticatedPrincipal,
)


@dataclass(frozen=True)
class BillingAuthorityBinding:
    """Same R64 transactional record store backs R63 read-only authorization."""
    adapter: BillingAdapter
    subscriptions: SubscriptionPolicyBackend


def bind_canonical_billing_authority(
    *, provider_id: str, verifier: TrustedBillingVerifier,
    store: AtomicBillingStore, plans: tuple[SubscriptionPlan, ...],
) -> BillingAuthorityBinding:
    """The caller supplies REAL provider verification and a durable ACID store.

    InMemoryBillingStore and synthetic verifiers are TEST-ONLY and cannot
    satisfy production readiness or issue a release approval.
    """
    adapter = BillingAdapter(provider_id=provider_id, verifier=verifier, store=store)
    subscriptions = SubscriptionPolicyBackend(plans=plans, record_loader=store.get)
    return BillingAuthorityBinding(adapter=adapter, subscriptions=subscriptions)


@dataclass(frozen=True)
class TrustedPremiumTransport:
    """Authenticated *server-derived* context; never hydrate from a browser body."""
    actor_id: str
    session_id: str
    account_id: str
    access_token: str
    installation_id: str
    device_id: str
    build_id: str
    raw_body: bytes
    now: datetime


class CanonicalPaidOperationCallback:
    """Use as the EXISTING ServerApplicationBoundary(premium_guard=...) hook.

    Only literal NEW from continuum R65 permits a handler to begin. The R65
    ledger keeps UNKNOWN until independent effect reconciliation; neither an
    ACK, a duplicate request, nor browser-supplied premium flags can create
    another paid operation. Queued heavy paid effects stay denied by the
    already-existing ServerOperation constructor.
    """

    def __init__(
        self, *, guard: ServerPremiumGuard,
        trusted_transport: Callable[[AuthenticatedPrincipal, ApiRequest],
                                    TrustedPremiumTransport],
    ):
        if type(guard) is not ServerPremiumGuard or not callable(trusted_transport):
            raise ValueError("R63_R65_BACKEND_NOT_CONFIGURED")
        self._guard = guard
        self._transport = trusted_transport

    def __call__(self, principal: AuthenticatedPrincipal, request: ApiRequest) -> bool:
        if (type(principal) is not AuthenticatedPrincipal
                or type(request) is not ApiRequest):
            return False
        try:
            ctx = self._transport(principal, request)
            if (type(ctx) is not TrustedPremiumTransport
                    or type(ctx.actor_id) is not str
                    or ctx.actor_id != principal.actor_id
                    or type(ctx.session_id) is not str
                    or ctx.session_id != principal.session_id
                    or type(ctx.account_id) is not str or not ctx.account_id
                    or type(ctx.access_token) is not str or not ctx.access_token
                    or type(ctx.installation_id) is not str
                    or not ctx.installation_id
                    or type(ctx.device_id) is not str or not ctx.device_id
                    or type(ctx.build_id) is not str or not ctx.build_id
                    or type(ctx.raw_body) is not bytes
                    or len(ctx.raw_body) > 65536
                    or not isinstance(ctx.now, datetime)
                    or ctx.now.tzinfo is None):
                return False
            result = self._guard.authorize_action(
                operation_id=request.operation,
                request_id=request.request_id,
                raw_body=ctx.raw_body, access_token=ctx.access_token,
                installation_id=ctx.installation_id,
                device_id=ctx.device_id, build_id=ctx.build_id, now=ctx.now,
            )
            return (type(result) is OperationAdmission
                    and result.state == "NEW"
                    and result.account_id == ctx.account_id
                    and result.operation_id == request.operation
                    and result.request_id == request.request_id)
        except Exception:
            # Authentication, subscription, R22/device, billing and quota
            # failures are private server information: fail closed.
            return False
