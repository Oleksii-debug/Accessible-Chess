from __future__ import annotations

import argparse
from pathlib import Path
import sys
from typing import Any

# When this verifier is executed directly (``python scripts/...py``), Python
# puts the scripts directory rather than the repository root on sys.path.
# Keep the module import path identical for direct CLI use and package/test
# imports so release qualification does not depend on the caller's PYTHONPATH.
if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.verify_p0_packaged_document_copy_evidence import (
    EvidenceError,
    _canonical_expected_sha,
    _read_json,
    _verify_package_binding,
)


_REQUIRED_TRUE = (
    "native_keyboard_dispatch",
    "foreground_product_verified",
    "manifest_product_sha_verified",
    "executable_checksum_verified",
    "alt_1_action_occurred",
    "alt_1_accessible_result_exposed",
    "alt_2_action_occurred",
    "alt_2_accessible_result_exposed",
)


def _require_true(evidence: dict[str, Any], key: str) -> None:
    if evidence.get(key) is not True:
        raise EvidenceError(f"required P0-G evidence flag is not true: {key}")


def _require_false(evidence: dict[str, Any], key: str) -> None:
    if evidence.get(key) is not False:
        raise EvidenceError(f"required P0-G evidence flag is not false: {key}")


def _bounded_text(evidence: dict[str, Any], key: str, *, maximum: int = 4096) -> str:
    value = evidence.get(key)
    if not isinstance(value, str) or not value.strip() or len(value) > maximum:
        raise EvidenceError(f"required bounded P0-G text is missing or invalid: {key}")
    return value.strip()


def _verify_result_semantics(text: str, index: int) -> None:
    lower = text.casefold()
    if f"variant {index}" not in lower and f"варіант {index}" not in lower:
        raise EvidenceError(f"Alt+{index} result does not identify selected variation")
    if "depth" not in lower and "глибин" not in lower:
        raise EvidenceError(f"Alt+{index} result omits analysis depth")
    if "eval" not in lower and "оцін" not in lower:
        raise EvidenceError(f"Alt+{index} result omits evaluation")
    if "uci" in lower or "debug" in lower or "traceback" in lower:
        raise EvidenceError(f"Alt+{index} result exposes raw provider/debug text")


def _verify_evidence(evidence: dict[str, Any], expected_sha: str) -> None:
    product_sha = evidence.get("product_sha")
    if not isinstance(product_sha, str) or product_sha.casefold() != expected_sha:
        raise EvidenceError("P0-G evidence product_sha does not match expected Product SHA")

    for key in _REQUIRED_TRUE:
        _require_true(evidence, key)
    for key in (
        "board_application_entered",
        "raw_uci_or_debug_exposed",
        "human_tested",
        "nvda_verified",
    ):
        _require_false(evidence, key)

    _bounded_text(evidence, "discovery")
    _bounded_text(evidence, "hotkey_focus_path")
    _bounded_text(evidence, "engine_enable_state", maximum=128)

    pre1 = _bounded_text(evidence, "alt_1_precondition_selected_state")
    selected1 = _bounded_text(evidence, "alt_1_selected_state")
    result1 = _bounded_text(evidence, "alt_1_result")
    pre2 = _bounded_text(evidence, "alt_2_precondition_selected_state")
    selected2 = _bounded_text(evidence, "alt_2_selected_state")
    result2 = _bounded_text(evidence, "alt_2_result")

    if pre1 == selected1:
        raise EvidenceError("Alt+1 evidence does not prove a causal selected-state transition")
    if pre2 == selected2:
        raise EvidenceError("Alt+2 evidence does not prove a causal selected-state transition")
    if selected1 == selected2:
        raise EvidenceError("Alt+1 and Alt+2 selected-state evidence is not distinct")
    if result1 == result2:
        raise EvidenceError("Alt+1 and Alt+2 accessible results are not distinct")

    _verify_result_semantics(result1, 1)
    _verify_result_semantics(result2, 2)


def verify(evidence_path: Path, product_root: Path, product_sha: str) -> None:
    expected_sha = _canonical_expected_sha(product_sha)
    _verify_package_binding(product_root, expected_sha)
    evidence = _read_json(evidence_path)
    _verify_evidence(evidence, expected_sha)


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify packaged P0-G hotkey result evidence")
    parser.add_argument("--evidence", required=True, type=Path)
    parser.add_argument("--product-root", required=True, type=Path)
    parser.add_argument("--product-sha", required=True)
    args = parser.parse_args()
    try:
        verify(args.evidence, args.product_root, args.product_sha)
    except EvidenceError as exc:
        print(f"P0-G PACKAGED HOTKEY RESULT EVIDENCE FAIL: {exc}")
        return 1
    print("P0-G PACKAGED HOTKEY RESULT EVIDENCE VERIFIED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
