from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

MOVE_NAMES = {"Хід", "Move"}


def _truth(value: Any) -> bool:
    return value is True


def _view_complete(view: dict[str, Any] | None) -> bool:
    if not isinstance(view, dict):
        return False
    return all(
        (
            _truth(view.get("started")),
            _truth(view.get("completed")),
            int(view.get("error_count", 0) or 0) == 0,
            not bool(view.get("cap_reached", False)),
            not bool(view.get("truncated", False)),
            int(view.get("disconnected_count", 0) or 0) == 0,
            int(view.get("cycle_or_duplicate_count", 0) or 0) == 0,
        )
    )


def _positive_bounds(bounds: Any) -> bool:
    return (
        isinstance(bounds, list)
        and len(bounds) >= 4
        and isinstance(bounds[2], (int, float))
        and isinstance(bounds[3], (int, float))
        and bounds[2] > 0
        and bounds[3] > 0
    )


def _edit_identity(edit: dict[str, Any]) -> str:
    rid = str(edit.get("runtime_id") or "").strip()
    if rid:
        return f"rid:{rid}"
    return "fallback:" + "|".join(
        str(edit.get(k) or "")
        for k in (
            "process_id",
            "native_window_handle",
            "automation_id",
            "name",
            "bounds",
        )
    )


def _valid_move_edit(edit: dict[str, Any]) -> bool:
    return all(
        (
            edit.get("control_type") == "ControlType.Edit",
            edit.get("name") in MOVE_NAMES,
            _truth(edit.get("connected_to_app")),
            _truth(edit.get("source_root_connected")),
            _truth(edit.get("source_contract_original_possible")),
            _truth(edit.get("enabled")),
            _truth(edit.get("keyboard_focusable")),
            not bool(edit.get("offscreen", True)),
            _truth(edit.get("is_control_element")),
            _truth(edit.get("is_content_element")),
            _truth(edit.get("value_pattern")),
            _positive_bounds(edit.get("bounds")),
        )
    )


def classify(report: dict[str, Any]) -> tuple[str, list[str]]:
    reasons: list[str] = []
    edits = [e for e in report.get("connected_edits", []) if isinstance(e, dict)]
    valid = [e for e in edits if _valid_move_edit(e)]
    unique_valid: dict[str, dict[str, Any]] = {}
    for edit in valid:
        unique_valid[_edit_identity(edit)] = edit

    named_move_edits = [
        e
        for e in edits
        if e.get("control_type") == "ControlType.Edit" and e.get("name") in MOVE_NAMES
    ]
    named_identities = {_edit_identity(e) for e in named_move_edits}

    if len(unique_valid) == 1 and len(named_identities) == 1:
        return "A", ["one unique connected real Move Edit satisfies the strict interactive contract"]
    if len(named_identities) > 1:
        reasons.append("ambiguous duplicate/proxy Move Edit identities")
    elif named_move_edits and not valid:
        reasons.append("Move-named Edit exists but fails visibility/focus/value/original-identity contract")

    roots = [r for r in report.get("root_attempts", []) if isinstance(r, dict)]
    relevant = [r for r in roots if _truth(r.get("relevant_provider_root"))]
    connected = [r for r in relevant if _truth(r.get("connected_to_app"))]
    complete = [
        r
        for r in connected
        if _truth(r.get("from_handle_success"))
        and _view_complete(r.get("raw_view"))
        and _view_complete(r.get("control_view"))
        and _truth(r.get("provider_subtree_seen"))
    ]

    chain = report.get("provider_chain") if isinstance(report.get("provider_chain"), dict) else {}
    chain_complete = all(
        (
            _truth(chain.get("host_found")),
            _truth(chain.get("native_relationship_proven")),
            _truth(chain.get("process_relationship_proven")),
            _truth(chain.get("provider_entry_proven")),
            _truth(chain.get("uia_subtree_proven")),
            _truth(chain.get("provider_transition_proven")),
            int(chain.get("unresolved_boundary_count", 0) or 0) == 0,
        )
    )

    all_relevant_complete = bool(relevant) and len(complete) == len(relevant)
    traversal_errors = any(
        not _view_complete(r.get(view_name))
        for r in connected
        for view_name in ("raw_view", "control_view")
    )

    if not relevant:
        reasons.append("no relevant Accessible Chess WebView2 provider roots proven")
    if relevant and len(connected) != len(relevant):
        reasons.append("one or more relevant provider roots are not connected to the app host")
    if connected and not all_relevant_complete:
        reasons.append("one or more relevant provider roots have incomplete RawView/ControlView traversal")
    if traversal_errors:
        reasons.append("traversal error/truncation/disconnection/cycle evidence prevents absence proof")
    if not chain_complete:
        reasons.append("host→WebView2→provider→UIA subtree chain is not fully proven")

    source_contract = report.get("source_contract") if isinstance(report.get("source_contract"), dict) else {}
    source_unique = _truth(source_contract.get("unique_original_move_edit"))
    source_no_proxy = _truth(source_contract.get("no_qa_proxy_in_product_tree"))
    if not source_unique:
        reasons.append("source contract does not prove exactly one original move input")
    if not source_no_proxy:
        reasons.append("source contract does not exclude QA proxy controls from product tree")

    if (
        chain_complete
        and all_relevant_complete
        and not traversal_errors
        and source_unique
        and source_no_proxy
        and len(named_identities) == 0
    ):
        return "B", ["complete connected provider traversal proves the required Move Edit absent"]

    if not reasons:
        reasons.append("evidence is insufficient for A or B")
    return "C", reasons


def apply_classification(report: dict[str, Any]) -> dict[str, Any]:
    classification, reasons = classify(report)
    report["classification"] = classification
    report["classification_reasons"] = reasons
    report["evidence_complete"] = classification in {"A", "B"}
    return report


def verify_source_contract(product_root: Path) -> dict[str, Any]:
    index = product_root / "web" / "index.html"
    text = index.read_text(encoding="utf-8")
    token_count = text.count('id="move-input"') + text.count("id='move-input'")
    input_count = text.count('<input id="move-input"') + text.count("<input id='move-input'")
    return {
        "unique_original_move_edit": token_count == 1 and input_count == 1,
        "move_input_id_occurrences": token_count,
        "move_input_input_occurrences": input_count,
        "no_qa_proxy_in_product_tree": not (product_root / "tools" / "qa").exists(),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("report", type=Path)
    parser.add_argument("--product-root", type=Path)
    args = parser.parse_args(argv)
    report = json.loads(args.report.read_text(encoding="utf-8-sig"))
    if args.product_root:
        report["source_contract"] = verify_source_contract(args.product_root)
    apply_classification(report)
    args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"classification={report['classification']}")
    for reason in report.get("classification_reasons", []):
        print(f"reason={reason}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
