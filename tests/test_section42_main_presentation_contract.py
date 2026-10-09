"""Section 42 product-neutral projection is immutable, validated, and independent of chess rules."""
import unittest

from acs.chesscore import Board
from acs.visual_board_contract import (
    BoardSurface, BoardTheme, PieceTheme, VisualBoardCell,
    VisualBoardPreferences, VisualBoardSnapshot,
)


def cells():
    return tuple(VisualBoardCell(file_name + rank, "", file_name + rank)
                 for rank in "12345678" for file_name in "abcdefgh")


class Section42MainPresentationContractTests(unittest.TestCase):
    def test_all_six_routes_have_identical_bounded_canonical_squares(self):
        expected = {file_name + rank for rank in "12345678" for file_name in "abcdefgh"}
        for surface in BoardSurface:
            with self.subTest(surface=surface):
                snap = VisualBoardSnapshot(
                    surface, VisualBoardPreferences(), cells(),
                    highlights=(("e4", "attack", "#ff0000"),),
                    arrows=(("e2", "e4", "idea", "#0099ff"),),
                ).as_dict()
                self.assertEqual(len(snap["cells"]), 64)
                self.assertEqual({cell["square"] for cell in snap["cells"]}, expected)
                self.assertEqual(snap["surface"], surface.value)
                self.assertEqual(snap["highlights"][0]["purpose"], "attack")
                self.assertEqual(snap["arrows"][0]["to"], "e4")

    def test_presentation_preferences_never_mutate_canonical_fen(self):
        board = Board()
        original_fen = board.fen()
        for theme in BoardTheme:
            for piece in PieceTheme:
                prefs = VisualBoardPreferences().updated("board_theme", theme.value)
                prefs = prefs.updated("piece_theme", piece.value)
                prefs = prefs.updated("scale_percent", 200)
                prefs = prefs.updated("low_power_mode", True)
                self.assertEqual(prefs.as_dict()["scalePercent"], 200)
                self.assertEqual(prefs.as_dict()["lowPowerMode"], True)
                self.assertEqual(board.fen(), original_fen)

    def test_untrusted_overlay_is_rejected(self):
        base = (BoardSurface.TEACHER, VisualBoardPreferences(), cells())
        bad_highlights = [
            (("z9", "attack", "#ff0000"),),
            (("e4", "<script>", "#ff0000"),),
            (("e4", "attack", "url(https://evil.invalid)"),),
        ]
        for highlights in bad_highlights:
            with self.subTest(highlights=highlights), self.assertRaises(ValueError):
                VisualBoardSnapshot(*base, highlights=highlights)
        for arrows in [
            (("e2", "e2", "idea", "#ff0000"),),
            (("e2", "e4", "<svg>", "#ff0000"),),
            (("e2", "e4", "idea", "blue"),),
        ]:
            with self.subTest(arrows=arrows), self.assertRaises(ValueError):
                VisualBoardSnapshot(*base, arrows=arrows)

    def test_invalid_prefs_reject_without_partial_commit(self):
        original = VisualBoardPreferences()
        for value in (None, "200", 201, True, 200.5):
            with self.subTest(value=value), self.assertRaises(ValueError):
                original.updated("scale_percent", value)
        for value in ("yes", 1, None):
            with self.subTest(value=value), self.assertRaises(ValueError):
                original.updated("animate_moves", value)
        self.assertFalse(original.animate_moves)


if __name__ == "__main__":
    unittest.main()
