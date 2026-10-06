from __future__ import annotations

import asyncio
from queue import Queue
from threading import Event, Thread, get_ident
import time
from types import SimpleNamespace
import unittest

from acs.acsdb import AcsDatabase
from acs.agent_execution_host import AgentOwnerThreadCall, bind_agent_runtime
from acs.agent_model_contracts import (
    ModelResponse,
    ModelUsage,
    ProviderCapabilities,
    ProviderKind,
)
from acs.agent_model_gateway import ModelGateway
from acs.agent_tools import ToolCall, ToolExecutor
from acs.agent_webview_bridge import AgentConversationWebViewBridge
from acs.agent_webview_projection import AgentConversationProjection
from acs.board_service import BoardCommandService, BoardSnapshot, MoveView
from acs.chess_agent_tools import ChessAgentToolRegistry
from acs.chesscore import Board
from acs.full_product_ui_shell import UILanguage
from acs.search_service import GameSearchService
from acs.universal_chess_agent import UniversalChessAgentRuntime
from acs.version2_final_product_application import Version2FinalProductApplication


PGN = """[Event "Agent Owner Thread"]
[Site "Test"]
[Date "2026.10.06"]
[Round "1"]
[White "Alpha"]
[Black "Beta"]
[Result "1-0"]

1. e4 e5 1-0
"""


class FinalProvider:
    def __init__(self, *, delay: float = 0.0) -> None:
        self.delay = delay
        self.thread_ids: list[int] = []

    @property
    def capabilities(self):
        return ProviderCapabilities(
            provider_id="fixture",
            kind=ProviderKind.LOCAL,
            supports_private_data=True,
        )

    async def complete(self, request):
        self.thread_ids.append(get_ident())
        if self.delay:
            await asyncio.sleep(self.delay)
        return ModelResponse(
            request_id=request.request_id,
            text='{"type":"final","text":"Canonical answer."}',
            provider_id="fixture",
            provider_kind=ProviderKind.LOCAL,
            model=request.model or "fixture-model",
            usage=ModelUsage(total_tokens=3),
        )


class BlockingProvider(FinalProvider):
    async def complete(self, request):
        self.thread_ids.append(get_ident())
        await asyncio.sleep(60)
        raise AssertionError("cancelled provider must not complete normally")


class LibraryToolProvider(FinalProvider):
    def __init__(self) -> None:
        super().__init__()
        self.calls = 0
        self.tool_message = ""

    async def complete(self, request):
        self.thread_ids.append(get_ident())
        self.calls += 1
        if self.calls == 1:
            text = (
                '{"type":"tool","tool_id":"library.search",'
                '"arguments":{"player":"Alpha","limit":5}}'
            )
        else:
            self.tool_message = request.messages[-1].content
            text = '{"type":"final","text":"Found Alpha versus Beta."}'
        return ModelResponse(
            request_id=request.request_id,
            text=text,
            provider_id="fixture",
            provider_kind=ProviderKind.LOCAL,
            model=request.model or "fixture-model",
            usage=ModelUsage(total_tokens=3),
        )


def runtime_for(provider, executor: ToolExecutor | None = None) -> UniversalChessAgentRuntime:
    gateway = ModelGateway()
    gateway.register(provider)
    return UniversalChessAgentRuntime(
        gateway=gateway,
        tools=executor or ToolExecutor(),
        provider_id="fixture",
        model="fixture-model",
        product_instruction="Use Accessible Chess canonical application state.",
    )


