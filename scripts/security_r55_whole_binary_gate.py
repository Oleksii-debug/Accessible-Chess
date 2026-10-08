"""R55 product-side, build-only whole-binary protection readback.

Uses the ONE existing continuum-runtime R55 verifier on the native executable
already owned by Accessible Chess. No vendor is selected, no SDK is installed,
no real commercial protection is inferred from a structurally valid PE.
First-party targets only: Stockfish and third-party runtimes must not be
silently reprotected. A successful check is NOT a product release approval.
"""
from __future__ import annotations

import hashlib
from pathlib import Path

from continuum_runtime.commercial_protector import (
    ProtectedCandidate, ProtectorError, ProtectorProfile,
)
from continuum_runtime.protection_diversity import DiversityReceipt
from continuum_runtime.whole_binary import (
    BinaryTarget, WholeBinaryPlan, WholeBinaryReceipt, check_whole_binary,
    _pe_image,
)
from scripts.security_r53_protector_candidate_gate import _safe_image
from scripts.security_r73_product_evidence_gate import (
    ProductEvidenceError, _digest_arg, _strict_json,
)

# R55 only names the already-owned compiled application image.
# Third-party Stockfish, Python, WebView2 and .NET dependencies are not ours
# to wrap with a proprietary protector.
_FIRST_PARTY = frozenset({"AccessibleChess.exe"})
_PROFILE = frozenset(ProtectorProfile.__dataclass_fields__)
_TARGET = frozenset(BinaryTarget.__dataclass_fields__)
_PLAN = frozenset(WholeBinaryPlan.__dataclass_fields__)
_RECEIPT = frozenset(WholeBinaryReceipt.__dataclass_fields__)
_DIVERSITY = frozenset(DiversityReceipt.__dataclass_fields__)
_CANDIDATE = frozenset(ProtectedCandidate.__dataclass_fields__)


def _receipt(packet: object) -> WholeBinaryReceipt:
    if type(packet) is not dict or set(packet) != _RECEIPT:
        raise ProductEvidenceError("R55_RECEIPT_SCHEMA_INVALID")
    rows = packet["target_receipts"]
    if type(rows) is not list or not 1 <= len(rows) <= len(_FIRST_PARTY):
        raise ProductEvidenceError("R55_RECEIPT_SCHEMA_INVALID")
    targets = []
    for row in rows:
        if (type(row) is not list or len(row) != 2 or type(row[0]) is not str
            or type(row[1]) is not dict or set(row[1]) != _DIVERSITY):
            raise ProductEvidenceError("R55_RECEIPT_SCHEMA_INVALID")
        child = dict(row[1])
        candidate = child["candidate"]
        if type(candidate) is not dict or set(candidate) != _CANDIDATE:
            raise ProductEvidenceError("R55_CANDIDATE_SCHEMA_INVALID")
        child["candidate"] = ProtectedCandidate(**candidate)
        targets.append((row[0], DiversityReceipt(**child)))
    if (type(packet["schema_version"]) is not int
        or packet["schema_version"] != 1
        or type(packet["release_status"]) is not str
        or packet["release_status"] != "EXTERNAL_VENDOR_QUALIFICATION_REQUIRED"):
        raise ProductEvidenceError("R55_RECEIPT_SCHEMA_INVALID")
    return WholeBinaryReceipt(
        schema_version=packet["schema_version"],
        build_id=packet["build_id"],
        protected_manifest_sha256=packet["protected_manifest_sha256"],
        target_receipts=tuple(targets),
        release_status=packet["release_status"],
    )


def assess_product_whole_binary(
    *, source_root: Path, protected_root: Path, plan_file: Path,
    profiles_file: Path, receipt_file: Path, expected_build_id: str,
    expected_product_sha256: str, secret_key: bytes,
) -> dict[str, object]:
    """Exact R55 structural candidate readback; never commercial proof."""
    _digest_arg(expected_product_sha256, "R55_PRODUCT")
    if type(expected_build_id) is not str or not expected_build_id:
        raise ProductEvidenceError("R55_BUILD_INVALID")
    plan_obj = _strict_json(plan_file, maximum=16 * 1024)
    profiles_obj = _strict_json(profiles_file, maximum=16 * 1024)
    receipt_obj = _strict_json(receipt_file, maximum=32 * 1024)
    if type(plan_obj) is not dict or set(plan_obj) != _PLAN:
        raise ProductEvidenceError("R55_PLAN_SCHEMA_INVALID")
    raw_targets = plan_obj["targets"]
    if (type(raw_targets) is not list
        or not 1 <= len(raw_targets) <= len(_FIRST_PARTY)
        or any(type(t) is not dict or set(t) != _TARGET for t in raw_targets)):
        raise ProductEvidenceError("R55_TARGET_SCHEMA_INVALID")
    names = tuple(t["name"] for t in raw_targets)
    if len(set(names)) != len(names) or set(names) != _FIRST_PARTY:
        raise ProductEvidenceError("R55_PRODUCT_TARGET_SCOPE_INVALID")
    if (type(profiles_obj) is not dict or set(profiles_obj) != set(names)
        or plan_obj["build_id"] != expected_build_id):
        raise ProductEvidenceError("R55_PROFILE_OR_BUILD_INVALID")
    try:
        targets = tuple(BinaryTarget(**t) for t in raw_targets)
        plan = WholeBinaryPlan(
            schema_version=plan_obj["schema_version"],
            build_id=plan_obj["build_id"], targets=targets,
        )
        profiles = {}
        sources = {}
        protected = {}
        for target in targets:
            profile_data = profiles_obj[target.name]
            if type(profile_data) is not dict or set(profile_data) != _PROFILE:
                raise ProductEvidenceError("R55_PROFILE_SCHEMA_INVALID")
            profiles[target.name] = ProtectorProfile(**profile_data)
            # Exact safe basenames from _FIRST_PARTY. No caller-chosen path,
            # directory traversal, symlink or cross-component alias is admitted.
            sources[target.name] = _safe_image(source_root / target.name)
            protected[target.name] = _safe_image(protected_root / target.name)
            if sources[target.name] == protected[target.name]:
                raise ProductEvidenceError("R55_UNPROTECTED_COPY")
        receipt = _receipt(receipt_obj)
        if check_whole_binary(
            plan=plan, sources=sources, profiles=profiles,
            product_sha256=expected_product_sha256, secret_key=secret_key,
            receipt=receipt, protected=protected,
            inspector=lambda _name, data: _pe_image(data),
        ) is not True:
            raise ProductEvidenceError("R55_NEUTRAL_VERIFIER_DENIED")
    except ProductEvidenceError:
        raise
    except (ProtectorError, TypeError, ValueError, KeyError):
        raise ProductEvidenceError("R55_NEUTRAL_VERIFIER_DENIED") from None
    return {
        "schema_version": 1,
        "status": "STRUCTURAL_PE_INTEGRITY_ONLY",
        "build_id": expected_build_id,
        "product_sha256": expected_product_sha256,
        "targets": list(names),
        "protected_manifest_sha256": receipt.protected_manifest_sha256,
        "protected_binary_sha256": {
            name: hashlib.sha256(protected[name]).hexdigest() for name in names
        },
        "release_approved": False,
        "independent_vendor_windows_nvda_verification": "REQUIRED",
        "native_protector_inspection": "NOT_PERFORMED",
    }
