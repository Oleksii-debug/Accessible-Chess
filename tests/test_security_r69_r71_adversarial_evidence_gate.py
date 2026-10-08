"""Build-only R69/R71 product artifact, independent keys and adversarial evidence."""
from __future__ import annotations

from dataclasses import asdict, replace
import hashlib
import json

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from continuum_runtime.offline_crack_qualification import (
    ATTACK_BOUNDARIES, ProbeEvidence, _payload,
)
from continuum_runtime.protector_release_qualification import (
    REQUIRED_CHECKS, ReleaseObservation, signable_observation,
)
from scripts.security_r69_r71_adversarial_evidence_gate import (
    assess_adversarial_product_evidence,
)
from scripts.security_r73_product_evidence_gate import ProductEvidenceError

NOW = 1791460000
SOURCE = "a" * 64


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


@pytest.fixture()
def trial(tmp_path):
    signer = Ed25519PrivateKey.generate()
    public = signer.public_key().public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    keys = tmp_path / "trusted-keys.json"
    keys.write_text(json.dumps({
        "schema_version": 1,
        "verifier_public_keys": {"independent.test": public.hex()},
    }))
    image = tmp_path / "protected-release.zip"
    image.write_bytes(b"test fixture, NOT A REAL WINDOWS ZIP")
    return {
        "tmp": tmp_path, "signer": signer, "image": image,
        "keys": keys, "keys_hash": sha(keys.read_bytes()),
        "artifact_hash": sha(image.read_bytes()),
    }


def packet(trial, section, *, incomplete=False):
    if section == "R69":
        rows = []
        for i, (scenario, boundary) in enumerate(sorted(ATTACK_BOUNDARIES.items()), start=1):
            obj = ProbeEvidence(
                scenario=scenario, boundary=boundary, evidence_class="SIMULATION",
                outcome="DENIED", source_sha256=SOURCE,
                artifact_sha256=trial["artifact_hash"], sequence=i,
                observed_at=NOW, nonce="nonce." + str(i),
                verifier_id="independent.test", signature_hex="0" * 128)
            obj = replace(obj, signature_hex=trial["signer"].sign(_payload(obj)).hex())
            rows.append(asdict(obj))
        if incomplete:
            rows = rows[:-1]
        return {"schema_version": 1, "probes": rows}
    rows = []
    for i, check in enumerate(sorted(REQUIRED_CHECKS), start=1):
        obj = ReleaseObservation(
            check=check, evidence_class="SIMULATION", outcome="ACCEPTED",
            source_sha256=SOURCE,
            protected_artifact_sha256=trial["artifact_hash"],
            build_id="build.one", platform="windows-x64", sequence=i,
            witnessed_at=NOW, nonce="nonce." + str(i),
            verifier_id="independent.test", signature_hex="0" * 128)
        obj = replace(obj, signature_hex=trial["signer"].sign(
            signable_observation(obj)).hex())
        rows.append(asdict(obj))
    if incomplete:
        rows = rows[:-1]
    return {"schema_version": 1, "observations": rows}


def assess(trial, section, **overrides):
    file = trial["tmp"] / "signed-proofs.json"
    file.write_text(json.dumps(packet(trial, section)))
    args = dict(section=section, protected_artifact=trial["image"],
                evidence=file, approved_keys=trial["keys"],
                approved_keys_sha256=trial["keys_hash"],
                expected_source_sha256=SOURCE,
                expected_build_id="build.one", expected_platform="windows-x64",
                now=NOW)
    args.update(overrides)
    return assess_adversarial_product_evidence(**args)


@pytest.mark.parametrize("section", ["R69", "R71"])
def test_r69_r71_complete_signed_synthetic_report_never_approves_release(trial, section):
    result = assess(trial, section)
    assert result["status"] == "FIXTURE_EVIDENCE_ONLY"
    assert result["release_approved"] is False
    assert result["missing"] == []
    assert result["physical_execution_and_independent_release_decision"] == "NOT_VERIFIED"


@pytest.mark.parametrize("section", ["R69", "R71"])
def test_r69_r71_missing_case_stays_inconclusive(trial, section):
    file = trial["tmp"] / "partial.json"
    file.write_text(json.dumps(packet(trial, section, incomplete=True)))
    result = assess(trial, section, evidence=file)
    assert result["status"] == "INCONCLUSIVE"
    assert result["release_approved"] is False
    assert len(result["missing"]) == 1


@pytest.mark.parametrize("section", ["R69", "R71"])
def test_r69_r71_real_artifact_byte_tamper_denied(trial, section):
    evidence = trial["tmp"] / "signed-proofs.json"
    evidence.write_text(json.dumps(packet(trial, section)))
    trial["image"].write_bytes(b"changed protected artifact after signing")
    with pytest.raises(ProductEvidenceError):
        assess(trial, section, evidence=evidence)


@pytest.mark.parametrize("section", ["R69", "R71"])
def test_r69_r71_wrong_independent_inventory_pin_denied(trial, section):
    with pytest.raises(ProductEvidenceError):
        assess(trial, section, approved_keys_sha256="b" * 64)


@pytest.mark.parametrize("section", ["R69", "R71"])
def test_r69_r71_replayed_sequence_floor_is_denied(trial, section):
    with pytest.raises(ProductEvidenceError):
        assess(trial, section, minimum_sequence_exclusive=1)


@pytest.mark.parametrize("section", ["R69", "R71"])
def test_r69_r71_signed_evidence_rejects_forged_body(trial, section):
    file = trial["tmp"] / "signed-proofs.json"
    data = packet(trial, section)
    label = "probes" if section == "R69" else "observations"
    data[label][0]["signature_hex"] = "0" * 128
    file.write_text(json.dumps(data))
    with pytest.raises(ProductEvidenceError):
        assess(trial, section, evidence=file)


def test_r71_wrong_build_denied(trial):
    with pytest.raises(ProductEvidenceError):
        assess(trial, "R71", expected_build_id="build.other")


def test_r71_non_windows_platform_is_not_qualified(trial):
    with pytest.raises(ProductEvidenceError):
        assess(trial, "R71", expected_platform="linux")


def test_r69_symlink_artifact_denied(trial):
    replacement = trial["tmp"] / "original-image.zip"
    replacement.write_bytes(trial["image"].read_bytes())
    trial["image"].unlink()
    try:
        trial["image"].symlink_to(replacement)
    except (OSError, NotImplementedError):
        pytest.skip("symlink unavailable")
    with pytest.raises(ProductEvidenceError):
        assess(trial, "R69")
