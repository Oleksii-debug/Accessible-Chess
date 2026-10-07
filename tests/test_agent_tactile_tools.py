from __future__ import annotations

import asyncio
import unittest

from acs.agent_tactile_tools import AgentTactileTools
from acs.agent_tools import ToolCall, ToolExecutor


class AgentTactileToolsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.refreshes = 0
        self.executor = ToolExecutor()

        def status():
            return {
                "connected": True,
                "syncRevision": 7,
                "source": "board",
            }

        def refresh():
            self.refreshes += 1
            return {
                "connected": True,
                "syncRevision": 8,
                "refreshed": True,
            }

        AgentTactileTools(
            status_provider=status,
            refresh_current=refresh,
        ).register(self.executor)

    def execute(self, tool_id, arguments=None):
        return asyncio.run(
            self.executor.execute(
                ToolCall(
                    call_id=tool_id,
                    tool_id=tool_id,
                    arguments=arguments or {},
                )
            )
        )

    def test_status_and_refresh_use_host_authority(self):
        status = self.execute("tactile.status")
        self.assertTrue(status.ok)
        self.assertEqual(status.output["syncRevision"], 7)

        refreshed = self.execute("tactile.refresh")
        self.assertTrue(refreshed.ok)
        self.assertEqual(self.refreshes, 1)
        self.assertTrue(refreshed.output["refreshed"])

    def test_model_cannot_supply_tactile_state_or_fen(self):
        result = self.execute(
            "tactile.refresh",
            {"fen": "8/8/8/8/8/8/8/8 w - - 0 1"},
        )
        self.assertFalse(result.ok)
        self.assertEqual(self.refreshes, 0)

    def test_active_top_level_result_fails_closed(self):
        class ActiveDict(dict):
            pass

        executor = ToolExecutor()
        AgentTactileTools(
            status_provider=lambda: ActiveDict({"connected": True}),
            refresh_current=lambda: {},
        ).register(executor)
        result = asyncio.run(
            executor.execute(
                ToolCall(call_id="active", tool_id="tactile.status", arguments={})
            )
        )
        self.assertFalse(result.ok)


if __name__ == "__main__":
    unittest.main()
