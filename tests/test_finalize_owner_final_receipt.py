from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from scripts import finalize_owner_final_receipt as finalizer_module
from scripts.build_owner_portable_candidate import OwnerPortableCandidateReport
from scripts.build_user_sound_pack import EXPECTED_SOURCE_INVENTORY_SHA256
from scripts.finalize_owner_final_receipt import (
    BASE_RECEIPT_KEYS,
    FINAL_RECEIPT_KEYS,
    OwnerFinalReceiptError,
    finalize_owner_final_receipt,
    main,
)


PRODUCT_SHA = "a" * 40
W4_SHA = "b" * 64
SEED_SHA = "c" * 64
FIRST_DOC_SHA = "d" * 64
SECOND_DOC_SHA = "e" * 64
SOUND_SHA = "f" * 64
PACKAGE_SHA = "1" * 64


def _receipt(final_zip: Path, **overrides: object) -> dict[str, object]:
    value: dict[str, object] = {
        "package_root": "owner-oneclick",
        "archive_path": str(final_zip),
        "archive_sha256": hashlib.sha256(final_zip.read_bytes()).hexdigest(),
        "integration_sha": PRODUCT_SHA,
        "document_sha256": [FIRST_DOC_SHA, SECOND_DOC_SHA],
        "sound_archive_sha256": SOUND_SHA,
        "sound_inventory_sha256": EXPECTED_SOURCE_INVENTORY_SHA256,
        "package_checksum_sha256": PACKAGE_SHA,
        "sound_wav_count": 330,
        "seed_source_count": 6,
        "seed_game_count": 3738,
        "human_tested": False,
        "nvda_verified": False,
        "result": "PASS",
    }
    value.update(overrides)
    return value


def _finalize(receipt: Path, final_zip: Path, **overrides: object) -> dict[str, object]:
    kwargs: dict[str, object] = {
        "expected_product_sha": PRODUCT_SHA,
        "expected_w4_candidate_sha256": W4_SHA,
        "expected_seed_archive_sha256": SEED_SHA,
        "expected_document_sha256": (FIRST_DOC_SHA, SECOND_DOC_SHA),
        "expected_sound_archive_sha256": SOUND_SHA,
        "source_w4_run_id": 37174317097,
        "source_w4_run_attempt": 2,
        "source_w4_workflow_id": 123456789,
        "source_w4_workflow_sha": PRODUCT_SHA,
        "finalizer_run_id": 37180000000,
        "finalizer_run_attempt": 1,
    }
    kwargs.update(overrides)
    return finalize_owner_final_receipt(receipt, final_zip, **kwargs)


