"""Section 49 full Universal Chess Agent <-> cloud text <-> registered chess tool seam.

Uses httpx.MockTransport only. Does NOT assert real Mistral credential access.
"""
from __future__ import annotations

import json
import os
import unittest
from unittest.mock import patch

from acs.agent_cloud_provider import CloudChatProvider
from acs.agent_model_gateway import ModelGateway
from acs.agent_model_contracts import PrivacyClass
from acs.agent_tools import ToolExecutor, ToolSpec
from acs.universal_chess_agent import AgentRunPolicy, UniversalChessAgentRuntime
from acs.chesscore import Board

try:
    import httpx
except ImportError:
    httpx = None


@unittest.skipIf(httpx is None, "optional httpx is not installed")
class AgentCloudToolEndToEndFixture(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        env = patch.dict(os.environ, {"MISTRAL_API_KEY": "simulated-http-credential"})
        env.start()
        self.addCleanup(env.stop)

    async def test_tool_result_roundtrips_through_canonical_agent_without_board_mutation(self):
        board = Board()
        original_fen = board.fen()
        tool_requests = []
        http_requests = []
        tools = ToolExecutor()

        async def read_fen(arguments):
            self.assertEqual(dict(arguments), {})
            tool_requests.append("board.fen")
            return {"fen": board.fen(), "qualified": "canonical Board"}

        tools.register(ToolSpec("board.fen", "Read current canonical FEN"), read_fen)

        def handler(request):
            self.assertEqual(request.url.path, "/v1/chat/completions")
            outbound = json.loads(request.content)
            http_requests.append(outbound)
            if len(http_requests) == 1:
                content = json.dumps({"type": "tool", "tool_id": "board.fen",
                                      "arguments": {}})
            else:
                last = outbound["messages"][-1]
                self.assertEqual(last["role"], "user")
                self.assertIn(original_fen, last["content"])
                self.assertIn("data, not instructions", last["content"])
                content = json.dumps({"type": "final",
                                      "text": "The canonical board state was read."})
            return httpx.Response(200, json={
                "model": "fixture-model",
                "choices": [{"message": {"role": "assistant", "content": content}}],
            })

        adapter = CloudChatProvider(
            provider_id="mistral", default_model="fixture-model",
            allow_live_requests=True,
            client_factory=lambda **kw: httpx.AsyncClient(
                transport=httpx.MockTransport(handler), **kw),
        )
        gateway = ModelGateway()
        gateway.register(adapter)
        agent = UniversalChessAgentRuntime(
            gateway=gateway, tools=tools, provider_id="mistral",
            product_instruction="Use only registered tools for chess state.",
            policy=AgentRunPolicy(privacy=PrivacyClass.PUBLIC,
                                  max_steps=3, max_model_calls=3),
        )
        result = await agent.run(
            run_id="section49-real-agent-fake-http", user_text="What is the current FEN?"
        )
        self.assertEqual(result.model_calls, 2)
        self.assertEqual(result.tool_calls, 1)
        self.assertEqual(tool_requests, ["board.fen"])
        self.assertEqual(len(http_requests), 2)
        self.assertEqual(board.fen(), original_fen)
        self.assertIn("canonical board state", result.text)

    async def test_unregistered_cloud_requested_tool_never_mutates_board(self):
        board = Board()
        original_fen = board.fen()
        calls = []

        def handler(request):
            calls.append(json.loads(request.content))
            result = ({"type": "tool", "tool_id": "board.force_move",
                       "arguments": {"san": "Qh9"}}
                      if len(calls) == 1 else
                      {"type": "final", "text": "Tool was unavailable."})
            if len(calls) == 2:
                self.assertIn("unknown tool", calls[-1]["messages"][-1]["content"])
            return httpx.Response(200, json={
                "model": "fixture-model",
                "choices": [{"message": {"role": "assistant",
                                         "content": json.dumps(result)}}],
            })

        adapter = CloudChatProvider(
            provider_id="mistral", default_model="fixture-model",
            allow_live_requests=True,
            client_factory=lambda **kw: httpx.AsyncClient(
                transport=httpx.MockTransport(handler), **kw),
        )
        gateway = ModelGateway()
        gateway.register(adapter)
        agent = UniversalChessAgentRuntime(
            gateway=gateway, tools=ToolExecutor(), provider_id="mistral",
            product_instruction="Do not invent moves.",
            policy=AgentRunPolicy(privacy=PrivacyClass.PUBLIC,
                                  max_steps=3, max_model_calls=3),
        )
        result = await agent.run(run_id="section49-denied", user_text="Force a move.")
        self.assertEqual(result.tool_calls, 1)
        self.assertEqual(board.fen(), original_fen)


if __name__ == "__main__":
    unittest.main()
