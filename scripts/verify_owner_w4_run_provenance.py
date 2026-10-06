from __future__ import annotations

"""Fail-closed provenance validation for an owner-selected W4 Actions run.

The owner finalizer receives a numeric run id from a human/operator. Artifact
names and self-reported run metadata are not proof that the id belongs to the
canonical W4 workflow. This module validates the authoritative GitHub Actions
run API response before any downloaded artifact is trusted.

It deliberately does not fetch the network itself. A workflow with Actions-read
permission should fetch /repos/{repo}/actions/runs/{id} and pass the bounded
JSON response here. Keeping transport separate makes this verifier deterministic
and unit-testable.
"""

import argparse
from dataclasses import dataclass
import json
import os
from pathlib import Path
import re
import stat
import sys
from typing import Any, Mapping


HEX40 = re.compile(r"^[0-9a-f]{40}$")
MAX_RUN_JSON_BYTES = 1024 * 1024
DEFAULT_W4_WORKFLOW_PATH = ".github/workflows/w4-v2-p0-fresh-windows-candidate.yml"


class W4RunProvenanceError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class W4RunProvenance:
    run_id: int
    workflow_id: int
    workflow_sha: str
    head_branch: str
    workflow_path: str
    repository: str
    run_attempt: int


def _fail(message: str) -> None:
    raise W4RunProvenanceError(message)


def _positive_int(value: object, *, label: str) -> int:
    if type(value) is not int or value <= 0:
        _fail(f"{label} must be a positive integer")
    return value


def _exact_text(value: object, *, label: str) -> str:
    if type(value) is not str or not value or value != value.strip():
        _fail(f"{label} must be non-empty canonical text")
    if any(ord(character) < 32 or ord(character) == 0x7F for character in value):
        _fail(f"{label} contains control characters")
    return value


def _repository_full_name(value: object, *, label: str) -> str:
    text = _exact_text(value, label=label)
    parts = text.split("/")
    if len(parts) != 2 or not all(parts):
        _fail(f"{label} must be owner/repository")
    if any(part in {".", ".."} or part != part.strip() for part in parts):
        _fail(f"{label} is invalid")
    return text


def _workflow_path(
    value: object,
    *,
    expected_path: str,
    expected_branch: str,
) -> str:
    raw = _exact_text(value, label="W4 run workflow path")
    if raw.count("@") > 1:
        _fail("W4 run workflow path is invalid")
    path, separator, authority = raw.partition("@")
    if path != expected_path:
        _fail("W4 run does not belong to the canonical workflow path")
    if separator and authority != f"refs/heads/{expected_branch}":
        _fail("W4 run workflow path authority is not the expected branch")
    return path


def _same_file_snapshot(left: os.stat_result, right: os.stat_result) -> bool:
    return all(
        getattr(left, field) == getattr(right, field)
        for field in (
            "st_dev",
            "st_ino",
            "st_mode",
            "st_size",
            "st_mtime_ns",
            "st_ctime_ns",
        )
    )


def validate_w4_run_provenance(
    value: Mapping[str, Any],
    *,
    expected_run_id: int,
    expected_repository: str,
    expected_branch: str,
    expected_workflow_path: str = DEFAULT_W4_WORKFLOW_PATH,
) -> W4RunProvenance:
    expected_run_id = _positive_int(expected_run_id, label="expected W4 run id")
    expected_repository = _repository_full_name(
        expected_repository,
        label="expected W4 repository",
    )
    expected_branch = _exact_text(expected_branch, label="expected W4 workflow branch")
    expected_workflow_path = _exact_text(
        expected_workflow_path,
        label="expected W4 workflow path",
    )
    if (
        not expected_workflow_path.startswith(".github/workflows/")
        or not expected_workflow_path.endswith((".yml", ".yaml"))
    ):
        _fail("expected W4 workflow path is invalid")

    if not isinstance(value, Mapping):
        _fail("W4 run API payload must be an object")

    run_id = _positive_int(value.get("id"), label="W4 run id")
    if run_id != expected_run_id:
        _fail("W4 run id does not match the requested run")

    workflow_id = _positive_int(value.get("workflow_id"), label="W4 workflow id")
    run_attempt = _positive_int(value.get("run_attempt"), label="W4 run attempt")

    repository = value.get("repository")
    head_repository = value.get("head_repository")
    if not isinstance(repository, Mapping) or not isinstance(head_repository, Mapping):
        _fail("W4 run repository provenance is missing")
    repository_name = _repository_full_name(
        repository.get("full_name"),
        label="W4 run repository",
    )
    head_repository_name = _repository_full_name(
        head_repository.get("full_name"),
        label="W4 run head repository",
    )
    if repository_name != expected_repository or head_repository_name != expected_repository:
        _fail("W4 run repository provenance does not match the current repository")

    event = _exact_text(value.get("event"), label="W4 run event")
    status = _exact_text(value.get("status"), label="W4 run status")
    conclusion = _exact_text(value.get("conclusion"), label="W4 run conclusion")
    if event != "workflow_dispatch":
        _fail("W4 run event must be workflow_dispatch")
    if status != "completed":
        _fail("W4 run must be completed")
    if conclusion != "success":
        _fail("W4 run conclusion must be success")

    head_branch = _exact_text(value.get("head_branch"), label="W4 run head branch")
    if head_branch != expected_branch:
        _fail("W4 run head branch is not the expected workflow authority branch")

    workflow_path = _workflow_path(
        value.get("path"),
        expected_path=expected_workflow_path,
        expected_branch=expected_branch,
    )
    workflow_sha = _exact_text(value.get("head_sha"), label="W4 run workflow SHA")
    if not HEX40.fullmatch(workflow_sha):
        _fail("W4 run workflow SHA must be lowercase exact 40-hex")

    return W4RunProvenance(
        run_id=run_id,
        workflow_id=workflow_id,
        workflow_sha=workflow_sha,
        head_branch=head_branch,
        workflow_path=workflow_path,
        repository=repository_name,
        run_attempt=run_attempt,
    )


