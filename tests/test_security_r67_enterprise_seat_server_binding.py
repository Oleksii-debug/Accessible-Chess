"""R67 product-side authenticated LAN seat bridge contract.

Isolated seam tests: mock ledger is NOT a real enterprise seat deployment.
Canonical neutral R67 ledger/anchor tests run separately on the upstream source.
"""
from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone

import pytest

from continuum_runtime.enterprise_seats import EnterpriseSeatServer
from continuum_runtime.license_container import ContainerKind, ContainerRequest
from acs.server_application_boundary import ApiRequest, AuthenticatedPrincipal
from acs.protection_enterprise_seat_server_binding import (
    CanonicalEnterpriseSeatBoundary, TrustedSeatSession,
)

NOW = datetime(2026, 10, 8, tzinfo=timezone.utc)
TICKET = "a" * 48


def principal(*, permissions=frozenset({"enterprise.seat.use"})):
    return AuthenticatedPrincipal(
        "actor.one", "workspace.one", "session.one",
        frozenset({"member"}), permissions,
    )


def request(operation="enterprise.seat.checkout", payload=None, workspace="workspace.one"):
    return ApiRequest(
        1, "request.one", workspace, operation,
        {} if payload is None else payload,
    )


def session():
    return TrustedSeatSession(
        license_request=ContainerRequest(
            kind=ContainerKind.ENTERPRISE, product_id="product.one",
            account_id="account.one", device_id="device.one",
            build_id="build.one", boundary_id="premium.analysis",
        ),
        enforcer=object(), context={"existing_service": "resolved"},
        trusted_public_keys={"issuer.one": b"fake-test-public-key"},
        minimum_policy_version=1, now=NOW,
    )


def boundary(*, resolved=None, ticket=TICKET, checkout_error=None, checkin_error=None):
    calls = []
    native = object.__new__(EnterpriseSeatServer)
    def checkout(**kw):
        calls.append(("checkout", kw))
        if checkout_error is not None:
            raise checkout_error
        return ticket
    def checkin(**kw):
        calls.append(("checkin", kw))
        if checkin_error is not None:
            raise checkin_error
    native.checkout = checkout
    native.checkin = checkin
    bridge = CanonicalEnterpriseSeatBoundary(
        seats=native,
        trusted_session=(lambda _principal: session()) if resolved is None else resolved,
    )
    return bridge, calls


def test_r67_checkout_binds_existing_entitlement_and_returns_opaque_ticket():
    bridge, calls = boundary()
    assert bridge.checkout(principal(), request()) == TICKET
    assert len(calls) == 1
    kw = calls[0][1]
    assert kw["request"].kind is ContainerKind.ENTERPRISE
    assert kw["request"].account_id == "account.one"
    assert kw["minimum_policy_version"] == 1
    assert "payload" not in kw and "ticket" not in kw


@pytest.mark.parametrize("p,r", [
    (principal(), request("enterprise.seat.checkin")),
    (principal(), request(payload={"account_id": "attacker"})),
    (principal(), request(workspace="workspace.other")),
    (principal(permissions=frozenset()), request()),
    (principal(), request(payload={"device_id": "attacker"})),
])
def test_r67_invalid_checkout_does_not_mutate_store(p, r):
    bridge, calls = boundary()
    assert bridge.checkout(p, r) is None
    assert calls == []


@pytest.mark.parametrize("bad", [None, 1, {}, object(),
                                 replace(session(), minimum_policy_version=True),
                                 replace(session(), trusted_public_keys={}),
                                 replace(session(), license_request=ContainerRequest(
                                     ContainerKind.CLOUD, "product.one", "account.one",
                                     "device.one", "build.one", "premium.analysis"))])
def test_r67_invalid_server_resolution_cannot_allocate(bad):
    bridge, calls = boundary(resolved=lambda _principal: bad)
    assert bridge.checkout(principal(), request()) is None
    assert calls == []


def test_r67_checkin_needs_well_formed_ticket_and_signed_subject():
    bridge, calls = boundary()
    r = request("enterprise.seat.checkin", {"ticket": TICKET})
    assert bridge.checkin(principal(), r) is True
    assert calls[0][0] == "checkin"
    assert calls[0][1]["ticket"] == TICKET


@pytest.mark.parametrize("payload", [{}, {"ticket": "broken"},
                                      {"ticket": TICKET, "device": "other"},
                                      {"ticket": True}])
def test_r67_invalid_checkin_payload_is_noop(payload):
    bridge, calls = boundary()
    assert bridge.checkin(principal(), request("enterprise.seat.checkin", payload)) is False
    assert calls == []


def test_r67_unknown_effect_never_blind_retried_by_adapter():
    bridge, calls = boundary(checkout_error=RuntimeError("UNKNOWN-PRIVATE-STORE"))
    assert bridge.checkout(principal(), request()) is None
    assert len(calls) == 1  # no blind retransmission
    bridge, calls = boundary(checkin_error=RuntimeError("UNKNOWN-PRIVATE-STORE"))
    assert bridge.checkin(principal(), request("enterprise.seat.checkin",
                                              {"ticket": TICKET})) is False
    assert len(calls) == 1


def test_r67_stale_or_malformed_return_never_grants_client_capability():
    for t in ("not-a-ticket", 1, True, object()):
        bridge, calls = boundary(ticket=t)
        assert bridge.checkout(principal(), request()) is None
        assert len(calls) == 1


def test_r67_missing_trusted_provider_cannot_be_configured():
    with pytest.raises(ValueError, match="R67_TRUSTED_SEAT_AUTHORITY_NOT_CONFIGURED"):
        CanonicalEnterpriseSeatBoundary(seats=None, trusted_session=lambda *_: session())
