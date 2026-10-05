from __future__ import annotations

"""Fail-closed release receipt for an already-qualified Version 2 package.

This module does not build, mutate, sign, publish, or promote a package. It
reuses the canonical Version 2 ZIP preflight and records the identity of the
accepted bytes together with attributable GitHub Actions evidence. Receipts can
be read back and verified against the package without trusting their JSON.
"""

from dataclasses import asdict, dataclass
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import stat
from typing import Any

from .version2_package_preflight import validate_version2_package_zip


RELEASE_RECEIPT_SCHEMA_VERSION = 1
REPOSITORY_FULL_NAME = "Oleksii-debug/Accessible-Chess"
CANONICAL_W5_WORKFLOW = ".github/workflows/post-freeze-v2-windows-package-qualification.yml"
_MAX_RECEIPT_BYTES = 16 * 1024
_SHA40_RE = re.compile(r"^[0-9a-f]{40}$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_SAFE_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._ -]{0,255}$")
_MAX_ID = (1 << 63) - 1
_RECEIPT_FIELDS = frozenset(
    {
        "schema_version",
        "product",
        "repository",
        "workflow_path",
        "workflow_run_id",
        "workflow_run_attempt",
        "qualification_head_sha",
        "artifact_id",
        "artifact_name",
        "integration_sha",
        "package_sha256",
        "inventory_sha256",
        "inventory_files",
        "total_bytes",
        "checksums_verified",
    }
)


class Version2ReleaseReceiptError(ValueError):
    """Raised when qualification evidence cannot be represented safely."""


@dataclass(frozen=True)
class Version2ReleaseReceipt:
    schema_version: int
    product: str
    repository: str
    workflow_path: str
    workflow_run_id: int
    workflow_run_attempt: int
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


