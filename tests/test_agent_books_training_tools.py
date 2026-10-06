from __future__ import annotations

import asyncio
import unittest

from acs.agent_books_training_tools import AgentBooksTrainingTools
from acs.agent_model_contracts import (
    ModelRequest,
    ModelResponse,
    ModelUsage,
    ProviderCapabilities,
    ProviderKind,
)
from acs.agent_model_gateway import ModelGateway
from acs.agent_tools import ToolCall, ToolExecutor
from acs.board_service import BoardCommandService, BoardSnapshot, MoveView
from acs.chess_agent_tools import ChessAgentToolRegistry
from acs.chesscore import Board
from acs.universal_chess_agent import UniversalChessAgentRuntime


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
    return BoardCommandService(
        BoardSnapshot(tuple(board.board), board.turn, legal, attacks, None)
    )


def _execute(executor: ToolExecutor, tool_id: str, arguments=None):
    return asyncio.run(
        executor.execute(
            ToolCall(
                call_id=f"call-{tool_id}",
                tool_id=tool_id,
                arguments=arguments or {},
            )
        )
    )


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


class AgentBooksTrainingToolsTests(unittest.TestCase):
    def setUp(self):
        self.snapshot = {
            "books": {
                "document": {"lang": "en", "landmark": "main"},
                "block": {
                    "dom_id": "book-block-7",
                    "index": 7,
                    "kind": "Paragraph",
                    "role": "paragraph",
                    "title": "Candidate positions",
                    "text": "A sanitized, selectable book paragraph.",
                    "heading_level": None,
                    "has_position": False,
                    "heading_path": ("Chapter 2",),
                    "source_anchor": "chapter-2",
                    "warning": "",
                },
                "actions": (
                    {"command": "book.previous", "label": "Previous", "enabled": True},
                    {"command": "book.next", "label": "Next", "enabled": True},
                ),
            },
            "training": {
                "document": {"lang": "en", "landmark": "main"},
                "title": "Find the best continuation",
                "status": "active",
                "progress": {
                    "step": 1,
                    "total": 3,
                    "attempts": 0,
                    "mistakes": 0,
                    "hints_used": 0,
                    "completed": False,
                },
                "message": "",
                "actions": (
                    {"command": "training.hint", "label": "Hint", "enabled": True},
                ),
            },
        }

    def test_tools_return_detached_sanitized_application_surfaces(self):
        executor = ToolExecutor()
        AgentBooksTrainingTools(lambda: self.snapshot).register(executor)

        books = _execute(executor, "books.current")
        training = _execute(executor, "training.status")

        self.assertTrue(books.ok, books.error)
        self.assertTrue(training.ok, training.error)
        self.assertTrue(books.output["available"])
        self.assertTrue(training.output["available"])
        self.assertEqual(
            books.output["view"]["block"]["heading_path"], ["Chapter 2"]
        )
        self.assertEqual(training.output["view"]["progress"]["step"], 1)

        self.snapshot["books"]["block"]["text"] = "mutated after result"
        self.assertEqual(
            books.output["view"]["block"]["text"],
            "A sanitized, selectable book paragraph.",
        )

    def test_unavailable_surfaces_are_explicit(self):
        executor = ToolExecutor()
        AgentBooksTrainingTools(lambda: {"books": None, "training": None}).register(
            executor
        )
        self.assertEqual(
            _execute(executor, "books.current").output, {"available": False}
        )
        self.assertEqual(
            _execute(executor, "training.status").output, {"available": False}
        )

    def test_active_or_malformed_snapshot_values_fail_closed(self):
        class ActiveDict(dict):
            pass

        snapshots = (
            ActiveDict(books={}, training={}),
            {"books": ActiveDict(), "training": None},
            {"books": {"block": object()}, "training": None},
        )
        for snapshot in snapshots:
            with self.subTest(snapshot=type(snapshot).__name__):
                executor = ToolExecutor()
                AgentBooksTrainingTools(
                    lambda snapshot=snapshot: snapshot
                ).register(executor)
                self.assertFalse(_execute(executor, "books.current").ok)

    def test_read_only_tools_reject_model_supplied_arguments(self):
        executor = ToolExecutor()
        AgentBooksTrainingTools(lambda: self.snapshot).register(executor)
        result = _execute(executor, "books.current", {"path": "secret"})
        self.assertFalse(result.ok)
        self.assertEqual(result.error, "tool failed")

    def test_registry_composes_books_training_without_new_semantics(self):
        board = Board()
        executor = ToolExecutor()
        ids = {
            spec.tool_id
            for spec in ChessAgentToolRegistry(
                executor=executor,
                board_provider=lambda: board,
                board_commands_provider=lambda: _board_commands(board),
                application_snapshot_provider=lambda: self.snapshot,
            ).register_all()
        }
        self.assertIn("books.current", ids)
        self.assertIn("training.status", ids)

        books = _execute(executor, "books.current")
        self.assertTrue(books.ok, books.error)
        rendered = str(books.output).casefold()
        self.assertNotIn("fen", rendered)
        self.assertNotIn("accepted_moves", rendered)

    def test_universal_agent_round_trips_both_application_surfaces(self):
        board = Board()
        executor = ToolExecutor()
        ChessAgentToolRegistry(
            executor=executor,
            board_provider=lambda: board,
            board_commands_provider=lambda: _board_commands(board),
            application_snapshot_provider=lambda: self.snapshot,
        ).register_all()
        provider = _ScriptedProvider(
            [
                '{"type":"tool","tool_id":"books.current","arguments":{}}',
                '{"type":"tool","tool_id":"training.status","arguments":{}}',
                '{"type":"final","text":"Book and training context read."}',
            ]
        )
        gateway = ModelGateway()
        gateway.register(provider)
        runtime = UniversalChessAgentRuntime(
            gateway=gateway,
            tools=executor,
            provider_id="fixture",
            model="fixture-model",
            product_instruction="Use Accessible Chess application tools only.",
        )

        result = asyncio.run(
            runtime.run(run_id="books-training-e2e", user_text="Read my learning context.")
        )

        self.assertEqual(result.text, "Book and training context read.")
        self.assertEqual(result.tool_calls, 2)
        self.assertEqual(len(provider.requests), 3)
        book_result = provider.requests[1].messages[-1].content
        training_result = provider.requests[2].messages[-1].content
        self.assertIn("A sanitized, selectable book paragraph.", book_result)
        self.assertIn("Find the best continuation", training_result)
        self.assertNotIn("accepted_moves", book_result)
        self.assertNotIn("start_fen", training_result)


if __name__ == "__main__":
    unittest.main()
