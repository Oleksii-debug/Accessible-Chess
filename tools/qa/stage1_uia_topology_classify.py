from __future__ import annotations

import argparse
import json
import sys
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


def _root_map(report: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        str(root.get("hwnd") or ""): root
        for root in report.get("root_attempts", [])
        if isinstance(root, dict) and root.get("hwnd")
    }


def _root_complete(root: dict[str, Any]) -> bool:
    return all(
        (
            _truth(root.get("connected_to_app")),
            _truth(root.get("from_handle_success")),
            _view_complete(root.get("raw_view")),
            _view_complete(root.get("control_view")),
        )
    )


def _source_contract_ok(report: dict[str, Any]) -> bool:
    contract = report.get("source_contract")
    return (
        isinstance(contract, dict)
        and _truth(contract.get("unique_original_move_edit"))
        and _truth(contract.get("no_qa_proxy_in_product_tree"))
    )


def _move_occurrence_evaluation(
    edit: dict[str, Any], roots: dict[str, dict[str, Any]]
) -> dict[str, Any]:
    source_root = roots.get(str(edit.get("source_root_hwnd") or ""))
    automation_id = str(edit.get("automation_id") or "")
    provenance_failures: list[str] = []
    if not _truth(edit.get("connected_to_app")):
        provenance_failures.append("not connected to app")
    if not _truth(edit.get("source_root_connected")):
        provenance_failures.append("source root not connected")
    if not _truth(edit.get("source_contract_original_possible")):
        provenance_failures.append("source contract does not permit original identity")
    if not source_root:
        provenance_failures.append("source root not retained")
    elif not _truth(source_root.get("provider_subtree_seen")):
        provenance_failures.append("source root does not expose provider subtree")
    if automation_id and automation_id != "move-input":
        provenance_failures.append(f"unexpected AutomationId={automation_id}")

    accessibility_failures: list[str] = []
    if not _truth(edit.get("enabled")):
        accessibility_failures.append("disabled")
    if not _truth(edit.get("keyboard_focusable")):
        accessibility_failures.append("not keyboard-focusable")
    if bool(edit.get("offscreen", True)):
        accessibility_failures.append("offscreen")
    if not _truth(edit.get("is_control_element")):
        accessibility_failures.append("not a ControlView element")
    if not _truth(edit.get("is_content_element")):
        accessibility_failures.append("not a ContentView element")
    if not _truth(edit.get("value_pattern")):
        accessibility_failures.append("ValuePattern unavailable")
    if not _positive_bounds(edit.get("bounds")):
        accessibility_failures.append("non-positive/unknown bounds")

    proven_original = not provenance_failures
    strict_valid = proven_original and not accessibility_failures
    return {
        "view": edit.get("view"),
        "source_root_hwnd": edit.get("source_root_hwnd"),
        "source_root_pid": edit.get("source_root_pid"),
        "source_root_class": edit.get("source_root_class"),
        "runtime_id": edit.get("runtime_id"),
        "process_id": edit.get("process_id"),
        "process_name": edit.get("process_name"),
        "native_window_handle": edit.get("native_window_handle"),
        "name": edit.get("name"),
        "automation_id": automation_id,
        "framework_id": edit.get("framework_id"),
        "enabled": bool(edit.get("enabled")),
        "keyboard_focusable": bool(edit.get("keyboard_focusable")),
        "has_keyboard_focus": bool(edit.get("has_keyboard_focus")),
        "offscreen": bool(edit.get("offscreen", True)),
        "is_control_element": bool(edit.get("is_control_element")),
        "is_content_element": bool(edit.get("is_content_element")),
        "value_pattern": bool(edit.get("value_pattern")),
        "bounds": edit.get("bounds"),
        "proven_original": proven_original,
        "strict_valid": strict_valid,
        "provenance_failures": provenance_failures,
        "accessibility_failures": accessibility_failures,
        "ancestor_path": edit.get("ancestor_path"),
    }


def _move_evaluations(report: dict[str, Any]) -> list[dict[str, Any]]:
    roots = _root_map(report)
    groups: dict[str, list[dict[str, Any]]] = {}
    for edit in report.get("connected_edits", []):
        if not isinstance(edit, dict):
            continue
        if edit.get("control_type") != "ControlType.Edit" or edit.get("name") not in MOVE_NAMES:
            continue
        groups.setdefault(_edit_identity(edit), []).append(edit)

    evaluations: list[dict[str, Any]] = []
    for identity, occurrences in groups.items():
        occurrence_evals = [_move_occurrence_evaluation(edit, roots) for edit in occurrences]
        proven = [x for x in occurrence_evals if x["proven_original"]]
        valid = [x for x in occurrence_evals if x["strict_valid"]]
        best = min(
            proven or occurrence_evals,
            key=lambda x: len(x["provenance_failures"]) + len(x["accessibility_failures"]),
        )
        evaluations.append(
            {
                "identity": identity,
                "occurrence_count": len(occurrence_evals),
                "proven_original": bool(proven),
                "strict_valid": bool(valid),
                "best_provenance_failures": best["provenance_failures"],
                "best_accessibility_failures": best["accessibility_failures"],
                "best_occurrence": best,
                "occurrences": occurrence_evals,
            }
        )
    return evaluations


