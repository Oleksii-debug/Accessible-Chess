from __future__ import annotations

import asyncio
import unittest

from acs.agent_coach import AgentCoachError, AgentCoachWorkflow, CoachMode, CoachRequest
from acs.agent_model_contracts import (
    ModelMessage,
    ModelRequest,
    ModelResponse,
    ModelUsage,
    ProviderCapabilities,
    ProviderKind,
)
from acs.agent_model_gateway import ModelGateway
from acs.agent_reliability import (
    AgentPermissionPolicy,
    AgentReliabilityError,
    AgentResourcePolicy,
    ReliableAgentSession,
)
from acs.agent_resource_budget import AgentResourceBudget, AgentResourceUsage
from acs.agent_tools import ToolExecutor, ToolRisk, ToolSpec
from acs.agent_voice import (
    AgentVoiceConversation,
    VoiceConversationError,
    VoicePermissionState,
)
from acs.universal_chess_agent import AgentProtocolError, UniversalChessAgentRuntime


class ScriptedProvider:
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


class BlockingSecondProvider(ScriptedProvider):
    def __init__(self) -> None:
        super().__init__(
            ['{"type":"tool","tool_id":"state.commit","arguments":{}}']
        )
        self.second_started = asyncio.Event()

    async def complete(self, request: ModelRequest) -> ModelResponse:
        if not self.responses:
            self.second_started.set()
            await asyncio.Event().wait()
            raise AssertionError("unreachable")
        return await super().complete(request)


def runtime(provider, tools: ToolExecutor) -> UniversalChessAgentRuntime:
    gateway = ModelGateway()
    gateway.register(provider)
    return UniversalChessAgentRuntime(
        gateway=gateway,
        tools=tools,
        provider_id="fixture",
        model="fixture-model",
        product_instruction="Use only canonical Accessible Chess evidence.",
    )


def register_coach_fixture_tools(executor: ToolExecutor, calls: list[tuple[str, dict]]) -> None:
    async def handler(tool_id: str, arguments):
        calls.append((tool_id, dict(arguments)))
        if tool_id == "board.current":
            return {"fen": "start", "turn": "white", "legalMoveCount": 20}
        if tool_id == "engine.analyze":
            return {"fen": "start", "lines": [{"pv": ["e4"], "scoreCp": 24}]}
        if tool_id == "gametree.current":
            return {
                "game": {
                    "white": "Alpha",
                    "black": "Beta",
                    "event": "Training event",
                    "result": "*",
                },
                "currentMove": {"san": "e4"},
                "previousMove": None,
            }
        if tool_id == "library.search":
            return {
                "items": [
                    {
                        "game_id": 7,
                        "white": "Alpha",
                        "black": "Gamma",
                        "eco": "C20",
                        "opening": "King Pawn Game",
                    }
                ],
                "hasMore": False,
            }
        if tool_id == "training.status":
            return {
                "available": True,
                "view": {"title": "Find the best move", "status": "active"},
            }
        if tool_id == "media.status":
            return {
                "positionMs": 42000,
                "synchronizedFen": "start",
                "qualification": "qualified",
            }
        if tool_id == "media.seek":
            return {"requested": "seek", "positionMs": arguments["position_ms"]}
        if tool_id == "media.restore_position":
            return {"restored": True, "fen": "start"}
        raise AssertionError(tool_id)

    for tool_id, risk in (
        ("board.current", ToolRisk.READ_ONLY),
        ("engine.analyze", ToolRisk.READ_ONLY),
        ("gametree.current", ToolRisk.READ_ONLY),
        ("library.search", ToolRisk.READ_ONLY),
        ("training.status", ToolRisk.READ_ONLY),
        ("media.status", ToolRisk.READ_ONLY),
        ("media.seek", ToolRisk.LOCAL_WRITE),
        ("media.restore_position", ToolRisk.LOCAL_WRITE),
    ):
        async def bound(arguments, tool_id=tool_id):
            return await handler(tool_id, arguments)

        executor.register(
            ToolSpec(tool_id, f"fixture {tool_id}", risk=risk),
            bound,
        )


