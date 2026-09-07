from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest

from acs.chesscore import Board
from acs.version2_release_ui import Version2ReleaseAccessibleChessAPI


class Version2ReviewOverlayCrossSurfaceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.api = Version2ReleaseAccessibleChessAPI(
            keymap_path=Path(self.temp.name) / "keymap.json"
        )
        self.addCleanup(self.api.close_analysis)
        self.application = SimpleNamespace(
            pgn_board_active=True,
            book_workflow=SimpleNamespace(active=False),
        )
        self.api.bind_version2_application(self.application)

    def test_review_overlay_drives_board_queries_and_analysis_without_mutating_live_game(self) -> None:
        played = self.api.make_move("e4")
        self.assertTrue(played["ok"])
        live_fen = self.api.board.fen()
        live_sans = tuple(self.api.sans)
        live_node = self.api.live_history_node

        reviewed = Board()
        reviewed.push_text("d4")
        reviewed.push_text("e5")
        reviewed.push_text("dxe5")
        reviewed_fen = reviewed.fen()
        self.assertNotEqual(reviewed_fen, live_fen)

        projected = self.api._project_review_fen(reviewed_fen)
        self.assertTrue(projected["ok"])

        state = self.api.get_state()
        self.assertEqual(state["fen"], reviewed_fen)
        self.assertEqual(state["analysis"]["fen"], reviewed_fen)
        self.assertFalse(state["atHistoryEnd"])
        self.assertEqual(len(state["board"]), 64)

        current = self.api.dispatch_action("board.current", "e5")
        self.assertTrue(current["ok"])
        self.assertEqual(current["focusSquare"], "e5")
        self.assertIn("білий пішак", current["announcement"])

        material = self.api.dispatch_action("board.material", "e5")
        self.assertTrue(material["ok"])
        self.assertIn("39", material["announcement"])
        self.assertIn("38", material["announcement"])
        self.assertIn("+1", material["announcement"])

        # Review is presentation state: mutation commands must not silently apply
        # to the preserved live game while an external PGN/Book overlay is active.
        blocked = self.api.make_move("Nf3")
        self.assertFalse(blocked["ok"])
        self.assertEqual(self.api.board.fen(), live_fen)
        self.assertEqual(tuple(self.api.sans), live_sans)
        self.assertEqual(self.api.live_history_node, live_node)

        self.application.pgn_board_active = False
        returned = self.api.get_state()
        self.assertEqual(returned["fen"], live_fen)
        self.assertEqual(returned["analysis"]["fen"], live_fen)
        self.assertTrue(returned["atHistoryEnd"])
        self.assertEqual(self.api.board.fen(), live_fen)
        self.assertEqual(tuple(self.api.sans), live_sans)
        self.assertEqual(self.api.live_history_node, live_node)


if __name__ == "__main__":
    unittest.main()
