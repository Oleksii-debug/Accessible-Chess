"""R72 signed incident and emergency-update evidence gate (build/ops only).

Reuses canonical continuum R72 plus R34 update-metadata verification. Never
executes revocation, key rotation, updating, recovery or release approval.
All approval/effect/update trust roots must be independently pinned off-repo.
"""
from __future__ import annotations

from pathlib import Path
import time

from continuum_runtime.incident_response import (
    EffectReceipt, IncidentCase, IncidentDenied, assess_incident,
)
from scripts.security_r73_product_evidence_gate import (
    ProductEvidenceError, _digest_arg, _sha256_file, _strict_json,
)

_CASE_FIELDS = frozenset(IncidentCase.__dataclass_fields__)
_RECEIPT_FIELDS = frozenset(EffectReceipt.__dataclass_fields__)
_KEYSETS = ("approval_public_keys", "effect_public_keys", "trusted_update_keys")


def assess_product_incident_evidence(
    *, case_file: Path, receipts_file: Path, incident_artifact: Path,
    signed_update_file: Path, independent_keys_file: Path,
    independent_keys_sha256: str, expected_source_sha256: str,
    now: int | None = None, minimum_sequence_exclusive: int = 0,
) -> dict[str, object]:
    """Read exact independent R72 case/receipts; UNKNOWN remains pending."""
    _digest_arg(independent_keys_sha256, "R72_TRUST")
    _digest_arg(expected_source_sha256, "R72_SOURCE")
    if (type(minimum_sequence_exclusive) is not int
        or minimum_sequence_exclusive < 0):
        raise ProductEvidenceError("R72_REPLAY_FLOOR_INVALID")
    actual_evidence_sha256 = _sha256_file(incident_artifact, maximum=64 * 1024 * 1024)
    trust = _strict_json(
        independent_keys_file, maximum=65536,
        expected_sha256=independent_keys_sha256,
        mismatch_code="R72_INDEPENDENT_KEY_PIN_MISMATCH")
    if (set(trust) != {"schema_version", *_KEYSETS}
        or type(trust["schema_version"]) is not int
        or trust["schema_version"] != 1):
        raise ProductEvidenceError("R72_TRUST_SCHEMA_INVALID")
    keysets = {}
    for role in _KEYSETS:
        raw = trust[role]
        if type(raw) is not dict or not 1 <= len(raw) <= 32:
            raise ProductEvidenceError("R72_TRUST_KEYS_INVALID")
        keys = {}
        for identity, key_hex in raw.items():
            if (type(identity) is not str or not 1 <= len(identity) <= 96
                or type(key_hex) is not str):
                raise ProductEvidenceError("R72_TRUST_KEYS_INVALID")
            _digest_arg(key_hex, "R72_PUBLIC_KEY")
            keys[identity] = bytes.fromhex(key_hex)
        keysets[role] = keys
    packet = _strict_json(case_file, maximum=8192)
    rows = _strict_json(receipts_file, maximum=65536)
    envelope = _strict_json(signed_update_file, maximum=16384)
    if (set(packet) != {"schema_version", "case"}
        or type(packet["schema_version"]) is not int
        or packet["schema_version"] != 1
        or type(packet["case"]) is not dict
        or set(packet["case"]) != _CASE_FIELDS
        or set(rows) != {"schema_version", "receipts"}
        or type(rows["schema_version"]) is not int
        or rows["schema_version"] != 1
        or type(rows["receipts"]) is not list
        or len(rows["receipts"]) > 10
        or any(type(record) is not dict or set(record) != _RECEIPT_FIELDS
               for record in rows["receipts"])):
        raise ProductEvidenceError("R72_INCIDENT_SCHEMA_INVALID")
    moment = int(time.time()) if now is None else now
    if type(moment) is not int or moment < 1:
        raise ProductEvidenceError("R72_CLOCK_INVALID")
    try:
        incident = IncidentCase(**packet["case"])
        receipts = tuple(EffectReceipt(**item) for item in rows["receipts"])
        result = assess_incident(
            case=incident, receipts=receipts,
            approval_keys=keysets["approval_public_keys"],
            effect_keys=keysets["effect_public_keys"],
            trusted_update_keys=keysets["trusted_update_keys"],
            expected_source_sha256=expected_source_sha256,
            expected_evidence_sha256=actual_evidence_sha256,
            update_metadata_envelope=envelope, now=moment,
            minimum_sequence_exclusive=minimum_sequence_exclusive)
    except (IncidentDenied, ValueError, TypeError, KeyError):
        raise ProductEvidenceError("R72_INDEPENDENT_RECEIPT_DENIED") from None
    return {
        "schema_version": 1,
        "status": result.status,
        "confirmed": list(result.confirmed),
        "pending": list(result.pending),
        "unknown_effects": list(result.unknown_effects),
        "max_sequence": result.max_sequence,
        "case_id": incident.case_id,
        "incident_evidence_sha256": actual_evidence_sha256,
        "release_approved": False,
        "actual_operator_execution": "NOT_VERIFIED",
        "independent_release_approval": "REQUIRED",
    }