class OwnerFinalReceiptTests(unittest.TestCase):
    def test_strict_base_receipt_schema_matches_current_owner_builder(self) -> None:
        report = OwnerPortableCandidateReport(
            package_root=Path("owner-oneclick"),
            archive_path=Path("Accessible-Chess-ONECLICK-OWNER-FINAL.zip"),
            archive_sha256="a" * 64,
            integration_sha="b" * 40,
            document_sha256=("c" * 64, "d" * 64),
            sound_archive_sha256="e" * 64,
            sound_inventory_sha256=EXPECTED_SOURCE_INVENTORY_SHA256,
            package_checksum_sha256="f" * 64,
            sound_wav_count=330,
            seed_source_count=6,
            seed_game_count=3738,
        ).as_dict()
        self.assertEqual(set(report), BASE_RECEIPT_KEYS)
        self.assertIs(report["human_tested"], False)
        self.assertIs(report["nvda_verified"], False)
        self.assertEqual(report["result"], "PASS")

    def test_finalizes_exact_machine_provenance_deterministically(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            final_zip = root / "Accessible-Chess-ONECLICK-OWNER-FINAL.zip"
            final_zip.write_bytes(b"owner-final-zip-bytes")
            receipt = root / "owner-final-receipt.json"
            receipt.write_text(
                json.dumps(_receipt(final_zip), sort_keys=True) + "\n",
                encoding="utf-8",
            )

            value = _finalize(receipt, final_zip)

            self.assertEqual(value["receipt_schema_version"], 1)
            self.assertEqual(value["finalizer_product_sha"], PRODUCT_SHA)
            self.assertEqual(value["finalizer_workflow_sha"], PRODUCT_SHA)
            self.assertEqual(value["source_w4_product_sha"], PRODUCT_SHA)
            self.assertEqual(value["source_w4_workflow_sha"], PRODUCT_SHA)
            self.assertEqual(value["source_w4_run_id"], 37174317097)
            self.assertEqual(value["source_w4_run_attempt"], 2)
            self.assertEqual(value["source_w4_workflow_id"], 123456789)
            self.assertEqual(value["source_w4_candidate_sha256"], W4_SHA)
            self.assertEqual(value["owner_seed_archive_sha256"], SEED_SHA)
            self.assertIs(value["machine_root_launch_verified"], True)
            self.assertIs(value["pre_upload_release_freshness"], True)
            self.assertIs(value["human_tested"], False)
            self.assertIs(value["nvda_verified"], False)
            raw_receipt = receipt.read_text(encoding="utf-8")
            self.assertEqual(
                raw_receipt,
                json.dumps(
                    value,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                )
                + "\n",
            )

    def test_cli_finalizes_exact_receipt_and_reports_success(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            final_zip = root / "Accessible-Chess-ONECLICK-OWNER-FINAL.zip"
            final_zip.write_bytes(b"owner-final-cli-zip")
            receipt = root / "owner-final-receipt.json"
            receipt.write_text(
                json.dumps(_receipt(final_zip), sort_keys=True) + "\n",
                encoding="utf-8",
            )
            result = main(
                [
                    "--receipt",
                    str(receipt),
                    "--final-zip",
                    str(final_zip),
                    "--product-sha",
                    PRODUCT_SHA,
                    "--w4-candidate-sha256",
                    W4_SHA,
                    "--seed-archive-sha256",
                    SEED_SHA,
                    "--first-docx-sha256",
                    FIRST_DOC_SHA,
                    "--second-docx-sha256",
                    SECOND_DOC_SHA,
                    "--sound-archive-sha256",
                    SOUND_SHA,
                    "--w4-run-id",
                    "37174317097",
                    "--w4-run-attempt",
                    "2",
                    "--w4-workflow-id",
                    "123456789",
                    "--w4-workflow-sha",
                    PRODUCT_SHA,
                    "--finalizer-run-id",
                    "37180000000",
                    "--finalizer-run-attempt",
                    "1",
                ]
            )
            self.assertEqual(result, 0)
            value = json.loads(receipt.read_text(encoding="utf-8"))
            self.assertEqual(value["source_w4_run_id"], 37174317097)
            self.assertIs(value["machine_root_launch_verified"], True)

    def test_rejects_duplicate_builder_receipt_keys(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            final_zip = root / "final.zip"
            final_zip.write_bytes(b"zip")
            value = _receipt(final_zip)
            receipt = root / "receipt.json"
            serialized = json.dumps(value, sort_keys=True)
            receipt.write_text(
                serialized[:-1] + ',"result":"PASS"}\n',
                encoding="utf-8",
            )
            with self.assertRaisesRegex(OwnerFinalReceiptError, "duplicate keys"):
                _finalize(receipt, final_zip)

    def test_rejects_boolean_counts_and_acceptance_overclaim(self) -> None:
        cases = (
            ({"sound_wav_count": True}, "content counts"),
            ({"seed_source_count": True}, "content counts"),
            ({"seed_game_count": True}, "content counts"),
            ({"human_tested": True}, "machine acceptance"),
            ({"nvda_verified": True}, "machine acceptance"),
        )
        for overrides, message in cases:
            with self.subTest(overrides=overrides), tempfile.TemporaryDirectory() as raw:
                root = Path(raw)
                final_zip = root / "final.zip"
                final_zip.write_bytes(b"zip")
                receipt = root / "receipt.json"
                receipt.write_text(
                    json.dumps(_receipt(final_zip, **overrides)),
                    encoding="utf-8",
                )
                with self.assertRaisesRegex(OwnerFinalReceiptError, message):
                    _finalize(receipt, final_zip)

    def test_rejects_wrong_archive_document_sound_or_product_identity(self) -> None:
        cases = (
            ({"package_root": "other-root"}, {}, "package root"),
            ({"archive_path": "other.zip"}, {}, "archive path"),
            ({"archive_sha256": "9" * 64}, {}, "does not match"),
            ({"document_sha256": [FIRST_DOC_SHA, "9" * 64]}, {}, "document"),
            ({"sound_archive_sha256": "9" * 64}, {}, "sound archive"),
            ({"integration_sha": "9" * 40}, {}, "product SHA mismatch"),
            (
                {"sound_inventory_sha256": "9" * 64},
                {},
                "sound inventory",
            ),
            (
                {},
                {"source_w4_workflow_sha": "9" * 40},
                "not the exact owner release",
            ),
        )
        for receipt_overrides, finalize_overrides, message in cases:
            with self.subTest(message=message), tempfile.TemporaryDirectory() as raw:
                root = Path(raw)
                final_zip = root / "final.zip"
                final_zip.write_bytes(b"zip")
                receipt = root / "receipt.json"
                receipt.write_text(
                    json.dumps(_receipt(final_zip, **receipt_overrides)),
                    encoding="utf-8",
                )
                with self.assertRaisesRegex(OwnerFinalReceiptError, message):
                    _finalize(receipt, final_zip, **finalize_overrides)

    def test_rejects_noncanonical_or_boolean_provenance_inputs(self) -> None:
        cases = (
            ({"expected_w4_candidate_sha256": W4_SHA.upper()}, "W4 candidate"),
            ({"source_w4_run_id": True}, "W4 run id"),
            ({"source_w4_run_attempt": 0}, "W4 run attempt"),
            ({"source_w4_workflow_id": False}, "W4 workflow id"),
            ({"finalizer_run_id": 0}, "finalizer run id"),
            ({"finalizer_run_attempt": True}, "finalizer run attempt"),
        )
        for overrides, message in cases:
            with self.subTest(overrides=overrides), tempfile.TemporaryDirectory() as raw:
                root = Path(raw)
                final_zip = root / "final.zip"
                final_zip.write_bytes(b"zip")
                receipt = root / "receipt.json"
                receipt.write_text(json.dumps(_receipt(final_zip)), encoding="utf-8")
                with self.assertRaisesRegex(OwnerFinalReceiptError, message):
                    _finalize(receipt, final_zip, **overrides)

    def test_rejects_derived_document_digest_tuple_before_iteration_hooks(self) -> None:
        touched: list[str] = []

        class ActiveTuple(tuple):
            def __iter__(self):
                touched.append("iter")
                raise AssertionError("derived tuple iteration executed")

        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            final_zip = root / "final.zip"
            final_zip.write_bytes(b"zip")
            receipt = root / "receipt.json"
            receipt.write_text(json.dumps(_receipt(final_zip)), encoding="utf-8")

            with self.assertRaisesRegex(TypeError, "exact two-item tuple"):
                _finalize(
                    receipt,
                    final_zip,
                    expected_document_sha256=ActiveTuple(
                        (FIRST_DOC_SHA, SECOND_DOC_SHA)
                    ),
                )

        self.assertEqual(touched, [])

    def test_exact_finalized_receipt_retry_is_idempotent_and_durable(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            final_zip = root / "final.zip"
            final_zip.write_bytes(b"zip")
            receipt = root / "receipt.json"
            receipt.write_text(json.dumps(_receipt(final_zip)), encoding="utf-8")

            first = _finalize(receipt, final_zip)
            first_bytes = receipt.read_bytes()
            real_sync = finalizer_module._sync_published_zip_namespace

            with mock.patch.object(
                finalizer_module,
                "_sync_published_zip_namespace",
                wraps=real_sync,
            ) as sync, mock.patch.object(
                finalizer_module.os,
                "replace",
                side_effect=AssertionError("idempotent retry must not replace"),
            ):
                second = _finalize(receipt, final_zip)

            self.assertEqual(second, first)
            self.assertEqual(receipt.read_bytes(), first_bytes)
            self.assertEqual(sync.call_count, 1)
            self.assertEqual(set(second), FINAL_RECEIPT_KEYS)
            self.assertEqual(list(root.glob(".receipt.json.publish-*.tmp")), [])

    def test_post_replace_durability_failure_is_retryable_from_finalized_receipt(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            final_zip = root / "final.zip"
            final_zip.write_bytes(b"zip")
            receipt = root / "receipt.json"
            receipt.write_text(json.dumps(_receipt(final_zip)), encoding="utf-8")

            with mock.patch.object(
                finalizer_module,
                "_sync_published_zip_namespace",
                side_effect=finalizer_module.Version2PortablePackageError(
                    "simulated final receipt durability failure"
                ),
            ):
                with self.assertRaisesRegex(
                    OwnerFinalReceiptError,
                    "publication durability could not be confirmed",
                ):
                    _finalize(receipt, final_zip)

            replaced = json.loads(receipt.read_text(encoding="utf-8"))
            self.assertEqual(set(replaced), FINAL_RECEIPT_KEYS)
            self.assertEqual(replaced["finalizer_run_id"], 37180000000)
            self.assertEqual(list(root.glob(".receipt.json.publish-*.tmp")), [])

            recovered = _finalize(receipt, final_zip)
            self.assertEqual(recovered, replaced)
            self.assertEqual(set(recovered), FINAL_RECEIPT_KEYS)

    def test_finalized_retry_rejects_mismatched_provenance_without_rewrite(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            final_zip = root / "final.zip"
            final_zip.write_bytes(b"zip")
            receipt = root / "receipt.json"
            receipt.write_text(json.dumps(_receipt(final_zip)), encoding="utf-8")
            _finalize(receipt, final_zip)

            value = json.loads(receipt.read_text(encoding="utf-8"))
            value["finalizer_run_id"] = 37180000001
            receipt.write_text(
                json.dumps(
                    value,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                )
                + "\n",
                encoding="utf-8",
            )
            before = receipt.read_bytes()

            with mock.patch.object(
                finalizer_module.os,
                "replace",
                side_effect=AssertionError("mismatch must not rewrite"),
            ):
                with self.assertRaisesRegex(
                    OwnerFinalReceiptError,
                    "finalized provenance mismatch: finalizer_run_id",
                ):
                    _finalize(receipt, final_zip)

            self.assertEqual(receipt.read_bytes(), before)

    def test_stale_prior_staging_never_blocks_or_gets_deleted_by_retry(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            final_zip = root / "final.zip"
            final_zip.write_bytes(b"zip")
            receipt = root / "receipt.json"
            receipt.write_text(json.dumps(_receipt(final_zip)), encoding="utf-8")
            stale = root / ".receipt.json.publish-stale.tmp"
            stale.write_bytes(b"prior-crash-residue")

            value = _finalize(receipt, final_zip)

            self.assertEqual(set(value), FINAL_RECEIPT_KEYS)
            self.assertEqual(stale.read_bytes(), b"prior-crash-residue")
            self.assertEqual(
                list(root.glob(".receipt.json.publish-*.tmp")),
                [stale],
            )

    def test_failed_publication_preserves_replaced_staging_path(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            final_zip = root / "final.zip"
            final_zip.write_bytes(b"zip")
            receipt = root / "receipt.json"
            original = json.dumps(_receipt(final_zip), sort_keys=True) + "\n"
            receipt.write_text(original, encoding="utf-8")
            foreign = b"foreign-staging-owned-by-another-writer"
            replaced_path: list[Path] = []

            def replace_staging_then_fail(source, _destination):
                staged = Path(source)
                staged.unlink()
                staged.write_bytes(foreign)
                replaced_path.append(staged)
                raise OSError("simulated replace failure after staging substitution")

            with mock.patch.object(
                finalizer_module.os,
                "replace",
                side_effect=replace_staging_then_fail,
            ):
                with self.assertRaisesRegex(
                    OwnerFinalReceiptError,
                    "could not be published",
                ):
                    _finalize(receipt, final_zip)

            self.assertEqual(receipt.read_text(encoding="utf-8"), original)
            self.assertEqual(len(replaced_path), 1)
            self.assertTrue(replaced_path[0].is_file())
            self.assertEqual(replaced_path[0].read_bytes(), foreign)

    def test_publication_failure_keeps_original_receipt_and_cleans_temp(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            final_zip = root / "final.zip"
            final_zip.write_bytes(b"zip")
            receipt = root / "receipt.json"
            original = json.dumps(_receipt(final_zip), sort_keys=True) + "\n"
            receipt.write_text(original, encoding="utf-8")

            with mock.patch.object(os, "replace", side_effect=OSError("blocked")):
                with self.assertRaisesRegex(OwnerFinalReceiptError, "could not be published"):
                    _finalize(receipt, final_zip)

            self.assertEqual(receipt.read_text(encoding="utf-8"), original)
            self.assertEqual(list(root.glob(".receipt.json.publish-*.tmp")), [])


if __name__ == "__main__":
    unittest.main()
