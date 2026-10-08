"""R61 actual-byte signed attribution reader; no issuer or release claims."""
from __future__ import annotations

from hashlib import sha256
import json
from dataclasses import asdict

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from continuum_runtime.watermark_attribution import issue_attribution
from scripts.security_r61_attribution_gate import (
    ProductEvidenceError, assess_product_attribution,
)


@pytest.fixture
def case(tmp_path):
    # This is a synthetic signed marker for contract testing, NOT a production
    # issuer key, actual protected native Chess executable or release evidence.
    private = Ed25519PrivateKey.generate()
    public_hex = private.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    ).hex()
    artifact = b"test-only-protected-first-party-piece-no-live-protector"
    protected = tmp_path / "protected-component.bin"
    protected.write_bytes(artifact)
    build = "chess-test-build"
    envelope = issue_attribution(
        build_id=build, protected_artifact=artifact,
        attribution_tag="3" * 64, key_id="independent-key",
        signer=private.sign,
    )
    envelope_file = tmp_path / "mark.json"
    envelope_file.write_text(json.dumps(envelope))
    keys = tmp_path / "approved-keys.json"
    keys.write_text(json.dumps({
        "schema_version": 1,
        "verifier_public_keys": {"independent-key": public_hex},
    }))
    return {
        "protected_artifact": protected, "envelope_file": envelope_file,
        "approved_keys": keys,
        "approved_keys_sha256": sha256(keys.read_bytes()).hexdigest(),
        "expected_artifact_sha256": sha256(artifact).hexdigest(),
        "expected_build_id": build,
    }


def test_signed_attribution_actual_bytes_never_approves_release(case):
    out = assess_product_attribution(**case)
    assert out["status"] == "INDEPENDENT_SIGNATURE_BYTE_READBACK_ONLY"
    assert out["release_approved"] is False
    assert "attribution_tag" not in out
    assert out["windows_nvda_protected_release"] == "NOT_VERIFIED"


def test_forged_artifact_after_signing_rejected(case):
    case["protected_artifact"].write_bytes(b"forged-bytes")
    with pytest.raises(ProductEvidenceError):
        assess_product_attribution(**case)


def test_unknown_key_rejected(case):
    packet = json.loads(case["envelope_file"].read_text())
    packet["key_id"] = "different-key"
    case["envelope_file"].write_text(json.dumps(packet))
    with pytest.raises(ProductEvidenceError, match="R61_CANONICAL_ATTRIBUTION_DENIED"):
        assess_product_attribution(**case)


def test_forged_signature_rejected(case):
    packet = json.loads(case["envelope_file"].read_text())
    packet["signature"] = "A" * 86
    case["envelope_file"].write_text(json.dumps(packet))
    with pytest.raises(ProductEvidenceError):
        assess_product_attribution(**case)


def test_wrong_build_or_digest_is_not_replayable(case):
    with pytest.raises(ProductEvidenceError):
        assess_product_attribution(**{**case, "expected_build_id": "other-build"})
    with pytest.raises(ProductEvidenceError):
        assess_product_attribution(**{**case, "expected_artifact_sha256": "0" * 64})


def test_trust_inventory_pin_cannot_be_swapped(case):
    trust = json.loads(case["approved_keys"].read_text())
    trust["verifier_public_keys"]["independent-key"] = "0" * 64
    case["approved_keys"].write_text(json.dumps(trust))
    with pytest.raises(ProductEvidenceError, match="R61_INDEPENDENT_TRUST_PIN_MISMATCH"):
        assess_product_attribution(**case)


@pytest.mark.parametrize("replacement", [
    {"schema_version": True, "verifier_public_keys": {}},
    {"schema_version": 1, "verifier_public_keys": {}},
    {"schema_version": 1, "verifier_public_keys": {"k": "ff"}},
])
def test_invalid_trust_schema_rejected(case, replacement):
    case["approved_keys"].write_text(json.dumps(replacement))
    kwargs = {**case, "approved_keys_sha256": sha256(case["approved_keys"].read_bytes()).hexdigest()}
    with pytest.raises(ProductEvidenceError):
        assess_product_attribution(**kwargs)


def test_duplicate_envelope_keys_rejected(case):
    raw = case["envelope_file"].read_text()
    case["envelope_file"].write_text('{"schema_version":1,"schema_version":1,"payload":{}}')
    with pytest.raises(ProductEvidenceError, match="EVIDENCE_DUPLICATE_KEY"):
        assess_product_attribution(**case)


def test_symlinked_artifact_never_used(case, tmp_path):
    original = case["protected_artifact"]
    original.unlink()
    target = tmp_path / "outside.bin"
    target.write_bytes(b"test")
    try:
        original.symlink_to(target)
    except (OSError, NotImplementedError):
        pytest.skip("symlink creation unavailable")
    with pytest.raises(ProductEvidenceError):
        assess_product_attribution(**case)


def test_missing_verification_envelope_denied(case):
    case["envelope_file"].unlink()
    with pytest.raises(ProductEvidenceError):
        assess_product_attribution(**case)