def _topology_evaluation(report: dict[str, Any]) -> dict[str, Any]:
    roots = [r for r in report.get("root_attempts", []) if isinstance(r, dict)]
    connected_roots = [r for r in roots if _truth(r.get("connected_to_app"))]
    provider_bearing = [r for r in connected_roots if _truth(r.get("provider_subtree_seen"))]
    shell_roots = [
        r
        for r in connected_roots
        if _truth(r.get("relevant_provider_root")) and not _truth(r.get("provider_subtree_seen"))
    ]
    incomplete = [r for r in connected_roots if not _root_complete(r)]
    disconnected = [r for r in roots if not _truth(r.get("connected_to_app"))]
    transitions = [t for t in report.get("provider_transitions", []) if isinstance(t, dict)]
    chain = report.get("provider_chain") if isinstance(report.get("provider_chain"), dict) else {}

    failures: list[str] = []
    if not roots:
        failures.append("no scalar candidate roots retained")
    if disconnected:
        failures.append("one or more retained candidate roots are not connected to the app")
    if incomplete:
        failures.append("one or more connected candidate roots have incomplete/error/truncated traversal")
    if not provider_bearing:
        failures.append("no connected provider-bearing UIA root exposes the WebView2 subtree")
    if not transitions:
        failures.append("no provider/process/native UIA transition was retained")
    if not _truth(chain.get("host_found")):
        failures.append("native app host was not proven")
    if not _truth(chain.get("native_relationship_proven")):
        failures.append("native host/WebView relationship was not proven")
    if not _truth(chain.get("process_relationship_proven")):
        failures.append("app/WebView process relationship was not proven")

    return {
        "complete": not failures,
        "candidate_root_count": len(roots),
        "connected_root_count": len(connected_roots),
        "provider_bearing_root_count": len(provider_bearing),
        "complete_provider_bearing_root_count": sum(_root_complete(r) for r in provider_bearing),
        "complete_shell_root_count": sum(_root_complete(r) for r in shell_roots),
        "shell_root_count": len(shell_roots),
        "provider_transition_count": len(transitions),
        "incomplete_root_hwnds": [r.get("hwnd") for r in incomplete],
        "disconnected_root_hwnds": [r.get("hwnd") for r in disconnected],
        "failures": failures,
    }


def classify(report: dict[str, Any]) -> tuple[str, list[str]]:
    move_evals = _move_evaluations(report)
    topology = _topology_evaluation(report)
    source_ok = _source_contract_ok(report)

    if len(move_evals) > 1:
        return "C", ["ambiguous duplicate/proxy Move Edit identities"]

    if len(move_evals) == 1 and move_evals[0]["strict_valid"]:
        return "A", ["one unique original connected real Move Edit satisfies the strict interactive contract"]

    reasons: list[str] = []
    if not source_ok:
        reasons.append("source contract does not prove one original move input with no QA proxy")
    reasons.extend(topology["failures"])

    if len(move_evals) == 1:
        move_eval = move_evals[0]
        if not move_eval["proven_original"]:
            failures = ", ".join(move_eval["best_provenance_failures"]) or "unknown provenance failure"
            reasons.append(f"Move-named Edit identity is not proven original: {failures}")
        elif topology["complete"] and source_ok:
            failures = ", ".join(move_eval["best_accessibility_failures"]) or "unknown accessibility failure"
            return "B", [f"the unique original Move Edit is present but accessibility-invalid: {failures}"]
        else:
            failures = ", ".join(move_eval["best_accessibility_failures"]) or "strict contract not satisfied"
            reasons.append(f"original Move Edit fails strict accessibility contract: {failures}")
    elif topology["complete"] and source_ok:
        return "B", ["complete connected provider traversal proves the required original Move Edit absent"]

    if not reasons:
        reasons.append("evidence is insufficient for A or B")
    return "C", reasons


def apply_classification(report: dict[str, Any]) -> dict[str, Any]:
    report["topology_evaluation"] = _topology_evaluation(report)
    report["move_edit_evaluations"] = _move_evaluations(report)
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


def _safe_print(text: str) -> None:
    try:
        print(text)
    except UnicodeEncodeError:
        encoding = getattr(sys.stdout, "encoding", None) or "ascii"
        replacement = text.encode(encoding, errors="backslashreplace").decode(encoding, errors="replace")
        print(replacement)


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
    _safe_print(f"classification={report['classification']}")
    topo = report["topology_evaluation"]
    _safe_print(
        "topology="
        f"complete={topo['complete']} roots={topo['candidate_root_count']} "
        f"provider_bearing={topo['provider_bearing_root_count']} "
        f"shells={topo['shell_root_count']} transitions={topo['provider_transition_count']}"
    )
    for move_eval in report.get("move_edit_evaluations", []):
        _safe_print(
            "move="
            f"identity={move_eval['identity']} occurrences={move_eval['occurrence_count']} "
            f"proven_original={move_eval['proven_original']} strict_valid={move_eval['strict_valid']} "
            f"provenance_failures={move_eval['best_provenance_failures']} "
            f"accessibility_failures={move_eval['best_accessibility_failures']}"
        )
    for reason in report.get("classification_reasons", []):
        _safe_print(f"reason={reason}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
