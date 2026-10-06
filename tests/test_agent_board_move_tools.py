from __future__ import annotations

import asyncio
from pathlib import Path
from queue import Queue
from threading import Event, Thread, get_ident
import tempfile
import unittest

from acs.agent_execution_host import AgentOwnerThreadCall
from acs.agent_tools import ToolCall, ToolExecutor, ToolRisk
from acs.board_service import BoardCommandService, BoardSnapshot, MoveView
from acs.chess_agent_tools import ChessAgentToolRegistry
from acs.chesscore import Board
from acs.stage1_release_ui import Stage1ReleaseAccessibleChessAPI


class OwnerHarness:
    def __init__(self) -> None:
        self._queue: Queue[object] = Queue()
        self._ready = Event()
        self.thread_id = -1
        self.move_threads: list[int] = []
        self.thread = Thread(
            target=self._run,
            name="AgentBoardMoveOwner",
            daemon=False,
        )
        self.thread.start()
        if not self._ready.wait(3):
            raise RuntimeError("owner thread did not start")

    def _run(self) -> None:
        self.thread_id = get_ident()
        self.board = Board()
        self._ready.set()
        while True:
            callback = self._queue.get()
            if callback is None:
                return
            callback()

    def post(self, callback) -> None:
        self._queue.put(callback)

    def board_commands(self) -> BoardCommandService:
        if get_ident() != self.thread_id:
            raise RuntimeError("board commands escaped owner thread")
        board = self.board
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

    def play_move(self, text: str) -> dict[str, object]:
        if get_ident() != self.thread_id:
            raise RuntimeError("board mutation escaped owner thread")
        self.move_threads.append(get_ident())
        san = self.board.push_text(text)
        return {"ok": True, "san": san, "fen": self.board.fen()}

    def close(self) -> None:
        self._queue.put(None)
        self.thread.join(3)
        if self.thread.is_alive():
            raise RuntimeError("owner thread did not stop")


