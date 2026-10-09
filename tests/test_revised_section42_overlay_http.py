"""No generic static file server: exact offline chess-art/CSS/overlay allowlist."""
from pathlib import Path
import unittest
from unittest.mock import patch
from acs.web_client_http import WebClientHttpError
from tests.test_section34_web_client import Section34WebClientTests

ROOT=Path(__file__).resolve().parents[1]

class Section42LocalAssetsHttpTests(unittest.TestCase):
    def setUp(self):
        self.harness=Section34WebClientTests()
        self.harness.setUp()

    def test_all_required_assets_serve_with_explicit_mime_and_auth(self):
        names=[
            ("/assets/accessible_chess_design.css",b"text/css; charset=utf-8"),
            ("/assets/tabler-core/accessibility.css",b"text/css; charset=utf-8"),
            ("/assets/tabler/chess-rook.svg",b"image/svg+xml"),
            ("/assets/tabler/adjustments.svg",b"image/svg+xml"),
            ("/assets/board_overlay_renderer.js",b"text/javascript; charset=utf-8"),
        ]+[(f"/assets/pieces/rhosgfx/{color}{piece}.svg",b"image/svg+xml")
          for color in "wb" for piece in "KQRBNP"]
        self.assertEqual(len(names),17)
        for name,mime in names:
            with self.subTest(name=name):
                res=self.harness._asgi("GET",name)
                self.assertEqual(res[0]["status"],200)
                headers=dict(res[0]["headers"])
                self.assertEqual(headers[b"content-type"],mime)
                self.assertEqual(headers[b"x-content-type-options"],b"nosniff")
                self.assertEqual(headers[b"cache-control"],b"no-store")
                self.assertGreater(len(res[1]["body"]),30)
                denied=self.harness._asgi("GET",name,principal=False)
                self.assertEqual(denied[0]["status"],401)

    def test_traversal_remote_art_and_injected_query_never_reach_static_reader(self):
        for path in (
            "/assets/pieces/rhosgfx/../wK.svg",
            "/assets/pieces/rhosgfx/wK.svg/../bK.svg",
            "/assets/pieces/rhosgfx/wK.svg%2f..%2fpackage.json",
            "/assets/pieces/evil.svg",
            "/assets/../../.env",
            "/assets/COPYING.md",
            "/assets/pieces/rhosgfx/wX.svg",
        ):
            with self.subTest(path=path):
                response=self.harness._asgi("GET",path)
                self.assertEqual(response[0]["status"],404)
        query=self.harness._asgi("GET","/assets/pieces/rhosgfx/wK.svg",query=b"path=../../etc")
        self.assertEqual(query[0]["status"],400)
        with patch("acs.web_client_http._local_visual_asset",
                   side_effect=WebClientHttpError(503,"Local visual asset unavailable.")):
            response=self.harness._asgi("GET","/assets/pieces/rhosgfx/wK.svg")
            self.assertEqual(response[0]["status"],503)

    def test_exact_same_aria_silent_overlay_renderer_both_clients(self):
        code=(ROOT/"web/board_overlay_renderer.js").read_text(encoding="utf-8")
        self.assertIn("globalThis.AccessibleChessBoardOverlay = Object.freeze({project})",code)
        self.assertIn('svg.setAttribute("aria-hidden","true")',code)
        self.assertIn('svg.setAttribute("focusable","false")',code)
        self.assertIn("positions.size !== 64",code)
        self.assertIn('summary.textContent=descriptions.join("; ")',code)
        for name in ("web/index.html","web/accessible_chess_web.html"):
            ui=(ROOT/name).read_text(encoding="utf-8")
            self.assertIn('class="ac42-board-annotation-summary" tabindex="0" aria-live="off"',ui)
        self.assertIn("validPurpose(item.purpose)",code)
        self.assertIn("validColor(item.color)",code)
        for forbidden in ("fetch(","innerHTML","eval(","localStorage","document.cookie"):
            self.assertNotIn(forbidden,code)
        native=(ROOT/"web/index.html").read_text(encoding="utf-8")
        web=(ROOT/"web/accessible_chess_web.html").read_text(encoding="utf-8")
        self.assertIn('src="board_overlay_renderer.js"',native)
        self.assertIn('src="/assets/board_overlay_renderer.js"',web)
        self.assertIn("overlayRenderer.project(grid,ordered,visual)",native)
        self.assertIn("overlayRenderer.project(boardGrid, ordered, visual)",(ROOT/"web/accessible_chess_web.js").read_text(encoding="utf-8"))

if __name__=="__main__":
    unittest.main()
