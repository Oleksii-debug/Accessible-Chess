from __future__ import annotations

"""Record physical owner acceptance without promoting machine evidence to human proof.

The owner-final machine receipt deliberately keeps human_tested/nvda_verified false.
This module is a separate, manual evidence layer. It binds one physical Windows/NVDA
observation record to the exact final ZIP bytes and the exact finalized machine receipt.

Recording is disabled in common CI environments. Verification remains automatable.
The record is an observation, not cryptographic proof of who performed the test.
"""

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import sys

from acs.version2_portable_package import (
    Version2PortablePackageError,
    _stable_bytes,
    _stable_digest,
)
from scripts.finalize_owner_final_receipt import (
    BASE_RECEIPT_KEYS,
    MAX_FINAL_ZIP_BYTES,
    MAX_RECEIPT_BYTES,
)


MAX_ACCEPTANCE_BYTES = 64 * 1024
HEX40 = re.compile(r"^[0-9a-f]{40}$")
HEX64 = re.compile(r"^[0-9a-f]{64}$")
UTC_TIMESTAMP = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")

REQUIRED_SCENARIOS = (
    "one_click_launch",
    "nvda_keyboard_navigation",
    "semantic_document_copy",
    "hotkey_result_feedback",
    "chess_sounds",
    "starter_content_offline",
    "restart_recovery",
)
SCENARIO_STATUSES = frozenset({"PASS", "FAIL", "NOT_TESTED"})

FINAL_MACHINE_RECEIPT_KEYS = BASE_RECEIPT_KEYS | {
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

ACCEPTANCE_RECORD_KEYS = {
    "schema_version",
    "observation_mode",
    "observed_at_utc",
    "machine_receipt_sha256",
    "final_zip_sha256",
    "product_sha",
    "machine_finalizer_run_id",
    "machine_finalizer_run_attempt",
    "scenario_results",
    "human_tested",
    "nvda_verified",
    "result",
}


class OwnerPhysicalAcceptanceError(RuntimeError):
    pass


def _fail(message: str) -> None:
    raise OwnerPhysicalAcceptanceError(message)


def _sha(value: object, *, bits: int, label: str) -> str:
    pattern = HEX40 if bits == 160 else HEX64
    if type(value) is not str or pattern.fullmatch(value) is None:
        _fail(f"{label} must be exact lowercase SHA-{bits}")
    return value


def _positive_int(value: object, *, label: str) -> int:
    if type(value) is not int or value <= 0:
        _fail(f"{label} must be a positive integer")
    return value


def _canonical_object_from_bytes(
    payload: bytes,
    *,
    label: str,
    expected_keys: set[str],
) -> dict[str, object]:
    def unique_pairs(items):
        result: dict[str, object] = {}
        for key, value in items:
            if key in result:
                _fail(f"{label} contains duplicate keys")
            result[key] = value
        return result

    try:
        value = json.loads(
            payload.decode("utf-8", errors="strict"),
            object_pairs_hook=unique_pairs,
        )
    except OwnerPhysicalAcceptanceError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError) as exc:
        raise OwnerPhysicalAcceptanceError(f"{label} is invalid canonical JSON") from exc
    if not isinstance(value, dict):
        _fail(f"{label} must be an object")
    if set(value) != expected_keys:
        missing = sorted(expected_keys - set(value))
        unexpected = sorted(set(value) - expected_keys)
        _fail(f"{label} key set mismatch; missing={missing} unexpected={unexpected}")
    canonical = (
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
    ).encode("utf-8")
    if payload != canonical:
        _fail(f"{label} is not exact canonical JSON")
    return value


def _read_stable_json(
    path: Path,
    *,
    label: str,
    maximum: int,
    expected_keys: set[str],
) -> tuple[bytes, dict[str, object]]:
    try:
        payload = _stable_bytes(path, label=label, maximum=maximum)
    except Version2PortablePackageError as exc:
        raise OwnerPhysicalAcceptanceError(f"{label} cannot be read stably") from exc
    return payload, _canonical_object_from_bytes(
        payload,
        label=label,
        expected_keys=expected_keys,
    )


