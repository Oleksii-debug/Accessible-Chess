"""Section 41 installed UI provenance, accessible palette and offline WebView gates."""
from __future__ import annotations
import hashlib
import json
from pathlib import Path
import re
import tempfile
import unittest

from acs.spdx_sbom import validate_spdx_document
from tools.revised_section41_mit_asset_qualification import (
    ROOT, Section41AssetError, build_asset_fixture_spdx,
    git_blob_sha1, qualified_mit_icons,
)


def ratio(a: str, b: str) -> float:
    def luminosity(token):
        assert re.fullmatch(r"#[a-f0-9]{6}", token), token
        x = [int(token[i:i+2],16)/255 for i in (1,3,5)]
        v = [z/12.92 if z<=.04045 else ((z+.055)/1.055)**2.4 for z in x]
        return sum(u*y for u,y in zip(v,(.2126,.7152,.0722)))
    x,y=luminosity(a),luminosity(b)
    return (max(x,y)+.05)/(min(x,y)+.05)


def palette(css: str, theme: str) -> dict:
    selector = ":root{" if theme=="light" else ':root[data-ac-ui-theme="'+theme+'"]{'
    at=css.index(selector)+len(selector)
    segment=css[at:css.index("}",at)]
    return dict(re.findall(r"(--ac41-[a-z-]+):([^;]+);",segment))


class Section41RealDesignTests(unittest.TestCase):
    def test_original_icons_are_exact_release_git_blobs_with_mit_spdx(self):
        receipt, components=qualified_mit_icons()
        self.assertEqual(receipt["asset_count"],2)
        self.assertEqual(len(components),2)
        self.assertFalse(receipt["section41_done"])
        self.assertEqual(receipt["tabler_core_status"],"NOT_INSTALLED_NO_CLAIM")
        for item in receipt["items"]:
            blob=(ROOT/item["local"]).read_bytes()
            self.assertEqual(git_blob_sha1(blob),item["git_blob_sha1"])
            self.assertEqual(hashlib.sha256(blob).hexdigest(),item["sha256"])
        evidence,spdx=build_asset_fixture_spdx(root=ROOT,exact_commit="a"*40)
        validate_spdx_document(spdx)
        self.assertEqual(evidence,receipt)
        self.assertEqual(len(spdx["packages"]),3)
        self.assertTrue(all(p["licenseDeclared"]=="MIT" for p in spdx["packages"][1:]))

    def test_poisoned_svg_and_edited_license_fail_closed(self):
        files=["web/assets/tabler/SECTION41_PROVENANCE.json",
               "web/assets/tabler/chess-rook.svg",
               "web/assets/tabler/adjustments.svg",
               "web/assets/tabler/LICENSE"]
        with tempfile.TemporaryDirectory() as raw:
            root=Path(raw)
            for relative in files:
                dst=root/relative
                dst.parent.mkdir(parents=True,exist_ok=True)
                dst.write_bytes((ROOT/relative).read_bytes())
            svg=root/files[1]
            svg.write_bytes(svg.read_bytes()+b"<script>alert(1)</script>")
            with self.assertRaises(Section41AssetError):
                qualified_mit_icons(root=root)
            svg.write_bytes((ROOT/files[1]).read_bytes())
            license_file=root/files[3]
            license_file.write_bytes(license_file.read_bytes()+b"tampered")
            with self.assertRaises(Section41AssetError):
                qualified_mit_icons(root=root)

    def test_wCAG_22_AA_palette_contrast_and_forced_colours(self):
        css=(ROOT/"web/assets/accessible_chess_design.css").read_text(encoding="utf-8")
        for theme in ("light","dark","contrast"):
            with self.subTest(theme=theme):
                c=palette(css,theme)
                for a,b in (("ink","bg"),("ink","surface"),("muted","surface"),
                            ("link","surface"),("on-action","action")):
                    self.assertGreaterEqual(ratio(c["--ac41-"+a],c["--ac41-"+b]),4.5)
                self.assertGreaterEqual(ratio(c["--ac41-focus"],c["--ac41-surface"]),3)
        for token in ('data-ac-ui-theme="system"',"@media(prefers-color-scheme:dark)",
                      "@media(prefers-reduced-motion:reduce)",
                      "@media(forced-colors:active)","outline:3px solid Highlight"):
            self.assertIn(token,css)
        self.assertNotIn("@import",css)
        self.assertNotIn("https://",css)

    def test_windows_package_must_include_all_local_design_dependencies(self):
        from acs.version2_package_preflight import Version2PackagePreflightError
        from tests.test_version2_package_preflight import (
            _make_tree, _write_checksums, _validate_tree,
        )
        with tempfile.TemporaryDirectory(prefix="acs-section41-package-gate-") as raw:
            package=Path(raw)/"candidate"
            package.mkdir()
            _make_tree(package)
            html=package/"AccessibleChess/web/index.html"
            html.write_text(
                '<!doctype html><html><head><link rel="stylesheet" '
                'href="assets/accessible_chess_design.css"></head><body>fixture</body></html>',
                encoding="utf-8",
            )
            _write_checksums(package)
            with self.assertRaises(Version2PackagePreflightError):
                _validate_tree(package)
            for relative in (
                "web/assets/accessible_chess_design.css",
                "web/assets/tabler/chess-rook.svg",
                "web/assets/tabler/adjustments.svg",
                "web/assets/tabler/LICENSE",
                "web/assets/tabler/SECTION41_PROVENANCE.json",
            ):
                dest=package/"AccessibleChess"/relative
                dest.parent.mkdir(parents=True,exist_ok=True)
                dest.write_bytes((ROOT/relative).read_bytes())
            _write_checksums(package)
            _validate_tree(package)

    def test_webview_and_web_use_one_local_stylesheet_and_semantic_controls(self):
        for path in ("web/index.html","web/accessible_chess_web.html"):
            with self.subTest(path=path):
                s=(ROOT/path).read_text(encoding="utf-8")
                self.assertIn('href="assets/accessible_chess_design.css"',s)
                self.assertIn('for="ac41-theme"',s)
                self.assertIn('id="ac41-theme"',s)
                for mode in ("system","light","dark","contrast"):
                    self.assertIn('<option value="'+mode+'">',s)
                self.assertIn("document.documentElement.dataset.acUiTheme",s)
                self.assertNotIn("cdn.jsdelivr.net",s)
        index=(ROOT/"web/index.html").read_text(encoding="utf-8")
        self.assertIn('id="board-grid"',index)
        self.assertIn('id="move-input"',index)
        self.assertIn("window.addEventListener('pywebviewready'",index)


if __name__=="__main__":
    unittest.main()
