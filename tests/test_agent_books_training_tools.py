from __future__ import annotations

import asyncio
import unittest

from acs.agent_books_training_tools import AgentBooksTrainingTools
from acs.agent_tools import ToolCall, ToolExecutor
from acs.board_service import BoardCommandService, BoardSnapshot, MoveView
from acs.chess_agent_tools import ChessAgentToolRegistry
from acs.chesscore import Board


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
        self.assertIn("accepts no arguments", result.error)

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


if __name__ == "__main__":
    unittest.main()
