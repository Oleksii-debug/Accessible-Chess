from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from acs.runtime_dependency_sbom import (
    RuntimeDependencySbomError,
    build_runtime_dependency_spdx23,
)


class RuntimeDependencySbomTests(unittest.TestCase):
    def _manifest(self, root: Path) -> Path:
        path = root / "PYTHON_RUNTIME_DEPENDENCIES.json"
        payload = {
            "schema_version": 2,
            "scope": "qualified Python build/runtime dependency notice evidence",
            "python": {
                "version": "3.12.10",
                "packaged_file": "Python-LICENSE.txt",
                "sha256": "1" * 64,
            },
            "distributions": [
                {
                    "distribution": "pywebview",
                    "version": "6.2.1",
                    "license_expression": "BSD-3-Clause",
                    "license_metadata": "BSD",
                    "project_urls": ["Homepage, https://pywebview.flowrl.com"],
                    "notice_files": [
                        {
                            "source_kind": "installed_distribution",
                            "source_path": "licenses/LICENSE.md",
                            "packaged_file": "pywebview-6.2.1-NOTICE-01.md",
                            "sha256": "a" * 64,
                        }
                    ],
                },
                {
                    "distribution": "ordered-set",
                    "version": "4.1.0",
                    "license_expression": None,
                    "license_metadata": "MIT",
                    "project_urls": [],
                    "notice_files": [
                        {
                            "source_kind": "verified_source_archive",
                            "source_path": "ordered-set-4.1.0/MIT-LICENSE",
                            "source_url": "https://example.invalid/ordered-set.tar.gz",
                            "source_artifact_sha256": "b" * 64,
                            "packaged_file": "ordered-set-4.1.0-NOTICE-01.txt",
                            "sha256": "c" * 64,
                        }
                    ],
                },
            ],
        }
        path.write_text(json.dumps(payload, sort_keys=True, indent=2) + "\n", encoding="utf-8")
        return path

    def test_projects_notice_authority_to_deterministic_spdx23(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            manifest = self._manifest(root)
            one = build_runtime_dependency_spdx23(
                manifest,
                root / "one.spdx.json",
                document_name="Accessible Chess qualified Windows runtime",
                created_utc="2026-09-26T16:00:00Z",
            )
            two = build_runtime_dependency_spdx23(
                manifest,
                root / "two.spdx.json",
                document_name="Accessible Chess qualified Windows runtime",
                created_utc="2026-09-26T16:00:00Z",
            )
            self.assertEqual(one.read_bytes(), two.read_bytes())
            data = json.loads(one.read_text(encoding="utf-8"))
            self.assertEqual(data["spdxVersion"], "SPDX-2.3")
            self.assertEqual(data["dataLicense"], "CC0-1.0")
            self.assertTrue(data["documentNamespace"].startswith("https://accessible-chess.invalid/spdx/"))
            packages = {row["name"]: row for row in data["packages"]}
            self.assertEqual(set(packages), {"Python", "ordered-set", "pywebview"})
            self.assertEqual(packages["pywebview"]["licenseDeclared"], "BSD-3-Clause")
            self.assertEqual(packages["ordered-set"]["licenseDeclared"], "NOASSERTION")
            self.assertEqual(
                packages["ordered-set"]["externalRefs"][0]["referenceLocator"],
                "pkg:pypi/ordered-set@4.1.0",
            )
            dependency_targets = {
                row["relatedSpdxElement"]
                for row in data["relationships"]
                if row["relationshipType"] == "DEPENDS_ON"
            }
            self.assertEqual(len(dependency_targets), 2)

    def test_rejects_obsolete_notice_manifest_schema(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            manifest = self._manifest(root)
            data = json.loads(manifest.read_text(encoding="utf-8"))
            data["schema_version"] = 1
            manifest.write_text(json.dumps(data), encoding="utf-8")
            with self.assertRaisesRegex(RuntimeDependencySbomError, "schema is unsupported"):
                build_runtime_dependency_spdx23(
                    manifest,
                    root / "sbom.json",
                    document_name="Accessible Chess runtime",
                    created_utc="2026-09-26T16:00:00Z",
                )

    def test_rejects_duplicate_distribution_authority(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            manifest = self._manifest(root)
            data = json.loads(manifest.read_text(encoding="utf-8"))
            duplicate = dict(data["distributions"][0])
            duplicate["distribution"] = "PYWEBVIEW"
            data["distributions"].append(duplicate)
            manifest.write_text(json.dumps(data), encoding="utf-8")
            with self.assertRaisesRegex(RuntimeDependencySbomError, "duplicate distributions"):
                build_runtime_dependency_spdx23(
                    manifest,
                    root / "sbom.json",
                    document_name="Accessible Chess runtime",
                    created_utc="2026-09-26T16:00:00Z",
                )

    def test_rejects_unverified_or_malformed_notice_hash(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            manifest = self._manifest(root)
            data = json.loads(manifest.read_text(encoding="utf-8"))
            data["distributions"][0]["notice_files"][0]["sha256"] = "not-a-digest"
            manifest.write_text(json.dumps(data), encoding="utf-8")
            with self.assertRaisesRegex(RuntimeDependencySbomError, "notice SHA-256 is invalid"):
                build_runtime_dependency_spdx23(
                    manifest,
                    root / "sbom.json",
                    document_name="Accessible Chess runtime",
                    created_utc="2026-09-26T16:00:00Z",
                )

    def test_rejects_non_utc_or_invalid_creation_time(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            manifest = self._manifest(root)
            for invalid in ("2026-09-26T16:00:00+02:00", "not-a-time"):
                with self.subTest(invalid=invalid):
                    with self.assertRaises(RuntimeDependencySbomError):
                        build_runtime_dependency_spdx23(
                            manifest,
                            root / f"{len(invalid)}.json",
                            document_name="Accessible Chess runtime",
                            created_utc=invalid,
                        )

    def test_refuses_overwrite(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            manifest = self._manifest(root)
            output = root / "sbom.json"
            output.write_text("existing", encoding="utf-8")
            with self.assertRaisesRegex(RuntimeDependencySbomError, "already exists"):
                build_runtime_dependency_spdx23(
                    manifest,
                    output,
                    document_name="Accessible Chess runtime",
                    created_utc="2026-09-26T16:00:00Z",
                )


if __name__ == "__main__":
    unittest.main()