from __future__ import annotations

import asyncio
import unittest

from acs.agent_tools import ToolCall, ToolExecutor, ToolRisk
from acs.analysis_service import AnalysisService
from acs.chess_agent_tools import ChessAgentToolRegistry
from acs.continuous_analysis import ContinuousAnalysisService
from acs.pgn_workspace import PgnWorkspace


PGN = """[Event "Agent convergence"]
[White "Alpha"]
[Black "Beta"]
[Result "*"]

1. e4 (1. d4 d5) e5 *
"""


class AgentCapabilityConvergenceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.analysis = AnalysisService(lambda: None)
        self.continuous = ContinuousAnalysisService(self.analysis)
        self.workspace = PgnWorkspace.from_text(PGN)
        self.opened: list[dict[str, int]] = []
        self.executor = ToolExecutor()
        ChessAgentToolRegistry(
            executor=self.executor,
            board_provider=lambda: None,
            board_commands_provider=lambda: None,
            continuous_analysis=self.continuous,
            workspace_provider=lambda: self.workspace,
            library_open_game_command=lambda payload: self.opened.append(dict(payload)),
        ).register_all()

    def tearDown(self) -> None:
        self.continuous.close()

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

    def test_registry_composes_green_agent_capability_children_without_duplicates(self) -> None:
        specs = {spec.tool_id: spec for spec in self.executor.specs()}
        expected = {
            "engine.request_analysis",
            "engine.analysis_status",
            "engine.cancel_analysis",
            "gametree.current",
            "gametree.next_move",
            "gametree.previous_move",
            "gametree.enter_variation",
            "gametree.leave_variation",
            "gametree.sibling_variation",
            "gametree.select_game",
            "gametree.next_game",
            "gametree.previous_game",
            "library.open_game",
            "formats.capabilities",
            "formats.chessbase_extension",
        }
        self.assertTrue(expected.issubset(specs))
        self.assertEqual(len(specs), len({spec.tool_id for spec in self.executor.specs()}))
        self.assertIs(specs["engine.analysis_status"].risk, ToolRisk.READ_ONLY)
        self.assertIs(specs["engine.request_analysis"].risk, ToolRisk.LOCAL_WRITE)
        self.assertIs(specs["gametree.current"].risk, ToolRisk.READ_ONLY)
        self.assertIs(specs["gametree.next_move"].risk, ToolRisk.LOCAL_WRITE)
        self.assertIs(specs["library.open_game"].risk, ToolRisk.LOCAL_WRITE)
        self.assertIs(specs["formats.capabilities"].risk, ToolRisk.READ_ONLY)
        self.assertIs(specs["formats.chessbase_extension"].risk, ToolRisk.READ_ONLY)

    def test_composed_registry_executes_gametree_and_library_boundaries(self) -> None:
        current = self.execute("gametree.current")
        self.assertTrue(current.ok, current.error)
        self.assertEqual(current.output["currentMove"]["san"], "e4")
        opened = self.execute(
            "library.open_game",
            {"game_id": 7, "source_id": 3, "source_index": 2},
        )
        self.assertTrue(opened.ok, opened.error)
        self.assertEqual(
            self.opened,
            [{"game_id": 7, "source_id": 3, "source_index": 2}],
        )


if __name__ == "__main__":
    unittest.main()
