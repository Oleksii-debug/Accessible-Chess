from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class PremiumVisualDesignTests(unittest.TestCase):
    def test_premium_visual_layer_keeps_semantic_and_keyboard_contracts(self):
        html = (ROOT / "web/index.html").read_text(encoding="utf-8")
        css = (ROOT / "web/design_system.css").read_text(encoding="utf-8")
        themes = (ROOT / "web/board_themes.css").read_text(encoding="utf-8")
        self.assertIn('class="product-header"', html)
        self.assertIn('id="product-title"', html)
        self.assertIn('id="product-mode"', html)
        self.assertIn('aria-hidden="true"', html)
        for token in ("--ac-gold", "--ac-surface-raised", "--ac-shadow", "--ac-radius"):
            self.assertIn(token, css)
        self.assertIn("main > section", css)
        self.assertIn("#board-grid [role=\"gridcell\"]:focus-visible", css)
        self.assertIn("forced-colors: active", css)
        self.assertIn("prefers-reduced-motion: reduce", css)
        self.assertIn("board-theme-high-contrast", themes)
        self.assertNotIn("https://", css)


if __name__ == "__main__":
    unittest.main()
