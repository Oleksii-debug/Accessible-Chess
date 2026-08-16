from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
HTML = ROOT / "web" / "teaching_board.html"
BOARD_KEYBOARD = ROOT / "web" / "accessible_board_keyboard.js"
LAUNCHER = ROOT / "acs" / "teaching_board_webapp.py"


class TeachingBoardWebSemanticTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.html = HTML.read_text(encoding="utf-8")
        cls.keyboard = BOARD_KEYBOARD.read_text(encoding="utf-8")
        cls.launcher = LAUNCHER.read_text(encoding="utf-8")

    def test_board_is_semantic_64_square_grid_with_one_live_region(self) -> None:
        self.assertIn('role="grid"', self.html)
        self.assertIn('aria-rowcount="8"', self.html)
        self.assertIn('aria-colcount="8"', self.html)
        self.assertIn("for(const row of visualBoard.squares)", self.html)
        self.assertIn("cell.setAttribute('role','gridcell')", self.html)
        self.assertIn("cell.setAttribute('aria-rowindex',String(row.row))", self.html)
        self.assertIn("cell.setAttribute('aria-colindex',String(row.column))", self.html)
        self.assertEqual(self.html.count('role="status"'), 1)

    def test_board_consumes_reusable_keyboard_primitive(self) -> None:
        self.assertIn('<script src="accessible_board_keyboard.js"></script>', self.html)
        self.assertIn("AccessibleChessBoardKeyboard.create", self.html)
        self.assertIn("boardKeyboard.syncRovingTabindex()", self.html)
        self.assertIn("boardKeyboard.focus(boardKeyboard.currentSquare)", self.html)
        self.assertNotIn("function moveSquare(", self.html)
        self.assertNotIn("el('board').addEventListener('keydown'", self.html)

    def test_shared_keyboard_primitive_owns_roving_tabindex_and_plain_navigation(self) -> None:
        self.assertIn("'[role=\"gridcell\"][data-square]'", self.keyboard)
        self.assertIn("cell.tabIndex = cell.dataset.square === currentSquare ? 0 : -1", self.keyboard)
        for key in ("ArrowLeft", "ArrowRight", "ArrowUp", "ArrowDown", "Home", "End"):
            self.assertIn(f"'{key}'", self.keyboard)
        self.assertIn("NAVIGATION_KEYS.has(event.key)", self.keyboard)
        self.assertIn("focus(moveSquare(square, event.key))", self.keyboard)
        self.assertNotIn("event.ctrlKey", self.keyboard)
        self.assertNotIn("event.metaKey", self.keyboard)

    def test_enter_and_space_use_existing_semantic_coach_pointer_contract(self) -> None:
        self.assertIn("event.key === 'Enter' || event.key === ' '", self.keyboard)
        self.assertIn("onActivate(square, event)", self.keyboard)
        self.assertIn("teaching_pointer_commit", self.html)
        self.assertIn("returnBoardFocus:true", self.html)
        self.assertNotIn("mousemove", self.html.lower() + self.keyboard.lower())
        self.assertNotIn("setcursorpos", self.html.lower() + self.keyboard.lower())

    def test_typed_square_commits_immediately_then_clears_and_refocuses(self) -> None:
        self.assertIn("event.target.value=''", self.html)
        self.assertIn("event.target.focus()", self.html)
        self.assertIn("normalizeSquare(raw)", self.html)
        self.assertIn("const SQUARE_RE = /^[a-h][1-8]$/", self.keyboard)

    def test_accessible_square_name_is_renderer_owned_and_theme_independent(self) -> None:
        self.assertIn("cell.setAttribute('aria-label',row.accessibleName)", self.html)
        self.assertIn("coord.setAttribute('aria-hidden','true')", self.html)
        self.assertIn("teaching_board_visual_snapshot", self.html)
        self.assertNotIn("board_theme_id+' '+row.square", self.html)
        self.assertNotIn("piece_theme_id+' '+row.square", self.html)

    def test_pointer_and_annotations_are_exposed_without_background_live_spam(self) -> None:
        self.assertIn("cell.setAttribute('aria-current','true')", self.html)
        self.assertIn("cell.setAttribute('aria-description',row.accessibleDescription)", self.html)
        self.assertIn('id="pointer-summary" class="status" aria-live="off"', self.html)
        self.assertEqual(self.html.count('aria-live="polite"'), 1)

    def test_full_visual_cluster_is_keyboard_native_and_independent(self) -> None:
        for control_id in ("board-theme", "piece-theme", "coordinate-mode", "board-scale", "piece-scale"):
            self.assertIn(f'id="{control_id}"', self.html)
        self.assertIn("board_theme_id:el('board-theme').value", self.html)
        self.assertIn("piece_theme_id:el('piece-theme').value", self.html)
        self.assertIn("board_scale_percent:Number(el('board-scale').value)", self.html)
        self.assertIn("piece_scale_percent:Number(el('piece-scale').value)", self.html)

    def test_piece_art_is_visual_only_and_never_replaces_semantic_piece_name(self) -> None:
        self.assertIn("row.pieceAssetUrl", self.html)
        self.assertIn("img.alt=''", self.html)
        self.assertIn("wrap.setAttribute('aria-hidden','true')", self.html)
        self.assertIn("glyphs[row.pieceId]", self.html)

    def test_missing_visual_pack_fallback_is_passive(self) -> None:
        self.assertIn("visualBoard.boardFallbackUsed", self.html)
        self.assertIn("visualBoard.pieceFallbackUsed", self.html)
        self.assertIn('id="visual-fallback" class="fallback" aria-live="off"', self.html)

    def test_normal_copy_and_selection_are_not_globally_hijacked(self) -> None:
        lowered = (self.html + self.keyboard).lower()
        self.assertNotIn("ctrl+c", lowered)
        self.assertNotIn("document.addeventlistener('keydown'", lowered)
        self.assertNotIn("window.addeventlistener('keydown'", lowered)
        self.assertNotIn("key==='c'", lowered)
        self.assertIn("board.addeventlistener('keydown'", lowered)
        self.assertIn("event.preventdefault()", lowered)
        self.assertIn("text_select=True", self.launcher)

    def test_primitive_is_theme_and_chess_state_agnostic(self) -> None:
        lowered = self.keyboard.lower()
        self.assertNotIn("board_theme", lowered)
        self.assertNotIn("piece_theme", lowered)
        self.assertNotIn("fen", lowered)
        self.assertNotIn("chesscore", lowered)
        self.assertNotIn("localstorage", lowered)
        self.assertNotIn("indexeddb", lowered)

    def test_launcher_subclasses_existing_teaching_api_and_stays_out_of_release_app(self) -> None:
        self.assertIn("from .teaching_webapp import TeachingAccessibleChessAPI", self.launcher)
        self.assertIn("class TeachingBoardAPI(TeachingAccessibleChessAPI)", self.launcher)
        self.assertIn('"web" / "teaching_board.html"', self.launcher)
        self.assertNotIn("chesscore", self.launcher.lower())
        self.assertNotIn("from . import webapp", self.launcher)
        self.assertNotIn("from .webapp", self.launcher)


if __name__ == "__main__":
    unittest.main()
