from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from scripts.record_owner_physical_acceptance import (
    OwnerPhysicalAcceptanceError,
    REQUIRED_SCENARIOS,
    main,
    record_owner_physical_acceptance,
    verify_owner_physical_acceptance,
)


PRODUCT_SHA = "a" * 40
W4_CANDIDATE_SHA = "b" * 64
SEED_SHA = "c" * 64
FIRST_DOC_SHA = "d" * 64
SECOND_DOC_SHA = "e" * 64
SOUND_SHA = "f" * 64
SOUND_INVENTORY_SHA = "1" * 64
PACKAGE_CHECKSUM_SHA = "2" * 64


def _scenarios(status: str = "PASS") -> dict[str, str]:
    return {name: status for name in REQUIRED_SCENARIOS}


def _machine_receipt(final_zip: Path, **overrides: object) -> dict[str, object]:
    value: dict[str, object] = {
        "package_root": "owner-oneclick",
        "archive_path": str(final_zip),
        "archive_sha256": hashlib.sha256(final_zip.read_bytes()).hexdigest(),
        "integration_sha": PRODUCT_SHA,
        "document_sha256": [FIRST_DOC_SHA, SECOND_DOC_SHA],
        "sound_archive_sha256": SOUND_SHA,
        "sound_inventory_sha256": SOUND_INVENTORY_SHA,
        "package_checksum_sha256": PACKAGE_CHECKSUM_SHA,
        "sound_wav_count": 330,
        "seed_source_count": 6,
        "seed_game_count": 3738,
        "human_tested": False,
        "nvda_verified": False,
        "result": "PASS",
        "receipt_schema_version": 1,
        "finalizer_product_sha": PRODUCT_SHA,
        "finalizer_workflow_sha": PRODUCT_SHA,
        "source_w4_product_sha": PRODUCT_SHA,
        "source_w4_workflow_sha": PRODUCT_SHA,
        "source_w4_run_id": 37174317097,
        "source_w4_run_attempt": 2,
        "source_w4_workflow_id": 123456789,
        "source_w4_candidate_sha256": W4_CANDIDATE_SHA,
        "owner_seed_archive_sha256": SEED_SHA,
        "machine_root_launch_verified": True,
        "pre_upload_release_freshness": True,
        "finalizer_run_id": 37180000000,
        "finalizer_run_attempt": 1,
    }
    value.update(overrides)
    return value


def _write_machine_receipt(path: Path, value: dict[str, object]) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )


def _record(
    machine_receipt: Path,
    final_zip: Path,
    output: Path,
    scenarios: dict[str, str],
):
    with mock.patch.dict(os.environ, {"GITHUB_ACTIONS": "", "CI": ""}, clear=False):
        return record_owner_physical_acceptance(
            machine_receipt,
            final_zip,
            output,
            observed_at_utc="2026-10-05T19:15:00Z",
            scenario_results=scenarios,
        )


