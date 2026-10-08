"""R66 server-only optional assurance, additive to existing R65 paid guard.

Synthetic fixtures exercise logic; they do NOT attest actual hardware, native
protection, NVDA or an independently authenticated production verifier.
"""
from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest

from continuum_runtime.high_assurance import (
    AssuranceCandidate, AssuranceEvidence, AssuranceMode, EvidenceClass,
    OptionalHighAssurance,
)
from continuum_runtime.server_premium import OperationAdmission, ServerPremiumGuard
from acs.protection_high_assurance_server_binding import (
    CanonicalHighAssurancePaidCallback, TrustedAssuranceContext,
)
from acs.protection_paid_server_binding import (
    CanonicalPaidOperationCallback, TrustedPremiumTransport,
)
from acs.server_application_boundary import ApiRequest, AuthenticatedPrincipal

NOW = datetime(2026, 10, 8, tzinfo=timezone.utc)
BUILD = "a" * 64


def principal_request(operation="premium.analysis"):
    return (
        AuthenticatedPrincipal("actor.one", "workspace.one", "session.one",
                               frozenset({"member"}), frozenset({"premium.use"})),
        ApiRequest(1, "request.one", "workspace.one", operation, {}),
    )


def evidence(**changes):
    base = AssuranceEvidence(
        candidate_id="candidate.one", build_sha256=BUILD, evidence_id="evidence.one",
        evidence_class=EvidenceClass.INDEPENDENT_EXTERNAL, observed_at=NOW,
        real_protected_build=True, genuine_hardware_or_cloud=True,
        binding_verified=True, nvda_compatible=True, keyboard_compatible=True,
        recovery_verified=True, loss_fails_closed=True,
        benchmark_within_budget=True, rollback_rejected=True,
    )
    return replace(base, **changes)


def assurance(verifier=lambda _ev: True):
    return OptionalHighAssurance(
        candidates=(AssuranceCandidate("candidate.one", AssuranceMode.USB_HARDWARE,
                                       "provider.one"),),
        independent_verifier=verifier,
        allowed_builds=frozenset({BUILD}),
    )


def paid_guard(state="NEW", calls=None):
    if calls is None:
        calls = []
    native = object.__new__(ServerPremiumGuard)
    def authorize(**kw):
        calls.append(kw)
        return OperationAdmission("account.one", "premium.analysis", "request.one", state)
    native.authorize_action = authorize
    return CanonicalPaidOperationCallback(
        guard=native,
        trusted_transport=lambda *_: TrustedPremiumTransport(
            actor_id="actor.one", session_id="session.one",
            account_id="account.one", access_token="server-access-only",
            installation_id="installation.one", device_id="device.one",
            build_id="build.one", raw_body=b"normalized-server-body", now=NOW,
        ),
    )


def trusted_context(**changes):
    return replace(TrustedAssuranceContext(
        candidate_id="candidate.one", build_sha256=BUILD,
        evidence=evidence(), now=NOW, baseline_authorized=True,
    ), **changes)


def callback(*, context=None, verifier=None, state="NEW", calls=None):
    return CanonicalHighAssurancePaidCallback(
        operation_id="premium.analysis",
        assurance=assurance() if verifier is None else assurance(verifier),
        trusted_context=(lambda *_: trusted_context()) if context is None else context,
        paid_callback=paid_guard(state, calls),
    )


def test_r66_success_is_only_additive_then_r65_reserves_paid_effect():
    calls = []
    # "independent" here is test-fixture simulation, NOT physical PoC.
    p, r = principal_request()
    assert callback(calls=calls)(p, r) is True
    assert len(calls) == 1
    assert calls[0]["operation_id"] == "premium.analysis"


@pytest.mark.parametrize("state", ["UNKNOWN", "CONFIRMED", "DENIED", ""])
def test_r66_never_promotes_non_new_r65_state(state):
    p, r = principal_request()
    assert callback(state=state)(p, r) is False


@pytest.mark.parametrize("changes", [
    {"baseline_authorized": False},
    {"baseline_authorized": 1},
    {"candidate_id": "other.candidate"},
    {"build_sha256": "b" * 64},
    {"evidence": evidence(evidence_class=EvidenceClass.SYNTHETIC_FIXTURE)},
    {"evidence": evidence(genuine_hardware_or_cloud=False)},
    {"evidence": evidence(nvda_compatible=False)},
    {"evidence": evidence(observed_at=NOW-timedelta(days=31))},
    {"evidence": evidence(observed_at=NOW+timedelta(seconds=1))},
])
def test_r66_denies_before_r65_side_effect_reservation(changes):
    calls = []
    p, r = principal_request()
    result = callback(context=lambda *_: trusted_context(**changes), calls=calls)(p, r)
    assert result is False
    assert calls == []


def test_r66_independent_verifier_fail_or_exception_denies():
    p, r = principal_request()
    for verifier in (lambda _ev: False, lambda _ev: 1,
                     lambda _ev: (_ for _ in ()).throw(RuntimeError("SECRET"))):
        calls = []
        assert callback(verifier=verifier, calls=calls)(p, r) is False
        assert calls == []


@pytest.mark.parametrize("value", [None, False, 1, {}, object()])
def test_r66_invalid_trusted_context_never_reaches_paid_guard(value):
    p, r = principal_request()
    calls = []
    assert callback(context=lambda *_: value, calls=calls)(p, r) is False
    assert calls == []


def test_r66_wrong_operation_and_private_exception_do_not_run_paid_effect():
    p, wrong = principal_request("premium.other")
    calls = []
    assert callback(calls=calls)(p, wrong) is False
    assert callback(context=lambda *_: (_ for _ in ()).throw(
        RuntimeError("PRIVATE_PROVIDER_SECRET")), calls=calls)(p, principal_request()[1]) is False
    assert calls == []


def test_r66_invalid_policy_fails_at_server_configuration():
    with pytest.raises(ValueError, match="R66_TRUSTED_AUTHORITY_NOT_CONFIGURED"):
        CanonicalHighAssurancePaidCallback(
            operation_id="premium.analysis", assurance=assurance(),
            trusted_context=lambda *_: trusted_context(), paid_callback=None,
        )


def test_r66_is_optional_not_global_and_cannot_bypass_other_paid_policy():
    # Original R65 remains exactly the callable for operations not registered
    # as high-assurance. This additional wrapper cannot authorize another op.
    p, r = principal_request()
    assert paid_guard()(p, r) is True
    assert callback()(p, principal_request("premium.other")[1]) is False
