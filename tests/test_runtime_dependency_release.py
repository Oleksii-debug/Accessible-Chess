from __future__ import annotations

import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from acs.runtime_dependency_release import (
    RuntimeDependencyReleaseError,
    publish_runtime_dependency_release_evidence,
)


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class RuntimeDependencyReleaseTests(unittest.TestCase):
    def _bundle(self, root: Path) -> Path:
        bundle = root / "bundle"
        bundle.mkdir()
        python_bytes = b"Python license\n"
        package_bytes = b"Package license\n"
        (bundle / "Python-LICENSE.txt").write_bytes(python_bytes)
        (bundle / "demo-1.2.3-NOTICE-01.txt").write_bytes(package_bytes)
        manifest = {
            "schema_version": 2,
            "scope": "qualified Python build/runtime dependency notice evidence",
            "python": {
                "version": "3.12.10",
                "packaged_file": "Python-LICENSE.txt",
                "sha256": _sha(python_bytes),
            },
            "distributions": [
                {
                    "distribution": "demo",
                    "version": "1.2.3",
                    "license_expression": "MIT",
                    "license_metadata": "MIT",
                    "project_urls": [],
                    "notice_files": [
                        {
                            "source_kind": "installed_distribution",
                            "source_path": "LICENSE",
                            "packaged_file": "demo-1.2.3-NOTICE-01.txt",
                            "sha256": _sha(package_bytes),
                        }
                    ],
                }
            ],
        }
        (bundle / "PYTHON_RUNTIME_DEPENDENCIES.json").write_text(
            json.dumps(manifest, sort_keys=True, indent=2) + "\n",
            encoding="utf-8",
        )
        return bundle

    def test_publishes_verified_bundle_and_spdx_into_existing_release_notices(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            bundle = self._bundle(root)
            notices = root / "third-party-notices"
            notices.mkdir()
            (notices / "Stockfish-NOTICE.txt").write_text("retained", encoding="utf-8")
            published = publish_runtime_dependency_release_evidence(
                bundle,
                notices,
                document_name="Accessible Chess qualified Windows runtime",
                created_utc="2026-09-26T16:00:00Z",
            )
            self.assertEqual(published.root, notices / "Python-Runtime")
            self.assertTrue(published.manifest_path.is_file())
            self.assertTrue(published.sbom_path.is_file())
            self.assertEqual(
                (notices / "Stockfish-NOTICE.txt").read_text(encoding="utf-8"),
                "retained",
            )
            self.assertEqual(
                (published.root / "demo-1.2.3-NOTICE-01.txt").read_bytes(),
                b"Package license\n",
            )
            spdx = json.loads(published.sbom_path.read_text(encoding="utf-8"))
            self.assertEqual(spdx["spdxVersion"], "SPDX-2.3")
            self.assertEqual({p["name"] for p in spdx["packages"]}, {"Python", "demo"})

    def test_rejects_untracked_bundle_content(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            bundle = self._bundle(root)
            (bundle / "mystery.txt").write_text("not manifested", encoding="utf-8")
            notices = root / "notices"
            notices.mkdir()
            with self.assertRaisesRegex(RuntimeDependencyReleaseError, "untracked"):
                publish_runtime_dependency_release_evidence(
                    bundle,
                    notices,
                    document_name="Accessible Chess runtime",
                    created_utc="2026-09-26T16:00:00Z",
                )
            self.assertFalse((notices / "Python-Runtime").exists())

    def test_rejects_notice_digest_mismatch_without_partial_publication(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            bundle = self._bundle(root)
            (bundle / "demo-1.2.3-NOTICE-01.txt").write_text("tampered", encoding="utf-8")
            notices = root / "notices"
            notices.mkdir()
            with self.assertRaisesRegex(RuntimeDependencyReleaseError, "SHA-256 mismatch"):
                publish_runtime_dependency_release_evidence(
                    bundle,
                    notices,
                    document_name="Accessible Chess runtime",
                    created_utc="2026-09-26T16:00:00Z",
                )
            self.assertFalse((notices / "Python-Runtime").exists())

    def test_rejects_duplicate_manifest_file_names(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            bundle = self._bundle(root)
            manifest_path = bundle / "PYTHON_RUNTIME_DEPENDENCIES.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["distributions"][0]["notice_files"][0]["packaged_file"] = "Python-LICENSE.txt"
            manifest["distributions"][0]["notice_files"][0]["sha256"] = manifest["python"]["sha256"]
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            notices = root / "notices"
            notices.mkdir()
            with self.assertRaisesRegex(RuntimeDependencyReleaseError, "duplicate files"):
                publish_runtime_dependency_release_evidence(
                    bundle,
                    notices,
                    document_name="Accessible Chess runtime",
                    created_utc="2026-09-26T16:00:00Z",
                )

    def test_refuses_existing_destination(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            bundle = self._bundle(root)
            notices = root / "notices"
            (notices / "Python-Runtime").mkdir(parents=True)
            with self.assertRaisesRegex(RuntimeDependencyReleaseError, "already exists"):
                publish_runtime_dependency_release_evidence(
                    bundle,
                    notices,
                    document_name="Accessible Chess runtime",
                    created_utc="2026-09-26T16:00:00Z",
                )


if __name__ == "__main__":
    unittest.main()
