import tempfile
import unittest
from pathlib import Path

from acs.webapp_keymap import KeymapAwareAccessibleChessAPI


class ReleaseHistoryP0Tests(unittest.TestCase):
    """Release-path invariants for the exact WebView composition root."""

    def _played_api(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        api = KeymapAwareAccessibleChessAPI(lang="en", keymap_path=Path(temp.name) / "keymap.json")
        for move in ("e4", "e5", "Nf3", "Nc6"):
            result = api.make_move(move)
            self.assertTrue(result["ok"], result.get("announcement"))
        return api

    def test_review_projection_never_replaces_live_board_or_undo_redo(self):
        api = self._played_api()
        live_board = api.board
        live_fen = api.board.fen()
        live_undo_len = len(api.board.undo_stack)
        live_redo_len = len(api.board.redo_stack)

        reviewed = api.review_previous()
        self.assertTrue(reviewed["ok"], reviewed.get("announcement"))
        self.assertIs(api.board, live_board, "review navigation replaced the live Board object")
        self.assertEqual(api.board.fen(), live_fen, "review navigation mutated the live position")
        self.assertEqual(len(api.board.undo_stack), live_undo_len)
        self.assertEqual(len(api.board.redo_stack), live_redo_len)
        self.assertNotEqual(reviewed["fen"], live_fen, "review state must expose a historical FEN projection")

        end = api.go_to_move("end")
        self.assertTrue(end["ok"], end.get("announcement"))
        self.assertIs(api.board, live_board)
        self.assertEqual(api.board.fen(), live_fen)

        undone = api.undo()
        self.assertTrue(undone["ok"], undone.get("announcement"))
        redo_ready_fen = api.board.fen()
        redone = api.redo()
        self.assertTrue(redone["ok"], redone.get("announcement"))
        self.assertNotEqual(redo_ready_fen, api.board.fen())
        self.assertEqual(api.board.fen(), live_fen, "review -> end -> undo -> redo did not restore exact live FEN")

    def test_history_speech_uses_shared_compact_piece_file_rank_spacing(self):
        api = self._played_api()
        state = api.get_state()
        self.assertIn("N f 3", state["moves"])
        self.assertIn("N c 6", state["moves"])
        self.assertNotIn("Nf 3", state["moves"])
        self.assertNotIn("Nc 6", state["moves"])
        self.assertNotIn("knight f 3", state["moves"].lower())


if __name__ == "__main__":
    unittest.main()