class Section23CoachTests(unittest.TestCase):
    def test_position_explanation_is_evidence_first_and_model_cannot_mutate(self):
        calls: list[tuple[str, dict]] = []
        tools = ToolExecutor()
        register_coach_fixture_tools(tools, calls)
        provider = ScriptedProvider(
            ['{"type":"final","text":"Grounded explanation."}']
        )
        coach = AgentCoachWorkflow(runtime=runtime(provider, tools), tools=tools)
        result = asyncio.run(
            coach.run(
                CoachRequest(
                    request_id="position-1",
                    mode=CoachMode.POSITION,
                    question="Why is e4 useful?",
                )
            )
        )
        self.assertEqual(result.text, "Grounded explanation.")
        self.assertEqual(
            [item.tool_id for item in result.evidence],
            ["board.current", "engine.analyze"],
        )
        self.assertEqual(result.model_tool_calls, 0)
        self.assertIn("CANONICAL_EVIDENCE_JSON=", provider.requests[0].messages[-1].content)

    def test_game_review_collects_gametree_engine_and_related_library_evidence(self):
        calls: list[tuple[str, dict]] = []
        tools = ToolExecutor()
        register_coach_fixture_tools(tools, calls)
        provider = ScriptedProvider(
            ['{"type":"final","text":"Review grounded in current evidence."}']
        )
        coach = AgentCoachWorkflow(runtime=runtime(provider, tools), tools=tools)
        result = asyncio.run(
            coach.run(
                CoachRequest(
                    request_id="review-1",
                    mode=CoachMode.GAME_REVIEW,
                    question="Review this game.",
                )
            )
        )
        self.assertEqual(
            [item.tool_id for item in result.evidence],
            ["gametree.current", "engine.analyze", "library.search"],
        )
        library_call = [args for tool_id, args in calls if tool_id == "library.search"][0]
        self.assertEqual(library_call["player"], "Alpha")
        self.assertEqual(library_call["event"], "Training event")
        self.assertEqual(library_call["limit"], 8)

    def test_training_builds_nonpersistent_exercise_from_canonical_evidence(self):
        calls: list[tuple[str, dict]] = []
        tools = ToolExecutor()
        register_coach_fixture_tools(tools, calls)
        provider = ScriptedProvider(
            ['{"type":"final","text":"Exercise: choose the best continuation."}']
        )
        coach = AgentCoachWorkflow(runtime=runtime(provider, tools), tools=tools)
        result = asyncio.run(
            coach.run(
                CoachRequest(
                    request_id="training-1",
                    mode=CoachMode.TRAINING,
                    question="Create Guess-the-Move.",
                )
            )
        )
        self.assertEqual(
            [item.tool_id for item in result.evidence],
            ["board.current", "engine.analyze", "training.status"],
        )
        self.assertIn("do not persist anything", provider.requests[0].messages[-1].content)

    def test_media_navigation_requires_explicit_owner_permission(self):
        calls: list[tuple[str, dict]] = []
        tools = ToolExecutor()
        register_coach_fixture_tools(tools, calls)
        provider = ScriptedProvider(
            [
                '{"type":"tool","tool_id":"media.seek","arguments":{"position_ms":41000}}',
                '{"type":"final","text":"Returned to the requested point."}',
            ]
        )
        coach = AgentCoachWorkflow(runtime=runtime(provider, tools), tools=tools)
        result = asyncio.run(
            coach.run(
                CoachRequest(
                    request_id="media-1",
                    mode=CoachMode.MEDIA,
                    question="Return before the mistake.",
                    allow_media_navigation=True,
                )
            )
        )
        self.assertEqual(result.model_tool_calls, 1)
        self.assertIn(("media.seek", {"position_ms": 41000}), calls)

    def test_media_write_is_fail_closed_when_navigation_not_authorized(self):
        calls: list[tuple[str, dict]] = []
        tools = ToolExecutor()
        register_coach_fixture_tools(tools, calls)
        provider = ScriptedProvider(
            ['{"type":"tool","tool_id":"media.seek","arguments":{"position_ms":41000}}']
        )
        coach = AgentCoachWorkflow(runtime=runtime(provider, tools), tools=tools)
        with self.assertRaises(AgentProtocolError):
            asyncio.run(
                coach.run(
                    CoachRequest(
                        request_id="media-2",
                        mode=CoachMode.MEDIA,
                        question="Move the video.",
                        allow_media_navigation=False,
                    )
                )
            )
        self.assertNotIn(("media.seek", {"position_ms": 41000}), calls)

    def test_missing_or_failed_grounding_stops_before_model_call(self):
        tools = ToolExecutor()

        async def board(_arguments):
            return {"fen": "start"}

        tools.register(ToolSpec("board.current", "board"), board)
        provider = ScriptedProvider(
            ['{"type":"final","text":"must not run"}']
        )
        coach = AgentCoachWorkflow(runtime=runtime(provider, tools), tools=tools)
        with self.assertRaises(AgentCoachError):
            asyncio.run(
                coach.run(
                    CoachRequest(
                        request_id="fail-1",
                        mode=CoachMode.POSITION,
                        question="Explain.",
                    )
                )
            )
        self.assertEqual(provider.requests, [])


