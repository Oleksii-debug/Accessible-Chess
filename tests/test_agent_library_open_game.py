from __future__ import annotations

import asyncio
from hashlib import sha256
from pathlib import Path
import tempfile
import unittest

from acs.acsdb import AcsDatabase
from acs.agent_library_tools import register_library_open_game_tool
from acs.agent_model_contracts import (
    ModelRequest,
    ModelResponse,
    ModelUsage,
    ProviderCapabilities,
    ProviderKind,
)
from acs.agent_model_gateway import ModelGateway
from acs.agent_tools import ToolCall, ToolExecutor, ToolRisk
from acs.analysis_service import AnalysisService
from acs.book_progress_store import BookProgressStore
from acs.chess_agent_tools import ChessAgentToolRegistry
from acs.engine_assisted_workflows import EngineAssistedWorkflowService
from acs.library_import_service import LibraryImportService
from acs.pgn_workspace import PgnWorkspace
from acs.search_service import GameSearchService
from acs.universal_chess_agent import UniversalChessAgentRuntime
from acs.version2_application import Version2Application


PGN = """[Event "Agent Library"]
[White "Alpha"]
[Black "Beta"]
[Result "*"]

1. e4 e5 2. Nf3 *
"""


class _ScriptedProvider:
    def __init__(self, responses: list[str]) -> None:
        self.responses = list(responses)
        self.requests: list[ModelRequest] = []

    @property
    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(
            provider_id="library-fixture",
            kind=ProviderKind.LOCAL,
            supports_private_data=True,
        )

    async def complete(self, request: ModelRequest) -> ModelResponse:
        self.requests.append(request)
        if not self.responses:
            raise AssertionError("unexpected model request")
        return ModelResponse(
            request_id=request.request_id,
            text=self.responses.pop(0),
            provider_id="library-fixture",
            provider_kind=ProviderKind.LOCAL,
            model=request.model or "fixture-model",
            usage=ModelUsage(
                input_tokens=1,
                output_tokens=1,
                total_tokens=2,
            ),
        )


