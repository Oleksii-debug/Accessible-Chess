from __future__ import annotations

import hashlib
import json
from pathlib import Path
import tempfile
import unittest
import zipfile

from acs.version2_package_preflight import Version2PackagePreflightError
from acs.version2_release_receipt import (
    CANONICAL_W5_WORKFLOW,
    RELEASE_RECEIPT_SCHEMA_VERSION,
    REPOSITORY_FULL_NAME,
    Version2ReleaseReceiptError,
    build_version2_release_receipt,
    main,
    read_version2_release_receipt,
    verify_version2_release_receipt,
    write_version2_release_receipt,
)
from tests.test_version2_package_preflight import _SHA, _make_tree


_HEAD_SHA = "b" * 40


def _zip_tree(
    root: Path,
    archive_path: Path,
    *,
    compression: int = zipfile.ZIP_DEFLATED,
) -> None:
    with zipfile.ZipFile(archive_path, "w", compression=compression) as archive:
        for path in sorted(
            (item for item in root.rglob("*") if item.is_file()),
            key=lambda item: item.relative_to(root).as_posix().casefold(),
        ):
            archive.write(path, path.relative_to(root).as_posix())


def _fixture(td: str) -> tuple[Path, Path]:
    base = Path(td)
    root = base / "package"
    root.mkdir()
    _make_tree(root)
    archive = base / "accessible-chess.zip"
    _zip_tree(root, archive)
    return root, archive


def _build(archive: Path, **kwargs):
    arguments = {
        "expected_integration_sha": _SHA,
        "workflow_run_id": 37139145605,
        "workflow_run_attempt": 1,
        "qualification_head_sha": _HEAD_SHA,
        "artifact_id": 11282014673,
        "artifact_name": "dostupni-shakhy-w5exact-win-x64-standalone",
    }
    arguments.update(kwargs)
    return build_version2_release_receipt(archive, **arguments)


def _canonical_json(payload: dict[str, object]) -> str:
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ) + "\n"


