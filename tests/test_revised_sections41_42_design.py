from __future__ import annotations

import unittest
from pathlib import Path

from acs.chesscore import Board
from acs.visual_board_contract import BoardTheme, VisualBoardPreferences
from acs.webapp import AccessibleChessAPI

ROOT = Path(__file__).resolve().parents[1]


class RevisedBoardDesignTests(unittest.TestCase):
    def setUp(self):
        self.html = (ROOT / "web" / "index.html").read_text(encoding="utf-8")

    def test_seven_palettes_are_in_same_canonical_preference_authority(self):
        names = {
            "classic", "blue", "high_contrast", "classic_wood",
            "modern_graphite", "tournament_blue", "light_minimal",
        }
        self.assertEqual({theme.value for theme in BoardTheme}, names)
        for name in names:
            with self.subTest(name=name):
                self.assertEqual(VisualBoardPreferences().updated("board_theme", name).board_theme.value, name)
                self.assertIn(f'value="{name}"', self.html)
                self.assertIn(f"setOptionText('board-theme','{name}'", self.html)
                if name not in {"classic"}:
                    self.assertIn(f"data-theme={name}", self.html)

    def test_low_vision_scale_from_same_owner(self):
        for scale in (75, 100, 125, 150, 175, 200):
            with self.subTest(scale=scale):
                self.assertEqual(VisualBoardPreferences().updated("scale_percent", scale).scale_percent, scale)
                self.assertIn(f'<option value="{scale}">{scale}%</option>', self.html)
        for value in (False, 74, 201, "200", 200.5):
            with self.subTest(invalid=value):
                with self.assertRaises(ValueError):
                    VisualBoardPreferences().updated("scale_percent", value)

    def test_all_palettes_preserve_fen_and_gametree(self):
        api = AccessibleChessAPI("en")
        try:
            fen = api.board.fen()
            tree = api.review_history.export_tree()
            for theme in BoardTheme:
                with self.subTest(theme=theme):
                    result = api.set_visual_preference("board_theme", theme.value)
                    self.assertTrue(result["ok"])
                    self.assertEqual(result["visualBoard"]["preferences"]["boardTheme"], theme.value)
                    self.assertEqual(api.board.fen(), fen)
                    self.assertEqual(api.review_history.export_tree(), tree)
            self.assertEqual(len(api.get_state()["visualBoard"]["cells"]), 64)
        finally:
            close = getattr(api, "close_analysis", None)
            if callable(close):
                close()

    def test_local_pinned_mit_tabler_icon_has_license_and_no_external_dependency(self):
        asset = ROOT / "web" / "assets" / "tabler" / "chess-rook.svg"
        settings = ROOT / "web" / "assets" / "tabler" / "adjustments.svg"
        license_text = (ROOT / "web" / "assets" / "tabler" / "LICENSE").read_text(encoding="utf-8")
        self.assertTrue(asset.is_file())
        self.assertTrue(settings.is_file())
        self.assertIn("MIT License", license_text)
        self.assertIn("Copyright (c) 2020-2026 Paweł Kuna", license_text)
        self.assertIn('class="ac-heading-icon"', self.html)
        self.assertIn('aria-hidden="true" focusable="false"', self.html)
        self.assertNotIn("cdn.jsdelivr.net", self.html)
        # The SVG XML namespace is a fixed URI, not a network fetch.
        # Forbid active CDN-loaded scripts/styles, not standards namespaces.
        self.assertNotIn('<script src="http', self.html)
        self.assertNotIn('<link rel="stylesheet" href="http', self.html)
        self.assertNotIn('@import url(http', self.html)

    def test_css_accessibility_safety_in_both_languages(self):
        for theme in ("classic_wood", "modern_graphite", "tournament_blue", "light_minimal"):
            self.assertIn(f"setOptionText('board-theme','{theme}',en?", self.html)
        for text in ("@media(forced-colors:active)", "@media(prefers-reduced-motion:reduce)",
                     ":focus-visible", "outline-offset:3px"):
            self.assertIn(text, self.html)
        self.assertIn("grid-template-columns:repeat(8,minmax(0,1fr))", self.html)
        self.assertIn("width:100%;max-width:52rem", self.html)
        self.assertIn("max-width:'+String(52*p.scalePercent/100)+'rem", self.html)
        self.assertIn("node.setAttribute('aria-label',cell.label)", self.html)
        self.assertNotIn("localStorage.setItem", self.html)


if __name__ == "__main__":
    unittest.main()
