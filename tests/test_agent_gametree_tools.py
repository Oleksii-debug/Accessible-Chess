from __future__ import annotations

import asyncio
import unittest

from acs.agent_gametree_tools import register_gametree_tools
from acs.agent_tools import ToolCall, ToolExecutor, ToolRisk
from acs.chess_agent_tools import ChessAgentToolRegistry
from acs.pgn_workspace import PgnWorkspace


PGN = """[Event "Tree One"]
[White "Alpha"]
[Black "Beta"]
[Result "*"]

1. e4 e5 (1... c5 2. Nf3) (1... e6 2. d4) 2. Nf3 Nc6 *

[Event "Tree Two"]
[White "Gamma"]
[Black "Delta"]
[Result "1-0"]

1. d4 d5 1-0
"""


class AgentGameTreeToolsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.workspace = PgnWorkspace.from_text(PGN)
        self.executor = ToolExecutor()
        register_gametree_tools(self.executor, lambda: self.workspace)

    def execute(self, tool_id: str, arguments=None):
        return asyncio.run(
            self.executor.execute(
                ToolCall(
                    call_id=f"call-{tool_id}",
                    tool_id=tool_id,
                    arguments=arguments or {},
                )
            )
        )

    def test_status_is_bounded_canonical_workspace_state(self) -> None:
        result = self.execute("gametree.current")
        self.assertTrue(result.ok, result.error)
        self.assertEqual(result.output["gameCount"], 2)
        self.assertEqual(result.output["selectedGameIndex"], 0)
        self.assertEqual(result.output["game"]["event"], "Tree One")
        self.assertEqual(result.output["cursor"]["linePath"], [])
        self.assertEqual(result.output["cursor"]["nextMoveIndex"], 0)
        self.assertEqual(result.output["currentMove"]["san"], "e4")
        self.assertIsNone(result.output["previousMove"])
        self.assertTrue(result.output["atLineStart"])
        self.assertFalse(result.output["atLineEnd"])
        self.assertFalse(result.output["dirty"])

    def test_navigation_reuses_workspace_branch_return_semantics(self) -> None:
        original_digest = self.workspace.content_digest
        self.assertTrue(self.execute("gametree.next_move").ok)
        parent = self.execute("gametree.next_move")
        self.assertTrue(parent.ok, parent.error)
        self.assertEqual(parent.output["previousMove"]["san"], "e5")
        self.assertEqual(parent.output["availableVariations"], 2)

        entered = self.execute(
            "gametree.enter_variation", {"variation_index": 0}
        )
        self.assertTrue(entered.ok, entered.error)
        self.assertEqual(
            entered.output["cursor"]["linePath"],
            [{"parentMoveIndex": 1, "variationIndex": 0}],
        )
        self.assertEqual(entered.output["currentMove"]["san"], "c5")
        self.assertEqual(entered.output["siblingVariationCount"], 2)

        sibling = self.execute(
            "gametree.sibling_variation", {"direction": "next"}
        )
        self.assertTrue(sibling.ok, sibling.error)
        self.assertEqual(
            sibling.output["cursor"]["linePath"],
            [{"parentMoveIndex": 1, "variationIndex": 1}],
        )
        self.assertEqual(sibling.output["currentMove"]["san"], "e6")

        left = self.execute("gametree.leave_variation")
        self.assertTrue(left.ok, left.error)
        self.assertEqual(left.output["cursor"]["linePath"], [])
        self.assertEqual(left.output["cursor"]["nextMoveIndex"], 2)
        self.assertEqual(left.output["currentMove"]["san"], "Nf3")

        self.assertEqual(self.workspace.content_digest, original_digest)
        self.assertFalse(self.workspace.dirty)
        self.assertEqual(self.workspace.content_revision, 0)

    def test_failed_navigation_is_atomic(self) -> None:
        before = self.workspace.view()
        digest = self.workspace.content_digest
        for tool_id, arguments in (
            ("gametree.previous_move", {}),
            ("gametree.enter_variation", {"variation_index": True}),
            ("gametree.enter_variation", {"variation_index": 0}),
        ):
            with self.subTest(tool_id=tool_id, arguments=arguments):
                result = self.execute(tool_id, arguments)
                self.assertFalse(result.ok)
                self.assertEqual(result.error, "tool failed")
                self.assertEqual(self.workspace.view(), before)
        self.assertEqual(self.workspace.content_digest, digest)
        self.assertFalse(self.workspace.dirty)

    def test_multi_game_navigation_resets_cursor_without_editing_pgn(self) -> None:
        digest = self.workspace.content_digest
        self.assertTrue(self.execute("gametree.next_move").ok)

        selected = self.execute("gametree.select_game", {"index": 1})
        self.assertTrue(selected.ok, selected.error)
        self.assertEqual(selected.output["selectedGameIndex"], 1)
        self.assertEqual(selected.output["game"]["event"], "Tree Two")
        self.assertEqual(selected.output["cursor"]["nextMoveIndex"], 0)
        self.assertEqual(selected.output["currentMove"]["san"], "d4")

        failed = self.execute("gametree.next_game")
        self.assertFalse(failed.ok)
        self.assertEqual(self.workspace.selected_game_index, 1)

        back = self.execute("gametree.previous_game")
        self.assertTrue(back.ok, back.error)
        self.assertEqual(back.output["selectedGameIndex"], 0)
        self.assertEqual(self.workspace.content_digest, digest)
        self.assertFalse(self.workspace.dirty)

    def test_navigation_risk_is_explicit(self) -> None:
        specs = {spec.tool_id: spec for spec in self.executor.specs()}
        self.assertEqual(specs["gametree.current"].risk, ToolRisk.READ_ONLY)
        for tool_id in (
            "gametree.next_move",
            "gametree.previous_move",
            "gametree.enter_variation",
            "gametree.leave_variation",
            "gametree.sibling_variation",
            "gametree.select_game",
            "gametree.next_game",
            "gametree.previous_game",
        ):
            self.assertEqual(specs[tool_id].risk, ToolRisk.LOCAL_WRITE)

    def test_main_registry_composes_same_gametree_adapter(self) -> None:
        executor = ToolExecutor()
        ChessAgentToolRegistry(
            executor=executor,
            board_provider=lambda: None,
            board_commands_provider=lambda: None,
            workspace_provider=lambda: self.workspace,
        ).register_all()
        ids = {spec.tool_id for spec in executor.specs()}
        self.assertTrue(
            {
                "gametree.current",
                "gametree.next_move",
                "gametree.previous_move",
                "gametree.enter_variation",
                "gametree.leave_variation",
                "gametree.sibling_variation",
                "gametree.select_game",
                "gametree.next_game",
                "gametree.previous_game",
            }.issubset(ids)
        )

    def test_workspace_provider_must_return_exact_workspace(self) -> None:
        executor = ToolExecutor()
        register_gametree_tools(executor, lambda: object())
        result = asyncio.run(
            executor.execute(
                ToolCall(
                    call_id="wrong-workspace",
                    tool_id="gametree.current",
                    arguments={},
                )
            )
        )
        self.assertFalse(result.ok)
        self.assertEqual(result.error, "tool failed")


if __name__ == "__main__":
    unittest.main()
