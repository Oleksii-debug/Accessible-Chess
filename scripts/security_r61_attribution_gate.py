"""R61 protected per-artifact attribution readback, not client licensing.

Runs ONLY during trusted build/evidence intake. Uses the ONE canonical
continuum-runtime R61 Ed25519 attribution verifier and the existing R73 key
inventory format pinned outside the candidate. Never issues attribution tags,
signatures, revocations or a release authorization. Size limit follows R61.
"""
from __future__ import annotations

import hashlib
from pathlib import Path

from continuum_runtime.watermark_attribution import (
    AttributionDenied, verify_attribution,
)
from scripts.security_r53_protector_candidate_gate import _safe_image
from scripts.security_r73_product_evidence_gate import (
    ProductEvidenceError, _digest_arg, _strict_json,
)

_MAX_R61_ARTIFACT = 16 * 1024 * 1024


def assess_product_attribution(
    *, protected_artifact: Path, envelope_file: Path,
    approved_keys: Path, approved_keys_sha256: str,
    expected_artifact_sha256: str, expected_build_id: str,
) -> dict[str, object]:
    """Verify a separately issued signed mark on exact protected product bytes."""
    _digest_arg(approved_keys_sha256, "R61_TRUST")
    _digest_arg(expected_artifact_sha256, "R61_ARTIFACT")
    artifact = _safe_image(protected_artifact)
    if (len(artifact) > _MAX_R61_ARTIFACT
            or hashlib.sha256(artifact).hexdigest() != expected_artifact_sha256):
        raise ProductEvidenceError("R61_PROTECTED_ARTIFACT_MISMATCH")
    trust = _strict_json(
        approved_keys, maximum=64 * 1024,
        expected_sha256=approved_keys_sha256,
        mismatch_code="R61_INDEPENDENT_TRUST_PIN_MISMATCH",
    )
    if (set(trust) != {"schema_version", "verifier_public_keys"}
            or type(trust["schema_version"]) is not int
            or trust["schema_version"] != 1
            or type(trust["verifier_public_keys"]) is not dict
            or not 1 <= len(trust["verifier_public_keys"]) <= 32):
        raise ProductEvidenceError("R61_INDEPENDENT_TRUST_INVALID")
    keys = {}
    for key_id, key_hex in trust["verifier_public_keys"].items():
        if (type(key_id) is not str or not 1 <= len(key_id) <= 96
                or type(key_hex) is not str):
            raise ProductEvidenceError("R61_INDEPENDENT_TRUST_INVALID")
        _digest_arg(key_hex, "R61_KEY")
        keys[key_id] = bytes.fromhex(key_hex)
    packet = _strict_json(envelope_file, maximum=4096)
    try:
        payload = verify_attribution(
            envelope=packet, protected_artifact=artifact,
            trusted_public_keys=keys, expected_build_id=expected_build_id,
        )
    except (AttributionDenied, TypeError, ValueError):
        raise ProductEvidenceError("R61_CANONICAL_ATTRIBUTION_DENIED") from None
    return {
        "schema_version": 1,
        "status": "INDEPENDENT_SIGNATURE_BYTE_READBACK_ONLY",
        "build_id": payload["build_id"],
        "artifact_sha256": expected_artifact_sha256,
        "release_approved": False,
        "server_allocation_provenance": "NOT_VERIFIED",
        "native_vendor_protection": "NOT_VERIFIED",
        "windows_nvda_protected_release": "NOT_VERIFIED",
    }
