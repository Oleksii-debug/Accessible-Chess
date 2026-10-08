"""R62 staged product server integration: signed proof, durable UNKNOWN, no client authority."""
from __future__ import annotations

from datetime import datetime, timezone

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from continuum_runtime.leak_response import LeakResponseService
from continuum_runtime.revocation import RevocationAuthority, RevocationKind
from continuum_runtime.watermark_attribution import issue_attribution, opaque_attribution_tag
from acs.protection_incident_response_boundary import (
    IncidentBoundaryDenied, TrustedIncidentBoundary,
)

NOW = datetime(2026, 10, 8, tzinfo=timezone.utc)
CASE = "e" * 32
EVIDENCE = "b" * 64


class Journal:
    """Test-only stand-in; NOT a production persistent transactional store."""
    def __init__(self):
        self.calls = []
        self.state = "EMPTY"
        self.finish_result = True

    def reserve(self, *, case_id, request_digest):
        self.calls.append(("reserve", case_id, request_digest))
        if self.state != "EMPTY":
            return "UNKNOWN"
        self.state = "UNKNOWN"
        return "NEW"

    def complete(self, *, case_id, request_digest, revocation_id):
        self.calls.append(("complete", case_id, request_digest))
        if self.finish_result is True:
            self.state = "DONE"
        return self.finish_result


@pytest.fixture()
def setup_case():
    signing = Ed25519PrivateKey.generate()
    public_key = signing.public_key().public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    artifact = b"synthetic first-party protected artifact" * 12
    tag = opaque_attribution_tag(
        issuer_secret=b"z" * 32, allocation_id="a" * 32, build_id="build.one")
    envelope = issue_attribution(
        build_id="build.one", protected_artifact=artifact,
        attribution_tag=tag, key_id="issuer.test", signer=signing.sign)
    r22 = RevocationAuthority()
    journal = Journal()
    verified = {"review": True, "approve": True, "operator": True}
    lineage = {"attribution_tag": tag, "build_id": "build.one",
               "device_id": "device.one", "credential_id": "credential.one"}
    svc = LeakResponseService(
        revocations=r22, trusted_public_keys={"issuer.test": public_key},
        lookup_allocation=lambda _tag: dict(lineage),
        corroborate=lambda *_: verified["review"],
        approve=lambda *_: verified["approve"],
    )
    bridge = TrustedIncidentBoundary(
        service=svc, authorize_operator=lambda *_: verified["operator"],
        durable_journal=journal)
    request = dict(operator_session="trusted-operator-session", case_id=CASE,
                   evidence_sha256=EVIDENCE, envelope=envelope,
                   protected_artifact=artifact, expected_build_id="build.one",
                   kind=RevocationKind.CREDENTIAL, now=NOW)
    return bridge, journal, r22, verified, request


def test_r62_exact_signed_corroborated_operator_action_writes_one_r22_target(setup_case):
    bridge, journal, r22, _, request = setup_case
    result = bridge.apply(**request)
    assert result["status"] == "R62_TARGET_REVOCATION_RECORDED"
    assert result["release_approved"] is False
    assert r22.is_revoked(kind=RevocationKind.CREDENTIAL, subject_id="credential.one")
    assert not r22.is_revoked(kind=RevocationKind.BUILD, subject_id="build.one")
    assert [c[0] for c in journal.calls] == ["reserve", "complete"]
    assert "credential.one" not in str(result)


@pytest.mark.parametrize("decision", [None, False, 0, 1, "yes"])
def test_r62_untrusted_or_truthy_operator_denied_before_reservation(setup_case, decision):
    bridge, journal, r22, config, request = setup_case
    config["operator"] = decision
    with pytest.raises(IncidentBoundaryDenied, match="R62_OPERATOR_DENIED"):
        bridge.apply(**request)
    assert journal.calls == []
    assert r22.history() == ()


@pytest.mark.parametrize("bad_field,bad_value", [
    ("case_id", "user@example.com"), ("evidence_sha256", "bad"),
    ("protected_artifact", b""), ("kind", RevocationKind.ACCOUNT),
    ("operator_session", ""), ("now", datetime(2026, 10, 8)),
])
def test_r62_invalid_request_never_reserves_or_revokes(
    setup_case, bad_field, bad_value
):
    bridge, journal, r22, _, request = setup_case
    with pytest.raises(IncidentBoundaryDenied, match="R62_REQUEST_INVALID"):
        bridge.apply(**(request | {bad_field: bad_value}))
    assert journal.calls == []
    assert r22.history() == ()


def test_r62_fake_watermark_or_uncorroborated_evidence_cannot_revoke(setup_case):
    bridge, journal, r22, config, request = setup_case
    config["review"] = False
    with pytest.raises(IncidentBoundaryDenied, match="R62_CANONICAL_RESPONSE_DENIED"):
        bridge.apply(**request)
    assert journal.state == "UNKNOWN"
    assert r22.history() == ()
    config["review"] = True
    with pytest.raises(IncidentBoundaryDenied, match="R62_CASE_NOT_NEW"):
        bridge.apply(**request)
    assert r22.history() == ()


def test_r62_changed_proof_and_replay_do_not_repeat_effect(setup_case):
    bridge, journal, r22, _, request = setup_case
    bridge.apply(**request)
    with pytest.raises(IncidentBoundaryDenied, match="R62_CASE_NOT_NEW"):
        bridge.apply(**request)
    with pytest.raises(IncidentBoundaryDenied, match="R62_CASE_NOT_NEW"):
        bridge.apply(**(request | {"evidence_sha256": "c" * 64}))
    assert len(r22.history()) == 1


def test_r62_unknown_journal_commit_never_reports_success_or_retries(setup_case):
    bridge, journal, r22, _, request = setup_case
    journal.finish_result = 1
    with pytest.raises(IncidentBoundaryDenied, match="R62_JOURNAL_UNKNOWN"):
        bridge.apply(**request)
    assert len(r22.history()) == 1
    with pytest.raises(IncidentBoundaryDenied, match="R62_CASE_NOT_NEW"):
        bridge.apply(**request)
    assert len(r22.history()) == 1


def test_r62_forged_envelope_fails_closed_without_disclosing_secrets(setup_case):
    bridge, journal, r22, _, request = setup_case
    forged = dict(request["envelope"])
    forged["signature"] = "PRIVATE-MARKER-NOT-A-REAL-SIGNATURE"
    with pytest.raises(IncidentBoundaryDenied, match="R62_CANONICAL_RESPONSE_DENIED") as err:
        bridge.apply(**(request | {"envelope": forged}))
    assert "PRIVATE-MARKER" not in str(err.value)
    assert r22.history() == ()


def test_r62_no_second_authority_and_no_missing_journal_fallback(setup_case):
    bridge, journal, r22, _, request = setup_case
    with pytest.raises(IncidentBoundaryDenied, match="R62_TRUSTED_BACKEND_NOT_CONFIGURED"):
        TrustedIncidentBoundary(service=bridge._service,
                                authorize_operator=lambda *_: True,
                                durable_journal=None)
    assert journal.calls == []
    assert r22.history() == ()
