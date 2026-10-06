from __future__ import annotations

import asyncio
import unittest

from acs.agent_accessibility import format_agent_status, format_media_status
from acs.agent_resource_budget import (
    AgentResourceBudget,
    AgentResourceUsage,
    evaluate_agent_resource_admission,
    narrow_agent_budget,
)
from acs.agent_verification import (
    AgentArtifactRef,
    AgentObservation,
    AgentObservationStatus,
    AgentVerification,
    AgentVerificationStatus,
)
from acs.assistive_announcements import (
    AnnouncementPriority,
    ChessAnnouncementEvent,
    ChessAnnouncementGate,
    ChessAnnouncementKind,
)
from acs.keyed_async_lock import KeyedAsyncLock
from acs.public_errors import PublicApplicationError


class MediaAgentSafetyPrimitiveTests(unittest.TestCase):
    def test_accessible_agent_status_is_plain_complete_and_copyable(self) -> None:
        text = format_agent_status(
            {
                "state": "running",
                "task_id": "review-1",
                "provider_id": "local",
                "model": "coach",
                "tool_id": "board.square",
                "steps": 4,
            }
        )
        self.assertIn("Accessible Chess agent status", text)
        self.assertIn("State: running", text)
        self.assertIn("Current tool: board.square", text)
        self.assertNotIn("\x1b", text)

    def test_accessible_media_status_exposes_restore_without_hidden_speech_state(self) -> None:
        text = format_media_status(
            {
                "playback_state": "paused",
                "current_ms": 42000,
                "reconciliation_status": "verified",
                "position_id": "p42",
                "move_id": "Nf3",
                "analysis_detached": True,
            }
        )
        self.assertIn("Restore Media Position is available", text)
        self.assertIn("Board mode: independent analysis", text)

    def test_ordinary_error_letters_do_not_trigger_control_character_rejection(self) -> None:
        err = PublicApplicationError("Normal request", code="bad_request", details={"field": "position_id"})
        self.assertEqual(err.status, 400)
        self.assertEqual(err.message, "Normal request")
        self.assertEqual(err.public_payload("request-1")["error"]["details"], {"field": "position_id"})

    def test_public_error_strips_private_path_metadata(self) -> None:
        err = PublicApplicationError(
            "Bad request",
            status=400,
            code="bad_request",
            details={
                "field": "position_id",
                "path": "C:\\private\\secret",
                "reason": "invalid_state",
            },
        )
        payload = err.public_payload("request-1")
        self.assertEqual(payload["error"]["details"]["field"], "position_id")
        self.assertNotIn("path", payload["error"]["details"])

    def test_public_error_fails_closed_on_header_injection(self) -> None:
        err = PublicApplicationError(
            "bad\r\nInjected: yes",
            status=400,
            code="bad_request",
        )
        self.assertEqual(err.status, 500)
        self.assertEqual(err.code, "internal_error")
        self.assertEqual(err.message, "Internal server error")

    def test_keyed_lock_serializes_same_identity_and_releases_key(self) -> None:
        async def scenario():
            lock = KeyedAsyncLock()
            order: list[str] = []

            async def op(name: str, delay: float):
                async def body():
                    order.append(name + ":start")
                    await asyncio.sleep(delay)
                    order.append(name + ":end")
                await lock.run("media-1", body)

            await asyncio.gather(op("a", 0.01), op("b", 0.0))
            return order, await lock.active_keys()

        order, active = asyncio.run(scenario())
        self.assertEqual(order, ["a:start", "a:end", "b:start", "b:end"])
        self.assertEqual(active, ())

    def test_keyed_lock_allows_different_identities(self) -> None:
        async def scenario():
            lock = KeyedAsyncLock()
            started = asyncio.Event()
            release = asyncio.Event()
            second_started = asyncio.Event()

            async def first():
                async def body():
                    started.set()
                    await release.wait()
                await lock.run("a", body)

            async def second():
                await started.wait()
                async def body():
                    second_started.set()
                await lock.run("b", body)
                release.set()

            await asyncio.wait_for(asyncio.gather(first(), second()), timeout=1.0)
            return second_started.is_set()

        self.assertTrue(asyncio.run(scenario()))

    def test_child_resource_budget_can_only_narrow_owner_authority(self) -> None:
        owner = AgentResourceBudget(100, 3600, 5_000_000)
        plan = AgentResourceBudget(10, 7200, 2_000_000)
        effective = narrow_agent_budget(owner, plan)
        self.assertEqual(effective.max_model_calls, 10)
        self.assertEqual(effective.max_runtime_seconds, 3600)
        self.assertEqual(effective.max_cost_usd_micros, 2_000_000)

    def test_resource_admission_fails_closed_at_effective_ceiling(self) -> None:
        decision = evaluate_agent_resource_admission(
            owner_budget=AgentResourceBudget(100, 1000, 1_000_000),
            plan_budget=AgentResourceBudget(10, 500, 500_000),
            current_usage=AgentResourceUsage(9, 100, 100_000),
            requested=AgentResourceUsage(2, 1, 1),
        )
        self.assertFalse(decision.allowed)
        self.assertEqual(decision.reason, "model_call_budget_exceeded")

    def test_observation_is_not_verification(self) -> None:
        observation = AgentObservation(
            observation_id="obs-1",
            invocation_id="inv-1",
            status=AgentObservationStatus.OK,
            summary="Vision candidate found",
            data={"position_id": "candidate-p1"},
        )
        self.assertEqual(observation.status, AgentObservationStatus.OK)
        verification = AgentVerification(
            verification_id="ver-1",
            invocation_id="inv-1",
            observation_id="obs-1",
            status=AgentVerificationStatus.AMBIGUOUS,
            reason_code="canonical_disagreement",
        )
        self.assertEqual(verification.status, AgentVerificationStatus.AMBIGUOUS)

    def test_verified_result_requires_observation_identity(self) -> None:
        with self.assertRaises(ValueError):
            AgentVerification(
                verification_id="ver-1",
                invocation_id="inv-1",
                observation_id=None,
                status=AgentVerificationStatus.VERIFIED,
                reason_code="verified",
            )

    def test_artifact_requires_exact_lowercase_sha256(self) -> None:
        with self.assertRaises(ValueError):
            AgentArtifactRef(
                artifact_id="artifact-1",
                kind="media-frame",
                uri="file:///frame.png",
                sha256="A" * 64,
            )

    def test_high_frequency_progress_is_silent(self) -> None:
        decision = ChessAnnouncementGate().decide(
            ChessAnnouncementEvent(
                ChessAnnouncementKind.MEDIA_PROGRESS,
                "Processing frame 100",
                "media-1:frame-100",
            )
        )
        self.assertFalse(decision.emit)
        self.assertEqual(decision.priority, AnnouncementPriority.SILENT)

    def test_polite_transition_is_deduplicated_without_focus_move(self) -> None:
        gate = ChessAnnouncementGate()
        event = ChessAnnouncementEvent(
            ChessAnnouncementKind.MEDIA_POSITION_CHANGED,
            "Knight g1 to f3",
            "media-1:node-42",
        )
        first = gate.decide(event)
        second = gate.decide(event)
        self.assertTrue(first.emit)
        self.assertFalse(first.move_focus)
        self.assertFalse(second.emit)
        self.assertEqual(second.reason, "DUPLICATE_STATE_TRANSITION")

    def test_assertive_ambiguity_deduplicates_by_episode(self) -> None:
        gate = ChessAnnouncementGate()
        first = gate.decide(
            ChessAnnouncementEvent(
                ChessAnnouncementKind.MEDIA_AMBIGUOUS,
                "Media position is ambiguous",
                "media-1:ambiguous-state",
                episode_id="ambiguity-episode-1",
            )
        )
        second = gate.decide(
            ChessAnnouncementEvent(
                ChessAnnouncementKind.MEDIA_AMBIGUOUS,
                "Still ambiguous",
                "media-1:another-state",
                episode_id="ambiguity-episode-1",
            )
        )
        self.assertEqual(first.priority, AnnouncementPriority.ASSERTIVE)
        self.assertFalse(second.emit)
        self.assertEqual(second.reason, "DUPLICATE_CRITICAL_EPISODE")


if __name__ == "__main__":
    unittest.main()
