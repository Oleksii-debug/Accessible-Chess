"""Section 41 canonical-main offline MIT asset and semantic UI convergence gates."""
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
    qualified_mit_icons, qualified_mit_tabler_core,
)


def _contrast(left: str, right: str) -> float:
    def luma(h: str) -> float:
        channels = [int(h[i:i + 2], 16) / 255 for i in (1, 3, 5)]
        channels = [x / 12.92 if x <= .04045 else ((x + .055) / 1.055) ** 2.4 for x in channels]
        return sum(a * b for a, b in zip(channels, (.2126, .7152, .0722)))
    a, b = sorted((luma(left), luma(right)), reverse=True)
    return (a + .05) / (b + .05)


class Section41CanonicalUIQualification(unittest.TestCase):
    def test_exact_original_upstream_assets_and_spdx(self):
        icons, components = qualified_mit_icons()
        core, _ = qualified_mit_tabler_core()
        self.assertEqual(icons["asset_count"], 2)
        self.assertEqual(core["version"], "1.6.1")
        self.assertEqual(len(components), 2)
        _, sbom = build_asset_fixture_spdx(root=ROOT, exact_commit="a" * 40)
        validate_spdx_document(sbom)
        self.assertEqual(len(sbom["packages"]), 4)
        self.assertTrue(all(row["licenseDeclared"] == "MIT" for row in sbom["packages"][1:]))
        self.assertNotIn("apexcharts", str(sbom).lower())
        self.assertNotIn("@tabler/pro", str(sbom).lower())

    def test_poisoned_svg_and_notice_rejected(self):
        names = [
            "web/assets/tabler/SECTION41_PROVENANCE.json",
            "web/assets/tabler/chess-rook.svg",
            "web/assets/tabler/adjustments.svg",
            "web/assets/tabler/LICENSE",
        ]
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            for relative in names:
                target = base / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes((ROOT / relative).read_bytes())
            for name, injection in (
                (names[1], b"<script>evil()</script>"),
                (names[3], b"MIT notice corrupted"),
            ):
                target = base / name
                original = target.read_bytes()
                target.write_bytes(original + injection)
                with self.assertRaises(Section41AssetError):
                    qualified_mit_icons(root=base)
                target.write_bytes(original)
            icons, _ = qualified_mit_icons(root=base)
            self.assertEqual(icons["asset_count"], 2)

    def test_main_webview_consumes_offline_assets_without_second_chess_core(self):
        html = (ROOT / "web/index.html").read_text(encoding="utf-8")
        self.assertEqual(html.count('href="assets/tabler-core/accessibility.css"'), 1)
        self.assertEqual(html.count('href="assets/accessible_chess_design.css"'), 1)
        self.assertIn('src="assets/tabler/chess-rook.svg"', html)
        self.assertIn('alt="" aria-hidden="true" focusable="false"', html)
        self.assertLess(html.index('href="assets/accessible_chess_design.css"'),
                        html.index('href="design_system.css"'))
        self.assertIn('id="visual-theme"', html)
        self.assertIn('id="visual-profile"', html)
        self.assertIn('id="visual-apply"', html)
        for value in ("system", "light", "dark", "contrast"):
            self.assertIn('<option value="' + value + '">', html)
        self.assertIn('id="board-grid"', html)
        self.assertNotIn("cdn.jsdelivr.net", html)
        self.assertNotIn('<script src="http', html)
        self.assertNotIn('<link rel="stylesheet" href="http', html)

    def test_wCAG_22_AA_palette_and_keyboard_forced_colors_motion(self):
        css = (ROOT / "web/assets/accessible_chess_design.css").read_text(encoding="utf-8")
        for theme, marker in (
            ("light", ":root{"),
            ("dark", ':root[data-ac-ui-theme="dark"]{'),
            ("contrast", ':root[data-ac-ui-theme="contrast"]{'),
        ):
            with self.subTest(theme=theme):
                start = css.index(marker) + len(marker)
                vals = dict(re.findall(r"(--ac41-[a-z-]+):([^;]+);", css[start:css.index("}", start)]))
                for one, other in (
                    ("ink", "bg"), ("ink", "surface"), ("muted", "surface"),
                    ("link", "surface"), ("on-action", "action")
                ):
                    self.assertGreaterEqual(
                        _contrast(vals["--ac41-" + one], vals["--ac41-" + other]), 4.5,
                        f"{theme}: {one}/{other}",
                    )
                self.assertGreaterEqual(_contrast(vals["--ac41-focus"], vals["--ac41-surface"]), 3)
        for rule in (
            ':root[data-ac-ui-theme="system"]',
            "@media(prefers-color-scheme:dark)",
            "@media(forced-colors:active)",
            "@media(prefers-reduced-motion:reduce)",
            "outline:3px solid Highlight",
            "max-width:100%",
        ):
            self.assertIn(rule, css)
        self.assertNotIn("@import", css)
        self.assertNotIn("https://", css)
        self.assertNotIn("http://", css)

    def test_semantic_demo_has_actual_controls_and_copyable_text(self):
        demo = (ROOT / "web/section41_components.html").read_text(encoding="utf-8")
        for marker in (
            'href="assets/tabler-core/accessibility.css"',
            'href="assets/accessible_chess_design.css"',
            '<main id="main" tabindex="-1">',
            '<nav aria-label=', '<th scope="col">',
            '<dialog id="fixture-dialog"',
            'aria-describedby="dialog-help"',
            'id="copy-content" tabindex="0"',
            'role="status" aria-live="polite"',
            "dialog.showModal()",
            "openButton.focus({preventScroll:true})",
        ):
            self.assertIn(marker, demo)
        self.assertNotIn('contenteditable="true"', demo)
        self.assertNotIn('window.location=', demo)


if __name__ == "__main__":
    unittest.main()
