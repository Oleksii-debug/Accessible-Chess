"""R54 non-production build diversity intake: canonical verifier, no release PASS."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from continuum_runtime.commercial_protector import ProtectorProfile
from continuum_runtime.protection_diversity import prepare_diverse_candidate
from scripts.security_r54_diversity_candidate_gate import (
    assess_product_diversity, ProductEvidenceError,
)


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


@pytest.fixture
def sample(tmp_path):
    source = b"MZonly-a-synthetic-protector-input"
    secret = bytes(range(1, 33))
    product = "d" * 64
    profile = ProtectorProfile(
        schema_version=1, vendor="pace-ilok",
        profile_id="fixture-one", build_id="r54-test",
        input_sha256=digest(source), tool_sha256="a" * 64,
        recipe_sha256="b" * 64,
    )
    def protector(raw, variation):
        return b"protected-fixture-" + variation + raw

    receipt, protected = prepare_diverse_candidate(
        profile=profile, product_sha256=product, secret_key=secret,
        input_bytes=source, protector=protector,
        inspector=lambda value: type(value) is bytes and
            value.startswith(b"protected-fixture-"),
    )
    original_file = tmp_path / "original"
    protected_file = tmp_path / "protected"
    profile_file = tmp_path / "profile.json"
    candidate_file = tmp_path / "candidate.json"
    diversity_file = tmp_path / "diversity.json"
    original_file.write_bytes(source)
    protected_file.write_bytes(protected)
    profile_file.write_text(json.dumps(profile.__dict__))
    candidate_file.write_text(json.dumps(receipt.candidate.__dict__))
    diversity_file.write_text(json.dumps({
        **{k: v for k, v in receipt.__dict__.items() if k != "candidate"},
        "candidate": receipt.candidate.__dict__,
    }))
    return {
        "original": original_file, "protected": protected_file,
        "profile_file": profile_file, "candidate_file": candidate_file,
        "diversity_receipt_file": diversity_file,
        "expected_source_sha256": digest(source),
        "expected_tool_sha256": "a" * 64, "expected_recipe_sha256": "b" * 64,
        "expected_build_id": "r54-test", "expected_product_sha256": product,
        "secret_key": secret,
    }


def review(sample, **overrides):
    return assess_product_diversity(**{**sample, **overrides})


def test_valid_synthetic_diversity_is_not_release_permission(sample):
    value = review(sample)
    assert value["status"] == "DIVERSITY_CANDIDATE_READBACK_ONLY"
    assert value["release_approved"] is False
    assert value["real_vendor_and_independent_physical_qualification"] == "REQUIRED"
    assert "secret" not in str(value).lower()


def test_wrong_private_build_context_rejected(sample):
    with pytest.raises(ProductEvidenceError, match="R54_DIVERSITY_VERIFIER_DENIED"):
        review(sample, secret_key=b"x" * 32)
    with pytest.raises(ProductEvidenceError, match="R54_DIVERSITY_VERIFIER_DENIED"):
        review(sample, expected_product_sha256="0" * 64)


def test_no_secret_fallback(sample):
    for wrong in (None, b"", b"x", 1, True):
        with pytest.raises(ProductEvidenceError):
            review(sample, secret_key=wrong)


def test_r53_parent_tamper_blocks_r54_even_with_original_diversity_receipt(sample):
    sample["protected"].write_bytes(b"tampered")
    with pytest.raises(ProductEvidenceError):
        review(sample)


def test_mismatched_nested_candidate_is_rejected(sample):
    packet = json.loads(sample["diversity_receipt_file"].read_text())
    packet["candidate"]["protected_sha256"] = "f" * 64
    sample["diversity_receipt_file"].write_text(json.dumps(packet))
    with pytest.raises(ProductEvidenceError, match="R54_RECEIPT_OR_PARENT_INVALID"):
        review(sample)


def test_forged_diversity_status_rejected(sample):
    packet = json.loads(sample["diversity_receipt_file"].read_text())
    packet["release_status"] = "RELEASE_APPROVED"
    sample["diversity_receipt_file"].write_text(json.dumps(packet))
    with pytest.raises(ProductEvidenceError, match="R54_RECEIPT_OR_PARENT_INVALID"):
        review(sample)


def test_forged_context_hash_is_denied(sample):
    packet = json.loads(sample["diversity_receipt_file"].read_text())
    packet["context_sha256"] = "0" * 64
    sample["diversity_receipt_file"].write_text(json.dumps(packet))
    with pytest.raises(ProductEvidenceError, match="R54_DIVERSITY_VERIFIER_DENIED"):
        review(sample)


@pytest.mark.parametrize("field", ["variation_commitment", "alternate_commitment"])
def test_missing_canonical_variation_check_rejected(sample, field):
    packet = json.loads(sample["diversity_receipt_file"].read_text())
    packet[field] = "1" * 64
    sample["diversity_receipt_file"].write_text(json.dumps(packet))
    with pytest.raises(ProductEvidenceError, match="R54_DIVERSITY_VERIFIER_DENIED"):
        review(sample)


def test_bool_pretending_to_be_schema_one_is_denied(sample):
    packet = json.loads(sample["diversity_receipt_file"].read_text())
    packet["schema_version"] = True
    sample["diversity_receipt_file"].write_text(json.dumps(packet))
    with pytest.raises(ProductEvidenceError, match="R54_RECEIPT_OR_PARENT_INVALID"):
        review(sample)


def test_diversity_receipt_symlink_is_not_followed(sample, tmp_path):
    path = sample["diversity_receipt_file"]
    external = tmp_path / "external"
    external.write_bytes(path.read_bytes())
    path.unlink()
    try:
        path.symlink_to(external)
    except (OSError, NotImplementedError):
        pytest.skip("symlink unavailable")
    with pytest.raises(ProductEvidenceError, match="FILE_MISSING_OR_UNSAFE"):
        review(sample)
