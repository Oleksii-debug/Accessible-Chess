"""Exact original Tabler Core v1.6.1 MIT CSS source, license and package qualification."""
from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from tools.revised_section41_mit_asset_qualification import (
    ROOT, Section41AssetError, git_blob_sha1, qualified_mit_tabler_core,
)


class Section41TablerCoreTests(unittest.TestCase):
    def test_original_mit_upstream_and_local_css(self):
        report, package = qualified_mit_tabler_core()
        self.assertEqual(report["version"], "1.6.1")
        self.assertEqual(report["license"], "MIT")
        self.assertEqual(package.license_declared, "MIT")
        expected = {
            "docs/third_party/tabler-core-1.6.1-accessibility.scss":
                "047720ee79039e213612cfbadd6af357534a7735",
            "web/assets/tabler-core/LICENSE":
                "aa69649cde83c2d6517ec2498a9c10f5bb3bf54c",
            "web/assets/tabler-core/accessibility.css":
                "0fe8f69f90411731513c9926827fb609bf51b267",
        }
        for name, digest in expected.items():
            with self.subTest(name=name):
                self.assertEqual(git_blob_sha1((ROOT/name).read_bytes()), digest)

    def test_core_asset_mutation_fails_qualification(self):
        names = (
            "docs/third_party/tabler-core-1.6.1-accessibility.scss",
            "web/assets/tabler-core/LICENSE",
            "web/assets/tabler-core/accessibility.css",
            "web/assets/tabler-core/SECTION41_CORE_PROVENANCE.json",
        )
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            for name in names:
                dst = root/name
                dst.parent.mkdir(parents=True, exist_ok=True)
                dst.write_bytes((ROOT/name).read_bytes())
            for name in names[:3]:
                with self.subTest(name=name):
                    path = root/name
                    original = path.read_bytes()
                    path.write_bytes(original + b"modified")
                    with self.assertRaises(Section41AssetError):
                        qualified_mit_tabler_core(root=root)
                    path.write_bytes(original)

    def test_unreviewed_framework_or_license_qualification_is_rejected(self):
        manifest = ROOT/"web/assets/tabler-core/SECTION41_CORE_PROVENANCE.json"
        data = json.loads(manifest.read_text(encoding="utf-8"))
        self.assertEqual(data["source_commit"], "ec33733290bd0f314ca19f6be58bc69a6ab3e4fa")
        self.assertEqual(data["upstream_license"], "MIT")
        self.assertNotIn("apexcharts", str(data["component_scope"]).lower())
        self.assertFalse(data["section41_done"])


if __name__ == "__main__":
    unittest.main()
