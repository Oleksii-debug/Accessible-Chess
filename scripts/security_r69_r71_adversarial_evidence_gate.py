"""R69/R71 independent adversarial evidence intake bound to actual product bytes.

Build/release verification ONLY. Canonical neutral continuum verifiers own signed
proof semantics. This code cannot execute attacks, select a vendor, approve a
product release or change the existing entitlement/revocation authorities.
"""
from __future__ import annotations

from pathlib import Path
import time

from continuum_runtime.offline_crack_qualification import (
    ATTACK_BOUNDARIES, OfflineQualificationDenied, ProbeEvidence,
    qualify_offline_evidence,
)
from continuum_runtime.protector_release_qualification import (
    REQUIRED_CHECKS, ReleaseObservation, ReleaseQualificationDenied,
    qualify_protected_release,
)
from scripts.security_r73_product_evidence_gate import (
    ProductEvidenceError, _digest_arg, _sha256_file, _strict_json,
)

_R69_FIELDS = frozenset(ProbeEvidence.__dataclass_fields__)
_R71_FIELDS = frozenset(ReleaseObservation.__dataclass_fields__)
_MAX_PROOF = 1024 * 1024
_MAX_TRUST = 65536
_MAX_ARTIFACT = 8 * 1024 * 1024 * 1024


def _independent_keys(path: Path, pinned_sha256: str) -> dict[str, bytes]:
    _digest_arg(pinned_sha256, "INDEPENDENT_VERIFIER_INVENTORY")
    packet = _strict_json(
        path, maximum=_MAX_TRUST, expected_sha256=pinned_sha256,
        mismatch_code="INDEPENDENT_VERIFIER_KEY_INVENTORY_MISMATCH",
    )
    if (set(packet) != {"schema_version", "verifier_public_keys"}
        or type(packet["schema_version"]) is not int
        or packet["schema_version"] != 1
        or type(packet["verifier_public_keys"]) is not dict
        or not 1 <= len(packet["verifier_public_keys"]) <= 32):
        raise ProductEvidenceError("INDEPENDENT_VERIFIER_INVENTORY_INVALID")
    keys = {}
    for name, token in packet["verifier_public_keys"].items():
        if (type(name) is not str or not 1 <= len(name) <= 96
            or type(token) is not str):
            raise ProductEvidenceError("INDEPENDENT_VERIFIER_INVENTORY_INVALID")
        _digest_arg(token, "INDEPENDENT_VERIFIER_PUBLIC_KEY")
        keys[name] = bytes.fromhex(token)
    return keys


def _rows(path: Path, row_key: str, fields: frozenset[str],
          maximum_rows: int, item_class: type) -> tuple[object, ...]:
    packet = _strict_json(path, maximum=_MAX_PROOF)
    if (set(packet) != {"schema_version", row_key}
        or type(packet["schema_version"]) is not int
        or packet["schema_version"] != 1
        or type(packet[row_key]) is not list
        or not 0 <= len(packet[row_key]) <= maximum_rows):
        raise ProductEvidenceError("ADVERSARIAL_EVIDENCE_SCHEMA_INVALID")
    rows = packet[row_key]
    if any(type(row) is not dict or set(row) != fields for row in rows):
        raise ProductEvidenceError("ADVERSARIAL_EVIDENCE_ROW_SCHEMA_INVALID")
    try:
        return tuple(item_class(**row) for row in rows)
    except (TypeError, KeyError, ValueError):
        raise ProductEvidenceError("ADVERSARIAL_EVIDENCE_ROW_INVALID") from None


def assess_adversarial_product_evidence(
    *, section: str, protected_artifact: Path, evidence: Path,
    approved_keys: Path, approved_keys_sha256: str,
    expected_source_sha256: str, expected_platform: str = "windows-x64",
    expected_build_id: str | None = None, now: int | None = None,
    minimum_sequence_exclusive: int = 0,
) -> dict[str, object]:
    """Observe R69 or R71 independently signed reports. No claim of physical PASS.

    Approved keys, source SHA, build identity and replay floor MUST originate
    outside the untrusted evidence bundle. A PHYSICAL claim remains merely a
    signed claim until external execution and verifier independence are proven.
    """
    if section not in ("R69", "R71") or type(section) is not str:
        raise ProductEvidenceError("ADVERSARIAL_SECTION_INVALID")
    _digest_arg(expected_source_sha256, "ADVERSARIAL_SOURCE")
    if (type(minimum_sequence_exclusive) is not int
        or minimum_sequence_exclusive < 0):
        raise ProductEvidenceError("ADVERSARIAL_REPLAY_FLOOR_INVALID")
    if section == "R71" and (type(expected_build_id) is not str
                            or not expected_build_id
                            or type(expected_platform) is not str
                            or expected_platform != "windows-x64"):
        raise ProductEvidenceError("R71_PRODUCT_BUILD_PLATFORM_INVALID")
    artifact_sha256 = _sha256_file(protected_artifact, maximum=_MAX_ARTIFACT)
    keys = _independent_keys(approved_keys, approved_keys_sha256)
    timestamp = int(time.time()) if now is None else now
    if type(timestamp) is not int or timestamp < 1:
        raise ProductEvidenceError("ADVERSARIAL_CLOCK_INVALID")
    try:
        if section == "R69":
            probes = _rows(evidence, "probes", _R69_FIELDS,
                           len(ATTACK_BOUNDARIES), ProbeEvidence)
            verdict = qualify_offline_evidence(
                probes=probes, expected_source_sha256=expected_source_sha256,
                expected_artifact_sha256=artifact_sha256,
                trusted_verifier_keys=keys, now=timestamp,
                minimum_sequence_exclusive=minimum_sequence_exclusive)
            coverage = list(verdict.covered)
            missing = list(verdict.absent)
        else:
            observations = _rows(evidence, "observations", _R71_FIELDS,
                                 len(REQUIRED_CHECKS), ReleaseObservation)
            verdict = qualify_protected_release(
                observations=observations,
                expected_source_sha256=expected_source_sha256,
                expected_artifact_sha256=artifact_sha256,
                expected_build_id=expected_build_id,
                expected_platform=expected_platform,
                trusted_verifier_keys=keys, now=timestamp,
                minimum_sequence_exclusive=minimum_sequence_exclusive)
            coverage = list(verdict.covered)
            missing = list(verdict.missing)
    except (OfflineQualificationDenied, ReleaseQualificationDenied,
            ValueError, TypeError, KeyError):
        raise ProductEvidenceError("ADVERSARIAL_INDEPENDENT_PROOF_DENIED") from None
    return {
        "schema_version": 1,
        "section": section,
        "status": verdict.status,
        "artifact_sha256": artifact_sha256,
        "source_sha256": expected_source_sha256,
        "covered": coverage,
        "missing": missing,
        "evidence_class": verdict.evidence_class,
        "max_sequence": verdict.max_sequence,
        "release_approved": False,
        "physical_execution_and_independent_release_decision": "NOT_VERIFIED",
    }