class Section24ReliabilityTests(unittest.TestCase):
    def test_runtime_tool_allowlist_blocks_hallucinated_mutation_before_handler(self):
        tools = ToolExecutor()
        changed: list[bool] = []

        async def write(_arguments):
            changed.append(True)
            return {"ok": True}

        tools.register(
            ToolSpec("board.fake_write", "must be denied", risk=ToolRisk.LOCAL_WRITE),
            write,
        )
        provider = ScriptedProvider(
            ['{"type":"tool","tool_id":"board.fake_write","arguments":{}}']
        )
        agent = runtime(provider, tools)
        with self.assertRaises(AgentProtocolError):
            asyncio.run(
                agent.run(
                    run_id="deny-write",
                    user_text="try mutation",
                    allowed_tool_ids=frozenset(),
                )
            )
        self.assertEqual(changed, [])

    def test_high_impact_requires_explicit_permission_policy(self):
        tools = ToolExecutor()

        async def high(_arguments):
            return {"ok": True}

        tools.register(
            ToolSpec("danger", "danger", risk=ToolRisk.HIGH_IMPACT),
            high,
        )
        policy = AgentPermissionPolicy(allowed_tool_ids=frozenset({"danger"}))
        with self.assertRaises(AgentReliabilityError):
            policy.validate(tools)

    def test_resource_plan_can_only_narrow_owner_budget_and_fails_closed(self):
        tools = ToolExecutor()
        provider = ScriptedProvider(
            ['{"type":"final","text":"not reached"}']
        )
        session = ReliableAgentSession(
            runtime=runtime(provider, tools),
            permissions=AgentPermissionPolicy(),
            resources=AgentResourcePolicy(
                owner_budget=AgentResourceBudget(
                    max_model_calls=10,
                    max_runtime_seconds=100,
                    max_cost_usd_micros=1000,
                ),
                plan_budget=AgentResourceBudget(
                    max_model_calls=1,
                    max_runtime_seconds=10,
                    max_cost_usd_micros=100,
                ),
            ),
        )
        with self.assertRaises(AgentReliabilityError):
            asyncio.run(
                session.run(
                    run_id="budget-deny",
                    user_text="hello",
                    current_usage=AgentResourceUsage(),
                    requested_usage=AgentResourceUsage(model_calls=2),
                )
            )
        self.assertEqual(provider.requests, [])

    def test_interruption_preserves_committed_canonical_state_and_no_replay(self):
        async def scenario():
            tools = ToolExecutor()
            state = {"revision": 0}

            async def commit(_arguments):
                if state["revision"] != 0:
                    raise AssertionError("write replayed")
                state["revision"] = 1
                return {"revision": 1}

            tools.register(
                ToolSpec("state.commit", "atomic fixture write", risk=ToolRisk.LOCAL_WRITE),
                commit,
            )
            provider = BlockingSecondProvider()
            agent = runtime(provider, tools)
            task = asyncio.create_task(
                agent.run(
                    run_id="interrupt-1",
                    user_text="commit once",
                    allowed_tool_ids=frozenset({"state.commit"}),
                )
            )
            await asyncio.wait_for(provider.second_started.wait(), timeout=2)
            self.assertTrue(await agent.cancel("interrupt-1"))
            with self.assertRaises(asyncio.CancelledError):
                await task
            self.assertEqual(state, {"revision": 1})

        asyncio.run(scenario())


