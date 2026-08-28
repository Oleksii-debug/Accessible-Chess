from __future__ import annotations

import inspect
import json
from pathlib import Path
import tempfile
import unittest

from acs.version2_package_preflight import (
    MANIFEST_NAME,
    PackageLimits,
    Version2PackagePreflightError,
    validate_version2_package_tree,
    validate_version2_package_zip,
)
from tests.test_version2_package_preflight import _make_tree, _write_checksums, _zip_tree


_EXPECTED_SHA = "a" * 40
_WRONG_SHA = "0" * 40


def _authority_kwargs() -> dict[str, str]:
    parameters = inspect.signature(validate_version2_package_tree).parameters
    if "expected_integration_sha" in parameters:
        return {"expected_integration_sha": _EXPECTED_SHA}
    return {}


class Version2PackagePreflightHardeningTests(unittest.TestCase):
    def test_manifest_requires_exact_json_scalar_types_for_tree_and_zip(self) -> None:
        cases = (
            ("manifest_schema", True),
            ("upgrade_journal_schema", True),
            ("nvda_verified", 0),
            ("upgrade_from_version1", 1),
            ("user_data_bundled", 0),
            ("raw_source_bundled", 0),
            ("optional_external_backends_bundled", 0),
        )
        for field, value in cases:
            with self.subTest(field=field), tempfile.TemporaryDirectory() as td:
                base = Path(td)
                root = base / "package"
                root.mkdir()
                _make_tree(root)
                manifest_path = root / MANIFEST_NAME
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                manifest[field] = value
                manifest_path.write_text(
                    json.dumps(manifest, sort_keys=True, indent=2) + "\n",
                    encoding="utf-8",
                )
                _write_checksums(root)
                kwargs = _authority_kwargs()
                with self.assertRaisesRegex(
                    Version2PackagePreflightError,
                    "manifest contract mismatch",
                ):
                    validate_version2_package_tree(root, **kwargs)

                archive = base / f"{field}.zip"
                _zip_tree(root, archive)
                with self.assertRaisesRegex(
                    Version2PackagePreflightError,
                    "manifest contract mismatch",
                ):
                    validate_version2_package_zip(archive, **kwargs)

    def test_expected_integration_authority_is_required_and_enforced(self) -> None:
        tree_params = inspect.signature(validate_version2_package_tree).parameters
        zip_params = inspect.signature(validate_version2_package_zip).parameters
        self.assertIn("expected_integration_sha", tree_params)
        self.assertIn("expected_integration_sha", zip_params)
        self.assertIs(
            tree_params["expected_integration_sha"].default,
            inspect.Parameter.empty,
        )
        self.assertIs(
            zip_params["expected_integration_sha"].default,
            inspect.Parameter.empty,
        )

        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            root = base / "package"
            root.mkdir()
            _make_tree(root)
            manifest_path = root / MANIFEST_NAME
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["integration_sha"] = _WRONG_SHA
            manifest_path.write_text(
                json.dumps(manifest, sort_keys=True, indent=2) + "\n",
                encoding="utf-8",
            )
            _write_checksums(root)

            with self.assertRaisesRegex(
                Version2PackagePreflightError,
                "integration_sha|authority",
            ):
                validate_version2_package_tree(
                    root,
                    expected_integration_sha=_EXPECTED_SHA,
                )

            archive = base / "wrong-authority.zip"
            _zip_tree(root, archive)
            with self.assertRaisesRegex(
                Version2PackagePreflightError,
                "integration_sha|authority",
            ):
                validate_version2_package_zip(
                    archive,
                    expected_integration_sha=_EXPECTED_SHA,
                )

    def test_large_text_hygiene_scan_has_no_size_bypass(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "package"
            root.mkdir()
            _make_tree(root)
            limits = PackageLimits(max_text_scan_bytes=64)
            leak = root / "AccessibleChess" / "diagnostic.txt"
            leak.write_bytes(
                b"x" * 65
                + b"\ngithub_pat_ABCDEFGHIJKLMNOPQRSTUVWXYZ1234567890\n"
            )
            _write_checksums(root)
            with self.assertRaisesRegex(
                Version2PackagePreflightError,
                "credential|secret|hygiene",
            ):
                validate_version2_package_tree(
                    root,
                    limits=limits,
                    **_authority_kwargs(),
                )


if __name__ == "__main__":
    unittest.main()
