"""R53 product candidate intake negative tests: no external protector claims."""
from __future__ import annotations

from dataclasses import replace
import hashlib
import json
from pathlib import Path
from unittest.mock import patch

import pytest

from continuum_runtime.commercial_protector import (
    ProtectorProfile, prepare_candidate,
)
from scripts.security_r53_protector_candidate_gate import (
    assess_protected_candidate, ProductEvidenceError,
)


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


@pytest.fixture
def candidate(tmp_path):
    original = tmp_path / "native-input.bin"
    protected = tmp_path / "native-protected.bin"
    source = b"MZsynthetic-fixture-only-not-a-real-protector"
    original.write_bytes(source)
    profile = ProtectorProfile(
        schema_version=1, vendor="pace-ilok", profile_id="fixture-1",
        build_id="build-r53", input_sha256=sha(source),
        tool_sha256="a" * 64, recipe_sha256="b" * 64,
    )
    receipt, protected_bytes = prepare_candidate(
        profile=profile, input_bytes=source,
        protector=lambda raw: b"wrapped-fixture-" + raw,
        inspector=lambda data: type(data) is bytes and data.startswith(b"wrapped-fixture-"),
    )
    protected.write_bytes(protected_bytes)
    profile_file = tmp_path / "profile.json"
    receipt_file = tmp_path / "receipt.json"
    profile_file.write_text(json.dumps(profile.__dict__))
    receipt_file.write_text(json.dumps(receipt.__dict__))
    return {
        "original": original, "protected": protected,
        "profile_file": profile_file, "candidate_file": receipt_file,
        "expected_source_sha256": sha(source),
        "expected_tool_sha256": "a" * 64,
        "expected_recipe_sha256": "b" * 64,
        "expected_build_id": "build-r53",
    }


def review(candidate, **changes):
    return assess_protected_candidate(**{**candidate, **changes})


def test_synthetic_byte_verification_cannot_claim_vendor_or_release(candidate):
    record = review(candidate)
    assert record["status"] == "CANDIDATE_BYTE_INTEGRITY_ONLY"
    assert record["release_approved"] is False
    assert record["independent_vendor_qualification"] == "REQUIRED"
    assert record["protected_windows_nvda_qualification"] == "REQUIRED"
    assert record["source_sha256"] == candidate["expected_source_sha256"]


def test_modified_protected_bytes_are_denied(candidate):
    candidate["protected"].write_bytes(b"substituted protected bytes")
    with pytest.raises(ProductEvidenceError, match="R53_CANONICAL_VERIFIER_DENIED"):
        review(candidate)


def test_modified_original_bytes_are_denied(candidate):
    candidate["original"].write_bytes(b"source was changed")
    with pytest.raises(ProductEvidenceError, match="R53_SOURCE_DIGEST_MISMATCH"):
        review(candidate)


@pytest.mark.parametrize("name", ["expected_tool_sha256", "expected_recipe_sha256", "expected_source_sha256"])
def test_independently_pinned_inputs_cannot_be_overridden_by_profile(candidate, name):
    with pytest.raises(ProductEvidenceError):
        review(candidate, **{name: "0" * 64})


def test_build_id_is_exact_and_cannot_be_switched(candidate):
    with pytest.raises(ProductEvidenceError, match="R53_TRUSTED_BUILD_BINDING_MISMATCH"):
        review(candidate, expected_build_id="other-build")
    with pytest.raises(ProductEvidenceError, match="R53_BUILD_ID_INVALID"):
        review(candidate, expected_build_id=True)


@pytest.mark.parametrize("bad", [True, 1.0, "42", -1])
def test_forged_candidate_size_is_not_trusted(candidate, bad):
    packet = json.loads(candidate["candidate_file"].read_text())
    packet["protected_size"] = bad
    candidate["candidate_file"].write_text(json.dumps(packet))
    with pytest.raises(ProductEvidenceError, match="R53_CANDIDATE_TYPE_OR_STATUS_INVALID"):
        review(candidate)


def test_forged_release_approval_not_admitted(candidate):
    packet = json.loads(candidate["candidate_file"].read_text())
    packet["release_status"] = "QUALIFIED"
    candidate["candidate_file"].write_text(json.dumps(packet))
    with pytest.raises(ProductEvidenceError, match="R53_CANDIDATE_TYPE_OR_STATUS_INVALID"):
        review(candidate)


def test_receipt_extra_field_and_duplicate_key_rejected(candidate):
    packet = json.loads(candidate["candidate_file"].read_text())
    packet["release_approved"] = True
    candidate["candidate_file"].write_text(json.dumps(packet))
    with pytest.raises(ProductEvidenceError, match="R53_CANDIDATE_SCHEMA_INVALID"):
        review(candidate)
    candidate["candidate_file"].write_text('{"schema_version":1,"schema_version":1}')
    with pytest.raises(ProductEvidenceError, match="EVIDENCE_DUPLICATE_KEY"):
        review(candidate)


def test_protected_file_symlink_rejected(candidate, tmp_path):
    candidate["protected"].unlink()
    try:
        candidate["protected"].symlink_to(candidate["original"])
    except (OSError, NotImplementedError):
        pytest.skip("symlink unsupported on this system")
    with pytest.raises(ProductEvidenceError):
        review(candidate)


def test_protected_path_swap_between_stat_and_open_is_denied(candidate, tmp_path):
    replacement = tmp_path / "replacement"
    replacement.write_bytes(b"another-file")
    original_open = Path.open
    swapped = []

    def substitute(path, *args, **kwargs):
        if path == candidate["protected"] and not swapped:
            replacement.replace(path)
            swapped.append(True)
        return original_open(path, *args, **kwargs)

    with patch.object(Path, "open", substitute):
        with pytest.raises(ProductEvidenceError):
            review(candidate)
    assert swapped == [True]


def test_original_byte_copy_never_counts_as_protected(candidate):
    source = candidate["original"].read_bytes()
    candidate["protected"].write_bytes(source)
    packet = json.loads(candidate["candidate_file"].read_text())
    packet["protected_sha256"] = sha(source)
    packet["protected_size"] = len(source)
    candidate["candidate_file"].write_text(json.dumps(packet))
    with pytest.raises(ProductEvidenceError, match="R53_CANONICAL_VERIFIER_DENIED"):
        review(candidate)
