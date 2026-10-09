from __future__ import annotations

"""Finalize the owner one-click machine receipt with exact provenance.

The package builder emits a receipt for the immutable ZIP it created.  The
owner finalizer later proves the root launcher starts and rechecks the live
release apex.  This module joins those already-proven facts into one bounded,
strict, deterministic receipt immediately before artifact publication.

It does not claim human or NVDA acceptance.  Both flags must remain false.
"""

import argparse
import json
import os
from pathlib import Path
import re
import sys
import tempfile

from acs.version2_portable_package import (
    Version2PortablePackageError,
    _complete_file_identity,
    _same_file_snapshot,
    _stable_bytes,
    _stable_digest,
    _sync_published_zip_namespace,
)
from scripts.build_user_sound_pack import EXPECTED_SOURCE_INVENTORY_SHA256


MAX_RECEIPT_BYTES = 64 * 1024
MAX_FINAL_ZIP_BYTES = 2 * 1024 * 1024 * 1024
HEX40 = re.compile(r"^[0-9a-f]{40}$")
HEX64 = re.compile(r"^[0-9a-f]{64}$")

BASE_RECEIPT_KEYS = {
    "package_root",
    "archive_path",
    "archive_sha256",
    "integration_sha",
    "document_sha256",
    "sound_archive_sha256",
    "sound_inventory_sha256",
    "package_checksum_sha256",
    "sound_wav_count",
    "seed_source_count",
    "seed_game_count",
    "human_tested",
    "nvda_verified",
    "result",
}

FINAL_RECEIPT_KEYS = BASE_RECEIPT_KEYS | {
    "receipt_schema_version",
    "finalizer_product_sha",
    "finalizer_workflow_sha",
    "source_w4_product_sha",
    "source_w4_workflow_sha",
    "source_w4_run_id",
    "source_w4_run_attempt",
    "source_w4_workflow_id",
    "source_w4_candidate_sha256",
    "owner_seed_archive_sha256",
    "machine_root_launch_verified",
    "pre_upload_release_freshness",
    "finalizer_run_id",
    "finalizer_run_attempt",
}


class OwnerFinalReceiptError(RuntimeError):
    pass


def _fail(message: str) -> None:
    raise OwnerFinalReceiptError(message)


def _sha(value: object, *, bits: int, label: str) -> str:
    if type(value) is not str:
        _fail(f"{label} must be exact lowercase SHA-{bits}")
    normalized = value.strip().casefold()
    pattern = HEX40 if bits == 160 else HEX64
    if value != normalized or pattern.fullmatch(normalized) is None:
        _fail(f"{label} must be exact lowercase SHA-{bits}")
    return normalized


def _positive_int(value: object, *, label: str) -> int:
    if type(value) is not int or value <= 0:
        _fail(f"{label} must be a positive integer")
    return value


def _strict_json_object(path: Path) -> dict[str, object]:
    def unique_pairs(items):
        result: dict[str, object] = {}
        for key, value in items:
            if key in result:
                _fail("owner final receipt contains duplicate keys")
            result[key] = value
        return result

    try:
        payload = _stable_bytes(
            path,
            label="owner final receipt",
            maximum=MAX_RECEIPT_BYTES,
        )
        value = json.loads(
            payload.decode("utf-8-sig", errors="strict"),
            object_pairs_hook=unique_pairs,
        )
    except OwnerFinalReceiptError:
        raise
    except Version2PortablePackageError as exc:
        raise OwnerFinalReceiptError("owner final receipt cannot be read stably") from exc
    except (UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError) as exc:
        raise OwnerFinalReceiptError("owner final receipt is invalid JSON") from exc
    if not isinstance(value, dict):
        _fail("owner final receipt must be an object")
    return value


