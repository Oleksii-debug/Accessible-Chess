"""R56 product-bound protected-function candidate readback (build-only).

There is no Python decryption/runtime loader, no client-side secret, and no
automatic protection of UI, input, NVDA, speech, startup or realtime handlers.
A genuine first-party R55 whole-binary receipt is mandatory before this readback.
Uses canonical neutral continuum R56 immutable function manifest checks.
Synthetic R56 fixture output is NOT commercial protection or release evidence.
"""
from __future__ import annotations

from pathlib import Path

from continuum_runtime.commercial_protector import ProtectorError
from continuum_runtime.function_protection import (
    FunctionPlan, FunctionTarget, FunctionReceipt, check_functions,
)
from scripts.security_r55_whole_binary_gate import (
    _receipt as parse_r55_receipt,
    assess_product_whole_binary,
)
from scripts.security_r53_protector_candidate_gate import _safe_image
from scripts.security_r73_product_evidence_gate import ProductEvidenceError, _strict_json

_FUNCTION_TARGET = frozenset(FunctionTarget.__dataclass_fields__)
_FUNCTION_PLAN = frozenset(FunctionPlan.__dataclass_fields__)
_FUNCTION_RECEIPT = frozenset(FunctionReceipt.__dataclass_fields__)
_ALLOWED_MODULE = "AccessibleChess.exe"
_MAX_FUNCTION_CIPHERTEXT = 4 * 1024 * 1024


def assess_product_functions(
    *, source_root: Path, protected_root: Path, r55_plan_file: Path,
    r55_profiles_file: Path, r55_receipt_file: Path,
    function_plan_file: Path, function_receipt_file: Path,
    function_cipher_root: Path, expected_build_id: str,
    expected_product_sha256: str, secret_key: bytes,
) -> dict[str, object]:
    parent = assess_product_whole_binary(
        source_root=source_root, protected_root=protected_root,
        plan_file=r55_plan_file, profiles_file=r55_profiles_file,
        receipt_file=r55_receipt_file, expected_build_id=expected_build_id,
        expected_product_sha256=expected_product_sha256, secret_key=secret_key,
    )
    if (parent.get("release_approved") is not False
        or parent.get("status") != "STRUCTURAL_PE_INTEGRITY_ONLY"):
        raise ProductEvidenceError("R56_PARENT_NOT_VERIFIED")
    plan_packet = _strict_json(function_plan_file, maximum=32 * 1024)
    receipt_packet = _strict_json(function_receipt_file, maximum=64 * 1024)
    if type(plan_packet) is not dict or set(plan_packet) != _FUNCTION_PLAN:
        raise ProductEvidenceError("R56_PLAN_SCHEMA_INVALID")
    if (type(plan_packet["targets"]) is not list
        or not 1 <= len(plan_packet["targets"]) <= 64
        or any(type(t) is not dict or set(t) != _FUNCTION_TARGET
               for t in plan_packet["targets"])):
        raise ProductEvidenceError("R56_TARGET_SCHEMA_INVALID")
    if (any(t.get("module_name") != _ALLOWED_MODULE for t in plan_packet["targets"])
        or type(receipt_packet) is not dict
        or set(receipt_packet) != _FUNCTION_RECEIPT):
        raise ProductEvidenceError("R56_UNTRUSTED_TARGET_OR_RECEIPT")
    rows = receipt_packet["rows"]
    if (type(rows) is not list or len(rows) != len(plan_packet["targets"])
        or any(type(row) is not list or len(row) != 5 for row in rows)):
        raise ProductEvidenceError("R56_RECEIPT_ROWS_INVALID")
    try:
        plan = FunctionPlan(
            schema_version=plan_packet["schema_version"],
            targets=tuple(FunctionTarget(**t) for t in plan_packet["targets"]),
        )
        parent_receipt = parse_r55_receipt(
            _strict_json(r55_receipt_file, maximum=32 * 1024)
        )
        receipt = FunctionReceipt(
            schema_version=receipt_packet["schema_version"],
            parent_manifest_sha256=receipt_packet["parent_manifest_sha256"],
            function_manifest_sha256=receipt_packet["function_manifest_sha256"],
            rows=tuple(tuple(row) for row in rows),
            release_status=receipt_packet["release_status"],
        )
        protected: dict[str, bytes] = {}
        for target in plan.targets:
            # FunctionPlan validates this identifier, avoiding path traversal.
            payload = _safe_image(function_cipher_root / (target.function_id + ".bin"))
            if len(payload) > _MAX_FUNCTION_CIPHERTEXT:
                raise ProductEvidenceError("R56_FUNCTION_PAYLOAD_TOO_LARGE")
            protected[target.function_id] = payload
        if check_functions(
            plan=plan, parent=parent_receipt,
            receipt=receipt, protected=protected,
        ) is not True:
            raise ProductEvidenceError("R56_CANONICAL_VERIFIER_DENIED")
    except ProductEvidenceError:
        raise
    except (ProtectorError, TypeError, KeyError, ValueError):
        raise ProductEvidenceError("R56_CANONICAL_VERIFIER_DENIED") from None
    return {
        "schema_version": 1,
        "status": "R56_FUNCTION_MANIFEST_INTEGRITY_ONLY",
        "parent_protected_manifest_sha256": parent["protected_manifest_sha256"],
        "function_manifest_sha256": receipt.function_manifest_sha256,
        "verified_function_count": len(plan.targets),
        "release_approved": False,
        "native_function_protector_execution": "NOT_PERFORMED",
        "windows_nvda_and_real_provider_qualification": "REQUIRED",
    }
