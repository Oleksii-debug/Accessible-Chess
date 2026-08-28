from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from acs.version2_package_preflight import (
    MANIFEST_NAME,
    Version2PackagePreflightError,
    validate_version2_package_tree,
    validate_version2_package_zip,
)
from tests.test_version2_package_preflight import (
    _make_tree,
    _write_checksums,
    _zip_tree,
)


class V2PackageManifestScalarTypesAuditTests(unittest.TestCase):
    def test_release_manifest_rejects_bool_int_scalar_aliases(self) -> None:
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

                with self.assertRaisesRegex(
                    Version2PackagePreflightError,
                    "manifest contract mismatch",
                    msg=f"release manifest field {field} must require its exact JSON scalar type",
                ):
                    validate_version2_package_tree(root)

                archive = base / f"{field}.zip"
                _zip_tree(root, archive)
                with self.assertRaisesRegex(
                    Version2PackagePreflightError,
                    "manifest contract mismatch",
                    msg=f"ZIP readback must reject noncanonical scalar type for {field}",
                ):
                    validate_version2_package_zip(archive)


if __name__ == "__main__":
    unittest.main()
