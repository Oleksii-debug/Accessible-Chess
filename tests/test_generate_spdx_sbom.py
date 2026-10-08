from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from tools.generate_spdx_sbom import (
    ManifestError,
    generate,
    load_release_manifest,
    main,
)


class GenerateSpdxSbomTests(unittest.TestCase):
    def manifest(self):
        return {
            "schema_version": 1,
            "created_at": "2026-09-26T21:00:00Z",
            "product": {
                "name": "Accessible Chess",
                "version": "0.4.0-dev3",
                "source_sha": "1" * 40,
                "sha256": "2" * 64,
                "supplier": "NOASSERTION",
                "license_declared": "NOASSERTION",
            },
            "components": [
                {
                    "name": "Alpha",
                    "version": "1.0",
                    "artifact_sha256": "a" * 64,
                    "license_declared": "MIT",
                    "purl": "pkg:pypi/alpha@1.0",
                }
            ],
        }

    def write_manifest(self, root: Path, value=None) -> Path:
        path = root / "release-components.json"
        path.write_text(
            json.dumps(self.manifest() if value is None else value),
            encoding="utf-8",
        )
        return path

    def test_generate_writes_valid_deterministic_spdx(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            manifest = self.write_manifest(root)
            output = root / "release.spdx.json"
            first = generate(manifest, output)
            self.assertEqual(first, output.read_text(encoding="utf-8"))
            second = generate(manifest, output)
            self.assertEqual(first, second)
            parsed = json.loads(second)
            self.assertEqual(parsed["spdxVersion"], "SPDX-2.3")
            self.assertEqual(parsed["packages"][1]["name"], "Alpha")

    def test_duplicate_json_keys_fail_closed(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            path = root / "manifest.json"
            path.write_text(
                '{"schema_version":1,"schema_version":1,'
                '"created_at":"2026-09-26T21:00:00Z",'
                '"product":{},"components":[]}',
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ManifestError, "duplicate JSON key"):
                load_release_manifest(path)

    def test_unknown_manifest_or_component_fields_fail_closed(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            value = self.manifest()
            value["unexpected"] = True
            with self.assertRaises(ManifestError):
                generate(self.write_manifest(root, value), root / "out.json")

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            value = self.manifest()
            value["components"][0]["unexpected"] = True
            with self.assertRaisesRegex(ManifestError, "component 0 keys"):
                generate(self.write_manifest(root, value), root / "out.json")

    def test_noncanonical_created_at_fails_closed(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            value = self.manifest()
            value["created_at"] = "2026-09-26T23:00:00+02:00"
            with self.assertRaisesRegex(ManifestError, "canonical UTC"):
                generate(self.write_manifest(root, value), root / "out.json")

    def test_input_symlink_is_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            real = self.write_manifest(root)
            link = root / "linked.json"
            try:
                link.symlink_to(real.name)
            except (OSError, NotImplementedError):
                self.skipTest("symlink creation unavailable")
            with self.assertRaisesRegex(ManifestError, "non-symlink"):
                load_release_manifest(link)

    def test_output_symlink_is_rejected_without_touching_target(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            manifest = self.write_manifest(root)
            target = root / "target.json"
            target.write_text("KEEP", encoding="utf-8")
            link = root / "release.spdx.json"
            try:
                link.symlink_to(target.name)
            except (OSError, NotImplementedError):
                self.skipTest("symlink creation unavailable")
            with self.assertRaisesRegex(ManifestError, "non-symlink"):
                generate(manifest, link)
            self.assertEqual(target.read_text(encoding="utf-8"), "KEEP")

    def test_cli_returns_nonzero_and_does_not_publish_on_bad_manifest(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            value = self.manifest()
            value["product"]["sha256"] = "bad"
            manifest = self.write_manifest(root, value)
            output = root / "release.spdx.json"
            self.assertEqual(
                main(["--input", str(manifest), "--output", str(output)]),
                2,
            )
            self.assertFalse(output.exists())


if __name__ == "__main__":
    unittest.main()
