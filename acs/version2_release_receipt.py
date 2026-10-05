from __future__ import annotations

"""Fail-closed release receipt for an already-qualified Version 2 package.

This module does not build, mutate, sign, publish, or promote a package.  It
reuses the canonical Version 2 ZIP preflight and records the identity of the
accepted bytes together with attributable GitHub Actions evidence.
"""

from dataclasses import asdict, dataclass
import argparse
import hashlib
import json
from pathlib import Path
import re

from .version2_package_preflight import validate_version2_package_zip


RELEASE_RECEIPT_SCHEMA_VERSION = 1
CANONICAL_W5_WORKFLOW = ".github/workflows/post-freeze-v2-windows-package-qualification.yml"
_SHA40_RE = re.compile(r"^[0-9a-f]{40}$")
_SAFE_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._ -]{0,255}$")
_MAX_ID = (1 << 63) - 1


class Version2ReleaseReceiptError(ValueError):
    """Raised when qualification metadata cannot be represented safely."""


@dataclass(frozen=True)
class Version2ReleaseReceipt:
    schema_version: int
    product: str
    workflow_path: str
    workflow_run_id: int
    qualification_head_sha: str
    artifact_id: int
    artifact_name: str
    integration_sha: str
    package_sha256: str
    inventory_sha256: str
    inventory_files: int
    total_bytes: int
    checksums_verified: int

    def to_json(self) -> str:
        return json.dumps(
            asdict(self),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ) + "\n"


def _positive_id(value: int, *, label: str) -> int:
    if type(value) is not int or not 0 < value <= _MAX_ID:
        raise Version2ReleaseReceiptError(
            f"{label} must be a positive signed 64-bit integer"
        )
    return value


def _sha40(value: str, *, label: str) -> str:
    if type(value) is not str or _SHA40_RE.fullmatch(value) is None:
        raise Version2ReleaseReceiptError(
            f"{label} must be an exact lowercase 40-character Git SHA"
        )
    return value


def _artifact_name(value: str) -> str:
    if type(value) is not str or _SAFE_NAME_RE.fullmatch(value) is None:
        raise Version2ReleaseReceiptError(
            "artifact_name must be 1-256 safe printable name characters"
        )
    if value in {".", ".."} or value != value.strip():
        raise Version2ReleaseReceiptError("artifact_name is not canonical")
    return value


def _inventory_digest(inventory: tuple[str, ...]) -> str:
    canonical = "".join(f"{item}\n" for item in inventory).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def build_version2_release_receipt(
    package_zip: str | Path,
    *,
    expected_integration_sha: str,
    workflow_run_id: int,
    qualification_head_sha: str,
    artifact_id: int,
    artifact_name: str,
) -> Version2ReleaseReceipt:
    """Validate one final ZIP and return an attributable immutable receipt."""

    integration_sha = _sha40(
        expected_integration_sha, label="expected_integration_sha"
    )
    head_sha = _sha40(qualification_head_sha, label="qualification_head_sha")
    run_id = _positive_id(workflow_run_id, label="workflow_run_id")
    action_artifact_id = _positive_id(artifact_id, label="artifact_id")
    safe_artifact_name = _artifact_name(artifact_name)

    report = validate_version2_package_zip(
        package_zip,
        expected_integration_sha=integration_sha,
    )
    if report.archive_sha256 is None:
        raise Version2ReleaseReceiptError(
            "canonical package preflight did not return the ZIP SHA-256"
        )
    if not report.inventory:
        raise Version2ReleaseReceiptError(
            "canonical package preflight returned an empty inventory"
        )

    return Version2ReleaseReceipt(
        schema_version=RELEASE_RECEIPT_SCHEMA_VERSION,
        product="Accessible Chess",
        workflow_path=CANONICAL_W5_WORKFLOW,
        workflow_run_id=run_id,
        qualification_head_sha=head_sha,
        artifact_id=action_artifact_id,
        artifact_name=safe_artifact_name,
        integration_sha=report.integration_sha,
        package_sha256=report.archive_sha256,
        inventory_sha256=_inventory_digest(report.inventory),
        inventory_files=len(report.inventory),
        total_bytes=report.total_bytes,
        checksums_verified=report.checksums_verified,
    )


def write_version2_release_receipt(
    output_path: str | Path,
    receipt: Version2ReleaseReceipt,
) -> None:
    """Write one receipt without replacing any existing release evidence."""

    if not isinstance(receipt, Version2ReleaseReceipt):
        raise TypeError("receipt must be Version2ReleaseReceipt")
    path = Path(output_path)
    if path.name in {"", ".", ".."}:
        raise Version2ReleaseReceiptError("output_path must name a file")
    try:
        with path.open("x", encoding="utf-8", newline="\n") as handle:
            handle.write(receipt.to_json())
    except FileExistsError as exc:
        raise Version2ReleaseReceiptError(
            "release receipt already exists; overwrite is forbidden"
        ) from exc


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Validate a Version 2 package ZIP and write an attributable release receipt."
    )
    parser.add_argument("--package", required=True)
    parser.add_argument("--expected-integration-sha", required=True)
    parser.add_argument("--workflow-run-id", required=True, type=int)
    parser.add_argument("--qualification-head-sha", required=True)
    parser.add_argument("--artifact-id", required=True, type=int)
    parser.add_argument("--artifact-name", required=True)
    parser.add_argument("--output", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    receipt = build_version2_release_receipt(
        args.package,
        expected_integration_sha=args.expected_integration_sha,
        workflow_run_id=args.workflow_run_id,
        qualification_head_sha=args.qualification_head_sha,
        artifact_id=args.artifact_id,
        artifact_name=args.artifact_name,
    )
    write_version2_release_receipt(args.output, receipt)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