def _final_provenance(
    *,
    product_sha: str,
    w4_workflow_sha: str,
    w4_run_id: int,
    w4_run_attempt: int,
    w4_workflow_id: int,
    w4_candidate_sha: str,
    seed_sha: str,
    run_id: int,
    run_attempt: int,
) -> dict[str, object]:
    return {
        "receipt_schema_version": 1,
        "finalizer_product_sha": product_sha,
        "finalizer_workflow_sha": product_sha,
        "source_w4_product_sha": product_sha,
        "source_w4_workflow_sha": w4_workflow_sha,
        "source_w4_run_id": w4_run_id,
        "source_w4_run_attempt": w4_run_attempt,
        "source_w4_workflow_id": w4_workflow_id,
        "source_w4_candidate_sha256": w4_candidate_sha,
        "owner_seed_archive_sha256": seed_sha,
        "machine_root_launch_verified": True,
        "pre_upload_release_freshness": True,
        "finalizer_run_id": run_id,
        "finalizer_run_attempt": run_attempt,
    }


def _validate_final_provenance(
    value: dict[str, object],
    expected: dict[str, object],
) -> None:
    for key, expected_value in expected.items():
        actual = value.get(key)
        if type(actual) is not type(expected_value) or actual != expected_value:
            _fail(f"owner final receipt finalized provenance mismatch: {key}")


def _canonical_receipt_bytes(value: dict[str, object]) -> bytes:
    try:
        return (
            json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            + "\n"
        ).encode("utf-8")
    except (TypeError, ValueError, UnicodeEncodeError, RecursionError) as exc:
        raise OwnerFinalReceiptError(
            "finalized owner receipt cannot be serialized canonically"
        ) from exc


def _remove_owned_staging_file(
    path: Path,
    expected_identity: os.stat_result,
) -> None:
    """Remove only the exact private staging object created by this invocation."""

    try:
        current = path.lstat()
    except OSError:
        return
    if not _complete_file_identity(expected_identity, current):
        return
    try:
        path.unlink()
    except OSError:
        return


def _confirm_final_receipt_durable(
    receipt: Path,
    expected_value: dict[str, object],
) -> None:
    """Confirm one canonical finalized receipt is crash-durable and unchanged."""

    try:
        before = receipt.lstat()
    except OSError as exc:
        raise OwnerFinalReceiptError(
            "owner final receipt publication cannot be inspected"
        ) from exc
    try:
        durable = _sync_published_zip_namespace(receipt, expected=before)
    except Version2PortablePackageError as exc:
        raise OwnerFinalReceiptError(
            "owner final receipt publication durability could not be confirmed"
        ) from exc
    try:
        payload = _stable_bytes(
            receipt,
            label="owner final receipt publication",
            maximum=MAX_RECEIPT_BYTES,
        )
    except Version2PortablePackageError as exc:
        raise OwnerFinalReceiptError(
            "owner final receipt publication cannot be read back stably"
        ) from exc
    try:
        after = receipt.lstat()
    except OSError as exc:
        raise OwnerFinalReceiptError(
            "owner final receipt publication cannot be revalidated"
        ) from exc
    if not _same_file_snapshot(durable, after):
        _fail("owner final receipt changed during publication readback")
    canonical = _canonical_receipt_bytes(expected_value)
    if len(canonical) > MAX_RECEIPT_BYTES:
        _fail("finalized owner receipt exceeds its byte budget")
    if payload != canonical:
        _fail("published owner final receipt does not match finalized provenance")