def wait_for(projection: AgentConversationProjection, state: str, timeout: float = 3.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        snapshot = projection.snapshot()
        if snapshot["state"] == state:
            return snapshot
        time.sleep(0.01)
    raise AssertionError(f"Agent projection did not reach {state}: {projection.snapshot()!r}")


class OwnerHarness:
    def __init__(self) -> None:
        self._queue: Queue[object] = Queue()
        self._ready = Event()
        self.thread_id = -1
        self.thread = Thread(target=self._run, name="AgentOwnerHarness", daemon=False)
        self.thread.start()
        if not self._ready.wait(3):
            raise RuntimeError("owner harness did not start")

    def _run(self) -> None:
        self.thread_id = get_ident()
        self.board = Board()
        self.database = AcsDatabase()
        self.database.import_pgn_text(PGN, source_name="owner-thread.pgn")
        self.search = GameSearchService(self.database)
        self._ready.set()
        while True:
            item = self._queue.get()
            if item is None:
                break
            callback, done, box = item
            try:
                box.append((True, callback()))
            except BaseException as error:
                box.append((False, error))
            finally:
                done.set()
        self.database.close()

    def invoke(self, callback):
        done = Event()
        box = []
        self._queue.put((callback, done, box))
        if not done.wait(3):
            raise RuntimeError("owner callback did not finish")
        ok, value = box[0]
        if not ok:
            raise value
        return value

    def board_commands(self):
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
        return BoardCommandService(
            BoardSnapshot(
                tuple(board.board),
                board.turn,
                legal,
                attacks,
                None,
            )
        )

    def close(self) -> None:
        self._queue.put(None)
        self.thread.join(3)
        if self.thread.is_alive():
            raise RuntimeError("owner harness did not stop")


class AgentExecutionHostTests(unittest.TestCase):
    def application_shell(self):
        app = Version2FinalProductApplication.__new__(Version2FinalProductApplication)
        app._thread = get_ident()
        app.shell = SimpleNamespace(language=UILanguage.EN)
        app.agent = AgentConversationWebViewBridge(
            AgentConversationProjection(language="en")
        )
        app._agent_execution_host = None
        return app

    def test_browser_submit_runs_model_off_owner_thread_and_publishes_result(self):
        provider = FinalProvider()
        app = self.application_shell()
        host = bind_agent_runtime(app, runtime_for(provider))
        try:
            result = app.browser_command(
                "agent",
                "agent.submit",
                {"text": "Describe the position."},
            )
            self.assertEqual(result["kind"], "accepted")
            done = wait_for(app.agent.projection, "completed")
            self.assertEqual(done["transcript"][-1]["text"], "Canonical answer.")
            self.assertEqual(done["focus_target"], "agent-input")
            self.assertEqual(done["status_text"].splitlines()[0], "The answer is ready.")
            self.assertTrue(provider.thread_ids)
            self.assertNotEqual(provider.thread_ids[0], get_ident())
            self.assertFalse(host._thread.daemon)
        finally:
            self.assertTrue(host.shutdown(timeout=3))

    def test_browser_cancel_interrupts_active_model_without_blocking_ui(self):
        provider = BlockingProvider()
        app = self.application_shell()
        host = bind_agent_runtime(app, runtime_for(provider))
        try:
            app.browser_command("agent", "agent.submit", {"text": "Analyze."})
            wait_for(app.agent.projection, "running")
            started = time.monotonic()
            result = app.browser_command("agent", "agent.cancel", {})
            self.assertEqual(result["kind"], "cancel-requested")
            self.assertLess(time.monotonic() - started, 0.5)
            cancelled = wait_for(app.agent.projection, "cancelled")
            self.assertTrue(cancelled["can_submit"])
            self.assertFalse(cancelled["can_cancel"])
        finally:
            self.assertTrue(host.shutdown(timeout=3))

    def test_shutdown_cancels_run_and_joins_non_daemon_worker(self):
        app = self.application_shell()
        host = bind_agent_runtime(app, runtime_for(BlockingProvider()))
        app.browser_command("agent", "agent.submit", {"text": "Keep thinking."})
        wait_for(app.agent.projection, "running")
        self.assertTrue(host.shutdown(timeout=3))
        self.assertFalse(host.alive)
        self.assertTrue(host.closed)
        self.assertIn(app.agent.projection.snapshot()["state"], {"cancelled", "failed"})

    def test_canonical_board_and_library_tools_execute_on_injected_owner_thread(self):
        owner = OwnerHarness()
        try:
            executor = ToolExecutor()
            dispatch_threads: list[int] = []

            def invoke(callback):
                def observed():
                    dispatch_threads.append(get_ident())
                    return callback()
                return owner.invoke(observed)

            ChessAgentToolRegistry(
                executor=executor,
                board_provider=lambda: owner.board,
                board_commands_provider=owner.board_commands,
                search_service=owner.search,
                owner_call=AgentOwnerThreadCall(invoke),
            ).register_all()

            async def exercise():
                board = await executor.execute(
                    ToolCall(
                        call_id="board",
                        tool_id="board.current",
                        arguments={},
                    )
                )
                library = await executor.execute(
                    ToolCall(
                        call_id="library",
                        tool_id="library.search",
                        arguments={"player": "Alpha"},
                    )
                )
                return board, library

            board_result, library_result = asyncio.run(exercise())
            self.assertTrue(board_result.ok, board_result.error)
            self.assertEqual(board_result.output["legalMoveCount"], 20)
            self.assertTrue(library_result.ok, library_result.error)
            self.assertEqual(library_result.output["items"][0]["white"], "Alpha")
            self.assertGreaterEqual(len(dispatch_threads), 2)
            self.assertEqual(set(dispatch_threads), {owner.thread_id})
            self.assertNotEqual(owner.thread_id, get_ident())
        finally:
            owner.close()

    def test_background_runtime_executes_library_tool_on_owner_and_returns_answer(self):
        owner = OwnerHarness()
        try:
            executor = ToolExecutor()
            dispatch_threads: list[int] = []

            def invoke(callback):
                def observed():
                    dispatch_threads.append(get_ident())
                    return callback()
                return owner.invoke(observed)

            ChessAgentToolRegistry(
                executor=executor,
                board_provider=lambda: owner.board,
                board_commands_provider=owner.board_commands,
                search_service=owner.search,
                owner_call=AgentOwnerThreadCall(invoke),
            ).register_all()
            provider = LibraryToolProvider()
            app = self.application_shell()
            host = bind_agent_runtime(app, runtime_for(provider, executor))
            try:
                accepted = app.browser_command(
                    "agent",
                    "agent.submit",
                    {"text": "Find Alpha's game."},
                )
                self.assertEqual(accepted["kind"], "accepted")
                done = wait_for(app.agent.projection, "completed")
                self.assertEqual(
                    done["transcript"][-1]["text"],
                    "Found Alpha versus Beta.",
                )
                self.assertIn('"white":"Alpha"', provider.tool_message)
                self.assertIn('"black":"Beta"', provider.tool_message)
                self.assertEqual(provider.calls, 2)
                self.assertTrue(dispatch_threads)
                self.assertEqual(set(dispatch_threads), {owner.thread_id})
            finally:
                self.assertTrue(host.shutdown(timeout=3))
        finally:
            owner.close()

    def test_owner_call_rejects_non_callable_boundary(self):
        owner_call = AgentOwnerThreadCall(lambda callback: callback())
        with self.assertRaises(TypeError):
            asyncio.run(owner_call(None))


if __name__ == "__main__":
    unittest.main()
