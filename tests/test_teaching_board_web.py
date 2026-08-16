from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
HTML = ROOT / "web" / "teaching_board.html"
LAUNCHER = ROOT / "acs" / "teaching_board_webapp.py"


class TeachingBoardWebSemanticTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.html = HTML.read_text(encoding="utf-8")
        cls.launcher = LAUNCHER.read_text(encoding="utf-8")

    def test_board_is_semantic_64_square_grid_with_one_live_region(self) -> None:
        self.assertIn('role="grid"', self.html)
        self.assertIn('aria-rowcount="8"', self.html)
        self.assertIn('aria-colcount="8"', self.html)
        self.assertIn("for(let rank=8;rank>=1;rank--)", self.html)
        self.assertIn("for(const file of 'abcdefgh')", self.html)
        self.assertIn("cell.setAttribute('role','gridcell')", self.html)
        self.assertIn("cell.setAttribute('aria-rowindex'", self.html)
        self.assertIn("cell.setAttribute('aria-colindex'", self.html)
        self.assertEqual(self.html.count('role="status"'), 1)

    def test_roving_tabindex_and_unmodified_arrow_navigation_are_present(self) -> None:
        self.assertIn("cell.tabIndex=square===focusSquare?0:-1", self.html)
        self.assertIn("'ArrowLeft'", self.html)
        self.assertIn("'ArrowRight'", self.html)
        self.assertIn("'ArrowUp'", self.html)
        self.assertIn("'ArrowDown'", self.html)
        self.assertIn("'Home'", self.html)
        self.assertIn("'End'", self.html)
        self.assertIn("focusCell(moveSquare(cell.dataset.square,key))", self.html)
        self.assertNotIn("event.ctrlKey", self.html)
        self.assertNotIn("event.metaKey", self.html)

    def test_enter_and_space_use_existing_semantic_coach_pointer_contract(self) -> None:
        self.assertIn("key==='Enter'||key===' '", self.html)
        self.assertIn("teaching_pointer_commit", self.html)
        self.assertIn("returnBoardFocus:true", self.html)
        self.assertNotIn("mousemove", self.html.lower())
        self.assertNotIn("setcursorpos", self.html.lower())

    def test_typed_square_commits_immediately_then_clears_and_refocuses(self) -> None:
        self.assertIn("/^[a-h][1-8]$/", self.html)
        self.assertIn("event.target.value=''", self.html)
        self.assertIn("event.target.focus()", self.html)

    def test_accessible_square_name_is_independent_from_visual_theme_and_coordinates(self) -> None:
        self.assertIn("cell.setAttribute('aria-label',squareName(square))", self.html)
        self.assertIn("coord.setAttribute('aria-hidden','true')", self.html)
        self.assertIn("snapshot.visual.coordinate_mode", self.html)
        self.assertIn("snapshot.visual.board_scale_percent", self.html)
        self.assertNotIn("board_theme_id+' '+square", self.html)
        self.assertNotIn("piece_theme_id+' '+square", self.html)

    def test_pointer_and_annotations_are_exposed_without_background_live_spam(self) -> None:
        self.assertIn("cell.setAttribute('aria-current','true')", self.html)
        self.assertIn("cell.setAttribute('aria-description'", self.html)
        self.assertIn('id="pointer-summary" aria-live="off"', self.html)
        self.assertEqual(self.html.count('aria-live="polite"'), 1)

    def test_normal_copy_and_selection_are_not_globally_hijacked(self) -> None:
        lowered = self.html.lower()
        self.assertNotIn("ctrl+c", lowered)
        self.assertNotIn("preventdefault()", lowered.split("addEventListener('keydown'", 1)[0])
        self.assertIn("text_select=True", self.launcher)

    def test_launcher_reuses_existing_teaching_api_and_stays_out_of_release_app(self) -> None:
        self.assertIn("from .teaching_webapp import TeachingAccessibleChessAPI", self.launcher)
        self.assertIn('"web" / "teaching_board.html"', self.launcher)
        self.assertNotIn("chesscore", self.launcher.lower())
        self.assertNotIn("from . import webapp", self.launcher)
        self.assertNotIn("from .webapp", self.launcher)


if __name__ == "__main__":
    unittest.main()
