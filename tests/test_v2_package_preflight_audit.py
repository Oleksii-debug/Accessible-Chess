from __future__ import annotations

import hashlib
import inspect
import json
from pathlib import Path
import tempfile
import unittest

from acs.acsdb import ACSDB_SCHEMA_VERSION
from acs.settings import SCHEMA_VERSION as SETTINGS_SCHEMA_VERSION
from acs.version2_package_preflight import (
    CHECKSUMS_NAME,
    MANIFEST_NAME,
    PackageLimits,
    V2_PACKAGE_MANIFEST_SCHEMA_VERSION,
    V2_PACKAGE_PROFILE,
    Version2PackagePreflightError,
    validate_version2_package_tree,
    validate_version2_package_zip,
)
from acs.version2_upgrade import UPGRADE_JOURNAL_SCHEMA_VERSION


_EXPECTED_AUTHORITY = "5ea7ca44518cbe9c5789da3f017bde458be7faa8"
_WRONG_BUT_WELL_FORMED_SHA = "0" * 40


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_checksums(root: Path) -> None:
    rows: list[str] = []
    for path in sorted(
        (
            item
            for item in root.rglob("*")
            if item.is_file() and item.name != CHECKSUMS_NAME
        ),
        key=lambda item: item.relative_to(root).as_posix().casefold(),
    ):
        rows.append(f"{_sha256(path)}  {path.relative_to(root).as_posix()}")
    (root / CHECKSUMS_NAME).write_text("\n".join(rows) + "\n", encoding="utf-8")


def _make_package(root: Path, *, integration_sha: str) -> None:
    product = root / "AccessibleChess"
    product.mkdir(parents=True)
    (product / "AccessibleChess.exe").write_bytes(b"MZ\x00audit")
    manifest = {
        "manifest_schema": V2_PACKAGE_MANIFEST_SCHEMA_VERSION,
        "product": "Accessible Chess",
        "package_profile": V2_PACKAGE_PROFILE,
        "integration_sha": integration_sha,
        "nvda_verified": False,
        "upgrade_from_version1": True,
        "upgrade_journal_schema": UPGRADE_JOURNAL_SCHEMA_VERSION,
        "settings_schema": SETTINGS_SCHEMA_VERSION,
        "acsdb_schema": ACSDB_SCHEMA_VERSION,
        "user_data_bundled": False,
        "raw_source_bundled": False,
        "optional_external_backends_bundled": False,
    }
    (root / MANIFEST_NAME).write_text(
        json.dumps(manifest, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    _write_checksums(root)


class V2PackagePreflightAuditTests(unittest.TestCase):
    def test_release_preflight_exposes_expected_authority_binding(self) -> None:
        """A 40-hex manifest value alone must not be release-source authority."""

        tree_params = inspect.signature(validate_version2_package_tree).parameters
        zip_params = inspect.signature(validate_version2_package_zip).parameters
        self.assertIn(
            "expected_integration_sha",
            tree_params,
            "tree preflight has no explicit expected release-authority binding",
        )
        self.assertIn(
            "expected_integration_sha",
            zip_params,
            "ZIP preflight has no explicit expected release-authority binding",
        )

        # Once the binding exists, a syntactically valid but wrong manifest SHA
        # must fail closed.  Keep this behavioral half here so a future repair
        # cannot satisfy the audit by adding an ignored parameter only.
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "package"
            root.mkdir()
            _make_package(root, integration_sha=_WRONG_BUT_WELL_FORMED_SHA)
            with self.assertRaises(Version2PackagePreflightError):
                validate_version2_package_tree(
                    root,
                    expected_integration_sha=_EXPECTED_AUTHORITY,
                )

    def test_large_text_secret_is_not_skipped_by_hygiene_scan(self) -> None:
        """Bounded hygiene must not turn into a silent credential-leak bypass."""

        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "package"
            root.mkdir()
            _make_package(root, integration_sha=_EXPECTED_AUTHORITY)

            limits = PackageLimits()
            leak = root / "AccessibleChess" / "diagnostic.txt"
            leak.write_bytes(
                b"x" * (limits.max_text_scan_bytes + 1)
                + b"\ngithub_pat_ABCDEFGHIJKLMNOPQRSTUVWXYZ1234567890\n"
            )
            _write_checksums(root)

            with self.assertRaisesRegex(
                Version2PackagePreflightError,
                "credential|secret|hygiene",
            ):
                validate_version2_package_tree(root, limits=limits)


if __name__ == "__main__":
    unittest.main()
