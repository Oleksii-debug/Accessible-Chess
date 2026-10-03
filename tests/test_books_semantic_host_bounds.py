from __future__ import annotations

from pathlib import Path
import unittest
from unittest.mock import patch

from acs import version2_book_workspace as book_workspace
from acs.analysis_service import AnalysisService
from acs.book_board_workflow import BookBoardMode, BookBoardWorkflow
from acs.bookdocument import BookDocument, Game
from acs.bookreader import BookReader
from acs.engine_assisted_workflows import EngineAssistedWorkflowService
from acs.full_product_presenters import PgnGameView, PgnTreeItem
from acs.gametree import Comment, MoveNode, PgnGame, VariationLine
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
    def presenter_item(**overrides) -> PgnTreeItem:
        values = {
            "node_id": "g0:m0",
            "kind": "move",
            "depth": 0,
            "label": "1. e4",
            "parent_id": None,
            "san": None,
            "comments": (),
            "nags": (),
            "trailing_comments": (),
            "comments_before": (),
            "comments_after": (),
            "result": None,
        }
        values.update(overrides)
        return PgnTreeItem(**values)

    @staticmethod
    def presenter_view(*items: PgnTreeItem, game_index: object = 0) -> PgnGameView:
        return PgnGameView(
            game_index=game_index,
            title="",
            result="*",
            tags=(),
            warnings=(),
            items=tuple(items),
            selected_node_id=None,
        )

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

    def test_sanitized_empty_comments_do_not_consume_serialized_entry_budget(self):
        reader, workflow, bridge = self.compose()
        before = reader.snapshot()
        game = self.semantic_game()
        # Raw preflight sees exactly eight semantic strings here: White, Black,
        # effective/line result, SAN, move number, plus these two comments.
        # Both comments sanitize to empty, so neither is serialized into the
        # browser semantic tree and the browser-visible text-entry count remains
        # the canonical eight entries for a single-move game.
        game.line.leading_comments = [Comment(""), Comment(" \x00 ")]

        with (
            patch.object(
                workflow,
                "semantic_game_snapshot",
                return_value=(BookBoardMode.GAME, game, ()),
            ),
            patch("acs.version2_book_workspace._MAX_BOOK_SEMANTIC_TEXT_ENTRIES", 8),
        ):
            snapshot = bridge.projection.snapshot()

        self.assertIsInstance(snapshot["semantic_tree"], dict)
        self.assertEqual(snapshot["semantic_tree"]["intro_comments"], ())
        self.assertFalse(workflow.active)
        self.assertEqual(workflow.revision, 0)
        self.assertEqual(reader.snapshot(), before)

    def test_visible_text_budget_counts_generated_variation_and_result_labels(self):
        reader, workflow, bridge = self.compose()
        before = reader.snapshot()
        game = self.semantic_game()

        def presenter_view(comment_size: int) -> PgnGameView:
            return self.presenter_view(
                self.presenter_item(),
                self.presenter_item(
                    kind="variation",
                    depth=1,
                    node_id="g0:m0/v0",
                    parent_id="g0:m0",
                    label="Variation 1",
                    comments=("x" * comment_size,),
                    result="*",
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
        malformed_view = self.presenter_view(
            self.presenter_item(
                kind="variation",
                depth=0,
                node_id="g0:main/v0",
                label="Variation 1",
            )
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

    def test_hostile_tag_key_falls_back_before_named_lookup(self):
        reader, workflow, bridge = self.compose()
        before = reader.snapshot()
        game = self.semantic_game()

        class HostileTagKey:
            def __hash__(self):
                return hash("White")

            def __eq__(self, other):
                raise AssertionError("hostile tag key must not participate in named lookup")

        game.tags = {
            HostileTagKey(): "Alpha",
            "Black": "Beta",
            "Result": "*",
        }

        with patch.object(
            workflow,
            "semantic_game_snapshot",
            return_value=(BookBoardMode.GAME, game, ()),
        ):
            snapshot = bridge.projection.snapshot()

        self.assert_accessible_fallback(snapshot, reader, workflow, before)

    def test_malformed_root_line_falls_back_before_result_property_access(self):
        reader, workflow, bridge = self.compose()
        before = reader.snapshot()
        game = self.semantic_game()

        class HostileLine:
            @property
            def result(self):
                raise AssertionError("malformed root line result must not be accessed")

        game.line = HostileLine()

        with patch.object(
            workflow,
            "semantic_game_snapshot",
            return_value=(BookBoardMode.GAME, game, ()),
        ):
            snapshot = bridge.projection.snapshot()

        self.assert_accessible_fallback(snapshot, reader, workflow, before)

    def test_root_result_subclass_falls_back_before_truthiness(self):
        reader, workflow, bridge = self.compose()
        before = reader.snapshot()
        game = self.semantic_game()

        class HostileResult(str):
            def __bool__(self):
                raise AssertionError("malformed root result must not be truth-tested")

        game.line.result = HostileResult("*")

        with (
            patch.object(
                workflow,
                "semantic_game_snapshot",
                return_value=(BookBoardMode.GAME, game, ()),
            ),
            patch(
                "acs.version2_book_workspace.PgnTreePresenter",
                side_effect=AssertionError(
                    "PgnTreePresenter must not receive a hostile root result"
                ),
            ) as presenter,
        ):
            snapshot = bridge.projection.snapshot()

        presenter.assert_not_called()
        self.assert_accessible_fallback(snapshot, reader, workflow, before)

    def test_malformed_mode_falls_back_before_value_access(self):
        reader, workflow, bridge = self.compose()
        before = reader.snapshot()
        game = self.semantic_game()

        class HostileMode:
            @property
            def value(self):
                raise AssertionError("malformed semantic mode value must not be accessed")

        with patch.object(
            workflow,
            "semantic_game_snapshot",
            return_value=(HostileMode(), game, ()),
        ):
            snapshot = bridge.projection.snapshot()

        self.assert_accessible_fallback(snapshot, reader, workflow, before)

    def test_raw_comment_budget_falls_back_before_presenter_scan(self):
        reader, workflow, bridge = self.compose()
        before = reader.snapshot()
        game = self.semantic_game(white="A")
        game.line.leading_comments = [Comment("x" * 1001)]

        with (
            patch.object(
                workflow,
                "semantic_game_snapshot",
                return_value=(BookBoardMode.GAME, game, ()),
            ),
            patch(
                "acs.version2_book_workspace._MAX_BOOK_BLOCK_VISIBLE_CHARS",
                1000,
            ),
            patch(
                "acs.version2_book_workspace.PgnTreePresenter",
                side_effect=AssertionError(
                    "PgnTreePresenter must not scan raw over-budget comments"
                ),
            ) as presenter,
        ):
            snapshot = bridge.projection.snapshot()

        presenter.assert_not_called()
        self.assert_accessible_fallback(snapshot, reader, workflow, before)

    def test_raw_supplementary_comment_uses_utf16_budget_before_presenter(self):
        reader, workflow, bridge = self.compose()
        before = reader.snapshot()
        game = self.semantic_game()
        # The unchanged raw game consumes 14 Python characters. Fifteen emoji
        # make the old code-point total exactly 29, but the comment alone costs
        # 30 UTF-16 units and must be rejected before presenter scanning.
        game.line.leading_comments = [Comment("😀" * 15)]

        with (
            patch.object(
                workflow,
                "semantic_game_snapshot",
                return_value=(BookBoardMode.GAME, game, ()),
            ),
            patch(
                "acs.version2_book_workspace._MAX_BOOK_BLOCK_VISIBLE_CHARS",
                29,
            ),
            patch(
                "acs.version2_book_workspace.PgnTreePresenter",
                side_effect=AssertionError(
                    "PgnTreePresenter must not scan UTF-16-over-budget comments"
                ),
            ) as presenter,
        ):
            snapshot = bridge.projection.snapshot()

        presenter.assert_not_called()
        self.assert_accessible_fallback(snapshot, reader, workflow, before)

    def test_raw_supplementary_comment_aggregate_uses_utf16_budget(self):
        reader, workflow, bridge = self.compose()
        before = reader.snapshot()
        game = self.semantic_game()
        # Fourteen ordinary units plus two eight-code-point emoji comments are
        # only 30 Python characters, but 46 UTF-16 units.
        game.line.leading_comments = [Comment("😀" * 8), Comment("😀" * 8)]

        with (
            patch.object(
                workflow,
                "semantic_game_snapshot",
                return_value=(BookBoardMode.GAME, game, ()),
            ),
            patch(
                "acs.version2_book_workspace._MAX_BOOK_BLOCK_VISIBLE_CHARS",
                30,
            ),
            patch(
                "acs.version2_book_workspace.PgnTreePresenter",
                side_effect=AssertionError(
                    "PgnTreePresenter must not scan UTF-16-over-budget comment aggregates"
                ),
            ) as presenter,
        ):
            snapshot = bridge.projection.snapshot()

        presenter.assert_not_called()
        self.assert_accessible_fallback(snapshot, reader, workflow, before)

    def test_raw_supplementary_players_fail_before_presenter_interpolation(self):
        reader, workflow, bridge = self.compose()
        before = reader.snapshot()
        # Each player scalar is individually legal, but 358 emoji consume 716
        # UTF-16 units; with " — " and "Beta" the rendered players field is 723.
        game = self.semantic_game(white="😀" * 358)

        with (
            patch.object(
                workflow,
                "semantic_game_snapshot",
                return_value=(BookBoardMode.GAME, game, ()),
            ),
            patch(
                "acs.version2_book_workspace.PgnTreePresenter",
                side_effect=AssertionError(
                    "PgnTreePresenter must not interpolate UTF-16-over-budget players"
                ),
            ) as presenter,
        ):
            snapshot = bridge.projection.snapshot()

        presenter.assert_not_called()
        self.assert_accessible_fallback(snapshot, reader, workflow, before)

    def test_raw_supplementary_nag_label_fails_before_presenter_join(self):
        reader, workflow, bridge = self.compose()
        before = reader.snapshot()
        game = self.semantic_game()
        # The NAG itself is 1,196 UTF-16 units. Adding "1. e4" presentation
        # punctuation makes the final label 1,201 units, above the 1,200 limit.
        game.line.moves[0].nags = ["😀" * 598]

        with (
            patch.object(
                workflow,
                "semantic_game_snapshot",
                return_value=(BookBoardMode.GAME, game, ()),
            ),
            patch(
                "acs.version2_book_workspace.PgnTreePresenter",
                side_effect=AssertionError(
                    "PgnTreePresenter must not join UTF-16-over-budget NAG labels"
                ),
            ) as presenter,
        ):
            snapshot = bridge.projection.snapshot()

        presenter.assert_not_called()
        self.assert_accessible_fallback(snapshot, reader, workflow, before)

    def test_raw_comment_count_falls_back_before_presenter_iteration(self):
        reader, workflow, bridge = self.compose()
        before = reader.snapshot()
        game = self.semantic_game()
        game.line.leading_comments = [Comment("x")] * 50_001

        with (
            patch.object(
                workflow,
                "semantic_game_snapshot",
                return_value=(BookBoardMode.GAME, game, ()),
            ),
            patch(
                "acs.version2_book_workspace.PgnTreePresenter",
                side_effect=AssertionError(
                    "PgnTreePresenter must not iterate over-count comments"
                ),
            ) as presenter,
        ):
            snapshot = bridge.projection.snapshot()

        presenter.assert_not_called()
        self.assert_accessible_fallback(snapshot, reader, workflow, before)

    def test_raw_nag_label_budget_falls_back_before_presenter_join(self):
        reader, workflow, bridge = self.compose()
        before = reader.snapshot()
        game = self.semantic_game()
        game.line.moves[0].nags = ["!" * 1201]

        with (
            patch.object(
                workflow,
                "semantic_game_snapshot",
                return_value=(BookBoardMode.GAME, game, ()),
            ),
            patch(
                "acs.version2_book_workspace.PgnTreePresenter",
                side_effect=AssertionError(
                    "PgnTreePresenter must not join over-budget NAG text"
                ),
            ) as presenter,
        ):
            snapshot = bridge.projection.snapshot()

        presenter.assert_not_called()
        self.assert_accessible_fallback(snapshot, reader, workflow, before)

    def test_empty_nag_join_boundary_is_accepted(self):
        reader, workflow, bridge = self.compose()
        before = reader.snapshot()
        game = self.semantic_game()
        # Base label "1 e4" costs four units. 1,196 empty NAG elements create
        # 1,195 join separators plus the presenter's one annotation separator:
        # exactly 1,200 raw label units.
        game.line.moves[0].nags = [""] * 1_196

        with patch.object(
            workflow,
            "semantic_game_snapshot",
            return_value=(BookBoardMode.GAME, game, ()),
        ):
            snapshot = bridge.projection.snapshot()

        self.assertIsInstance(snapshot["semantic_tree"], dict)
        self.assertEqual(snapshot["semantic_tree"]["items"][0]["label"], "1 e4")
        self.assertFalse(workflow.active)
        self.assertEqual(workflow.revision, 0)
        self.assertEqual(reader.snapshot(), before)

    def test_empty_nag_join_overflow_falls_back_before_presenter(self):
        reader, workflow, bridge = self.compose()
        before = reader.snapshot()
        game = self.semantic_game()
        # One more empty element creates one more join separator. The old
        # cumulative-nonempty accounting saw zero annotation units here.
        game.line.moves[0].nags = [""] * 1_197

        with (
            patch.object(
                workflow,
                "semantic_game_snapshot",
                return_value=(BookBoardMode.GAME, game, ()),
            ),
            patch(
                "acs.version2_book_workspace.PgnTreePresenter",
                side_effect=AssertionError(
                    "PgnTreePresenter must not join an over-budget NAG annotation"
                ),
            ) as presenter,
        ):
            snapshot = bridge.projection.snapshot()

        presenter.assert_not_called()
        self.assert_accessible_fallback(snapshot, reader, workflow, before)

    def test_effective_result_bound_precedes_result_set_hashing_and_presenter(self):
        reader, workflow, bridge = self.compose()
        before = reader.snapshot()
        game = self.semantic_game()
        game.line.result = "x" * 17

        with (
            patch.object(
                workflow,
                "semantic_game_snapshot",
                return_value=(BookBoardMode.GAME, game, ()),
            ),
            patch(
                "acs.version2_book_workspace.PgnTreePresenter",
                side_effect=AssertionError(
                    "PgnTreePresenter must not receive an over-budget result"
                ),
            ) as presenter,
        ):
            snapshot = bridge.projection.snapshot()

        presenter.assert_not_called()
        self.assert_accessible_fallback(snapshot, reader, workflow, before)

    def test_noncanonical_presenter_view_falls_back_before_attribute_access(self):
        reader, workflow, bridge = self.compose()
        before = reader.snapshot()
        game = self.semantic_game()

        class HostileView:
            @property
            def game_index(self):
                raise AssertionError("noncanonical presenter view must not be inspected")

        with (
            patch.object(
                workflow,
                "semantic_game_snapshot",
                return_value=(BookBoardMode.GAME, game, ()),
            ),
            patch(
                "acs.version2_book_workspace.PgnTreePresenter.view",
                return_value=HostileView(),
            ),
        ):
            snapshot = bridge.projection.snapshot()

        self.assert_accessible_fallback(snapshot, reader, workflow, before)

    def test_noncanonical_presenter_item_falls_back_before_field_access(self):
        reader, workflow, bridge = self.compose()
        before = reader.snapshot()
        game = self.semantic_game()

        class HostileItem:
            @property
            def kind(self):
                raise AssertionError("noncanonical presenter item must not be inspected")

        malformed_view = self.presenter_view(HostileItem())

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

    def test_presenter_items_tuple_subclass_is_rejected_before_len(self):
        reader, workflow, bridge = self.compose()
        before = reader.snapshot()
        game = self.semantic_game()

        class HostileItems(tuple):
            def __len__(self):
                raise AssertionError("noncanonical items tuple must not be measured")

        malformed_view = PgnGameView(
            game_index=0,
            title="",
            result="*",
            tags=(),
            warnings=(),
            items=HostileItems(),
            selected_node_id=None,
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

    def test_presenter_game_index_subclass_is_rejected_before_comparison(self):
        reader, workflow, bridge = self.compose()
        before = reader.snapshot()
        game = self.semantic_game()

        class HostileIndex(int):
            def __eq__(self, other):
                raise AssertionError("hostile presenter index must not be compared")

            def __ne__(self, other):
                raise AssertionError("hostile presenter index must not be compared")

        malformed_view = self.presenter_view(game_index=HostileIndex(0))

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

    def test_presenter_comment_slots_are_bounded_before_aggregate_comparison(self):
        reader, workflow, bridge = self.compose()
        before = reader.snapshot()
        game = self.semantic_game()
        malformed_view = self.presenter_view(
            self.presenter_item(
                comments=("x" * 1201,),
                comments_before=("x" * 1201,),
            )
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
            patch(
                "acs.version2_book_workspace._MAX_BOOK_BLOCK_VISIBLE_CHARS",
                1200,
            ),
        ):
            snapshot = bridge.projection.snapshot()

        self.assert_accessible_fallback(snapshot, reader, workflow, before)

    def test_presenter_node_identity_bound_precedes_dictionary_hashing(self):
        reader, workflow, bridge = self.compose()
        before = reader.snapshot()
        game = self.semantic_game()
        malformed_view = self.presenter_view(
            self.presenter_item(node_id="xxxxx")
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
            patch(
                "acs.version2_book_workspace._MAX_BOOK_SEMANTIC_NODE_ID_CHARS",
                4,
            ),
        ):
            snapshot = bridge.projection.snapshot()

        self.assert_accessible_fallback(snapshot, reader, workflow, before)

    def test_presenter_node_id_subclass_is_rejected_before_hash(self):
        reader, workflow, bridge = self.compose()
        before = reader.snapshot()
        game = self.semantic_game()

        class HostileNodeId(str):
            def __hash__(self):
                raise AssertionError("hostile semantic node id must never be hashed")

        malformed_view = self.presenter_view(
            self.presenter_item(node_id=HostileNodeId("g0:m0"))
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
