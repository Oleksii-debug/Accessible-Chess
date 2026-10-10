"""Section 45/42 genuine hosted Web visual assets, strict principal and MIME QA."""
from __future__ import annotations

from pathlib import Path
import unittest

from tests.test_section34_web_client import Section34WebClientTests

ROOT = Path(__file__).resolve().parents[1]


class Section45ProfessionalWebAssetTests(unittest.TestCase):
    def setUp(self):
        self.harness = Section34WebClientTests()
        self.harness.setUp()

    def test_real_web_html_links_offline_css_studio_and_board_overlay(self):
        html = (ROOT / "web/accessible_chess_web.html").read_text(encoding="utf-8")
        for link in (
            '<link rel="stylesheet" href="/assets/accessible_chess_design.css">',
            '<script src="/assets/section45_design_studio.js"></script>',
            '<script src="/assets/board_overlay_renderer.js"></script>',
        ):
            self.assertIn(link, html)
        self.assertLess(
            html.index('<script src="/assets/board_overlay_renderer.js"></script>'),
            html.index('<script src="/assets/accessible_chess_web.js"></script>'),
        )
        self.assertIn('data-route="online"', html)
        self.assertIn('data-route="spectator"', html)

    def test_exact_authenticated_art_studio_and_css_only(self):
        expected = [
            ("/assets/section45_design_studio.js", b"text/javascript; charset=utf-8"),
            ("/assets/accessible_chess_design.css", b"text/css; charset=utf-8"),
            ("/assets/board_overlay_renderer.js", b"text/javascript; charset=utf-8"),
        ]
        expected += [
            ("/assets/pieces/rhosgfx/" + c + p + ".svg", b"image/svg+xml")
            for c in "wb" for p in "KQRBNP"
        ]
        self.assertEqual(len(expected), 15)
        for path, mime in expected:
            with self.subTest(path=path):
                ok = self.harness._asgi("GET", path)
                self.assertEqual(ok[0]["status"], 200)
                headers = dict(ok[0]["headers"])
                self.assertEqual(headers[b"content-type"], mime)
                self.assertEqual(headers[b"x-content-type-options"], b"nosniff")
                self.assertEqual(headers[b"cache-control"], b"no-store")
                self.assertGreater(len(ok[1]["body"]), 30)
                denied = self.harness._asgi("GET", path, principal=False)
                self.assertEqual(denied[0]["status"], 401)
                bad_query = self.harness._asgi("GET", path, query=b"remote=1")
                self.assertEqual(bad_query[0]["status"], 400)

    def test_remote_paths_and_traversal_have_no_generic_file_egress(self):
        for path in (
            "/assets/pieces/rhosgfx/../wK.svg",
            "/assets/pieces/rhosgfx/wK.svg/../bK.svg",
            "/assets/pieces/rhosgfx/wZ.svg",
            "/assets/pieces/rhosgfx/wK.SVG",
            "/assets/pieces/rhosgfx/SOURCE_COPYING.md",
            "/assets/section45_design_studio.js/../secrets",
            "/assets/accessible_chess_design.css/../.env",
            "/assets/pieces/other/wK.svg",
            "/assets/../../.env",
        ):
            with self.subTest(path=path):
                self.assertEqual(self.harness._asgi("GET", path)[0]["status"], 404)

    def test_no_second_chess_parser_or_remote_asset_loader(self):
        script = (ROOT / "web/section45_design_studio.js").read_text(encoding="utf-8")
        css = (ROOT / "web/assets/accessible_chess_design.css").read_text(encoding="utf-8")
        self.assertIn("get_design_studio_state", script)
        self.assertIn("save_design_studio_state", script)
        self.assertIn("aria-expanded", script)
        for forbidden in ("fetch(", "XMLHttpRequest", "WebSocket", "document.cookie", "innerHTML="):
            self.assertNotIn(forbidden, script)
        self.assertIn("@media(forced-colors:active)", css)
        self.assertIn("@media(prefers-reduced-motion:reduce)", css)


if __name__ == "__main__":
    unittest.main()
