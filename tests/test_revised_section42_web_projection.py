"""Section 42 cross-product visual projection uses one canonical 64-cell contract."""
from pathlib import Path
import unittest

ROOT=Path(__file__).resolve().parents[1]

class WebBoardProjectionTests(unittest.TestCase):
    def test_web_play_and_modes_reuse_visual_board_state_without_chess_rules(self):
        script=(ROOT/"web/accessible_chess_web.js").read_text(encoding="utf-8")
        for x in ('snapshot && snapshot.visualBoard && snapshot.visualBoard.cells',
            'visual.preferences', 'p.orientation === "black" ? [...cells].reverse()',
            'boardGrid.dataset.theme = theme',
            'boardGrid.dataset.pieceTheme = style',
            'button.setAttribute("aria-label", label)',
            'button.setAttribute("aria-rowindex"',
            'image.src = "assets/pieces/rhosgfx/" + file',
            'image.addEventListener("error"',
            'decoration.setAttribute("aria-hidden", "true")',
            'document.activeElement.closest("#board-grid") === boardGrid',
            'boardGrid.children[activeIndex].focus({preventScroll:true})',
        ):
            with self.subTest(token=x):
                self.assertIn(x,script)
        for forbidden in ('new Chess(', 'parseFEN(', 'generateLegalMoves(', 'localStorage'):
            self.assertNotIn(forbidden,script)

    def test_one_offline_css_palette_available_on_both_surfaces(self):
        css=(ROOT/"web/assets/accessible_chess_design.css").read_text(encoding="utf-8")
        for color in ("classic","high_contrast","blue","classic_wood",
                      "modern_graphite","tournament_blue","light_minimal"):
            self.assertIn("#board-grid[data-theme="+color+"]",css)
        self.assertIn("@media(prefers-reduced-motion:reduce),(forced-colors:active)",css)
        for filename in ("web/index.html","web/accessible_chess_web.html"):
            markup=(ROOT/filename).read_text(encoding="utf-8")
            self.assertIn('href="assets/accessible_chess_design.css"',markup)
        self.assertNotIn("https://",css)

if __name__=="__main__":
    unittest.main()
