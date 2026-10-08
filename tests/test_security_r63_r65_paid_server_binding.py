"""Canonical R63/R64 billing reader + R65 server callback candidate contracts."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from continuum_runtime.billing_adapter import (
    InMemoryBillingStore, VerifiedBillingEvent, BillingError,
)
from continuum_runtime.server_premium import (
    OperationAdmission, ServerPremiumGuard,
)
from continuum_runtime.subscription_policy import (
    AccessSource, SubscriptionPlan, SubscriptionState, SubscriptionError,
)
from acs.server_application_boundary import (
    ApiRequest, AuthenticatedPrincipal,
)
from acs.protection_paid_server_binding import (
    CanonicalPaidOperationCallback, TrustedPremiumTransport,
    bind_canonical_billing_authority,
)

NOW = datetime(2026, 10, 8, tzinfo=timezone.utc)


def bill_event(*, event_id="event.one", sequence=1,
               state=SubscriptionState.ACTIVE,
               account_id="account.one", plan_id="premium"):
    return VerifiedBillingEvent(
        provider_id="synthetic.provider", event_id=event_id,
        account_id=account_id, subscription_id="subscription.one",
        plan_id=plan_id, state=state,
        valid_until=NOW + timedelta(days=5),
        grace_until=None, sequence=sequence, occurred_at=NOW,
    )


class FixtureVerifier:
    """Test-only; not a production webhook signature or authenticated API."""
    def __init__(self):
        self.event = bill_event()
    def verify_webhook(self, raw_body, headers, now):
        return self.event
    def fetch_verified_snapshot(self, account_id, now):
        return self.event


def test_r63_r64_share_one_trusted_store_and_revoke_immediately():
    store = InMemoryBillingStore()
    verifier = FixtureVerifier()
    bind = bind_canonical_billing_authority(
        provider_id="synthetic.provider", verifier=verifier,
        store=store, plans=(SubscriptionPlan("premium", frozenset({"premium.analysis"})),),
    )
    with pytest.raises(SubscriptionError):
        bind.subscriptions.authorize(
            account_id="account.one",
            requested_capabilities=frozenset({"premium.analysis"}), now=NOW)
    bind.adapter.handle_webhook(raw_body=b"fixture", headers={}, now=NOW)
    assert bind.subscriptions.authorize(
        account_id="account.one",
        requested_capabilities=frozenset({"premium.analysis"}), now=NOW) > NOW
    # Replayed paid webhook must read CURRENT state, never restore stale success.
    verifier.event = bill_event(event_id="event.two", sequence=2,
                                state=SubscriptionState.REVOKED)
    bind.adapter.handle_webhook(raw_body=b"fixture", headers={}, now=NOW)
    verifier.event = bill_event()
    bind.adapter.handle_webhook(raw_body=b"fixture", headers={}, now=NOW)
    with pytest.raises(SubscriptionError):
        bind.subscriptions.authorize(
            account_id="account.one",
            requested_capabilities=frozenset({"premium.analysis"}), now=NOW)


def test_r64_stale_provider_sequence_cannot_promote_account():
    store = InMemoryBillingStore()
    verifier = FixtureVerifier()
    bind = bind_canonical_billing_authority(
        provider_id="synthetic.provider", verifier=verifier,
        store=store, plans=(SubscriptionPlan("premium", frozenset({"premium.analysis"})),),
    )
    verifier.event = bill_event(event_id="event.two", sequence=2,
                                state=SubscriptionState.REVOKED)
    bind.adapter.handle_webhook(raw_body=b"fixture", headers={}, now=NOW)
    verifier.event = bill_event(event_id="event.one", sequence=1)
    with pytest.raises(BillingError):
        bind.adapter.handle_webhook(raw_body=b"fixture", headers={}, now=NOW)


def principal_request():
    principal = AuthenticatedPrincipal(
        actor_id="actor.one", workspace_id="workspace.one", session_id="session.one",
        roles=frozenset({"member"}), permissions=frozenset({"premium.use"}))
    request = ApiRequest(
        schema_version=1, request_id="request.one", workspace_id="workspace.one",
        operation="premium.analysis", payload={"premium": True})
    return principal, request


def good_transport():
    return TrustedPremiumTransport(
        actor_id="actor.one", session_id="session.one", account_id="account.one",
        access_token="server-session-token", installation_id="installation.one",
        device_id="device.one", build_id="build.one",
        raw_body=b"trusted-server-normalized-body", now=NOW)


def guard_with(admit):
    # Isolate the native product callback while preserving the EXACT canonical
    # ServerPremiumGuard type. Real R65 internals have their own negative suites.
    guard = object.__new__(ServerPremiumGuard)
    guard.authorize_action = admit
    return guard


def test_r65_new_canonical_admission_only_allows_handler_callback():
    seen = []
    guard = guard_with(lambda **kw: seen.append(kw) or OperationAdmission(
        "account.one", "premium.analysis", "request.one", "NEW"))
    callback = CanonicalPaidOperationCallback(
        guard=guard, trusted_transport=lambda *_: good_transport())
    p, r = principal_request()
    assert callback(p, r) is True
    assert seen[0]["access_token"] == "server-session-token"
    assert seen[0]["raw_body"] == b"trusted-server-normalized-body"
    assert "premium" not in seen[0]


@pytest.mark.parametrize("state", ["UNKNOWN", "CONFIRMED", "DENIED", ""])
def test_r65_unknown_ack_replay_or_invalid_admission_does_not_execute(state):
    guard = guard_with(lambda **_: OperationAdmission(
        "account.one", "premium.analysis", "request.one", state))
    callback = CanonicalPaidOperationCallback(
        guard=guard, trusted_transport=lambda *_: good_transport())
    p, r = principal_request()
    assert callback(p, r) is False


def test_r65_transport_session_actor_binding_prevents_reservation():
    called = []
    guard = guard_with(lambda **_: called.append(1))
    bad = TrustedPremiumTransport(
        **{**good_transport().__dict__, "session_id": "other-session"})
    callback = CanonicalPaidOperationCallback(
        guard=guard, trusted_transport=lambda *_: bad)
    p, r = principal_request()
    assert callback(p, r) is False
    assert called == []


@pytest.mark.parametrize("bad", [False, None, 1, "yes", {}])
def test_r65_invalid_trusted_transport_fails_closed_without_effect(bad):
    guard = guard_with(lambda **_: pytest.fail("untrusted transport reached R65"))
    callback = CanonicalPaidOperationCallback(
        guard=guard, trusted_transport=lambda *_: bad)
    p, r = principal_request()
    assert callback(p, r) is False


def test_r65_private_auth_exception_redacted_to_boolean_denial():
    def bad_auth(**_):
        raise RuntimeError("PRIVATE-SERVICE-TOKEN-DO-NOT-LOG")
    callback = CanonicalPaidOperationCallback(
        guard=guard_with(bad_auth),
        trusted_transport=lambda *_: good_transport())
    p, r = principal_request()
    assert callback(p, r) is False