def _validate_timestamp(value: object) -> str:
    if type(value) is not str or UTC_TIMESTAMP.fullmatch(value) is None:
        _fail("observed_at_utc must be exact YYYY-MM-DDTHH:MM:SSZ")
    try:
        parsed = datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(
            tzinfo=timezone.utc
        )
    except ValueError as exc:
        raise OwnerPhysicalAcceptanceError(
            "observed_at_utc is not a valid UTC timestamp"
        ) from exc
    if parsed.strftime("%Y-%m-%dT%H:%M:%SZ") != value:
        _fail("observed_at_utc is not canonical UTC")
    return value


def _validate_scenarios(value: object) -> dict[str, str]:
    if not isinstance(value, dict) or set(value) != set(REQUIRED_SCENARIOS):
        _fail("scenario_results must contain every required physical scenario exactly once")
    normalized: dict[str, str] = {}
    for name in REQUIRED_SCENARIOS:
        status = value.get(name)
        if type(status) is not str or status not in SCENARIO_STATUSES:
            _fail(f"scenario {name} must be PASS, FAIL, or NOT_TESTED")
        normalized[name] = status
    return normalized


def _derived_result(scenarios: dict[str, str]) -> tuple[bool, bool, str]:
    statuses = tuple(scenarios[name] for name in REQUIRED_SCENARIOS)
    human_tested = any(status != "NOT_TESTED" for status in statuses)
    all_pass = all(status == "PASS" for status in statuses)
    if all_pass:
        return human_tested, True, "PASS"
    if any(status == "FAIL" for status in statuses):
        return human_tested, False, "FAIL"
    return human_tested, False, "INCOMPLETE"


def _validate_machine_receipt(value: dict[str, object]) -> tuple[str, str, int, int]:
    if type(value.get("receipt_schema_version")) is not int or value.get(
        "receipt_schema_version"
    ) != 1:
        _fail("machine receipt schema version is invalid")
    if (
        value.get("package_root") != "owner-oneclick"
        or value.get("result") != "PASS"
        or value.get("human_tested") is not False
        or value.get("nvda_verified") is not False
        or value.get("machine_root_launch_verified") is not True
        or value.get("pre_upload_release_freshness") is not True
    ):
        _fail("machine receipt is not a successful machine-only owner-final receipt")

    product_sha = _sha(value.get("integration_sha"), bits=160, label="product SHA")
    for key in (
        "finalizer_product_sha",
        "finalizer_workflow_sha",
        "source_w4_product_sha",
        "source_w4_workflow_sha",
    ):
        if _sha(value.get(key), bits=160, label=key) != product_sha:
            _fail(f"machine receipt {key} does not match product SHA")

    archive_sha = _sha(
        value.get("archive_sha256"),
        bits=256,
        label="final ZIP SHA-256",
    )
    for key in (
        "package_checksum_sha256",
        "sound_archive_sha256",
        "sound_inventory_sha256",
        "source_w4_candidate_sha256",
        "owner_seed_archive_sha256",
    ):
        _sha(value.get(key), bits=256, label=key)
    documents = value.get("document_sha256")
    if (
        not isinstance(documents, list)
        or len(documents) != 2
        or any(type(item) is not str or HEX64.fullmatch(item) is None for item in documents)
    ):
        _fail("machine receipt document SHA-256 values are invalid")
    if (
        type(value.get("sound_wav_count")) is not int
        or value.get("sound_wav_count") != 330
        or type(value.get("seed_source_count")) is not int
        or value.get("seed_source_count") != 6
        or type(value.get("seed_game_count")) is not int
        or value.get("seed_game_count") != 3738
    ):
        _fail("machine receipt owner content counts are invalid")
    for key in (
        "source_w4_run_id",
        "source_w4_run_attempt",
        "source_w4_workflow_id",
        "finalizer_run_id",
        "finalizer_run_attempt",
    ):
        _positive_int(value.get(key), label=key)
    return (
        product_sha,
        archive_sha,
        int(value["finalizer_run_id"]),
        int(value["finalizer_run_attempt"]),
    )


