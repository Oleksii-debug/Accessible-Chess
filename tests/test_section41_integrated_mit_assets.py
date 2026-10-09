"""Section 41 main integration: exact MIT assets and nonintrusive accessibility."""
from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from acs.spdx_sbom import validate_spdx_document
from tools.revised_section41_mit_asset_qualification import (
    ROOT, Section41AssetError, build_asset_fixture_spdx, git_blob_sha1,
    qualified_mit_icons, qualified_mit_tabler_core,
)


class Section41IntegratedMITAssetsTests(unittest.TestCase):
    def test_exact_upstream_icons_notice_and_spdx(self):
        receipt, records = qualified_mit_icons()
        self.assertEqual(receipt["asset_count"], 2)
        self.assertEqual(len(records), 2)
        self.assertFalse(receipt["paid_assets_included"])
        for row in receipt["items"]:
            self.assertEqual(
                git_blob_sha1((ROOT / row["local"]).read_bytes()),
                row["git_blob_sha1"],
            )
        evidence, spdx = build_asset_fixture_spdx(root=ROOT, exact_commit="a" * 40)
        validate_spdx_document(spdx)
        self.assertEqual(evidence["items"], receipt["items"])
        self.assertEqual(len(spdx["packages"]), 4)

    def test_tabler_core_is_pinned_isolated_mit_css(self):
        receipt, component = qualified_mit_tabler_core()
        self.assertEqual(receipt["license"], "MIT")
        self.assertEqual(receipt["version"], "1.6.1")
        self.assertEqual(component.license_declared, "MIT")
        css = (ROOT / "web/assets/tabler-core/accessibility.css").read_text()
        self.assertIn("forced-colors", css)
        self.assertIn("prefers-reduced-motion", css)
        self.assertNotIn("@import", css)
        self.assertNotIn("https://", css)

    def test_poisoned_icon_and_license_are_rejected(self):
        files = (
            "web/assets/tabler/SECTION41_PROVENANCE.json",
            "web/assets/tabler/chess-rook.svg",
            "web/assets/tabler/adjustments.svg",
            "web/assets/tabler/LICENSE",
        )
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for name in files:
                dest = root / name
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_bytes((ROOT / name).read_bytes())
            icon = root / files[1]
            original = icon.read_bytes()
            icon.write_bytes(original + b"<script>alert(1)</script>")
            with self.assertRaises(Section41AssetError):
                qualified_mit_icons(root=root)
            icon.write_bytes(original)
            license_file = root / files[3]
            license_file.write_bytes(license_file.read_bytes() + b"corrupted")
            with self.assertRaises(Section41AssetError):
                qualified_mit_icons(root=root)

    def test_product_uses_one_existing_design_authority_and_local_tabler_css(self):
        html = (ROOT / "web/index.html").read_text(encoding="utf-8")
        self.assertIn('href="design_system.css"', html)
        self.assertIn('href="assets/tabler-core/accessibility.css"', html)
        self.assertIn('id="visual-theme"', html)
        self.assertIn('id="language-select"', html)
        self.assertIn('aria-live="polite"', html)
        self.assertNotIn("cdn.jsdelivr.net", html)
        self.assertNotIn('<script src="http', html)
        self.assertNotIn('<link rel="stylesheet" href="http', html)

    def test_component_fixture_has_semantic_keyboard_and_copy_controls(self):
        page = (ROOT / "web/section41_components.html").read_text(encoding="utf-8")
        self.assertIn('href="assets/tabler-core/accessibility.css"', page)
        self.assertIn('href="assets/accessible_chess_design.css"', page)
        self.assertIn('aria-labelledby="dialog-heading"', page)
        self.assertIn('aria-describedby="dialog-help"', page)
        self.assertIn('id="copy-content" tabindex="0"', page)
        self.assertIn('aria-hidden="true"', page)
        self.assertIn('id="fixture-search"', page)
        self.assertIn('role="status"', page)
        self.assertIn('event.preventDefault()', page)
        self.assertIn('openButton.focus({preventScroll:true})', page)
        self.assertNotIn('<script src="http', page)

    def test_manifest_excludes_paid_and_unqualified_bundles(self):
        for name in (
            "web/assets/tabler/SECTION41_PROVENANCE.json",
            "web/assets/tabler-core/SECTION41_CORE_PROVENANCE.json",
        ):
            data = json.loads((ROOT / name).read_text(encoding="utf-8"))
            self.assertNotIn("ApexCharts", str(data.get("component_scope", [])))
            self.assertFalse(data.get("section41_done", False))
        provenance = json.loads(
            (ROOT / "web/assets/tabler/SECTION41_PROVENANCE.json").read_text(encoding="utf-8")
        )
        self.assertIn("apexcharts", provenance["prohibited"])
        self.assertIn("@tabler/pro", provenance["prohibited"])


if __name__ == "__main__":
    unittest.main()