def _sha256(value: str, *, label: str) -> str:
    if type(value) is not str or _SHA256_RE.fullmatch(value) is None:
        raise Version2ReleaseReceiptError(
            f"{label} must be an exact lowercase SHA-256 digest"
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


def _json_object_without_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise Version2ReleaseReceiptError(
                f"release receipt contains duplicate JSON key {key!r}"
            )
        result[key] = value
    return result


def _receipt_from_mapping(payload: object) -> Version2ReleaseReceipt:
    if not isinstance(payload, dict):
        raise Version2ReleaseReceiptError("release receipt must be a JSON object")
    keys = frozenset(payload)
    if keys != _RECEIPT_FIELDS:
        missing = sorted(_RECEIPT_FIELDS - keys)
        extra = sorted(keys - _RECEIPT_FIELDS)
        raise Version2ReleaseReceiptError(
            f"release receipt schema mismatch; missing={missing!r} extra={extra!r}"
        )
    if type(payload["schema_version"]) is not int or payload["schema_version"] != RELEASE_RECEIPT_SCHEMA_VERSION:
        raise Version2ReleaseReceiptError("unsupported release receipt schema_version")
    if payload["product"] != "Accessible Chess":
        raise Version2ReleaseReceiptError("release receipt product identity mismatch")
    if payload["repository"] != REPOSITORY_FULL_NAME:
        raise Version2ReleaseReceiptError("release receipt repository identity mismatch")
    if payload["workflow_path"] != CANONICAL_W5_WORKFLOW:
        raise Version2ReleaseReceiptError("release receipt workflow identity mismatch")

    return Version2ReleaseReceipt(
        schema_version=RELEASE_RECEIPT_SCHEMA_VERSION,
        product="Accessible Chess",
        repository=REPOSITORY_FULL_NAME,
        workflow_path=CANONICAL_W5_WORKFLOW,
        workflow_run_id=_positive_id(payload["workflow_run_id"], label="workflow_run_id"),
        workflow_run_attempt=_positive_id(
            payload["workflow_run_attempt"], label="workflow_run_attempt"
        ),
        qualification_head_sha=_sha40(
            payload["qualification_head_sha"], label="qualification_head_sha"
        ),
        artifact_id=_positive_id(payload["artifact_id"], label="artifact_id"),
        artifact_name=_artifact_name(payload["artifact_name"]),
        integration_sha=_sha40(payload["integration_sha"], label="integration_sha"),
        package_sha256=_sha256(payload["package_sha256"], label="package_sha256"),
        inventory_sha256=_sha256(payload["inventory_sha256"], label="inventory_sha256"),
        inventory_files=_positive_id(payload["inventory_files"], label="inventory_files"),
        total_bytes=_positive_id(payload["total_bytes"], label="total_bytes"),
        checksums_verified=_positive_id(
            payload["checksums_verified"], label="checksums_verified"
        ),
    )


def read_version2_release_receipt(
    receipt_path: str | Path,
) -> Version2ReleaseReceipt:
    """Read one bounded, byte-canonical receipt with a strict JSON schema."""

    path = Path(receipt_path)
    try:
        with path.open("rb") as handle:
            info = os.fstat(handle.fileno())
            if not stat.S_ISREG(info.st_mode):
                raise Version2ReleaseReceiptError(
                    "release receipt must be a regular file"
                )
            if info.st_size > _MAX_RECEIPT_BYTES:
                raise Version2ReleaseReceiptError(
                    "release receipt exceeds size limit"
                )
            raw = handle.read(_MAX_RECEIPT_BYTES + 1)
    except Version2ReleaseReceiptError:
        raise
    except OSError as exc:
        raise Version2ReleaseReceiptError(
            f"release receipt is unreadable: {type(exc).__name__}"
        ) from exc
    if len(raw) > _MAX_RECEIPT_BYTES:
        raise Version2ReleaseReceiptError("release receipt exceeds size limit")
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise Version2ReleaseReceiptError("release receipt is not UTF-8") from exc
    try:
        payload = json.loads(text, object_pairs_hook=_json_object_without_duplicates)
    except Version2ReleaseReceiptError:
        raise
    except (json.JSONDecodeError, TypeError, ValueError) as exc:
        raise Version2ReleaseReceiptError("release receipt is not valid JSON") from exc
    receipt = _receipt_from_mapping(payload)
    if raw != receipt.to_json().encode("utf-8"):
        raise Version2ReleaseReceiptError(
            "release receipt bytes are not in canonical serialization"
        )
    return receipt


def build_version2_release_receipt(
    package_zip: str | Path,
    *,
    expected_integration_sha: str,
    workflow_run_id: int,
    workflow_run_attempt: int,
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
    run_attempt = _positive_id(workflow_run_attempt, label="workflow_run_attempt")
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
        repository=REPOSITORY_FULL_NAME,
        workflow_path=CANONICAL_W5_WORKFLOW,
        workflow_run_id=run_id,
        workflow_run_attempt=run_attempt,
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


def verify_version2_release_receipt(
    receipt_path: str | Path,
    package_zip: str | Path,
) -> Version2ReleaseReceipt:
    """Revalidate package bytes and require exact equality with stored evidence."""

    receipt = read_version2_release_receipt(receipt_path)
    rebuilt = build_version2_release_receipt(
        package_zip,
        expected_integration_sha=receipt.integration_sha,
        workflow_run_id=receipt.workflow_run_id,
        workflow_run_attempt=receipt.workflow_run_attempt,
        qualification_head_sha=receipt.qualification_head_sha,
        artifact_id=receipt.artifact_id,
        artifact_name=receipt.artifact_name,
    )
    if rebuilt != receipt:
        raise Version2ReleaseReceiptError(
            "release receipt does not match the revalidated package bytes"
        )
    return receipt


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
    except OSError as exc:
        raise Version2ReleaseReceiptError(
            f"release receipt could not be written: {type(exc).__name__}"
        ) from exc


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Create or verify an attributable Accessible Chess Version 2 release receipt."
    )
    commands = parser.add_subparsers(dest="command", required=True)

    create = commands.add_parser(
        "create",
        help="validate a Version 2 package ZIP and write an immutable receipt",
    )
    create.add_argument("--package", required=True)
    create.add_argument("--expected-integration-sha", required=True)
    create.add_argument("--workflow-run-id", required=True, type=int)
    create.add_argument("--workflow-run-attempt", required=True, type=int)
    create.add_argument("--qualification-head-sha", required=True)
    create.add_argument("--artifact-id", required=True, type=int)
    create.add_argument("--artifact-name", required=True)
    create.add_argument("--output", required=True)

    verify = commands.add_parser(
        "verify",
        help="revalidate package bytes against an existing immutable receipt",
    )
    verify.add_argument("--package", required=True)
    verify.add_argument("--receipt", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.command == "verify":
        verify_version2_release_receipt(args.receipt, args.package)
        return 0

    receipt = build_version2_release_receipt(
        args.package,
        expected_integration_sha=args.expected_integration_sha,
        workflow_run_id=args.workflow_run_id,
        workflow_run_attempt=args.workflow_run_attempt,
        qualification_head_sha=args.qualification_head_sha,
        artifact_id=args.artifact_id,
        artifact_name=args.artifact_name,
    )
    write_version2_release_receipt(args.output, receipt)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