class AgentLibraryOpenGameTests(unittest.TestCase):
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

    def test_exact_provenance_is_passed_to_host_and_result_is_safe(self) -> None:
        calls = []
        executor = ToolExecutor()
        spec = register_library_open_game_tool(executor, calls.append)
        self.assertEqual(spec.risk, ToolRisk.LOCAL_WRITE)

        result = self.execute(
            executor,
            "library.open_game",
            {"game_id": 7, "source_id": 3, "source_index": 2},
        )

        self.assertTrue(result.ok, result.error)
        self.assertEqual(
            calls,
            [{"game_id": 7, "source_id": 3, "source_index": 2}],
        )
        self.assertEqual(
            result.output,
            {
                "opened": True,
                "gameId": 7,
                "sourceId": 3,
                "sourceIndex": 2,
            },
        )

    def test_invalid_authority_never_reaches_host(self) -> None:
        calls = []
        executor = ToolExecutor()
        register_library_open_game_tool(executor, calls.append)
        cases = (
            {"game_id": True, "source_id": 1, "source_index": 0},
            {"game_id": 1, "source_id": 0, "source_index": 0},
            {"game_id": 1, "source_id": 1, "source_index": -1},
            {"game_id": 1, "source_id": 1},
            {"game_id": 1, "source_id": 1, "source_index": 0, "extra": 1},
        )
        for index, arguments in enumerate(cases):
            with self.subTest(index=index):
                result = self.execute(
                    executor, "library.open_game", arguments
                )
                self.assertFalse(result.ok)
                self.assertEqual(result.error, "tool failed")
        self.assertEqual(calls, [])

    def test_host_failure_is_fail_closed(self) -> None:
        def fail(_payload):
            raise ValueError("stale or refused by canonical application")

        executor = ToolExecutor()
        register_library_open_game_tool(executor, fail)
        result = self.execute(
            executor,
            "library.open_game",
            {"game_id": 1, "source_id": 1, "source_index": 0},
        )
        self.assertFalse(result.ok)
        self.assertIsNone(result.output)
        self.assertEqual(result.error, "tool failed")

    def test_registry_composes_optional_open_command(self) -> None:
        executor = ToolExecutor()
        ChessAgentToolRegistry(
            executor=executor,
            board_provider=lambda: None,
            board_commands_provider=lambda: None,
            library_open_game_command=lambda _payload: None,
        ).register_all()
        specs = {spec.tool_id: spec for spec in executor.specs()}
        self.assertIn("library.open_game", specs)
        self.assertEqual(
            specs["library.open_game"].risk,
            ToolRisk.LOCAL_WRITE,
        )


    def test_universal_agent_searches_then_opens_real_library_game(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            database = AcsDatabase(root / "library.acsdb")
            analysis = AnalysisService(lambda: None)
            try:
                game = PgnWorkspace.from_text(PGN).games()[0]
                imported = LibraryImportService(database).import_games(
                    (game,),
                    source_name="agent-library.pgn",
                    source_format="pgn",
                    source_sha256=sha256(PGN.encode("utf-8")).hexdigest(),
                )
                app = Version2Application(
                    database,
                    progress_store=BookProgressStore(root / "progress.json"),
                    engine_assistance=EngineAssistedWorkflowService(analysis),
                    board_dispatch=lambda *_args, **_kwargs: None,
                )

                executor = ToolExecutor()
                ChessAgentToolRegistry(
                    executor=executor,
                    board_provider=lambda: None,
                    board_commands_provider=lambda: None,
                    search_service=GameSearchService(database),
                    library_open_game_command=lambda payload: app.router.dispatch(
                        "library.open_game", payload
                    ).value,
                ).register_all()

                provider = _ScriptedProvider(
                    [
                        '{"type":"tool","tool_id":"library.search","arguments":{"event":"Agent Library","limit":5}}',
                        (
                            '{"type":"tool","tool_id":"library.open_game","arguments":'
                            f'{{"game_id":{imported.first_game_id},"source_id":{imported.source_id},"source_index":0}}'
                            "}"
                        ),
                        '{"type":"final","text":"Opened the matching Library game."}',
                    ]
                )
                gateway = ModelGateway()
                gateway.register(provider)
                runtime = UniversalChessAgentRuntime(
                    gateway=gateway,
                    tools=executor,
                    provider_id="library-fixture",
                    model="fixture-model",
                    product_instruction="Use canonical Accessible Chess Library tools.",
                )

                result = asyncio.run(
                    runtime.run(
                        run_id="library-open-runtime",
                        user_text="Find Agent Library and open that game.",
                    )
                )

                self.assertEqual(
                    result.text,
                    "Opened the matching Library game.",
                )
                self.assertEqual(result.tool_calls, 2)
                self.assertEqual(result.model_calls, 3)
                self.assertEqual(app.shell.current_route.route_id, "pgn")
                self.assertEqual(
                    app.session.workspace.current_game().tags["Event"],
                    "Agent Library",
                )
                self.assertIn(
                    '"tool_id":"library.search"',
                    provider.requests[1].messages[-1].content,
                )
                self.assertIn(
                    f'"game_id":{imported.first_game_id}',
                    provider.requests[1].messages[-1].content,
                )
                self.assertIn(
                    '"tool_id":"library.open_game"',
                    provider.requests[2].messages[-1].content,
                )
                self.assertIn(
                    '"opened":true',
                    provider.requests[2].messages[-1].content,
                )
            finally:
                analysis.close()
                database.close()

    def test_real_application_open_and_dirty_document_guard(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            database = AcsDatabase(root / "library.acsdb")
            analysis = AnalysisService(lambda: None)
            try:
                game = PgnWorkspace.from_text(PGN).games()[0]
                imported = LibraryImportService(database).import_games(
                    (game,),
                    source_name="agent-library.pgn",
                    source_format="pgn",
                    source_sha256=sha256(PGN.encode("utf-8")).hexdigest(),
                )
                app = Version2Application(
                    database,
                    progress_store=BookProgressStore(root / "progress.json"),
                    engine_assistance=EngineAssistedWorkflowService(analysis),
                    board_dispatch=lambda *_args, **_kwargs: None,
                )

                def canonical_open(payload):
                    return app.router.dispatch(
                        "library.open_game", payload
                    ).value

                executor = ToolExecutor()
                ChessAgentToolRegistry(
                    executor=executor,
                    board_provider=lambda: None,
                    board_commands_provider=lambda: None,
                    library_open_game_command=canonical_open,
                ).register_all()
                provenance = {
                    "game_id": imported.first_game_id,
                    "source_id": imported.source_id,
                    "source_index": 0,
                }

                opened = self.execute(
                    executor, "library.open_game", provenance
                )
                self.assertTrue(opened.ok, opened.error)
                self.assertIsNotNone(app.session)
                self.assertEqual(
                    app.session.workspace.current_game().tags["Event"],
                    "Agent Library",
                )
                self.assertEqual(app.shell.current_route.route_id, "pgn")

                stale = self.execute(
                    executor,
                    "library.open_game",
                    {
                        **provenance,
                        "source_id": imported.source_id + 1,
                    },
                )
                self.assertFalse(stale.ok)
                self.assertEqual(
                    app.session.workspace.current_game().tags["Event"],
                    "Agent Library",
                )

                app.browser_command(
                    "pgn", "pgn.select", {"node_id": "g0:main/m0"}
                )
                edited = app.browser_command(
                    "pgn", "pgn.comment_edit", {"text": "unsaved"}
                )
                self.assertEqual(edited["kind"], "selection")
                self.assertTrue(app.session.dirty)
                before_text = app.session.workspace.to_text()

                refused = self.execute(
                    executor, "library.open_game", provenance
                )
                self.assertFalse(refused.ok)
                self.assertTrue(app.session.dirty)
                self.assertEqual(
                    app.session.workspace.to_text(),
                    before_text,
                )
                self.assertNotEqual(
                    database.get_game(imported.first_game_id)["pgn_text"],
                    before_text,
                )
            finally:
                analysis.close()
                database.close()


if __name__ == "__main__":
    unittest.main()
