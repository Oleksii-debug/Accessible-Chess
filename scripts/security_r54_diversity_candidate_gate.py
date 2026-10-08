"""R54 product-scoped diversity readback, dependent on existing R53 intake.

This is a private build-time diagnostic. The build-only secret must arrive from
a trusted provider and never enter public source, command lines, logs or the
release ZIP. No native vendor protector or independent release authority is
implemented here.
"""
from __future__ import annotations

from pathlib import Path

from continuum_runtime.commercial_protector import (
    ProtectedCandidate, ProtectorError, ProtectorProfile,
)
from continuum_runtime.protection_diversity import (
    DiversityReceipt, check_diverse_candidate,
)
from scripts.security_r53_protector_candidate_gate import (
    _safe_image, assess_protected_candidate,
)
from scripts.security_r73_product_evidence_gate import (
    ProductEvidenceError, _digest_arg, _strict_json,
)

_RECEIPT_FIELDS = frozenset(DiversityReceipt.__dataclass_fields__)
_CANDIDATE_FIELDS = frozenset(ProtectedCandidate.__dataclass_fields__)
_PROFILE_FIELDS = frozenset(ProtectorProfile.__dataclass_fields__)


def assess_product_diversity(
    *, original: Path, protected: Path, profile_file: Path,
    candidate_file: Path, diversity_receipt_file: Path,
    expected_source_sha256: str, expected_tool_sha256: str,
    expected_recipe_sha256: str, expected_build_id: str,
    expected_product_sha256: str, secret_key: bytes,
) -> dict[str, object]:
    """Accept only same-image source/R53/R54 readback, never release approval."""
    _digest_arg(expected_product_sha256, "R54_PRODUCT")
    # Canonical R53 has priority: do not let diversity override malformed
    # image bytes, profile or candidate or mint an independent verification.
    parent = assess_protected_candidate(
        original=original, protected=protected,
        profile_file=profile_file, candidate_file=candidate_file,
        expected_source_sha256=expected_source_sha256,
        expected_tool_sha256=expected_tool_sha256,
        expected_recipe_sha256=expected_recipe_sha256,
        expected_build_id=expected_build_id,
    )
    profile_json = _strict_json(profile_file, maximum=16 * 1024)
    candidate_json = _strict_json(candidate_file, maximum=16 * 1024)
    packet = _strict_json(diversity_receipt_file, maximum=16 * 1024)
    if (set(profile_json) != _PROFILE_FIELDS
            or set(candidate_json) != _CANDIDATE_FIELDS
            or set(packet) != _RECEIPT_FIELDS
            or type(packet["candidate"]) is not dict
            or set(packet["candidate"]) != _CANDIDATE_FIELDS
            or packet["candidate"] != candidate_json):
        raise ProductEvidenceError("R54_RECEIPT_OR_PARENT_INVALID")
    if (packet["profile_sha256"] != parent["profile_sha256"]
            or packet["release_status"]
            != "EXTERNAL_VENDOR_QUALIFICATION_REQUIRED"
            or type(packet["schema_version"]) is not int
            or packet["schema_version"] != 1):
        raise ProductEvidenceError("R54_RECEIPT_OR_PARENT_INVALID")
    try:
        profile = ProtectorProfile(**profile_json)
        candidate = ProtectedCandidate(**candidate_json)
        receipt = DiversityReceipt(
            schema_version=packet["schema_version"],
            profile_sha256=packet["profile_sha256"],
            context_sha256=packet["context_sha256"],
            variation_commitment=packet["variation_commitment"],
            alternate_commitment=packet["alternate_commitment"],
            candidate=candidate, release_status=packet["release_status"],
        )
        if (check_diverse_candidate(
            profile=profile, product_sha256=expected_product_sha256,
            secret_key=secret_key, receipt=receipt,
            protected_bytes=_safe_image(protected),
        ) is not True):
            raise ProductEvidenceError("R54_DIVERSITY_VERIFIER_DENIED")
    except (ProtectorError, TypeError, ValueError):
        raise ProductEvidenceError("R54_DIVERSITY_VERIFIER_DENIED") from None
    return {
        "schema_version": 1,
        "status": "DIVERSITY_CANDIDATE_READBACK_ONLY",
        "build_id": expected_build_id,
        "source_sha256": parent["source_sha256"],
        "protected_sha256": parent["protected_sha256"],
        "profile_sha256": parent["profile_sha256"],
        "product_sha256": expected_product_sha256,
        "release_approved": False,
        "real_vendor_and_independent_physical_qualification": "REQUIRED",
    }
