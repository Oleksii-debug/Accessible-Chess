from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest

from acs.version2_release_ui import Version2ReleaseAccessibleChessAPI


START_FEN = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"


class _ExternalReviewAnalysis:
    """Minimal analysis-presentation seam exposing the inherited return contract."""

    def __init__(self, target_fen: str) -> None:
        self.target_fen = target_fen
        self.exploration = None
        self.return_calls = 0

    def begin_exploration(self, fen: str):
        if fen != self.target_fen:
            raise AssertionError("analysis did not start from displayed review FEN")
        self.exploration = SimpleNamespace(
            line=SimpleNamespace(multipv=1),
            san="e4",
        )
        return self.exploration

    def return_from_exploration(self) -> None:
        self.return_calls += 1
        self.exploration = None


class ExternalReviewAnalysisReturnEvidenceTests(unittest.TestCase):
    """RED-first oracle for synthetic external-review analysis origin cleanup."""

    def test_pgn_review_exploration_can_return_without_selecting_synthetic_history_node(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            api = Version2ReleaseAccessibleChessAPI(
                keymap_path=Path(directory) / "keymap.json"
            )
            self.addCleanup(api.close_analysis)

            # Keep a real hidden live history identity behind the external review.
            moved = api.make_move("e4")
            self.assertTrue(moved["ok"])
            hidden_history = api.review_history.export_tree()
            hidden_fen = api.board.fen()

            application = SimpleNamespace(pgn_board_active=True, book_workflow=None)
            api.bind_version2_application(application)
            projected = api.v2_project_review_fen(START_FEN)
            self.assertTrue(projected["ok"])
            self.assertNotEqual(projected["fen"], hidden_fen)

            # #554 deliberately presents external review with synthetic node_id=-1.
            self.assertEqual(api._display_review().node_id, -1)
            api._analysis_origin_node_id = -1
            fake_analysis = _ExternalReviewAnalysis(projected["fen"])
            api.analysis_ui = fake_analysis

            explored = api.explore_analysis_pv()
            self.assertTrue(explored["ok"], explored)
            self.assertIsNotNone(fake_analysis.exploration)

            returned = api.return_from_analysis()

            # Required contract: external review is presentation state, therefore
            # Return must clear temporary exploration without selecting/appending
            # the synthetic -1 node in the canonical live ReviewHistory.
            self.assertTrue(
                returned["ok"],
                "external-review Stockfish exploration could not return from synthetic node -1",
            )
            self.assertIsNone(fake_analysis.exploration)
            self.assertEqual(fake_analysis.return_calls, 1)
            self.assertEqual(api.review_history.export_tree(), hidden_history)
            self.assertEqual(api.board.fen(), hidden_fen)
            self.assertEqual(api.get_state()["fen"], projected["fen"])


if __name__ == "__main__":
    unittest.main()
