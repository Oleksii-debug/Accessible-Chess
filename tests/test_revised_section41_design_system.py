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
    git_blob_sha1, qualified_mit_icons, qualified_mit_tabler_core,
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
        self.assertEqual(receipt["tabler_core_status"],"REVIEWED_CSS_COMPONENT_ONLY")
        for item in receipt["items"]:
            blob=(ROOT/item["local"]).read_bytes()
            self.assertEqual(git_blob_sha1(blob),item["git_blob_sha1"])
            self.assertEqual(hashlib.sha256(blob).hexdigest(),item["sha256"])
        evidence,spdx=build_asset_fixture_spdx(root=ROOT,exact_commit="a"*40)
        validate_spdx_document(spdx)
        self.assertEqual(evidence["items"],receipt["items"])
        self.assertEqual(evidence["tabler_core"]["version"],"1.6.1")
        self.assertEqual(len(spdx["packages"]),4)
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

    def test_offline_component_fixture_has_native_keyboard_semantics_and_focus_recovery(self):
        page=(ROOT/"web/section41_components.html").read_text(encoding="utf-8")
        for term in (
            'href="#main"', 'id="main" tabindex="-1"', 'aria-label="Навігація прикладів"',
            '<form id="fixture-form">', '<fieldset>', '<legend>',
            '<th scope="col">', '<th scope="row">',
            'role="status" aria-live="polite"', '<dialog id="fixture-dialog"',
            'aria-labelledby="dialog-heading"', 'aria-describedby="dialog-help"',
            'dialog.showModal()', 'dialog.addEventListener("close",',
            'openButton.focus({preventScroll:true})', '<summary>',
            'id="copy-content" tabindex="0"', 'assets/accessible_chess_design.css',
        ):
            with self.subTest(component=term):
                self.assertIn(term,page)
        self.assertNotIn('onfocus=',page)
        self.assertNotIn('onblur=',page)
        self.assertNotIn('onerror=',page)
        self.assertNotIn('<script src="http',page)
        css=(ROOT/"web/assets/accessible_chess_design.css").read_text(encoding="utf-8")
        self.assertIn('.ac41-skip:focus-visible',css)

    def test_real_webview_theme_styles_override_old_inline_body_and_block_css(self):
        style=(ROOT/"web/assets/accessible_chess_design.css").read_text(encoding="utf-8")
        self.assertIn("body{background:var(--ac41-bg);color:var(--ac41-ink);",style)
        self.assertIn(".block,fieldset,dialog{background:var(--ac41-surface);color:var(--ac41-ink);",style)
        self.assertIn("a{color:var(--ac41-link);",style)
        self.assertNotIn(":where(body){background:var(--ac41-bg)",style)
        self.assertNotIn(":where(fieldset,dialog,.block){background:var(--ac41-surface)",style)
        for html_file in ("web/index.html","web/accessible_chess_web.html"):
            with self.subTest(html_file=html_file):
                page=(ROOT/html_file).read_text(encoding="utf-8")
                self.assertLess(page.index("</style>"),
                    page.index('<link rel="stylesheet" href="assets/accessible_chess_design.css">'))
        # Inline Stage1 'body' and '.block' previously defeated any
        # zero-specificity :where selector even though stylesheet loaded last.
        self.assertIn("body{margin:0;padding:",(ROOT/"web/index.html").read_text(encoding="utf-8"))
        self.assertIn(".block{white-space:pre-wrap",(
            ROOT/"web/index.html").read_text(encoding="utf-8"))

    def test_real_live_board_gametree_unchanged_by_persistent_theme(self):
        from acs.settings import Settings
        from acs.stage1_release_ui_core import Stage1ReleaseAccessibleChessAPI
        with tempfile.TemporaryDirectory(prefix="ac41-real-core-") as tmp:
            settings_path=Path(tmp)/"settings.json"
            api=Stage1ReleaseAccessibleChessAPI(
                keymap_path=Path(tmp)/"keymap.json",
                settings=Settings(settings_path),
            )
            try:
                prior_fen=api.board.fen()
                prior_game=api.review_history.export_tree()
                self.assertEqual(api.get_state()["uiTheme"],"system")
                for mode in ("dark","contrast","light","system"):
                    with self.subTest(mode=mode):
                        self.assertEqual(
                            api.set_ui_theme(mode),{"ok":True,"uiTheme":mode})
                        state=api.get_state()
                        self.assertEqual(state["uiTheme"],mode)
                        self.assertEqual(api.board.fen(),prior_fen)
                        self.assertEqual(api.review_history.export_tree(),prior_game)
                        self.assertEqual(len(state["visualBoard"]["cells"]),64)
                self.assertEqual(api.set_ui_theme("dark")["uiTheme"],"dark")
            finally:
                api.close_analysis()
            reopened=Stage1ReleaseAccessibleChessAPI(
                keymap_path=Path(tmp)/"next-keymap.json",
                settings=Settings(settings_path),
            )
            try:
                self.assertEqual(reopened.get_state()["uiTheme"],"dark")
            finally:
                reopened.close_analysis()

    def test_restart_persists_ui_theme_through_one_canonical_settings_owner(self):
        from acs.settings import Settings, SettingsError
        from acs.stage1_release_ui_core import Stage1ReleaseAccessibleChessAPI
        with tempfile.TemporaryDirectory(prefix="ac41-settings-") as tmp:
            location=Path(tmp)/"settings.json"
            settings=Settings(location)
            api=object.__new__(Stage1ReleaseAccessibleChessAPI)
            api._settings=settings
            self.assertEqual(api.get_ui_theme()["uiTheme"],"system")
            for theme in ("dark","light","contrast","system"):
                with self.subTest(theme=theme):
                    result=api.set_ui_theme(theme)
                    self.assertEqual(result,{"ok":True,"uiTheme":theme})
                    reopened=Settings(location)
                    after=object.__new__(Stage1ReleaseAccessibleChessAPI)
                    after._settings=reopened
                    self.assertEqual(after.get_ui_theme()["uiTheme"],theme)
                    self.assertEqual(reopened.get("ui_theme"),theme)
            settings.set("ui_theme","contrast")
            self.assertEqual(api.get_ui_theme()["uiTheme"],"contrast")
            for invalid in ("#fafafa","SYSTEM","<script>",None,42,True):
                with self.subTest(invalid=invalid):
                    self.assertFalse(api.set_ui_theme(invalid)["ok"])
                    self.assertEqual(Settings(location).get("ui_theme"),"contrast")
            no_settings=object.__new__(Stage1ReleaseAccessibleChessAPI)
            no_settings._settings=None
            self.assertFalse(no_settings.set_ui_theme("dark")["ok"])
            self.assertEqual(no_settings.get_ui_theme()["uiTheme"],"system")
            with self.assertRaises(SettingsError):
                Settings(location).set("ui_theme","unexpected")

    def test_production_webview_theme_change_roundtrips_only_via_durable_api(self):
        html=(ROOT/"web/index.html").read_text(encoding="utf-8")
        self.assertIn("async function loadAc41Theme()",html)
        self.assertIn("await a.get_ui_theme()",html)
        self.assertIn("await a.set_ui_theme(wanted)",html)
        self.assertIn("let ac41ThemeSaveInFlight=false",html)
        self.assertIn("control.disabled=true",html)
        self.assertIn("finally{control.disabled=false;ac41ThemeSaveInFlight=false}",html)
        self.assertIn("const current=await a.get_ui_theme()",html)
        self.assertIn("recovered=current.uiTheme",html)
        self.assertIn("applyAc41Theme(recovered)",html)
        self.assertIn("if(!result||result.ok!==true||result.uiTheme!==wanted)",html)
        self.assertIn("await loadAc41Theme();await loadKeymap()",html)
        self.assertNotIn("localStorage.setItem",html)
        # The first-party Web-only demo can be ephemeral; only desktop
        # claims persistence after an acknowledged Settings.set.
        self.assertIn("state[\"uiTheme\"] = self.get_ui_theme()",(
            ROOT/"acs/stage1_release_ui_core.py").read_text(encoding="utf-8"))

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
                'href="assets/accessible_chess_design.css"><link rel="stylesheet" href="assets/tabler-core/accessibility.css"></head><body>fixture</body></html>',
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
                "web/assets/tabler-core/accessibility.css",
                "web/assets/tabler-core/LICENSE",
                "web/assets/tabler-core/SECTION41_CORE_PROVENANCE.json",
            ):
                dest=package/"AccessibleChess"/relative
                dest.parent.mkdir(parents=True,exist_ok=True)
                dest.write_bytes((ROOT/relative).read_bytes())
            _write_checksums(package)
            _validate_tree(package)
            for part in ("web/assets/tabler/chess-rook.svg",
                         "web/assets/tabler-core/accessibility.css"):
                with self.subTest(tampered=part):
                    target=package/"AccessibleChess"/part
                    original=target.read_bytes()
                    target.write_bytes(original+b"tampered")
                    _write_checksums(package)
                    with self.assertRaises(Version2PackagePreflightError):
                        _validate_tree(package)
                    target.write_bytes(original)
                    _write_checksums(package)
                    _validate_tree(package)

    def test_webview_and_web_use_one_local_stylesheet_and_semantic_controls(self):
        for path in ("web/index.html","web/accessible_chess_web.html"):
            with self.subTest(path=path):
                s=(ROOT/path).read_text(encoding="utf-8")
                self.assertIn('href="assets/accessible_chess_design.css"',s)
                self.assertIn('href="assets/tabler-core/accessibility.css"',s)
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
