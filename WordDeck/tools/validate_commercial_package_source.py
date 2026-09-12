#!/usr/bin/env python3
"""Validate the exact authorized WordDeck commercial package producer contract."""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any, Mapping, Sequence


class SourceContractFailure(Exception):
    pass


def _positive_int(value: Any, field: str) -> int:
    if isinstance(value, bool):
        raise SourceContractFailure(f"{field}: expected positive integer")
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise SourceContractFailure(f"{field}: expected positive integer") from exc
    if parsed <= 0:
        raise SourceContractFailure(f"{field}: expected positive integer")
    return parsed


def validate_source_contract(
    run: Any,
    artifacts: Any,
    *,
    expected_run_id: int,
    expected_workflow_path: str,
    expected_branch: str,
    expected_sha: str,
    expected_artifact_name: str,
) -> Mapping[str, Any]:
    if not isinstance(run, dict):
        raise SourceContractFailure("run: expected JSON object")
    if not isinstance(artifacts, list):
        raise SourceContractFailure("artifacts: expected JSON array")

    expected_run_id = _positive_int(expected_run_id, "expected_run_id")
    if not re.fullmatch(r"[0-9a-fA-F]{40}", expected_sha or ""):
        raise SourceContractFailure("expected_sha: expected exact 40-hex commit SHA")
    if not expected_workflow_path:
        raise SourceContractFailure("expected_workflow_path: required")
    if not expected_branch:
        raise SourceContractFailure("expected_branch: required")
    if not expected_artifact_name:
        raise SourceContractFailure("expected_artifact_name: required")

    run_id = _positive_int(run.get("id"), "run.id")
    if run_id != expected_run_id:
        raise SourceContractFailure(
            f"run.id: expected {expected_run_id}, got {run_id}"
        )
    if run.get("path") != expected_workflow_path:
        raise SourceContractFailure(
            f"run.path: unauthorized producer {run.get('path')!r}; "
            f"expected {expected_workflow_path!r}"
        )
    if run.get("head_branch") != expected_branch:
        raise SourceContractFailure(
            f"run.head_branch: expected {expected_branch!r}, got {run.get('head_branch')!r}"
        )
    if run.get("conclusion") != "success":
        raise SourceContractFailure(
            f"run.conclusion: expected 'success', got {run.get('conclusion')!r}"
        )

    actual_sha = str(run.get("head_sha") or "").lower()
    if not re.fullmatch(r"[0-9a-f]{40}", actual_sha):
        raise SourceContractFailure("run.head_sha: expected exact 40-hex commit SHA")
    if actual_sha != expected_sha.lower():
        raise SourceContractFailure(
            f"run.head_sha: expected {expected_sha.lower()}, got {actual_sha}"
        )

    matches = [
        artifact
        for artifact in artifacts
        if isinstance(artifact, dict)
        and artifact.get("name") == expected_artifact_name
    ]
    if len(matches) != 1:
        raise SourceContractFailure(
            f"artifacts: expected exactly one {expected_artifact_name!r}, found {len(matches)}"
        )

    artifact = matches[0]
    artifact_id = _positive_int(artifact.get("id"), "artifact.id")
    if artifact.get("expired") is not False:
        raise SourceContractFailure("artifact.expired: exact release artifact is expired/unknown")

    return {
        "run_id": run_id,
        "workflow_path": expected_workflow_path,
        "branch": expected_branch,
        "source_sha": actual_sha,
        "artifact_id": artifact_id,
        "artifact_name": expected_artifact_name,
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--contract-json", required=True, type=Path)
    parser.add_argument("--expected-run-id", required=True, type=int)
    parser.add_argument("--expected-workflow-path", required=True)
    parser.add_argument("--expected-branch", required=True)
    parser.add_argument("--expected-sha", required=True)
    parser.add_argument("--expected-artifact-name", required=True)
    args = parser.parse_args(argv)

    try:
        payload = json.loads(args.contract_json.read_text(encoding="utf-8-sig"))
        if not isinstance(payload, dict):
            raise SourceContractFailure("contract JSON: expected object")
        result = validate_source_contract(
            payload.get("run"),
            payload.get("artifacts"),
            expected_run_id=args.expected_run_id,
            expected_workflow_path=args.expected_workflow_path,
            expected_branch=args.expected_branch,
            expected_sha=args.expected_sha,
            expected_artifact_name=args.expected_artifact_name,
        )
    except (OSError, json.JSONDecodeError, SourceContractFailure) as exc:
        print(f"COMMERCIAL_PACKAGE_SOURCE_FAIL: {exc}", file=sys.stderr)
        return 1

    print(
        "COMMERCIAL_PACKAGE_SOURCE_PASS "
        f"run={result['run_id']} "
        f"workflow={result['workflow_path']} "
        f"sha={result['source_sha']} "
        f"artifact={result['artifact_name']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