class Version2ReleaseReceiptTests(unittest.TestCase):
    def test_receipt_binds_validated_zip_and_attributable_action_identity(self):
        with tempfile.TemporaryDirectory() as td:
            _root, archive = _fixture(td)
            receipt = _build(archive)

            self.assertEqual(receipt.schema_version, RELEASE_RECEIPT_SCHEMA_VERSION)
            self.assertEqual(receipt.product, "Accessible Chess")
            self.assertEqual(receipt.repository, REPOSITORY_FULL_NAME)
            self.assertEqual(receipt.workflow_path, CANONICAL_W5_WORKFLOW)
            self.assertEqual(receipt.workflow_run_id, 37139145605)
            self.assertEqual(receipt.workflow_run_attempt, 1)
            self.assertEqual(receipt.qualification_head_sha, _HEAD_SHA)
            self.assertEqual(receipt.artifact_id, 11282014673)
            self.assertEqual(
                receipt.package_sha256,
                hashlib.sha256(archive.read_bytes()).hexdigest(),
            )
            self.assertEqual(receipt.integration_sha, _SHA)
            self.assertGreater(receipt.inventory_files, 0)
            self.assertGreater(receipt.total_bytes, 0)
            self.assertGreater(receipt.checksums_verified, 0)
            self.assertRegex(receipt.inventory_sha256, r"^[0-9a-f]{64}$")

            payload = json.loads(receipt.to_json())
            self.assertEqual(payload["package_sha256"], receipt.package_sha256)
            self.assertNotIn(str(archive), receipt.to_json())

    def test_receipt_reuses_canonical_zip_preflight_and_rejects_corruption(self):
        with tempfile.TemporaryDirectory() as td:
            _root, archive = _fixture(td)
            archive.write_bytes(b"not-a-zip")
            with self.assertRaises(Version2PackagePreflightError):
                _build(archive)

    def test_receipt_rejects_wrong_integration_authority(self):
        with tempfile.TemporaryDirectory() as td:
            _root, archive = _fixture(td)
            with self.assertRaisesRegex(
                Version2PackagePreflightError,
                "integration_sha does not match",
            ):
                _build(archive, expected_integration_sha="c" * 40)

    def test_metadata_is_strict_and_bools_are_not_ids(self):
        with tempfile.TemporaryDirectory() as td:
            _root, archive = _fixture(td)
            invalid = (
                {"workflow_run_id": True},
                {"workflow_run_id": 0},
                {"workflow_run_attempt": False},
                {"workflow_run_attempt": 0},
                {"artifact_id": False},
                {"artifact_id": -1},
                {"qualification_head_sha": "B" * 40},
                {"qualification_head_sha": "b" * 39},
                {"artifact_name": "../artifact"},
                {"artifact_name": "artifact\nspoof"},
                {"artifact_name": " artifact"},
            )
            for override in invalid:
                with self.subTest(override=override), self.assertRaises(
                    Version2ReleaseReceiptError
                ):
                    _build(archive, **override)

    def test_receipt_json_is_canonical_and_output_is_no_replace(self):
        with tempfile.TemporaryDirectory() as td:
            _root, archive = _fixture(td)
            receipt = _build(archive)
            output = Path(td) / "release-receipt.json"

            write_version2_release_receipt(output, receipt)
            raw = output.read_text(encoding="utf-8")
            self.assertEqual(raw, receipt.to_json())
            self.assertTrue(raw.endswith("\n"))
            self.assertEqual(len(raw.splitlines()), 1)
            self.assertEqual(read_version2_release_receipt(output), receipt)
            self.assertEqual(verify_version2_release_receipt(output, archive), receipt)

            with self.assertRaisesRegex(
                Version2ReleaseReceiptError,
                "overwrite is forbidden",
            ):
                write_version2_release_receipt(output, receipt)
            self.assertEqual(output.read_text(encoding="utf-8"), raw)

    def test_readback_rejects_duplicate_unknown_wrong_authority_and_reformatting(self):
        with tempfile.TemporaryDirectory() as td:
            _root, archive = _fixture(td)
            receipt = _build(archive)
            output = Path(td) / "receipt.json"
            payload = json.loads(receipt.to_json())

            payload["repository"] = "somewhere/else"
            output.write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaisesRegex(
                Version2ReleaseReceiptError,
                "repository identity mismatch",
            ):
                read_version2_release_receipt(output)

            payload["repository"] = REPOSITORY_FULL_NAME
            payload["unexpected"] = True
            output.write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaisesRegex(
                Version2ReleaseReceiptError,
                "schema mismatch",
            ):
                read_version2_release_receipt(output)

            duplicate = receipt.to_json().rstrip("\n")
            duplicate = duplicate[:-1] + ',"artifact_id":1}'
            output.write_text(duplicate, encoding="utf-8")
            with self.assertRaisesRegex(
                Version2ReleaseReceiptError,
                "duplicate JSON key 'artifact_id'",
            ):
                read_version2_release_receipt(output)

            pretty = json.dumps(json.loads(receipt.to_json()), ensure_ascii=False, indent=2, sort_keys=True) + "\n"
            output.write_text(pretty, encoding="utf-8")
            with self.assertRaisesRegex(
                Version2ReleaseReceiptError,
                "not in canonical serialization",
            ):
                read_version2_release_receipt(output)

            output.write_text(receipt.to_json().rstrip("\n"), encoding="utf-8")
            with self.assertRaisesRegex(
                Version2ReleaseReceiptError,
                "not in canonical serialization",
            ):
                read_version2_release_receipt(output)

    def test_readback_rejects_semantically_valid_but_different_zip_bytes(self):
        with tempfile.TemporaryDirectory() as td:
            root, archive = _fixture(td)
            receipt_path = Path(td) / "receipt.json"
            write_version2_release_receipt(receipt_path, _build(archive))

            alternate = Path(td) / "alternate.zip"
            _zip_tree(root, alternate, compression=zipfile.ZIP_STORED)
            self.assertNotEqual(
                hashlib.sha256(archive.read_bytes()).hexdigest(),
                hashlib.sha256(alternate.read_bytes()).hexdigest(),
            )
            with self.assertRaisesRegex(
                Version2ReleaseReceiptError,
                "does not match the revalidated package bytes",
            ):
                verify_version2_release_receipt(receipt_path, alternate)

    def test_readback_rejects_tampered_digest_even_when_package_is_valid(self):
        with tempfile.TemporaryDirectory() as td:
            _root, archive = _fixture(td)
            receipt = _build(archive)
            output = Path(td) / "receipt.json"
            payload = json.loads(receipt.to_json())
            payload["package_sha256"] = "0" * 64
            output.write_text(_canonical_json(payload), encoding="utf-8")

            with self.assertRaisesRegex(
                Version2ReleaseReceiptError,
                "does not match the revalidated package bytes",
            ):
                verify_version2_release_receipt(output, archive)

    def test_cli_create_and_verify_same_qualified_receipt(self):
        with tempfile.TemporaryDirectory() as td:
            _root, archive = _fixture(td)
            output = Path(td) / "receipt.json"
            create_result = main(
                [
                    "create",
                    "--package",
                    str(archive),
                    "--expected-integration-sha",
                    _SHA,
                    "--workflow-run-id",
                    "37139145605",
                    "--workflow-run-attempt",
                    "1",
                    "--qualification-head-sha",
                    _HEAD_SHA,
                    "--artifact-id",
                    "11282014673",
                    "--artifact-name",
                    "dostupni-shakhy-w5exact-win-x64-standalone",
                    "--output",
                    str(output),
                ]
            )
            self.assertEqual(create_result, 0)
            payload = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(payload["repository"], REPOSITORY_FULL_NAME)
            self.assertEqual(payload["workflow_run_id"], 37139145605)
            self.assertEqual(payload["workflow_run_attempt"], 1)
            self.assertEqual(payload["artifact_id"], 11282014673)
            self.assertEqual(payload["qualification_head_sha"], _HEAD_SHA)

            verify_result = main(
                [
                    "verify",
                    "--package",
                    str(archive),
                    "--receipt",
                    str(output),
                ]
            )
            self.assertEqual(verify_result, 0)
            self.assertEqual(
                verify_version2_release_receipt(output, archive),
                read_version2_release_receipt(output),
            )


if __name__ == "__main__":
    unittest.main()
