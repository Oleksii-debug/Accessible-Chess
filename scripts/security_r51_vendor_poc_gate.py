"""R51 product-specific independent protector-PoC proof intake. No license issuer.

Reuse the accepted continuum-runtime vendor evaluation; the public Chess build
gate checks that the alleged PoC was independently signed for the *actual*
candidate artifact and exact build. Synthetic fixtures cannot select a vendor,
activate protection, unlock a premium capability, or approve a release.
"""
from __future__ import annotations

import json
from pathlib import Path
import re

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from continuum_runtime.vendor_evaluation import assess_vendor
from scripts.security_r73_product_evidence_gate import (
    ProductEvidenceError, _sha256_file, _strict_json, _digest_arg, _MAX_ARTIFACT,
)

_SIG = re.compile(r"^[0-9a-f]{128}$")
_REVIEW_ID = re.compile(r"^[A-Za-z0-9._:-]{8,128}$")
_REVIEWER_ID = re.compile(r"^[A-Za-z0-9._:-]{8,96}$")


def assess_product_vendor(
    *, artifact: Path, proof_file: Path, approved_reviewers: Path,
    approved_reviewers_sha256: str, expected_build_sha256: str,
) -> dict[str, object]:
    _digest_arg(approved_reviewers_sha256, "REVIEWER_KEYS")
    _digest_arg(expected_build_sha256, "BUILD")
    artifact_sha = _sha256_file(artifact, maximum=_MAX_ARTIFACT)
    trust = _strict_json(
        approved_reviewers, maximum=64 * 1024,
        expected_sha256=approved_reviewers_sha256,
        mismatch_code="R51_REVIEWER_TRUST_PIN_MISMATCH",
    )
    if set(trust) != {"schema_version", "reviewer_public_keys"} or type(trust["schema_version"]) is not int or trust["schema_version"] != 1 or type(trust["reviewer_public_keys"]) is not dict:
        raise ProductEvidenceError("R51_TRUST_SCHEMA_INVALID")
    packet = _strict_json(proof_file, maximum=1024 * 1024)
    if set(packet) != {"schema_version", "assessment", "reviewer_id", "review_signature_hex"} or type(packet["schema_version"]) is not int or packet["schema_version"] != 1:
        raise ProductEvidenceError("R51_POC_SCHEMA_INVALID")
    assessment = packet["assessment"]
    reviewer_id = packet["reviewer_id"]
    sig = packet["review_signature_hex"]
    if (type(assessment) is not dict or type(reviewer_id) is not str
            or not _REVIEWER_ID.fullmatch(reviewer_id)
            or type(sig) is not str or not _SIG.fullmatch(sig)):
        raise ProductEvidenceError("R51_POC_SCHEMA_INVALID")
    if assessment.get("artifact_sha256") != artifact_sha or assessment.get("build_sha256") != expected_build_sha256:
        raise ProductEvidenceError("R51_PRODUCT_BUILD_MISMATCH")
    pub = trust["reviewer_public_keys"].get(reviewer_id)
    if type(pub) is not str or not re.fullmatch("[0-9a-f]{64}", pub):
        raise ProductEvidenceError("R51_REVIEWER_UNTRUSTED")
    signed = (
        b"accessible-chess-r51-independent-poc-v1\x00"
        + json.dumps(
            {"assessment": assessment, "reviewer_id": reviewer_id},
            sort_keys=True, separators=(",", ":"), ensure_ascii=True,
            allow_nan=False,
        ).encode("ascii")
    )

    def independently_verified(artifact_digest: str, build_digest: str, review_id: str) -> bool:
        if (artifact_digest != artifact_sha or build_digest != expected_build_sha256
                or review_id != assessment.get("review_id")
                or type(review_id) is not str or not _REVIEW_ID.fullmatch(review_id)):
            return False
        try:
            Ed25519PublicKey.from_public_bytes(bytes.fromhex(pub)).verify(bytes.fromhex(sig), signed)
            return True
        except Exception:
            return False

    try:
        evaluated = assess_vendor(
            report=assessment,
            verify_independent_evidence=independently_verified,
        )
    except (ValueError, TypeError):
        raise ProductEvidenceError("R51_VENDOR_EVALUATION_DENIED") from None
    return {
        "schema_version": 1,
        "vendor": evaluated.vendor,
        "vendor_poc_assessment": evaluated.decision,
        "reason": evaluated.reason,
        "protected_artifact_sha256": artifact_sha,
        "product_release_approved": False,
        "next_gate": "selected_vendor_native_protector_and_independent_full_product_qualification",
    }