class FakeSpeechInput:
    def __init__(self) -> None:
        self.calls = 0

    async def transcribe(self, audio: bytes, *, language: str | None) -> str:
        self.calls += 1
        return "Explain the position."


class FakeSpeechOutput:
    def __init__(self) -> None:
        self.texts: list[str] = []

    async def synthesize(self, text: str, *, language: str | None) -> bytes:
        self.texts.append(text)
        return b"spoken"


class PermissionSequence:
    def __init__(self, values: list[VoicePermissionState]) -> None:
        self.values = list(values)

    def __call__(self) -> VoicePermissionState:
        if not self.values:
            raise AssertionError("unexpected permission read")
        return self.values.pop(0)


def voice_session(provider) -> ReliableAgentSession:
    tools = ToolExecutor()
    return ReliableAgentSession(
        runtime=runtime(provider, tools),
        permissions=AgentPermissionPolicy(),
        resources=AgentResourcePolicy(
            owner_budget=AgentResourceBudget(
                max_model_calls=10,
                max_runtime_seconds=120,
                max_cost_usd_micros=1000000,
            ),
            plan_budget=AgentResourceBudget(
                max_model_calls=3,
                max_runtime_seconds=30,
                max_cost_usd_micros=100000,
            ),
        ),
    )


class Section24VoiceTests(unittest.TestCase):
    def test_replaceable_voice_round_trip(self):
        provider = ScriptedProvider(
            ['{"type":"final","text":"Use the open file."}']
        )
        speech_in = FakeSpeechInput()
        speech_out = FakeSpeechOutput()
        voice = AgentVoiceConversation(
            session=voice_session(provider),
            speech_input=speech_in,
            speech_output=speech_out,
            permission_provider=PermissionSequence(
                [
                    VoicePermissionState(True, True, True),
                    VoicePermissionState(True, True, True),
                    VoicePermissionState(True, True, True),
                ]
            ),
        )
        result = asyncio.run(
            voice.converse(
                run_id="voice-1",
                audio=b"audio",
                language="uk",
                current_usage=AgentResourceUsage(),
                requested_usage=AgentResourceUsage(model_calls=1),
            )
        )
        self.assertEqual(result.transcript, "Explain the position.")
        self.assertEqual(result.audio, b"spoken")
        self.assertEqual(speech_out.texts, ["Use the open file."])

    def test_live_output_revocation_never_sends_text_to_tts_provider(self):
        provider = ScriptedProvider(
            ['{"type":"final","text":"Private response."}']
        )
        speech_out = FakeSpeechOutput()
        voice = AgentVoiceConversation(
            session=voice_session(provider),
            speech_input=FakeSpeechInput(),
            speech_output=speech_out,
            permission_provider=PermissionSequence(
                [
                    VoicePermissionState(True, True, True),
                    VoicePermissionState(True, True, True),
                    VoicePermissionState(True, True, False),
                ]
            ),
        )
        result = asyncio.run(
            voice.converse(
                run_id="voice-2",
                audio=b"audio",
                current_usage=AgentResourceUsage(),
                requested_usage=AgentResourceUsage(model_calls=1),
            )
        )
        self.assertTrue(result.output_suppressed)
        self.assertIsNone(result.audio)
        self.assertEqual(speech_out.texts, [])

    def test_model_permission_revocation_stops_after_transcription(self):
        provider = ScriptedProvider(
            ['{"type":"final","text":"must not run"}']
        )
        speech_in = FakeSpeechInput()
        voice = AgentVoiceConversation(
            session=voice_session(provider),
            speech_input=speech_in,
            speech_output=FakeSpeechOutput(),
            permission_provider=PermissionSequence(
                [
                    VoicePermissionState(True, True, True),
                    VoicePermissionState(True, False, True),
                ]
            ),
        )
        with self.assertRaises(VoiceConversationError):
            asyncio.run(
                voice.converse(
                    run_id="voice-3",
                    audio=b"audio",
                    current_usage=AgentResourceUsage(),
                    requested_usage=AgentResourceUsage(model_calls=1),
                )
            )
        self.assertEqual(speech_in.calls, 1)
        self.assertEqual(provider.requests, [])


if __name__ == "__main__":
    unittest.main()
