from __future__ import annotations

import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from acs.runtime_sbom import (
    RuntimeSbomError,
    build_runtime_cyclonedx_sbom,
)


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class RuntimeSbomTests(unittest.TestCase):
    def make_notice_manifest(
        self,
        root: Path,
        *,
        distributions: list[dict] | None = None,
    ) -> Path:
        python_bytes = b"Python license evidence\n"
        python_name = "Python-LICENSE.txt"
        (root / python_name).write_bytes(python_bytes)

        if distributions is None:
            notice_bytes = b"pywebview license evidence\n"
            notice_name = "pywebview-6.2.1-NOTICE-01.txt"
            (root / notice_name).write_bytes(notice_bytes)
            distributions = [
                {
                    "distribution": "pywebview",
                    "version": "6.2.1",
                    "license_expression": "BSD-3-Clause",
                    "license_metadata": "BSD 3-Clause",
                    "project_urls": ["https://pywebview.flowrl.com/"],
                    "notice_files": [
                        {
                            "source_kind": "installed_distribution",
                            "source_path": "pywebview-6.2.1.dist-info/licenses/LICENSE.md",
                            "packaged_file": notice_name,
                            "sha256": sha256_bytes(notice_bytes),
                        }
                    ],
                }
            ]

        payload = {
            "schema_version": 2,
            "scope": "qualified Python build/runtime dependency notice evidence",
            "python": {
                "version": "3.12.10",
                "packaged_file": python_name,
                "sha256": sha256_bytes(python_bytes),
            },
            "distributions": distributions,
        }
        path = root / "PYTHON_RUNTIME_DEPENDENCIES.json"
        path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
            newline="\n",
        )
        return path

    def test_builds_deterministic_cyclonedx_from_exact_notice_inventory(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            manifest = self.make_notice_manifest(root)
            first = root / "runtime-sbom-1.json"
            second = root / "runtime-sbom-2.json"

            one = build_runtime_cyclonedx_sbom(
                manifest,
                first,
                product_version="2.0.0",
            )
            two = build_runtime_cyclonedx_sbom(
                manifest,
                second,
                product_version="2.0.0",
            )

            self.assertEqual(first.read_bytes(), second.read_bytes())
            self.assertEqual(one.sha256, two.sha256)
            self.assertEqual(one.notice_manifest_sha256, two.notice_manifest_sha256)
            self.assertEqual(one.component_count, 2)

            payload = json.loads(first.read_text(encoding="utf-8"))
            self.assertEqual(payload["bomFormat"], "CycloneDX")
            self.assertEqual(payload["specVersion"], "1.6")
            self.assertEqual(payload["version"], 1)
            self.assertTrue(payload["serialNumber"].startswith("urn:uuid:"))
            self.assertEqual(payload["metadata"]["component"]["name"], "Accessible Chess")
            self.assertEqual(payload["metadata"]["component"]["version"], "2.0.0")
            self.assertEqual(
                [row["name"] for row in payload["components"]],
                ["Python", "pywebview"],
            )
            self.assertEqual(
                payload["components"][1]["purl"],
                "pkg:pypi/pywebview@6.2.1",
            )
            root_dependency = payload["dependencies"][0]
            self.assertEqual(
                len(root_dependency["dependsOn"]),
                len(payload["components"]),
            )

    def test_distribution_order_does_not_depend_on_manifest_order(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            rows = []
            for name, version in (("zeta_pkg", "2.0"), ("Alpha.Pkg", "1.0")):
                data = f"{name} notice\n".encode()
                filename = f"{name}-{version}-NOTICE-01.txt"
                (root / filename).write_bytes(data)
                rows.append(
                    {
                        "distribution": name,
                        "version": version,
                        "license_expression": "",
                        "license_metadata": "Custom license",
                        "project_urls": [],
                        "notice_files": [
                            {
                                "source_kind": "installed_distribution",
                                "source_path": f"{name}.dist-info/LICENSE",
                                "packaged_file": filename,
                                "sha256": sha256_bytes(data),
                            }
                        ],
                    }
                )
            manifest = self.make_notice_manifest(root, distributions=list(reversed(rows)))
            output = root / "sbom.json"
            build_runtime_cyclonedx_sbom(manifest, output, product_version="2.0.0")
            payload = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(
                [row["name"] for row in payload["components"][1:]],
                ["Alpha.Pkg", "zeta_pkg"],
            )

    def test_verified_source_archive_provenance_is_preserved(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            data = b"fallback upstream license\n"
            filename = "ordered-set-4.1.0-NOTICE-01.txt"
            (root / filename).write_bytes(data)
            distributions = [
                {
                    "distribution": "ordered-set",
                    "version": "4.1.0",
                    "license_expression": "MIT",
                    "license_metadata": "",
                    "project_urls": ["https://github.com/rspeer/ordered-set"],
                    "notice_files": [
                        {
                            "source_kind": "verified_source_archive",
                            "source_path": "ordered_set-4.1.0/LICENSE",
                            "source_url": "https://files.pythonhosted.org/packages/source/o/ordered-set.tar.gz",
                            "source_artifact_sha256": "a" * 64,
                            "packaged_file": filename,
                            "sha256": sha256_bytes(data),
                        }
                    ],
                }
            ]
            manifest = self.make_notice_manifest(root, distributions=distributions)
            output = root / "sbom.json"
            build_runtime_cyclonedx_sbom(manifest, output, product_version="2.0.0")
            component = json.loads(output.read_text(encoding="utf-8"))["components"][1]
            properties = {item["name"]: item["value"] for item in component["properties"]}
            self.assertEqual(
                properties["accessiblechess:notice:01:source_kind"],
                "verified_source_archive",
            )
            self.assertEqual(
                properties["accessiblechess:notice:01:source_artifact_sha256"],
                "a" * 64,
            )

    def test_changed_notice_bytes_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            manifest = self.make_notice_manifest(root)
            (root / "pywebview-6.2.1-NOTICE-01.txt").write_text(
                "tampered\n",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(RuntimeSbomError, "sha256 mismatch"):
                build_runtime_cyclonedx_sbom(
                    manifest,
                    root / "sbom.json",
                    product_version="2.0.0",
                )

    def test_missing_notice_file_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            manifest = self.make_notice_manifest(root)
            (root / "pywebview-6.2.1-NOTICE-01.txt").unlink()
            with self.assertRaisesRegex(RuntimeSbomError, "unavailable"):
                build_runtime_cyclonedx_sbom(
                    manifest,
                    root / "sbom.json",
                    product_version="2.0.0",
                )

    def test_duplicate_distribution_identity_is_rejected_case_insensitively(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            data = b"notice\n"
            for index in (1, 2):
                (root / f"notice-{index}.txt").write_bytes(data)
            rows = []
            for index, name in enumerate(("Package.Name", "package.name"), start=1):
                rows.append(
                    {
                        "distribution": name,
                        "version": "1.0",
                        "license_expression": "MIT",
                        "license_metadata": "",
                        "project_urls": [],
                        "notice_files": [
                            {
                                "source_kind": "installed_distribution",
                                "source_path": f"{name}.dist-info/LICENSE",
                                "packaged_file": f"notice-{index}.txt",
                                "sha256": sha256_bytes(data),
                            }
                        ],
                    }
                )
            manifest = self.make_notice_manifest(root, distributions=rows)
            with self.assertRaisesRegex(RuntimeSbomError, "duplicate distributions"):
                build_runtime_cyclonedx_sbom(
                    manifest,
                    root / "sbom.json",
                    product_version="2.0.0",
                )

    def test_duplicate_json_key_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            manifest = root / "PYTHON_RUNTIME_DEPENDENCIES.json"
            manifest.write_text(
                '{"schema_version":2,"schema_version":2,"scope":"x","python":{},"distributions":[]}\n',
                encoding="utf-8",
            )
            with self.assertRaisesRegex(RuntimeSbomError, "duplicate JSON keys"):
                build_runtime_cyclonedx_sbom(
                    manifest,
                    root / "sbom.json",
                    product_version="2.0.0",
                )

    def test_unknown_manifest_schema_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            manifest = self.make_notice_manifest(root)
            payload = json.loads(manifest.read_text(encoding="utf-8"))
            payload["schema_version"] = 99
            manifest.write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaisesRegex(RuntimeSbomError, "schema version"):
                build_runtime_cyclonedx_sbom(
                    manifest,
                    root / "sbom.json",
                    product_version="2.0.0",
                )

    def test_unknown_manifest_field_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            manifest = self.make_notice_manifest(root)
            payload = json.loads(manifest.read_text(encoding="utf-8"))
            payload["unexpected"] = True
            manifest.write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaisesRegex(RuntimeSbomError, "manifest fields"):
                build_runtime_cyclonedx_sbom(
                    manifest,
                    root / "sbom.json",
                    product_version="2.0.0",
                )

    def test_unsafe_packaged_notice_path_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            manifest = self.make_notice_manifest(root)
            payload = json.loads(manifest.read_text(encoding="utf-8"))
            payload["distributions"][0]["notice_files"][0]["packaged_file"] = "../LICENSE"
            manifest.write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaisesRegex(RuntimeSbomError, "filename is unsafe"):
                build_runtime_cyclonedx_sbom(
                    manifest,
                    root / "sbom.json",
                    product_version="2.0.0",
                )

    def test_external_notice_url_with_credentials_or_fragment_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            data = b"license\n"
            filename = "pkg-NOTICE.txt"
            (root / filename).write_bytes(data)
            row = {
                "distribution": "pkg",
                "version": "1.0",
                "license_expression": "MIT",
                "license_metadata": "",
                "project_urls": [],
                "notice_files": [
                    {
                        "source_kind": "verified_source_archive",
                        "source_path": "pkg/LICENSE",
                        "source_url": "https://user@example.com/pkg.tar.gz#license",
                        "source_artifact_sha256": "b" * 64,
                        "packaged_file": filename,
                        "sha256": sha256_bytes(data),
                    }
                ],
            }
            manifest = self.make_notice_manifest(root, distributions=[row])
            with self.assertRaisesRegex(RuntimeSbomError, "source URL is invalid"):
                build_runtime_cyclonedx_sbom(
                    manifest,
                    root / "sbom.json",
                    product_version="2.0.0",
                )

    def test_duplicate_project_urls_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            manifest = self.make_notice_manifest(root)
            payload = json.loads(manifest.read_text(encoding="utf-8"))
            url = payload["distributions"][0]["project_urls"][0]
            payload["distributions"][0]["project_urls"] = [url, url]
            manifest.write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaisesRegex(RuntimeSbomError, "URLs contain duplicates"):
                build_runtime_cyclonedx_sbom(
                    manifest,
                    root / "sbom.json",
                    product_version="2.0.0",
                )

    def test_invalid_product_identity_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            manifest = self.make_notice_manifest(root)
            with self.assertRaisesRegex(RuntimeSbomError, "product name is unsafe"):
                build_runtime_cyclonedx_sbom(
                    manifest,
                    root / "one.json",
                    product_name="../Accessible Chess",
                    product_version="2.0.0",
                )
            with self.assertRaisesRegex(RuntimeSbomError, "product version is unsafe"):
                build_runtime_cyclonedx_sbom(
                    manifest,
                    root / "two.json",
                    product_version="2.0 beta",
                )

    def test_existing_output_is_never_overwritten(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            manifest = self.make_notice_manifest(root)
            output = root / "sbom.json"
            output.write_text("sentinel", encoding="utf-8")
            with self.assertRaisesRegex(RuntimeSbomError, "already exists"):
                build_runtime_cyclonedx_sbom(
                    manifest,
                    output,
                    product_version="2.0.0",
                )
            self.assertEqual(output.read_text(encoding="utf-8"), "sentinel")

    def test_symlinked_notice_evidence_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            manifest = self.make_notice_manifest(root)
            target = root / "real-license.txt"
            target.write_bytes(b"pywebview license evidence\n")
            link = root / "pywebview-6.2.1-NOTICE-01.txt"
            link.unlink()
            try:
                link.symlink_to(target.name)
            except OSError:
                self.skipTest("symlinks are unavailable on this runner")
            with self.assertRaisesRegex(RuntimeSbomError, "must not be a symlink"):
                build_runtime_cyclonedx_sbom(
                    manifest,
                    root / "sbom.json",
                    product_version="2.0.0",
                )


if __name__ == "__main__":
    unittest.main()
