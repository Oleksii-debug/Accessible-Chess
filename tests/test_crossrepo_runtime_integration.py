from __future__ import annotations

import asyncio
import unittest
from dataclasses import replace
from decimal import Decimal

from acs.agent_budget import ModelCostBudget
from acs.agent_model_contracts import (
    ModelErrorCode,
    ModelFailureEffect,
    ModelGatewayError,
    ModelMessage,
    ModelRequest,
    ModelResponse,
    ModelUsage,
    PrivacyClass,
    ProviderCapabilities,
    ProviderKind,
)
from acs.agent_model_gateway import ModelGateway
from acs.agent_task_state import TaskState, can_transition, require_transition
from acs.agent_tools import ToolCall, ToolExecutor, ToolRisk, ToolSpec
from acs.assistive_announcement import (
    AnnouncementEvent,
    AnnouncementGate,
    AnnouncementKind,
    AnnouncementPriority,
)
from acs.media_foundation import TranscriptSegment
from acs.media_transcription import (
    ChunkPlanPolicy,
    ChunkState,
    TranscriptionChunk,
    merge_completed_chunks,
    plan_chunks,
)


class FailingProvider:
    @property
    def capabilities(self):
        return ProviderCapabilities(
            provider_id="first",
            kind=ProviderKind.LOCAL,
            supports_private_data=True,
        )

    async def complete(self, request):
        raise ModelGatewayError(
            ModelErrorCode.UNAVAILABLE,
            "secret internal provider diagnostic",
            provider_id="first",
            retryable=True,
            failure_effect=ModelFailureEffect.NO_EFFECT,
        )


class SuccessProvider:
    @property
    def capabilities(self):
        return ProviderCapabilities(
            provider_id="second",
            kind=ProviderKind.LOCAL,
            supports_private_data=True,
        )

    async def complete(self, request):
        return ModelResponse(
            request_id=request.request_id,
            text="ok",
            provider_id="second",
            provider_kind=ProviderKind.LOCAL,
            model=request.model or "fixture",
            usage=ModelUsage(total_tokens=3),
        )


class CrossRepoRuntimeIntegrationTests(unittest.TestCase):
    def test_nika_model_gateway_safe_fallback_is_live(self):
        gateway = ModelGateway()
        gateway.register(FailingProvider())
        gateway.register(SuccessProvider())
        request = ModelRequest(
            request_id="req-1",
            messages=(ModelMessage(role="user", content="fixture"),),
            provider_id="first",
            fallback_provider_ids=("second",),
            privacy=PrivacyClass.PRIVATE,
        )
        response = asyncio.run(gateway.complete(request))
        self.assertEqual(response.provider_id, "second")
        self.assertEqual(response.text, "ok")

    def test_model_gateway_blocks_private_route_to_public_only_provider(self):
        class PublicOnly(SuccessProvider):
            @property
            def capabilities(self):
                return ProviderCapabilities(
                    provider_id="second",
                    kind=ProviderKind.CLOUD,
                    supports_private_data=False,
                )

        gateway = ModelGateway()
        gateway.register(PublicOnly())
        request = ModelRequest(
            request_id="private-1",
            messages=(ModelMessage(role="user", content="private chess notes"),),
            provider_id="second",
            privacy=PrivacyClass.SENSITIVE,
        )
        with self.assertRaises(ModelGatewayError) as caught:
            asyncio.run(gateway.complete(request))
        self.assertEqual(caught.exception.code, ModelErrorCode.INVALID_REQUEST)

    def test_autotrade_budget_pattern_bounds_agent_cost(self):
        budget = ModelCostBudget("1.00")
        budget.reserve("request-a", "0.40")
        self.assertEqual(budget.snapshot().available, Decimal("0.60"))
        with self.assertRaises(ValueError):
            budget.reserve("request-b", "0.70")
        budget.settle("request-a", incurred="0.25", estimated_unbilled="0.05")
        self.assertEqual(budget.snapshot().incurred, Decimal("0.25"))
        self.assertEqual(
            budget.snapshot().estimated_unbilled,
            Decimal("0.05"),
        )

    def test_agent_task_state_machine_reuses_nika_lifecycle(self):
        self.assertTrue(can_transition(TaskState.CREATED, TaskState.READY))
        self.assertTrue(can_transition(TaskState.RUNNING, TaskState.WAITING_TOOL))
        with self.assertRaises(ValueError):
            require_transition(TaskState.COMPLETED, TaskState.RUNNING)

    def test_tool_executor_runs_read_only_and_fails_closed_for_external(self):
        executor = ToolExecutor()

        async def read(arguments):
            return {"value": arguments.get("value")}

        executor.register(
            ToolSpec("fixture.read", "read fixture"),
            read,
        )
        result = asyncio.run(
            executor.execute(
                ToolCall(
                    call_id="call-read",
                    tool_id="fixture.read",
                    arguments={"value": 7},
                )
            )
        )
        self.assertTrue(result.ok)
        self.assertEqual(result.output, {"value": 7})

        executor.register(
            ToolSpec(
                "fixture.external",
                "external fixture",
                risk=ToolRisk.EXTERNAL_SIDE_EFFECT,
            ),
            read,
        )
        denied = asyncio.run(
            executor.execute(
                ToolCall(
                    call_id="call-external",
                    tool_id="fixture.external",
                    arguments={},
                    task_id="task-1",
                )
            )
        )
        self.assertFalse(denied.ok)
        self.assertIn("approval", denied.error)

    def test_autosport_announcement_gate_suppresses_churn_and_duplicates(self):
        gate = AnnouncementGate()
        silent = gate.decide(
            AnnouncementEvent(
                AnnouncementKind.MEDIA_CLOCK_TICK,
                "00:01",
                "clock-1",
            )
        )
        self.assertFalse(silent.emit)
        move = AnnouncementEvent(
            AnnouncementKind.MEDIA_MOVE,
            "e4",
            "media-move-1",
        )
        first = gate.decide(move)
        second = gate.decide(move)
        self.assertTrue(first.emit)
        self.assertEqual(first.priority, AnnouncementPriority.POLITE)
        self.assertFalse(first.move_focus)
        self.assertFalse(second.emit)

        critical = AnnouncementEvent(
            AnnouncementKind.MEDIA_RESYNC_REQUIRED,
            "Position needs resynchronization",
            "resync-state",
            episode_id="episode-1",
        )
        assertive = gate.decide(critical)
        self.assertTrue(assertive.emit)
        self.assertEqual(
            assertive.priority,
            AnnouncementPriority.ASSERTIVE,
        )

    def test_nika_chunk_planning_and_overlap_merge_are_available(self):
        chunks = plan_chunks(
            job_id="job-1",
            duration_ms=65_000,
            policy=ChunkPlanPolicy(chunk_ms=30_000, overlap_ms=2_000),
        )
        self.assertEqual(len(chunks), 3)
        self.assertEqual(chunks[0].start_ms, 0)
        self.assertEqual(chunks[1].start_ms, 28_000)

        completed = []
        for chunk in chunks:
            middle = chunk.core_start_ms + 1000
            completed.append(
                replace(
                    chunk,
                    state=ChunkState.COMPLETED,
                    segments=(
                        TranscriptSegment(
                            segment_id=f"segment-{chunk.ordinal}",
                            start_ms=middle,
                            end_ms=middle + 500,
                            text=f"text {chunk.ordinal}",
                        ),
                    ),
                )
            )
        merged = merge_completed_chunks(tuple(completed))
        self.assertEqual(
            [segment.text for segment in merged],
            ["text 0", "text 1", "text 2"],
        )


if __name__ == "__main__":
    unittest.main()
