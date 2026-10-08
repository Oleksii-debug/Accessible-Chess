"""R72 read-only signed incident/update evidence and UNKNOWN reconciliation."""
from __future__ import annotations

from dataclasses import asdict, replace
from datetime import datetime
import hashlib
import json

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from continuum_runtime.incident_response import (
    EffectReceipt, IncidentCase, signable_case, signable_receipt,
    effect_idempotency_key,
)
from continuum_runtime.update_metadata import build_signed_update_metadata
from scripts.security_r72_incident_evidence_gate import assess_product_incident_evidence
from scripts.security_r73_product_evidence_gate import ProductEvidenceError

NOW = 1791460000
SRC = "a" * 64
_ACTIONS = (
    "PRESERVE_EVIDENCE", "REVOKE_BUILD", "RAISE_BUILD_FLOOR",
    "PUBLISH_SIGNED_UPDATE", "CUSTOMER_RECOVERY",
)


def sha(data):
    return hashlib.sha256(data).hexdigest()


def public(private):
    return private.public_key().public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw)


@pytest.fixture()
def fixture(tmp_path):
    approval, effect, updater = (Ed25519PrivateKey.generate() for _ in range(3))
    trust = tmp_path / "independent.json"
    trust.write_text(json.dumps({
        "schema_version": 1,
        "approval_public_keys": {"reviewer": public(approval).hex()},
        "effect_public_keys": {"effect-authority": public(effect).hex()},
        "trusted_update_keys": {"updater": public(updater).hex()},
    }))
    artifact = tmp_path / "incident-original-evidence.bin"
    artifact.write_bytes(b"synthetic isolated incident evidence")
    case = IncidentCase(
        case_id="case-007", kind="BUILD", compromised_id="build-010",
        compromised_build=10, channel="stable", source_sha256=SRC,
        evidence_sha256=sha(artifact.read_bytes()),
        opened_at=NOW-300, sequence=11,
        approver_id="reviewer", signature_hex="0"*128)
    case = replace(case, signature_hex=approval.sign(signable_case(case)).hex())
    digest = sha(signable_case(case) + bytes.fromhex(case.signature_hex))
    case_file = tmp_path / "incident.json"
    case_file.write_text(json.dumps({"schema_version": 1, "case": asdict(case)}))
    def signed_receipt(action, sequence, outcome="CONFIRMED", effect_id=None):
        item = EffectReceipt(
            case_digest=digest, action=action,
            effect_id=effect_id or "effect."+action,
            idempotency_key=effect_idempotency_key(digest, action),
            outcome=outcome, sequence=sequence, witnessed_at=NOW-3,
            verifier_id="effect-authority", signature_hex="0"*128)
        return replace(item, signature_hex=effect.sign(signable_receipt(item)).hex())
    records = tmp_path / "receipts.json"
    def set_receipts(items):
        records.write_text(json.dumps({
            "schema_version": 1, "receipts": [asdict(x) for x in items],
        }))
    set_receipts([])
    signed_update = build_signed_update_metadata(payload={
        "schema_version": 1, "metadata_type": "signed-update-metadata-v1",
        "sequence": 12, "channel": "stable", "version": "1.0.11",
        "build_number": 11, "minimum_supported_build": 11,
        "package_id": "emergency-11", "package_size": 16,
        "package_sha256": "c" * 64,
    }, key_id="updater", signer=updater.sign)
    update_file = tmp_path / "update.json"
    update_file.write_text(json.dumps(signed_update))
    return dict(case_file=case_file, receipts_file=records,
                incident_artifact=artifact, signed_update_file=update_file,
                independent_keys_file=trust,
                independent_keys_sha256=sha(trust.read_bytes()),
                expected_source_sha256=SRC, now=NOW,
                minimum_sequence_exclusive=10, set_receipts=set_receipts,
                signed_receipt=signed_receipt)


def assess(trial, **kw):
    args = {k:v for k,v in trial.items()
            if k not in ("set_receipts", "signed_receipt")}
    return assess_product_incident_evidence(**(args | kw))


def test_r72_absent_effects_never_claim_incident_complete(fixture):
    result = assess(fixture)
    assert result["status"] == "EFFECTS_RECONCILIATION_REQUIRED"
    assert len(result["pending"]) == 5
    assert result["release_approved"] is False


def test_r72_independently_signed_complete_receipts_remain_nonrelease(fixture):
    fixture["set_receipts"]([
        fixture["signed_receipt"](act, 12+i) for i,act in enumerate(_ACTIONS)
    ])
    result = assess(fixture)
    assert result["status"] == "INDEPENDENT_EFFECT_RECEIPTS_COMPLETE"
    assert result["pending"] == []
    assert result["release_approved"] is False
    assert result["actual_operator_execution"] == "NOT_VERIFIED"


def test_r72_unknown_is_pending_and_requires_same_effect_signed_reconciliation(fixture):
    first = fixture["signed_receipt"](_ACTIONS[0], 12, "UNKNOWN")
    fixture["set_receipts"]([first])
    result = assess(fixture)
    assert _ACTIONS[0] in result["unknown_effects"]
    assert _ACTIONS[0] in result["pending"]
    confirmed = fixture["signed_receipt"](_ACTIONS[0], 13, "CONFIRMED", first.effect_id)
    fixture["set_receipts"]([first, confirmed])
    result = assess(fixture)
    assert _ACTIONS[0] in result["confirmed"]
    assert result["unknown_effects"] == []


def test_r72_tampered_signature_and_cross_source_denied(fixture):
    bad = fixture["signed_receipt"](_ACTIONS[0], 12)
    fixture["set_receipts"]([replace(bad, signature_hex="f"*128)])
    with pytest.raises(ProductEvidenceError):
        assess(fixture)
    fixture["set_receipts"]([])
    with pytest.raises(ProductEvidenceError):
        assess(fixture, expected_source_sha256="b"*64)


def test_r72_actual_original_evidence_tamper_denied(fixture):
    fixture["incident_artifact"].write_bytes(b"changed incident evidence")
    with pytest.raises(ProductEvidenceError):
        assess(fixture)


def test_r72_trust_pin_and_signed_update_tamper_denied(fixture):
    with pytest.raises(ProductEvidenceError):
        assess(fixture, independent_keys_sha256="b"*64)
    fixture["signed_update_file"].write_text(json.dumps({"forged": True}))
    with pytest.raises(ProductEvidenceError):
        assess(fixture)


def test_r72_changed_case_context_and_replay_floor_denied(fixture):
    with pytest.raises(ProductEvidenceError):
        assess(fixture, minimum_sequence_exclusive=11)
    data = json.loads(fixture["case_file"].read_text())
    data["case"]["compromised_build"] = 9
    fixture["case_file"].write_text(json.dumps(data))
    with pytest.raises(ProductEvidenceError):
        assess(fixture)


def test_r72_no_unsigned_incident_override(fixture):
    data = json.loads(fixture["case_file"].read_text())
    data["case"]["signature_hex"] = "0"*128
    fixture["case_file"].write_text(json.dumps(data))
    with pytest.raises(ProductEvidenceError):
        assess(fixture)