def _manual_recording_allowed() -> None:
    for name in ("GITHUB_ACTIONS", "CI"):
        value = os.environ.get(name, "").strip().casefold()
        if value in {"1", "true", "yes", "on"}:
            _fail(
                "physical acceptance recording is disabled in automation; "
                "only verification may run there"
            )


def _final_zip_sha(path: Path) -> str:
    try:
        return _stable_digest(
            path,
            label="physical-acceptance final ZIP",
            maximum=MAX_FINAL_ZIP_BYTES,
        )
    except Version2PortablePackageError as exc:
        raise OwnerPhysicalAcceptanceError(
            "physical-acceptance final ZIP cannot be hashed stably"
        ) from exc


def _publish_exclusive(path: Path, payload: bytes) -> None:
    if path.exists():
        _fail("physical acceptance record already exists")
    temporary = path.with_name(f".{path.name}.{secrets.token_hex(8)}.tmp")
    try:
        with temporary.open("xb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.link(temporary, path)
    except FileExistsError as exc:
        raise OwnerPhysicalAcceptanceError(
            "physical acceptance record already exists"
        ) from exc
    except OSError as exc:
        raise OwnerPhysicalAcceptanceError(
            "physical acceptance record could not be published"
        ) from exc
    finally:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass


def record_owner_physical_acceptance(
    machine_receipt_path: str | Path,
    final_zip_path: str | Path,
    output_path: str | Path,
    *,
    observed_at_utc: str,
    scenario_results: dict[str, str],
) -> dict[str, object]:
    """Record one manual observation set for exact already-machine-qualified bytes."""
    _manual_recording_allowed()
    machine_receipt = Path(machine_receipt_path)
    final_zip = Path(final_zip_path)
    output = Path(output_path)

    machine_bytes, machine = _read_stable_json(
        machine_receipt,
        label="owner final machine receipt",
        maximum=MAX_RECEIPT_BYTES,
        expected_keys=FINAL_MACHINE_RECEIPT_KEYS,
    )
    product_sha, declared_zip_sha, finalizer_run_id, finalizer_run_attempt = (
        _validate_machine_receipt(machine)
    )
    actual_zip_sha = _final_zip_sha(final_zip)
    if actual_zip_sha != declared_zip_sha:
        _fail("physical acceptance ZIP does not match the owner final machine receipt")

    scenarios = _validate_scenarios(scenario_results)
    human_tested, nvda_verified, result = _derived_result(scenarios)
    observed = _validate_timestamp(observed_at_utc)

    value: dict[str, object] = {
        "schema_version": 1,
        "observation_mode": "manual_owner_physical_windows_nvda",
        "observed_at_utc": observed,
        "machine_receipt_sha256": hashlib.sha256(machine_bytes).hexdigest(),
        "final_zip_sha256": actual_zip_sha,
        "product_sha": product_sha,
        "machine_finalizer_run_id": finalizer_run_id,
        "machine_finalizer_run_attempt": finalizer_run_attempt,
        "scenario_results": scenarios,
        "human_tested": human_tested,
        "nvda_verified": nvda_verified,
        "result": result,
    }
    serialized = (
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
    ).encode("utf-8")
    if len(serialized) > MAX_ACCEPTANCE_BYTES:
        _fail("physical acceptance record exceeds its byte budget")
    _publish_exclusive(output, serialized)
    verify_owner_physical_acceptance(output, machine_receipt, final_zip)
    return value


def verify_owner_physical_acceptance(
    record_path: str | Path,
    machine_receipt_path: str | Path,
    final_zip_path: str | Path,
) -> dict[str, object]:
    """Verify byte binding and deterministic semantics of a manual acceptance record."""
    record = Path(record_path)
    machine_receipt = Path(machine_receipt_path)
    final_zip = Path(final_zip_path)

    _, value = _read_stable_json(
        record,
        label="owner physical acceptance record",
        maximum=MAX_ACCEPTANCE_BYTES,
        expected_keys=ACCEPTANCE_RECORD_KEYS,
    )
    machine_bytes, machine = _read_stable_json(
        machine_receipt,
        label="owner final machine receipt",
        maximum=MAX_RECEIPT_BYTES,
        expected_keys=FINAL_MACHINE_RECEIPT_KEYS,
    )
    product_sha, declared_zip_sha, finalizer_run_id, finalizer_run_attempt = (
        _validate_machine_receipt(machine)
    )
    actual_zip_sha = _final_zip_sha(final_zip)
    if actual_zip_sha != declared_zip_sha:
        _fail("verified ZIP does not match the owner final machine receipt")

    if (
        value.get("schema_version") != 1
        or type(value.get("schema_version")) is not int
        or value.get("observation_mode") != "manual_owner_physical_windows_nvda"
    ):
        _fail("physical acceptance record schema or observation mode is invalid")
    _validate_timestamp(value.get("observed_at_utc"))
    if value.get("machine_receipt_sha256") != hashlib.sha256(machine_bytes).hexdigest():
        _fail("physical acceptance record machine receipt digest mismatch")
    if value.get("final_zip_sha256") != actual_zip_sha:
        _fail("physical acceptance record final ZIP digest mismatch")
    if value.get("product_sha") != product_sha:
        _fail("physical acceptance record product SHA mismatch")
    if value.get("machine_finalizer_run_id") != finalizer_run_id:
        _fail("physical acceptance record finalizer run id mismatch")
    if value.get("machine_finalizer_run_attempt") != finalizer_run_attempt:
        _fail("physical acceptance record finalizer run attempt mismatch")

    scenarios = _validate_scenarios(value.get("scenario_results"))
    human_tested, nvda_verified, result = _derived_result(scenarios)
    if (
        value.get("human_tested") is not human_tested
        or value.get("nvda_verified") is not nvda_verified
        or value.get("result") != result
    ):
        _fail("physical acceptance record derived acceptance state is invalid")
    return value


def _scenario_arguments(parser: argparse.ArgumentParser) -> None:
    for name in REQUIRED_SCENARIOS:
        parser.add_argument(
            "--" + name.replace("_", "-"),
            required=True,
            choices=sorted(SCENARIO_STATUSES),
        )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Record or verify physical owner Windows/NVDA acceptance"
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    record = subparsers.add_parser(
        "record",
        help="manually record observations for exact owner-final package bytes",
    )
    record.add_argument("--machine-receipt", required=True, type=Path)
    record.add_argument("--final-zip", required=True, type=Path)
    record.add_argument("--output", required=True, type=Path)
    record.add_argument("--observed-at-utc", required=True)
    _scenario_arguments(record)

    verify = subparsers.add_parser(
        "verify",
        help="verify an existing manual observation record without promoting it",
    )
    verify.add_argument("--record", required=True, type=Path)
    verify.add_argument("--machine-receipt", required=True, type=Path)
    verify.add_argument("--final-zip", required=True, type=Path)

    args = parser.parse_args(argv)
    try:
        if args.command == "record":
            scenarios = {name: getattr(args, name) for name in REQUIRED_SCENARIOS}
            value = record_owner_physical_acceptance(
                args.machine_receipt,
                args.final_zip,
                args.output,
                observed_at_utc=args.observed_at_utc,
                scenario_results=scenarios,
            )
        else:
            value = verify_owner_physical_acceptance(
                args.record,
                args.machine_receipt,
                args.final_zip,
            )
    except (OwnerPhysicalAcceptanceError, TypeError) as exc:
        print(f"OWNER PHYSICAL ACCEPTANCE FAIL: {exc}", file=sys.stderr)
        return 1

    print(f"OWNER_PHYSICAL_ACCEPTANCE_RESULT={value['result']}")
    print(f"OWNER_PHYSICAL_ACCEPTANCE_ZIP_SHA256={value['final_zip_sha256']}")
    print(f"HUMAN_TESTED={'YES' if value['human_tested'] else 'NO'}")
    print(f"NVDA_VERIFIED={'YES' if value['nvda_verified'] else 'NO'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "ACCEPTANCE_RECORD_KEYS",
    "FINAL_MACHINE_RECEIPT_KEYS",
    "MAX_ACCEPTANCE_BYTES",
    "OwnerPhysicalAcceptanceError",
    "REQUIRED_SCENARIOS",
    "SCENARIO_STATUSES",
    "record_owner_physical_acceptance",
    "verify_owner_physical_acceptance",
]
