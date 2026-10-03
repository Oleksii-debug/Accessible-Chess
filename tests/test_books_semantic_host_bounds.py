from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from acs import version2_book_workspace as book_workspace
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
            event_sink=lambda _event: None,
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

    def test_text_entry_budget_matches_every_serialized_semantic_string(self):
        reader, workflow, bridge = self.compose()
        before = reader.snapshot()
        game = self.semantic_game()

        # One single-move browser snapshot contains exactly eight semantic text
        # entries: section label, players label/value, result label, variation-depth
        # label, result value, move label/result. Eight must pass; seven must fail
        # on the host before WebView.
        with (
            patch.object(
                workflow,
                "semantic_game_snapshot",
                return_value=(BookBoardMode.GAME, game, ()),
            ),
            patch("acs.version2_book_workspace._MAX_BOOK_SEMANTIC_TEXT_ENTRIES", 8),
        ):
            accepted = bridge.projection.snapshot()
        self.assertIsInstance(accepted["semantic_tree"], dict)
        self.assertEqual(reader.snapshot(), before)

        with (
            patch.object(
                workflow,
                "semantic_game_snapshot",
                return_value=(BookBoardMode.GAME, game, ()),
            ),
            patch("acs.version2_book_workspace._MAX_BOOK_SEMANTIC_TEXT_ENTRIES", 7),
        ):
            rejected = bridge.projection.snapshot()

        self.assert_accessible_fallback(rejected, reader, workflow, before)

    def test_visible_text_budget_counts_generated_variation_and_result_labels(self):
        reader, workflow, bridge = self.compose()
        before = reader.snapshot()
        game = self.semantic_game()

        def presenter_view(comment_size: int) -> SimpleNamespace:
            return SimpleNamespace(
                game_index=0,
                items=(
                    SimpleNamespace(
                        kind="move",
                        depth=0,
                        node_id="g0:m0",
                        parent_id=None,
                        label="1. e4",
                        comments=(),
                        comments_before=(),
                        comments_after=(),
                        trailing_comments=(),
                        result=None,
                    ),
                    SimpleNamespace(
                        kind="variation",
                        depth=1,
                        node_id="g0:m0/v0",
                        parent_id="g0:m0",
                        label="Variation 1",
                        comments=("x" * comment_size,),
                        comments_before=(),
                        comments_after=(),
                        trailing_comments=(),
                        result="*",
                    ),
                ),
            )

        # With the canonical Ukrainian labels this projection has 97 rendered
        # UTF-16 units before the variation comment. 1903 is therefore exactly
        # the 2000-unit boundary; one additional unit must fail closed. The old
        # serialized-field accounting saw only 76 fixed units and accepted both.
        with (
            patch.object(
                workflow,
                "semantic_game_snapshot",
                return_value=(BookBoardMode.GAME, game, ()),
            ),
            patch(
                "acs.version2_book_workspace.PgnTreePresenter.view",
                return_value=presenter_view(1903),
            ),
            patch("acs.version2_book_workspace._MAX_BOOK_BLOCK_VISIBLE_CHARS", 2000),
        ):
            accepted = bridge.projection.snapshot()
        self.assertIsInstance(accepted["semantic_tree"], dict)
        self.assertEqual(reader.snapshot(), before)

        with (
            patch.object(
                workflow,
                "semantic_game_snapshot",
                return_value=(BookBoardMode.GAME, game, ()),
            ),
            patch(
                "acs.version2_book_workspace.PgnTreePresenter.view",
                return_value=presenter_view(1904),
            ),
            patch("acs.version2_book_workspace._MAX_BOOK_BLOCK_VISIBLE_CHARS", 2000),
        ):
            rejected = bridge.projection.snapshot()

        self.assert_accessible_fallback(rejected, reader, workflow, before)

    def test_block_kind_mismatch_falls_back_before_browser_serialization(self):
        reader, workflow, bridge = self.compose()
        before = reader.snapshot()
        game = self.semantic_game()

        with patch.object(
            workflow,
            "semantic_game_snapshot",
            return_value=(BookBoardMode.VARIATION, game, ()),
        ):
            snapshot = bridge.projection.snapshot()

        self.assert_accessible_fallback(snapshot, reader, workflow, before)

    def test_item_kind_depth_mismatch_falls_back_before_browser_serialization(self):
        reader, workflow, bridge = self.compose()
        before = reader.snapshot()
        game = self.semantic_game()
        malformed_view = SimpleNamespace(
            game_index=0,
            items=(
                SimpleNamespace(
                    kind="variation",
                    depth=0,
                    node_id="g0:main/v0",
                    parent_id=None,
                    label="Variation 1",
                    comments=(),
                    comments_before=(),
                    comments_after=(),
                    trailing_comments=(),
                    result=None,
                ),
            ),
        )

        with (
            patch.object(
                workflow,
                "semantic_game_snapshot",
                return_value=(BookBoardMode.GAME, game, ()),
            ),
            patch(
                "acs.version2_book_workspace.PgnTreePresenter.view",
                return_value=malformed_view,
            ),
        ):
            snapshot = bridge.projection.snapshot()

        self.assert_accessible_fallback(snapshot, reader, workflow, before)

    def test_python_host_limits_match_the_browser_semantic_contract(self):
        script = (
            Path(__file__).resolve().parents[1] / "web" / "full_product_books_training.js"
        ).read_text(encoding="utf-8")

        self.assertEqual(book_workspace._MAX_BOOK_SEMANTIC_ITEMS, 10_000)
        self.assertEqual(book_workspace._MAX_BOOK_SEMANTIC_DEPTH, 256)
        self.assertEqual(book_workspace._MAX_BOOK_SEMANTIC_TEXT_ENTRIES, 50_000)
        self.assertIn("const MAX_BOOK_SEMANTIC_ITEMS = 10000;", script)
        self.assertIn("const MAX_BOOK_SEMANTIC_DEPTH = 256;", script)
        self.assertIn("const MAX_BOOK_SEMANTIC_TEXT_ENTRIES = 50000;", script)
        self.assertIn('item.kind === "move" && item.depth % 2 !== 0', script)
        self.assertIn('item.kind === "variation" && item.depth % 2 !== 1', script)

        scalar_contract = (
            (
                book_workspace._MAX_BOOK_SEMANTIC_SECTION_LABEL_UNITS,
                'semanticText(tree.label, "Book semantic label", false, 360);',
            ),
            (
                book_workspace._MAX_BOOK_SEMANTIC_FIELD_LABEL_UNITS,
                'semanticText(tree.players_label, "Book semantic players label", false, 120);',
            ),
            (
                book_workspace._MAX_BOOK_SEMANTIC_PLAYERS_UNITS,
                'semanticText(tree.players, "Book semantic players", false, 720);',
            ),
            (
                book_workspace._MAX_BOOK_SEMANTIC_FIELD_LABEL_UNITS,
                '"Book semantic variation depth label"',
            ),
            (
                book_workspace._MAX_BOOK_SEMANTIC_ITEM_LABEL_UNITS,
                'semanticText(item.label, "Book semantic item label", false, 1200);',
            ),
            (
                book_workspace._MAX_BOOK_SEMANTIC_RESULT_UNITS,
                'semanticText(item.result, "Book semantic item result", true, 16);',
            ),
        )
        for host_limit, browser_contract in scalar_contract:
            with self.subTest(browser_contract=browser_contract):
                self.assertIn(browser_contract, script)
                self.assertGreater(host_limit, 0)
        self.assertEqual(book_workspace._MAX_BOOK_SEMANTIC_SECTION_LABEL_UNITS, 360)
        self.assertEqual(book_workspace._MAX_BOOK_SEMANTIC_FIELD_LABEL_UNITS, 120)
        self.assertEqual(book_workspace._MAX_BOOK_SEMANTIC_PLAYERS_UNITS, 720)
        self.assertEqual(book_workspace._MAX_BOOK_SEMANTIC_ITEM_LABEL_UNITS, 1_200)
        self.assertEqual(book_workspace._MAX_BOOK_SEMANTIC_RESULT_UNITS, 16)


if __name__ == "__main__":
    unittest.main()
