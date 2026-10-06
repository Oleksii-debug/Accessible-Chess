from __future__ import annotations

import asyncio

import pytest

from acs.board_service import BoardCommandService, BoardSnapshot, MoveView
from acs.agent_budget import ModelCostBudget
from acs.agent_model_contracts import (
    ModelRequest,
    ModelResponse,
    ModelUsage,
    ProviderCapabilities,
    ProviderKind,
)
from acs.agent_model_gateway import ModelGateway
from acs.agent_tools import ToolExecutor
from acs.chess_agent_tools import ChessAgentToolRegistry
from acs.chesscore import Board
from acs.universal_chess_agent import AgentRunPolicy, UniversalChessAgentRuntime


class _ScriptedProvider:
    def __init__(self, responses: list[str]) -> None:
        self.responses = list(responses)
        self.requests: list[ModelRequest] = []

    @property
    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(
            provider_id="fixture",
            kind=ProviderKind.LOCAL,
            supports_private_data=True,
        )

    async def complete(self, request: ModelRequest) -> ModelResponse:
        self.requests.append(request)
        if not self.responses:
            raise AssertionError("unexpected model call")
        return ModelResponse(
            request_id=request.request_id,
            text=self.responses.pop(0),
            provider_id="fixture",
            provider_kind=ProviderKind.LOCAL,
            model=request.model or "fixture-model",
            usage=ModelUsage(input_tokens=1, output_tokens=1, total_tokens=2),
        )


class _BlockingProvider(_ScriptedProvider):
    async def complete(self, request: ModelRequest) -> ModelResponse:
        self.requests.append(request)
        await asyncio.sleep(60)
        raise AssertionError("cancel should interrupt provider coroutine")


def _board_commands(board: Board) -> BoardCommandService:
    legal = tuple(
        MoveView(
            move.frm,
            move.to,
            board.san(move),
            bool(board.board[move.to]) or move.en_passant,
        )
        for move in board.legal_moves()
    )
    attacks = {}
    for target in range(64):
        origins = tuple(board.attackers_of(target))
        if origins:
            attacks[target] = origins
    last = board.last_move
    last_view = None if last is None else MoveView(last.frm, last.to)
    return BoardCommandService(
        BoardSnapshot(
            tuple(board.board),
            board.turn,
            legal,
            attacks,
            last_view,
        )
    )


def _runtime(provider, *, budget=None, max_steps=5):
    gateway = ModelGateway()
    gateway.register(provider)
    tools = ToolExecutor()
    board = Board()
    ChessAgentToolRegistry(
        executor=tools,
        board_provider=lambda: board,
        board_commands_provider=lambda: _board_commands(board),
    ).register_all()
    return UniversalChessAgentRuntime(
        gateway=gateway,
        tools=tools,
        provider_id="fixture",
        model="fixture-model",
        product_instruction="Help the user with Accessible Chess.",
        policy=AgentRunPolicy(
            max_steps=max_steps,
            max_model_calls=max_steps,
            estimated_cost_per_model_call="0.10",
        ),
        budget=budget,
    )


def test_agent_executes_real_board_tool_then_returns_final_answer() -> None:
    provider = _ScriptedProvider(
        [
            '{"type":"tool","tool_id":"board.current","arguments":{}}',
            '{"type":"final","text":"White to move; there are 20 legal moves."}',
        ]
    )
    budget = ModelCostBudget("1.00")
    runtime = _runtime(provider, budget=budget)

    result = asyncio.run(
        runtime.run(run_id="run-1", user_text="Describe the current board.")
    )

    assert result.text == "White to move; there are 20 legal moves."
    assert result.model_calls == 2
    assert result.tool_calls == 1
    assert len(provider.requests) == 2
    second_messages = provider.requests[1].messages
    assert second_messages[-1].role == "tool"
    assert '"tool_id":"board.current"' in second_messages[-1].content
    assert '"legalMoveCount":20' in second_messages[-1].content
    assert budget.snapshot().incurred == budget.snapshot().ceiling * 0 + budget.snapshot().incurred
    assert str(budget.snapshot().incurred) == "0.20"


def test_agent_rejects_unregistered_tool_without_granting_authority() -> None:
    provider = _ScriptedProvider(
        [
            '{"type":"tool","tool_id":"filesystem.delete","arguments":{"path":"x"}}',
            '{"type":"final","text":"That tool is not available."}',
        ]
    )
    runtime = _runtime(provider)

    result = asyncio.run(
        runtime.run(run_id="run-2", user_text="Delete something.")
    )

    assert result.tool_calls == 1
    assert result.text == "That tool is not available."
    assert '"ok":false' in provider.requests[1].messages[-1].content
    assert '"error":"unknown tool"' in provider.requests[1].messages[-1].content


@pytest.mark.parametrize(
    "response",
    [
        "not json",
        '{"type":"final","text":"ok","extra":true}',
        '{"type":"tool","tool_id":"board.current","arguments":[]}',
        '{"type":"unknown"}',
    ],
)
def test_agent_protocol_fails_closed_on_malformed_model_envelope(response: str) -> None:
    runtime = _runtime(_ScriptedProvider([response]))
    with pytest.raises(ValueError):
        asyncio.run(runtime.run(run_id="bad-envelope", user_text="test"))


def test_agent_stops_at_model_call_limit() -> None:
    provider = _ScriptedProvider(
        ['{"type":"tool","tool_id":"board.current","arguments":{}}'] * 3
    )
    runtime = _runtime(provider, max_steps=2)
    with pytest.raises(RuntimeError, match="step limit|model-call limit"):
        asyncio.run(runtime.run(run_id="bounded", user_text="loop"))


def test_agent_run_can_be_cancelled() -> None:
    async def scenario() -> None:
        provider = _BlockingProvider([])
        runtime = _runtime(provider)
        task = asyncio.create_task(
            runtime.run(run_id="cancel-me", user_text="wait")
        )
        await asyncio.sleep(0)
        assert await runtime.cancel("cancel-me") is True
        with pytest.raises(asyncio.CancelledError):
            await task
        assert await runtime.cancel("cancel-me") is False

    asyncio.run(scenario())