def _load_run_json(path: Path) -> Mapping[str, Any]:
    try:
        before = path.lstat()
    except OSError as exc:
        _fail(f"W4 run API payload cannot be inspected: {type(exc).__name__}")
    if stat.S_ISLNK(before.st_mode) or not stat.S_ISREG(before.st_mode):
        _fail("W4 run API payload must be one regular file")
    if before.st_size <= 0 or before.st_size > MAX_RUN_JSON_BYTES:
        _fail("W4 run API payload size is outside accepted bounds")
    try:
        with path.open("rb") as stream:
            opened = os.fstat(stream.fileno())
            if not _same_file_snapshot(before, opened):
                _fail("W4 run API payload changed before stable read")
            payload = stream.read(MAX_RUN_JSON_BYTES + 1)
            after_read = os.fstat(stream.fileno())
        after = path.lstat()
    except W4RunProvenanceError:
        raise
    except OSError as exc:
        _fail(f"W4 run API payload cannot be read: {type(exc).__name__}")
    if (
        len(payload) != opened.st_size
        or len(payload) == 0
        or len(payload) > MAX_RUN_JSON_BYTES
    ):
        _fail("W4 run API payload size changed during stable read")
    if (
        not _same_file_snapshot(opened, after_read)
        or not _same_file_snapshot(before, after)
    ):
        _fail("W4 run API payload changed during stable read")
    try:
        value = json.loads(payload.decode("utf-8", errors="strict"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        _fail(f"W4 run API payload is invalid JSON: {type(exc).__name__}")
    if not isinstance(value, dict):
        _fail("W4 run API payload must be an object")
    return value


def _write_github_output(path: Path, provenance: W4RunProvenance) -> None:
    payload = (
        f"workflow_sha={provenance.workflow_sha}\n"
        f"workflow_id={provenance.workflow_id}\n"
        f"run_attempt={provenance.run_attempt}\n"
    )
    try:
        with path.open("a", encoding="utf-8", newline="\n") as stream:
            stream.write(payload)
    except OSError as exc:
        _fail(f"GitHub output could not be written: {type(exc).__name__}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Validate canonical W4 GitHub Actions run provenance"
    )
    parser.add_argument("--run-json", required=True, type=Path)
    parser.add_argument("--run-id", required=True, type=int)
    parser.add_argument("--repository", required=True)
    parser.add_argument("--default-branch", required=True)
    parser.add_argument("--workflow-path", default=DEFAULT_W4_WORKFLOW_PATH)
    parser.add_argument("--github-output", type=Path)
    args = parser.parse_args(argv)
    try:
        provenance = validate_w4_run_provenance(
            _load_run_json(args.run_json),
            expected_run_id=args.run_id,
            expected_repository=args.repository,
            expected_branch=args.default_branch,
            expected_workflow_path=args.workflow_path,
        )
        if args.github_output is not None:
            _write_github_output(args.github_output, provenance)
    except W4RunProvenanceError as exc:
        print(f"W4 RUN PROVENANCE FAIL: {exc}", file=sys.stderr)
        return 1
    print(f"W4_RUN_ID={provenance.run_id}")
    print(f"W4_RUN_WORKFLOW_ID={provenance.workflow_id}")
    print(f"W4_RUN_WORKFLOW_SHA={provenance.workflow_sha}")
    print(f"W4_RUN_ATTEMPT={provenance.run_attempt}")
    print("W4_RUN_PROVENANCE=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "DEFAULT_W4_WORKFLOW_PATH",
    "MAX_RUN_JSON_BYTES",
    "W4RunProvenance",
    "W4RunProvenanceError",
    "validate_w4_run_provenance",
]
