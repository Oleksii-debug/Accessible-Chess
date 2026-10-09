from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class Section42BoardThemeTests(unittest.TestCase):
    def test_board_themes_are_local_and_do_not_replace_semantic_board(self):
        html = (ROOT / "web/index.html").read_text(encoding="utf-8")
        css = (ROOT / "web/board_themes.css").read_text(encoding="utf-8")
        self.assertIn('<link rel="stylesheet" href="board_themes.css">', html)
        for theme in ("wood", "graphite", "blue", "minimal", "high-contrast"):
            self.assertIn(f"board-theme-{theme}", css)
        self.assertIn("[role=gridcell]", html)
        self.assertIn("forced-colors: active", css)
        self.assertIn("prefers-reduced-motion: reduce", css)
        self.assertNotIn("https://", css)


if __name__ == "__main__":
    unittest.main()