class OwnerPhysicalAcceptanceTests(unittest.TestCase):
    def test_all_required_physical_scenarios_pass_for_exact_bytes(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            final_zip = root / "Accessible-Chess-ONECLICK-OWNER-FINAL.zip"
            final_zip.write_bytes(b"exact-owner-final-bytes")
            machine = root / "owner-final-receipt.json"
            _write_machine_receipt(machine, _machine_receipt(final_zip))
            output = root / "owner-physical-acceptance.json"

            value = _record(machine, final_zip, output, _scenarios())

            self.assertEqual(value["result"], "PASS")
            self.assertIs(value["human_tested"], True)
            self.assertIs(value["nvda_verified"], True)
            self.assertEqual(
                value["final_zip_sha256"],
                hashlib.sha256(final_zip.read_bytes()).hexdigest(),
            )
            self.assertEqual(
                value["machine_receipt_sha256"],
                hashlib.sha256(machine.read_bytes()).hexdigest(),
            )
            self.assertEqual(value["product_sha"], PRODUCT_SHA)
            self.assertEqual(value["machine_finalizer_run_id"], 37180000000)
            self.assertEqual(
                verify_owner_physical_acceptance(output, machine, final_zip),
                value,
            )

    def test_real_failure_is_durable_human_tested_rejection_not_nvda_success(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            final_zip = root / "final.zip"
            final_zip.write_bytes(b"zip")
            machine = root / "machine.json"
            _write_machine_receipt(machine, _machine_receipt(final_zip))
            output = root / "physical.json"
            scenarios = _scenarios()
            scenarios["one_click_launch"] = "FAIL"

            value = _record(machine, final_zip, output, scenarios)

            self.assertEqual(value["result"], "FAIL")
            self.assertIs(value["human_tested"], True)
            self.assertIs(value["nvda_verified"], False)
            self.assertEqual(
                json.loads(output.read_text(encoding="utf-8"))["scenario_results"][
                    "one_click_launch"
                ],
                "FAIL",
            )

    def test_partial_manual_run_is_incomplete_not_verified(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            final_zip = root / "final.zip"
            final_zip.write_bytes(b"zip")
            machine = root / "machine.json"
            _write_machine_receipt(machine, _machine_receipt(final_zip))
            output = root / "physical.json"
            scenarios = _scenarios()
            scenarios["restart_recovery"] = "NOT_TESTED"

            value = _record(machine, final_zip, output, scenarios)

            self.assertEqual(value["result"], "INCOMPLETE")
            self.assertIs(value["human_tested"], True)
            self.assertIs(value["nvda_verified"], False)

    def test_all_not_tested_does_not_claim_human_testing(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            final_zip = root / "final.zip"
            final_zip.write_bytes(b"zip")
            machine = root / "machine.json"
            _write_machine_receipt(machine, _machine_receipt(final_zip))
            output = root / "physical.json"

            value = _record(machine, final_zip, output, _scenarios("NOT_TESTED"))

            self.assertEqual(value["result"], "INCOMPLETE")
            self.assertIs(value["human_tested"], False)
            self.assertIs(value["nvda_verified"], False)

    def test_recording_is_disabled_under_github_actions_and_generic_ci(self) -> None:
        for env in (
            {"GITHUB_ACTIONS": "true", "CI": ""},
            {"GITHUB_ACTIONS": "", "CI": "true"},
        ):
            with self.subTest(env=env), tempfile.TemporaryDirectory() as raw:
                root = Path(raw)
                final_zip = root / "final.zip"
                final_zip.write_bytes(b"zip")
                machine = root / "machine.json"
                _write_machine_receipt(machine, _machine_receipt(final_zip))
                output = root / "physical.json"
                with mock.patch.dict(os.environ, env, clear=False):
                    with self.assertRaisesRegex(
                        OwnerPhysicalAcceptanceError,
                        "disabled in automation",
                    ):
                        record_owner_physical_acceptance(
                            machine,
                            final_zip,
                            output,
                            observed_at_utc="2026-10-05T19:15:00Z",
                            scenario_results=_scenarios(),
                        )
                self.assertFalse(output.exists())

    def test_rejects_machine_receipt_that_claims_human_or_nvda_success(self) -> None:
        for overrides in (
            {"human_tested": True},
            {"nvda_verified": True},
            {"result": "FAIL"},
            {"machine_root_launch_verified": False},
            {"pre_upload_release_freshness": False},
        ):
            with self.subTest(overrides=overrides), tempfile.TemporaryDirectory() as raw:
                root = Path(raw)
                final_zip = root / "final.zip"
                final_zip.write_bytes(b"zip")
                machine = root / "machine.json"
                _write_machine_receipt(machine, _machine_receipt(final_zip, **overrides))
                with self.assertRaisesRegex(
                    OwnerPhysicalAcceptanceError,
                    "machine-only",
                ):
                    _record(
                        machine,
                        final_zip,
                        root / "physical.json",
                        _scenarios(),
                    )

    def test_rejects_noncanonical_or_duplicate_machine_receipt(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            final_zip = root / "final.zip"
            final_zip.write_bytes(b"zip")
            machine = root / "machine.json"
            value = _machine_receipt(final_zip)
            machine.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")
            with self.assertRaisesRegex(
                OwnerPhysicalAcceptanceError,
                "not exact canonical JSON",
            ):
                _record(machine, final_zip, root / "physical.json", _scenarios())

        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            final_zip = root / "final.zip"
            final_zip.write_bytes(b"zip")
            machine = root / "machine.json"
            value = _machine_receipt(final_zip)
            canonical = json.dumps(
                value,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
            machine.write_text(
                canonical[:-1] + ',"result":"PASS"}\n',
                encoding="utf-8",
            )
            with self.assertRaisesRegex(
                OwnerPhysicalAcceptanceError,
                "duplicate keys",
            ):
                _record(machine, final_zip, root / "physical.json", _scenarios())

    def test_rejects_final_zip_tamper_after_machine_receipt(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            final_zip = root / "final.zip"
            final_zip.write_bytes(b"qualified bytes")
            machine = root / "machine.json"
            _write_machine_receipt(machine, _machine_receipt(final_zip))
            final_zip.write_bytes(b"changed bytes")
            with self.assertRaisesRegex(
                OwnerPhysicalAcceptanceError,
                "does not match",
            ):
                _record(machine, final_zip, root / "physical.json", _scenarios())

    def test_record_is_exclusive_and_existing_evidence_is_not_overwritten(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            final_zip = root / "final.zip"
            final_zip.write_bytes(b"zip")
            machine = root / "machine.json"
            _write_machine_receipt(machine, _machine_receipt(final_zip))
            output = root / "physical.json"
            output.write_bytes(b"existing evidence")
            with self.assertRaisesRegex(
                OwnerPhysicalAcceptanceError,
                "already exists",
            ):
                _record(machine, final_zip, output, _scenarios())
            self.assertEqual(output.read_bytes(), b"existing evidence")

    def test_verifier_detects_semantic_acceptance_tamper(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            final_zip = root / "final.zip"
            final_zip.write_bytes(b"zip")
            machine = root / "machine.json"
            _write_machine_receipt(machine, _machine_receipt(final_zip))
            output = root / "physical.json"
            value = _record(machine, final_zip, output, _scenarios())
            value["nvda_verified"] = False
            output.write_text(
                json.dumps(
                    value,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                )
                + "\n",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(
                OwnerPhysicalAcceptanceError,
                "derived acceptance state",
            ):
                verify_owner_physical_acceptance(output, machine, final_zip)

    def test_cli_verify_is_safe_in_automation(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            final_zip = root / "final.zip"
            final_zip.write_bytes(b"zip")
            machine = root / "machine.json"
            _write_machine_receipt(machine, _machine_receipt(final_zip))
            output = root / "physical.json"
            _record(machine, final_zip, output, _scenarios())

            with mock.patch.dict(
                os.environ,
                {"GITHUB_ACTIONS": "true", "CI": "true"},
                clear=False,
            ):
                result = main(
                    [
                        "verify",
                        "--record",
                        str(output),
                        "--machine-receipt",
                        str(machine),
                        "--final-zip",
                        str(final_zip),
                    ]
                )
            self.assertEqual(result, 0)


if __name__ == "__main__":
    unittest.main()
