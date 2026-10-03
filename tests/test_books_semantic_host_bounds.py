from __future__ import annotations

import unittest
from unittest.mock import patch

from acs.analysis_service import AnalysisService
from acs.book_board_workflow import BookBoardMode, BookBoardWorkflow
from acs.bookdocument import BookDocument, Game
from acs.bookreader import BookReader
from acs.engine_assisted_workflows import EngineAssistedWorkflowService
from acs.gametree import MoveNode, PgnGame, VariationLine
from acs.version2_book_workspace import build_version2_book_webview
from acs.version2_profile import build_version2_router, build_version2_shell
from acs.version2_windows_book_board_adapter import Version2WindowsBookBoardActionDelegate


class BooksSemanticHostBoundsTests(unittest.TestCase):
    def compose(self):
        reader = BookReader(
            BookDocument(
                title="Semantic host bounds",
                blocks=[Game(pgn='[Result "*"]\n\n1. e4 *', title="Readable title")],
            )
        )
        analysis = AnalysisService(lambda: None)
        self.addCleanup(analysis.close)
        workflow = BookBoardWorkflow(reader, EngineAssistedWorkflowService(analysis))
        delegate = Version2WindowsBookBoardActionDelegate(
            workflow,
            next_delegate=lambda *_: self.fail("unexpected action"),
        )
        router = build_version2_router(build_version2_shell(), delegate)
        bridge = build_version2_book_webview(reader, workflow, router.dispatch)
        return reader, workflow, bridge

    @staticmethod
    def semantic_game(*, white: str = "Alpha", san: str = "e4") -> PgnGame:
        return PgnGame(
            tags={"White": white, "Black": "Beta", "Result": "*"},
            line=VariationLine(
                moves=[MoveNode(san=san, move_number="1")],
                result="*",
            ),
        )

    def assert_accessible_fallback(self, snapshot, reader, workflow, before):
        self.assertIsNone(snapshot["semantic_tree"])
        self.assertEqual(snapshot["block"]["text"], "Readable title")
        self.assertIn("шахівниця", snapshot["block"]["warning"])
        actions = {item["command"]: item["enabled"] for item in snapshot["actions"]}
        self.assertTrue(actions["book.open_game"])
        self.assertFalse(workflow.active)
        self.assertEqual(workflow.revision, 0)
        self.assertEqual(reader.snapshot(), before)

    def test_players_scalar_bound_falls_back_before_browser_serialization(self):
        reader, workflow, bridge = self.compose()
        before = reader.snapshot()
        # 718 + " — " + 4 UTF-16 units is larger than the browser's 720-unit
        # players field contract while remaining far below the aggregate 12 MiB budget.
        game = self.semantic_game(white="W" * 718)

        with patch.object(
            workflow,
            "semantic_game_snapshot",
            return_value=(BookBoardMode.GAME, game, ()),
        ):
            snapshot = bridge.projection.snapshot()

        self.assert_accessible_fallback(snapshot, reader, workflow, before)

    def test_item_label_scalar_bound_falls_back_before_browser_serialization(self):
        reader, workflow, bridge = self.compose()
        before = reader.snapshot()
        game = self.semantic_game(san="e" * 1_201)

        with patch.object(
            workflow,
            "semantic_game_snapshot",
            return_value=(BookBoardMode.GAME, game, ()),
        ):
            snapshot = bridge.projection.snapshot()

        self.assert_accessible_fallback(snapshot, reader, workflow, before)

    def test_text_entry_budget_counts_every_serialized_semantic_string(self):
        reader, workflow, bridge = self.compose()
        before = reader.snapshot()
        game = self.semantic_game()

        # One single-move browser snapshot contains seven semantic text entries:
        # section label, players label/value, result label/value, move label/result.
        # Lower the production budget to six to prove the host rejects the same
        # payload before WebView validation rather than under-counting trusted fields.
        with (
            patch.object(
                workflow,
                "semantic_game_snapshot",
                return_value=(BookBoardMode.GAME, game, ()),
            ),
            patch("acs.version2_book_workspace._MAX_BOOK_SEMANTIC_TEXT_ENTRIES", 6),
        ):
            snapshot = bridge.projection.snapshot()

        self.assert_accessible_fallback(snapshot, reader, workflow, before)


if __name__ == "__main__":
    unittest.main()
