from __future__ import annotations

import ast
from pathlib import Path
import unittest

from tests.test_section34_web_client import Section34WebClientTests

ROOT = Path(__file__).resolve().parent.parent


class Section46VisualContracts(unittest.TestCase):
    def test_every_authenticated_local_design_asset_is_served_without_leaking(self):
        base = Section34WebClientTests("test_semantic_document_and_script_are_browser_native")
        base.setUp()
        assets = {
            "/assets/accessible_chess_design.css": b"text/css",
            "/assets/tabler-core/accessibility.css": b"text/css",
            "/assets/section45_design_studio.js": b"text/javascript",
        }
        for path, content_type in assets.items():
            with self.subTest(asset=path):
                response = base._asgi("GET", path)
                self.assertEqual(response[0]["status"], 200)
                headers = dict(response[0]["headers"])
                self.assertIn(content_type, headers[b"content-type"])
                self.assertTrue(response[1]["body"])
                denied = base._asgi("GET", path, principal=False)
                self.assertEqual(denied[0]["status"], 401)
                with_query = base._asgi("GET", path, query=b"user_id=other")
                self.assertEqual(with_query[0]["status"], 400)
        for path in ("/assets/../../acs/settings.py", "/assets/section45_design_studio.js/../settings"):
            self.assertNotEqual(base._asgi("GET", path)[0]["status"], 200)

    def test_real_windows_and_web_studio_routes_are_in_original_documents(self):
        win = (ROOT / "web/index.html").read_text(encoding="utf-8")
        browser = (ROOT / "web/accessible_chess_web.html").read_text(encoding="utf-8")
        js = (ROOT / "web/section45_design_studio.js").read_text(encoding="utf-8")
        css = (ROOT / "web/assets/accessible_chess_design.css").read_text(encoding="utf-8")
        design = (ROOT / "web/design_system.css").read_text(encoding="utf-8")
        self.assertIn('src="section45_design_studio.js"', win)
        self.assertIn('src="/assets/section45_design_studio.js"', browser)
        self.assertIn('id="visual-theme"', win)
        self.assertIn('id="workspace"', browser)
        self.assertIn('document.querySelector("header")||document.body', js)
        self.assertIn('/assets/tabler-core/accessibility.css', browser)
        self.assertIn('box-sizing:border-box;max-width:100%;min-width:0', css)
        self.assertIn('#ac45-name{display:block;margin-block:var(--ac41-space-2);min-width:0', css)
        self.assertIn('grid-template-columns:repeat(8,minmax(0,1fr));width:min(100%,52rem)', win)
        self.assertIn('#main-content > section > h2 { min-width: 0; flex-wrap: wrap;', design)
        self.assertIn('#video-source-url, #ai-agent-region input[type="url"] { min-width: 0; width: 100%; }', design)
        self.assertIn('box-sizing: border-box;', design)
        self.assertIn('#main-content > section fieldset {', design)
        self.assertIn('box-sizing:border-box;min-width:0;max-width:100%;width:100%;', design)
        self.assertIn('.brand-lockup { display: flex; flex-wrap: wrap;', design)
        self.assertIn(':root[data-ac-ui-theme="contrast"] .eyebrow { color: #ffff00; }', design)
        self.assertIn('.eyebrow { color: CanvasText !important; }', design)
        self.assertIn('#board-grid[role=grid] > [role=row]{display:contents}', css)
        for name in ("Classic", "Tournament", "Coach", "Classroom Presentation",
                     "Low Vision", "High Contrast"):
            self.assertIn(name, js)
        for token in ('setAttribute("aria-expanded"', 'aria-live"', "preview()",
                      "function validPrefs(", "function validStore(", "localStorage",
                      "get_design_studio_state", "save_design_studio_state"):
            self.assertIn(token, js)
        self.assertNotIn("innerHTML=", js.replace(" ", ""))
        self.assertNotIn("chess.Board(", js)
        for token in ("forced-colors:active", "prefers-reduced-motion:reduce",
                      ":focus-visible", "#ac45-studio", "@media(max-width:40rem)",
                      "--ac45-font-scale"):
            self.assertIn(token, css)

    def test_licenses_and_local_asset_refs_are_present(self):
        for name in ("web/assets/tabler/LICENSE",
                     "web/assets/tabler-core/LICENSE",
                     "web/assets/pieces/rhosgfx/SOURCE_COPYING.md"):
            with self.subTest(path=name):
                file = ROOT / name
                self.assertTrue(file.is_file(), name)
                self.assertGreater(len(file.read_bytes()), 20)
        for name in ("web/assets/accessible_chess_design.css",
                     "web/section45_design_studio.js"):
            s = (ROOT / name).read_text(encoding="utf-8")
            self.assertNotIn("@import url(http", s.lower())
            self.assertNotIn("https://cdn.", s)
        self.assertIn("rhosgfx", (ROOT / "web/index.html").read_text(encoding="utf-8"))

    def test_settings_and_api_depend_on_one_canonical_writer(self):
        source = (ROOT / "acs/stage1_release_ui.py").read_text(encoding="utf-8")
        self.assertIn('self._settings.set("design_profiles_json", encoded)', source)
        self.assertIn("self.get_design_studio_state()", source)
        self.assertNotIn("pickle.", (ROOT / "acs/section45_design_profiles.py").read_text(encoding="utf-8"))
        ast.parse((ROOT / "acs/section45_design_profiles.py").read_text(encoding="utf-8"))
        ast.parse(source)


if __name__ == "__main__":
    unittest.main()