class AgentBoardMoveToolTests(unittest.TestCase):
    def execute(self, executor, tool_id, arguments):
        return asyncio.run(
            executor.execute(
                ToolCall(
                    call_id=f"call-{tool_id}",
                    tool_id=tool_id,
                    arguments=arguments,
                )
            )
        )

    @staticmethod
    def commands_for(board: Board) -> BoardCommandService:
        legal = tuple(
            MoveView(
                move.frm,
                move.to,
                board.san(move),
                bool(board.board[move.to]) or move.en_passant,
            )
            for move in board.legal_moves()
        )
        return BoardCommandService(
            BoardSnapshot(tuple(board.board), board.turn, legal)
        )

    def registry(self, board, *, board_move=None, owner_call=None):
        executor = ToolExecutor()
        ChessAgentToolRegistry(
            executor=executor,
            board_provider=lambda: board,
            board_commands_provider=lambda: self.commands_for(board),
            board_move=board_move,
            owner_call=owner_call,
        ).register_all()
        return executor

    def test_preview_move_uses_canonical_rules_without_mutating_board(self) -> None:
        board = Board()
        before = board.fen()
        executor = self.registry(board)

        result = self.execute(
            executor,
            "board.preview_move",
            {"move": "e4"},
        )
        self.assertTrue(result.ok, result.error)
        self.assertFalse(result.output["applied"])
        self.assertEqual(result.output["san"], "e4")
        self.assertNotEqual(result.output["fen"], before)
        self.assertEqual(result.output["turn"], "b")
        self.assertEqual(board.fen(), before)

    def test_preview_illegal_or_malformed_move_is_atomic(self) -> None:
        board = Board()
        before = board.fen()
        executor = self.registry(board)
        for arguments in (
            {"move": "e9"},
            {"move": ""},
            {"move": "e4\n"},
            {"move": "e4", "extra": True},
            {},
        ):
            with self.subTest(arguments=arguments):
                result = self.execute(
                    executor,
                    "board.preview_move",
                    arguments,
                )
                self.assertFalse(result.ok)
                self.assertEqual(result.error, "tool failed")
                self.assertEqual(board.fen(), before)

    def test_play_move_is_not_published_without_application_port(self) -> None:
        board = Board()
        executor = self.registry(board)
        specs = {spec.tool_id: spec for spec in executor.specs()}
        self.assertIn("board.preview_move", specs)
        self.assertNotIn("board.play_move", specs)

    def test_play_move_prevalidates_and_delegates_to_application_port(self) -> None:
        board = Board()
        calls: list[str] = []

        def apply(text: str) -> dict[str, object]:
            calls.append(text)
            san = board.push_text(text)
            return {"ok": True, "san": san, "fen": board.fen()}

        executor = self.registry(board, board_move=apply)
        specs = {spec.tool_id: spec for spec in executor.specs()}
        self.assertEqual(specs["board.play_move"].risk, ToolRisk.LOCAL_WRITE)

        result = self.execute(
            executor,
            "board.play_move",
            {"move": "e2e4"},
        )
        self.assertTrue(result.ok, result.error)
        self.assertEqual(calls, ["e2e4"])
        self.assertTrue(result.output["applied"])
        self.assertEqual(result.output["san"], "e4")
        self.assertEqual(result.output["fen"], board.fen())
        self.assertEqual(result.output["turn"], "b")

    def test_illegal_play_never_reaches_mutation_port(self) -> None:
        board = Board()
        before = board.fen()
        calls: list[str] = []

        def apply(text: str) -> dict[str, object]:
            calls.append(text)
            raise AssertionError("illegal move must be rejected before mutation")

        executor = self.registry(board, board_move=apply)
        result = self.execute(
            executor,
            "board.play_move",
            {"move": "e9"},
        )
        self.assertFalse(result.ok)
        self.assertEqual(result.error, "tool failed")
        self.assertEqual(calls, [])
        self.assertEqual(board.fen(), before)

    def test_rejected_application_move_must_leave_canonical_board_unchanged(self) -> None:
        board = Board()
        before = board.fen()
        calls: list[str] = []

        def reject(text: str) -> dict[str, object]:
            calls.append(text)
            return {"ok": False, "announcement": "rejected"}

        executor = self.registry(board, board_move=reject)
        result = self.execute(
            executor,
            "board.play_move",
            {"move": "e4"},
        )
        self.assertFalse(result.ok)
        self.assertEqual(result.error, "tool failed")
        self.assertEqual(calls, ["e4"])
        self.assertEqual(board.fen(), before)

    def test_divergent_mutation_port_fails_closed(self) -> None:
        board = Board()

        def wrong(_text: str) -> dict[str, object]:
            board.push_text("d4")
            return {"ok": True}

        executor = self.registry(board, board_move=wrong)
        result = self.execute(
            executor,
            "board.play_move",
            {"move": "e4"},
        )
        self.assertFalse(result.ok)
        self.assertEqual(result.error, "tool failed")
        expected = Board()
        expected.push_text("d4")
        self.assertEqual(board.fen(), expected.fen())


    def test_real_stage1_release_make_move_is_a_compatible_analysis_port(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            api = Stage1ReleaseAccessibleChessAPI(
                keymap_path=Path(temp) / "keymap.json"
            )
            executor = ToolExecutor()
            ChessAgentToolRegistry(
                executor=executor,
                board_provider=lambda: api.board,
                board_commands_provider=lambda: self.commands_for(api.board),
                board_move=api.make_move,
            ).register_all()

            before = api.board.fen()
            illegal = self.execute(
                executor,
                "board.play_move",
                {"move": "e9"},
            )
            self.assertFalse(illegal.ok)
            self.assertEqual(illegal.error, "tool failed")
            self.assertEqual(api.board.fen(), before)
            self.assertEqual(len(api.sans), 0)

            played = self.execute(
                executor,
                "board.play_move",
                {"move": "e4"},
            )
            self.assertTrue(played.ok, played.error)
            self.assertEqual(played.output["san"], "e4")
            self.assertEqual(played.output["fen"], api.board.fen())
            self.assertEqual(api.sans, ["e4"])
            self.assertEqual(len(api.board.undo_stack), 1)

    def test_owner_thread_boundary_covers_preview_and_mutation(self) -> None:
        owner = OwnerHarness()
        try:
            executor = ToolExecutor()
            owner_call = AgentOwnerThreadCall(owner.post)
            ChessAgentToolRegistry(
                executor=executor,
                board_provider=lambda: owner.board,
                board_commands_provider=owner.board_commands,
                board_move=owner.play_move,
                owner_call=owner_call,
            ).register_all()

            async def exercise():
                preview = await executor.execute(
                    ToolCall(
                        call_id="preview-owner",
                        tool_id="board.preview_move",
                        arguments={"move": "e4"},
                    )
                )
                played = await executor.execute(
                    ToolCall(
                        call_id="play-owner",
                        tool_id="board.play_move",
                        arguments={"move": "e4"},
                    )
                )
                current = await executor.execute(
                    ToolCall(
                        call_id="current-owner",
                        tool_id="board.current",
                        arguments={},
                    )
                )
                return preview, played, current

            preview, played, current = asyncio.run(exercise())
            self.assertTrue(preview.ok, preview.error)
            self.assertTrue(played.ok, played.error)
            self.assertTrue(current.ok, current.error)
            self.assertEqual(owner.move_threads, [owner.thread_id])
            self.assertEqual(current.output["fen"], played.output["fen"])
            self.assertEqual(current.output["turn"], "b")
        finally:
            owner.close()

    def test_registry_rejects_non_callable_board_move_port(self) -> None:
        board = Board()
        with self.assertRaisesRegex(TypeError, "board_move"):
            ChessAgentToolRegistry(
                executor=ToolExecutor(),
                board_provider=lambda: board,
                board_commands_provider=lambda: self.commands_for(board),
                board_move=object(),
            )


if __name__ == "__main__":
    unittest.main()