def finalize_owner_final_receipt(
    receipt_path: str | Path,
    final_zip_path: str | Path,
    *,
    expected_product_sha: str,
    expected_w4_candidate_sha256: str,
    expected_seed_archive_sha256: str,
    expected_document_sha256: tuple[str, str],
    expected_sound_archive_sha256: str,
    source_w4_run_id: int,
    source_w4_run_attempt: int,
    source_w4_workflow_id: int,
    source_w4_workflow_sha: str,
    finalizer_run_id: int,
    finalizer_run_attempt: int,
) -> dict[str, object]:
    receipt = Path(receipt_path)
    final_zip = Path(final_zip_path)
    product_sha = _sha(expected_product_sha, bits=160, label="product SHA")
    w4_candidate_sha = _sha(
        expected_w4_candidate_sha256,
        bits=256,
        label="W4 candidate SHA-256",
    )
    seed_sha = _sha(
        expected_seed_archive_sha256,
        bits=256,
        label="owner seed archive SHA-256",
    )
    if type(expected_document_sha256) is not tuple or len(expected_document_sha256) != 2:
        raise TypeError("expected_document_sha256 must be an exact two-item tuple")
    document_sha = tuple(
        _sha(value, bits=256, label=f"owner document {index + 1} SHA-256")
        for index, value in enumerate(expected_document_sha256)
    )
    sound_sha = _sha(
        expected_sound_archive_sha256,
        bits=256,
        label="owner sound archive SHA-256",
    )
    w4_workflow_sha = _sha(
        source_w4_workflow_sha,
        bits=160,
        label="W4 workflow SHA",
    )
    if w4_workflow_sha != product_sha:
        _fail("W4 workflow SHA is not the exact owner release product SHA")

    w4_run_id = _positive_int(source_w4_run_id, label="W4 run id")
    w4_run_attempt = _positive_int(source_w4_run_attempt, label="W4 run attempt")
    w4_workflow_id = _positive_int(source_w4_workflow_id, label="W4 workflow id")
    run_id = _positive_int(finalizer_run_id, label="finalizer run id")
    run_attempt = _positive_int(finalizer_run_attempt, label="finalizer run attempt")

    value = _strict_json_object(receipt)
    keys = set(value)
    already_finalized = keys == FINAL_RECEIPT_KEYS
    if keys != BASE_RECEIPT_KEYS and not already_finalized:
        missing_base = sorted(BASE_RECEIPT_KEYS - keys)
        unexpected_base = sorted(keys - BASE_RECEIPT_KEYS)
        missing_final = sorted(FINAL_RECEIPT_KEYS - keys)
        unexpected_final = sorted(keys - FINAL_RECEIPT_KEYS)
        _fail(
            "owner final receipt key set mismatch; "
            f"base_missing={missing_base} base_unexpected={unexpected_base} "
            f"final_missing={missing_final} final_unexpected={unexpected_final}"
        )
    if value.get("package_root") != "owner-oneclick":
        _fail("owner final receipt package root mismatch")
    if value.get("integration_sha") != product_sha:
        _fail("owner final receipt product SHA mismatch")
    if value.get("archive_path") != str(final_zip):
        _fail("owner final receipt archive path mismatch")
    if value.get("document_sha256") != [document_sha[0], document_sha[1]]:
        _fail("owner final receipt document SHA-256 mismatch")
    if value.get("sound_archive_sha256") != sound_sha:
        _fail("owner final receipt sound archive SHA-256 mismatch")
    if value.get("sound_inventory_sha256") != EXPECTED_SOURCE_INVENTORY_SHA256:
        _fail("owner final receipt sound inventory SHA-256 mismatch")
    _sha(value.get("package_checksum_sha256"), bits=256, label="package checksum SHA-256")

    if (
        type(value.get("sound_wav_count")) is not int
        or value.get("sound_wav_count") != 330
        or type(value.get("seed_source_count")) is not int
        or value.get("seed_source_count") != 6
        or type(value.get("seed_game_count")) is not int
        or value.get("seed_game_count") != 3738
    ):
        _fail("owner final receipt content counts are invalid")
    if (
        value.get("human_tested") is not False
        or value.get("nvda_verified") is not False
        or value.get("result") != "PASS"
    ):
        _fail("owner final receipt machine acceptance flags are invalid")

    declared_archive_sha = _sha(
        value.get("archive_sha256"),
        bits=256,
        label="owner final ZIP SHA-256",
    )
    try:
        actual_archive_sha = _stable_digest(
            final_zip,
            label="owner final ZIP",
            maximum=MAX_FINAL_ZIP_BYTES,
        )
    except Version2PortablePackageError as exc:
        raise OwnerFinalReceiptError("owner final ZIP cannot be hashed stably") from exc
    if actual_archive_sha != declared_archive_sha:
        _fail("owner final ZIP does not match the package-builder receipt")

    expected_provenance = _final_provenance(
        product_sha=product_sha,
        w4_workflow_sha=w4_workflow_sha,
        w4_run_id=w4_run_id,
        w4_run_attempt=w4_run_attempt,
        w4_workflow_id=w4_workflow_id,
        w4_candidate_sha=w4_candidate_sha,
        seed_sha=seed_sha,
        run_id=run_id,
        run_attempt=run_attempt,
    )
    if already_finalized:
        _validate_final_provenance(value, expected_provenance)
        _confirm_final_receipt_durable(receipt, value)
        return value

    value.update(expected_provenance)
    serialized_bytes = _canonical_receipt_bytes(value)
    if len(serialized_bytes) > MAX_RECEIPT_BYTES:
        _fail("finalized owner receipt exceeds its byte budget")
    serialized = serialized_bytes.decode("utf-8")

    temporary: Path | None = None
    staging_identity: os.stat_result | None = None
    fd: int | None = None
    try:
        try:
            fd, temporary_name = tempfile.mkstemp(
                prefix=f".{receipt.name}.publish-",
                suffix=".tmp",
                dir=receipt.parent,
            )
            temporary = Path(temporary_name)
            staging_identity = os.fstat(fd)
        except OSError as exc:
            raise OwnerFinalReceiptError(
                "owner final receipt staging file could not be created"
            ) from exc

        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
            fd = None
            stream.write(serialized)
            stream.flush()
            os.fsync(stream.fileno())
            staged = os.fstat(stream.fileno())

        try:
            staged_path = temporary.lstat()
        except OSError as exc:
            raise OwnerFinalReceiptError(
                "owner final receipt staging pathname cannot be inspected"
            ) from exc
        if not _same_file_snapshot(staged, staged_path):
            _fail("owner final receipt staging pathname changed before publication")

        os.replace(temporary, receipt)
    except OwnerFinalReceiptError:
        raise
    except OSError as exc:
        raise OwnerFinalReceiptError("owner final receipt could not be published") from exc
    finally:
        if fd is not None:
            try:
                os.close(fd)
            except OSError:
                pass
        if temporary is not None and staging_identity is not None:
            _remove_owned_staging_file(temporary, staging_identity)

    _confirm_final_receipt_durable(receipt, value)
    return value


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Finalize exact owner one-click provenance receipt"
    )
    parser.add_argument("--receipt", required=True, type=Path)
    parser.add_argument("--final-zip", required=True, type=Path)
    parser.add_argument("--product-sha", required=True)
    parser.add_argument("--w4-candidate-sha256", required=True)
    parser.add_argument("--seed-archive-sha256", required=True)
    parser.add_argument("--first-docx-sha256", required=True)
    parser.add_argument("--second-docx-sha256", required=True)
    parser.add_argument("--sound-archive-sha256", required=True)
    parser.add_argument("--w4-run-id", required=True, type=int)
    parser.add_argument("--w4-run-attempt", required=True, type=int)
    parser.add_argument("--w4-workflow-id", required=True, type=int)
    parser.add_argument("--w4-workflow-sha", required=True)
    parser.add_argument("--finalizer-run-id", required=True, type=int)
    parser.add_argument("--finalizer-run-attempt", required=True, type=int)
    args = parser.parse_args(argv)
    try:
        value = finalize_owner_final_receipt(
            args.receipt,
            args.final_zip,
            expected_product_sha=args.product_sha,
            expected_w4_candidate_sha256=args.w4_candidate_sha256,
            expected_seed_archive_sha256=args.seed_archive_sha256,
            expected_document_sha256=(
                args.first_docx_sha256,
                args.second_docx_sha256,
            ),
            expected_sound_archive_sha256=args.sound_archive_sha256,
            source_w4_run_id=args.w4_run_id,
            source_w4_run_attempt=args.w4_run_attempt,
            source_w4_workflow_id=args.w4_workflow_id,
            source_w4_workflow_sha=args.w4_workflow_sha,
            finalizer_run_id=args.finalizer_run_id,
            finalizer_run_attempt=args.finalizer_run_attempt,
        )
    except (OwnerFinalReceiptError, TypeError) as exc:
        print(f"OWNER FINAL RECEIPT FAIL: {exc}", file=sys.stderr)
        return 1
    print(f"OWNER_FINAL_ZIP_SHA256={value['archive_sha256']}")
    print(f"OWNER_FINAL_SOURCE_W4_RUN_ID={value['source_w4_run_id']}")
    print("OWNER_FINAL_RECEIPT_PROVENANCE=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "BASE_RECEIPT_KEYS",
    "FINAL_RECEIPT_KEYS",
    "MAX_FINAL_ZIP_BYTES",
    "MAX_RECEIPT_BYTES",
    "OwnerFinalReceiptError",
    "finalize_owner_final_receipt",
]
