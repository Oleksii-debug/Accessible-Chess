from __future__ import annotations

import unittest
from pathlib import Path

from acs.chesscore import Board
from acs.teacher_presentation import TeacherPresentationState
from acs.teacher_webview_projection import TeacherWebViewProjection
from acs.visual_board_contract import (
    BoardOrientation,
    BoardSurface,
    BoardTheme,
    CoordinateMode,
    PieceTheme,
    VisualBoardCell,
    VisualBoardPreferences,
    VisualBoardSnapshot,
)
from acs.webapp import AccessibleChessAPI


def _cells() -> tuple[VisualBoardCell, ...]:
    return tuple(
        VisualBoardCell(
            square=f"{file_name}{rank}",
            piece="",
            accessible_label=f"{file_name} {rank}",
        )
        for rank in "12345678"
        for file_name in "abcdefgh"
    )


class Section15VisualBoardContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.api = AccessibleChessAPI("en")
        self.root = Path(__file__).resolve().parents[1]
        self.html = (self.root / "web" / "index.html").read_text(encoding="utf-8")

    def test_shared_contract_names_every_required_surface(self):
        self.assertEqual(
            {surface.value for surface in BoardSurface},
            {"ordinary_play", "teacher", "online", "spectator"},
        )
        for surface in BoardSurface:
            snapshot = VisualBoardSnapshot(
                surface=surface,
                preferences=VisualBoardPreferences(),
                cells=_cells(),
            )
            self.assertEqual(snapshot.as_dict()["surface"], surface.value)

    def test_preferences_cover_theme_pieces_orientation_coordinates_and_size(self):
        prefs = VisualBoardPreferences()
        prefs = prefs.updated("board_theme", "high_contrast")
        prefs = prefs.updated("piece_theme", "letters")
        prefs = prefs.updated("orientation", "black")
        prefs = prefs.updated("coordinate_mode", "every_square")
        prefs = prefs.updated("scale_percent", 150)
        prefs = prefs.updated("show_last_move", False)
        self.assertEqual(prefs.board_theme, BoardTheme.HIGH_CONTRAST)
        self.assertEqual(prefs.piece_theme, PieceTheme.LETTERS)
        self.assertEqual(prefs.orientation, BoardOrientation.BLACK)
        self.assertEqual(prefs.coordinate_mode, CoordinateMode.EVERY_SQUARE)
        self.assertEqual(prefs.scale_percent, 150)
        self.assertFalse(prefs.show_last_move)

    def test_invalid_visual_preferences_fail_closed(self):
        prefs = VisualBoardPreferences()
        for field, value in (
            ("board_theme", "hostile"),
            ("piece_theme", "svg-script"),
            ("orientation", "sideways"),
            ("coordinate_mode", "unknown"),
            ("scale_percent", 151),
            ("scale_percent", True),
            ("show_last_move", 1),
            ("unknown", "value"),
        ):
            with self.subTest(field=field, value=value):
                with self.assertRaises(ValueError):
                    prefs.updated(field, value)

    def test_visual_contract_rejects_partial_or_duplicate_board(self):
        with self.assertRaises(ValueError):
            VisualBoardSnapshot(
                surface=BoardSurface.TEACHER,
                preferences=VisualBoardPreferences(),
                cells=_cells()[:-1],
            )
        duplicate = list(_cells())
        duplicate[-1] = duplicate[0]
        with self.assertRaises(ValueError):
            VisualBoardSnapshot(
                surface=BoardSurface.ONLINE,
                preferences=VisualBoardPreferences(),
                cells=tuple(duplicate),
            )

    def test_ordinary_play_projection_has_canonical_pieces(self):
        state = self.api.get_state()
        visual = state["visualBoard"]
        self.assertEqual(visual["surface"], "ordinary_play")
        self.assertEqual(len(visual["cells"]), 64)
        pieces = {cell["square"]: cell["piece"] for cell in visual["cells"]}
        self.assertEqual(pieces["e1"], "K")
        self.assertEqual(pieces["e2"], "P")
        self.assertEqual(pieces["e7"], "p")
        self.assertEqual(pieces["e8"], "k")
        self.assertIsNone(visual["selectedSquare"])
        self.assertEqual(visual["legalTargets"], [])
        self.assertIsNone(visual["lastMove"])

    def test_selected_piece_legal_targets_come_from_canonical_board(self):
        selected = self.api.activate_square("e2")
        self.assertTrue(selected["ok"])
        visual = selected["visualBoard"]
        self.assertEqual(visual["selectedSquare"], "e2")
        self.assertEqual(set(visual["legalTargets"]), {"e3", "e4"})
        self.assertEqual(self.api.board.fen(), selected["fen"])

    def test_last_move_is_visual_projection_of_canonical_move(self):
        before = self.api.board.fen()
        moved = self.api.make_move("e4")
        self.assertTrue(moved["ok"])
        self.assertNotEqual(before, self.api.board.fen())
        self.assertEqual(moved["visualBoard"]["lastMove"], {"from": "e2", "to": "e4"})
        self.assertEqual(moved["visualBoard"]["legalTargets"], [])

    def test_visual_preference_change_never_mutates_chess_truth(self):
        fen = self.api.board.fen()
        history = self.api.review_history.export_tree()
        result = self.api.set_visual_preference("orientation", "black")
        self.assertTrue(result["ok"])
        self.assertEqual(result["visualBoard"]["preferences"]["orientation"], "black")
        self.assertEqual(self.api.board.fen(), fen)
        self.assertEqual(self.api.review_history.export_tree(), history)
        self.assertEqual(len(self.api.sans), 0)

    def test_rejected_visual_preference_is_atomic(self):
        before = self.api.visual_preferences
        fen = self.api.board.fen()
        result = self.api.set_visual_preference("scale_percent", 999)
        self.assertFalse(result["ok"])
        self.assertIs(self.api.visual_preferences, before)
        self.assertEqual(self.api.board.fen(), fen)

    def test_history_review_cannot_publish_stale_visual_selection_or_last_move(self):
        self.assertTrue(self.api.make_move("e4")["ok"])
        self.assertTrue(self.api.review_previous()["ok"])
        visual = self.api.get_state()["visualBoard"]
        self.assertIsNone(visual["selectedSquare"])
        self.assertIsNone(visual["lastMove"])
        self.assertEqual(visual["legalTargets"], [])

    def test_teacher_projection_publishes_same_shared_visual_contract(self):
        teacher = TeacherPresentationState(
            lambda *_args: None,
            lambda: {
                "pointer_square": "e4",
                "highlights": (),
                "arrows": (),
                "coordinates_visible": True,
                "board_permission": "locked",
                "engine_visibility": "hidden",
            },
        )
        projection = TeacherWebViewProjection(
            teacher,
            position_fen_provider=lambda: Board().fen(),
        )
        visual = projection.snapshot(language="en")["visualBoard"]
        self.assertEqual(visual["surface"], "teacher")
        self.assertEqual(len(visual["cells"]), 64)
        self.assertEqual(visual["selectedSquare"], "e4")
        pieces = {cell["square"]: cell["piece"] for cell in visual["cells"]}
        self.assertEqual(pieces["e1"], "K")
        self.assertEqual(pieces["e8"], "k")

    def test_visual_controls_and_high_contrast_contract_are_present(self):
        for control in (
            'id="board-theme"',
            'id="piece-theme"',
            'id="board-orientation"',
            'id="board-coordinates"',
            'id="board-scale"',
            'id="board-show-last"',
        ):
            self.assertIn(control, self.html)
        self.assertIn(
            "#board-grid[data-theme=high_contrast]{--light:#fff;--dark:#000;--piece-light:#000;--piece-dark:#fff}",
            self.html,
        )
        self.assertEqual(self.html.count('aria-live="polite"'), 1)
        self.assertNotIn("localStorage.setItem", self.html)
        self.assertNotIn("localStorage.getItem", self.html)

    def test_visual_decorations_stay_hidden_from_accessible_square_name(self):
        self.assertIn("piece.setAttribute('aria-hidden','true')", self.html)
        self.assertIn("label.setAttribute('aria-hidden','true')", self.html)
        self.assertIn("node.setAttribute('aria-label',cell.label)", self.html)
        self.assertIn("node.setAttribute('aria-selected',cell.selected?'true':'false')", self.html)

    def test_orientation_keeps_keyboard_actions_bound_to_rendered_square(self):
        self.assertIn("function currentBoardCell()", self.html)
        self.assertIn(
            "return state.board.find(cell=>cell.square===node.dataset.square)||null",
            self.html,
        )
        self.assertNotIn(
            "const cell=state&&state.board&&state.board[boardIndex];",
            self.html,
        )
        self.assertIn(
            "const cell=currentBoardCell();if(cell)return apiAction('activate_square',cell.square)",
            self.html,
        )
        self.assertIn(
            "p.orientation==='black'?[...cells].reverse():[...cells]",
            self.html,
        )

    def test_last_move_selected_and_legal_targets_have_distinct_visual_channels(self):
        self.assertIn("node.dataset.lastMove='true'", self.html)
        self.assertIn("node.dataset.legalTarget='true'", self.html)
        self.assertIn("aria-selected", self.html)
        self.assertIn("[data-last-move=true]", self.html)
        self.assertIn("[data-legal-target=true]", self.html)


if __name__ == "__main__":
    unittest.main()
