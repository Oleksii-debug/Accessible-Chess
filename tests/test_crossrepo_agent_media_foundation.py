from __future__ import annotations

import asyncio
import json
import tempfile
import unittest
import wave
from pathlib import Path

from acs.agent_model_gateway import (
    AgentModelErrorCode,
    AgentModelGateway,
    AgentModelGatewayError,
    AgentModelMessage,
    AgentModelRequest,
    AgentModelResponse,
    AgentModelUsage,
    AgentPrivacyClass,
    AgentProviderCapabilities,
    AgentProviderKind,
)
from acs.agent_runtime import (
    AgentErrorCode,
    AgentOutcome,
    AgentResult,
    AgentRetryPolicy,
)
from acs.agent_tools import (
    ChessToolCall,
    ChessToolExecutor,
    ChessToolRisk,
    ChessToolSpec,
    chess_tool_arguments_fingerprint,
)
from acs.durable_checkpoint import CheckpointCorruptError, FileCheckpointStore
from acs.media_audio import AudioInspectionPolicy, inspect_pcm16_wav
from acs.board_service import BoardCommandService, BoardSnapshot, MoveView
from acs.media_application import MediaApplicationService
from acs.media_core import MediaPlaybackState, MediaSession
from acs.universal_chess_agent import UniversalChessAgentTools
from acs.media_timeline_store import MediaTimelineStore
from acs.media_core import (
    ChessStateReconciler,
    MediaPositionTimeline,
    ReconciliationStatus,
    TimelineEntry,
)


class FakeProvider:
    def __init__(
        self,
        provider_id: str,
        kind: AgentProviderKind,
        *,
        private: bool,
        behavior: str,
        hard_cancel: bool = True,
    ):
        self._capabilities = AgentProviderCapabilities(
            provider_id=provider_id,
            kind=kind,
            supports_private_data=private,
            supports_hard_cancellation=hard_cancel,
        )
        self.behavior = behavior

    @property
    def capabilities(self):
        return self._capabilities

    async def complete(self, request):
        if self.behavior == "timeout":
            raise AgentModelGatewayError(
                AgentModelErrorCode.TIMEOUT,
                "timeout",
                provider_id=self.capabilities.provider_id,
                retryable=True,
            )
        if self.behavior == "fail":
            raise RuntimeError("untyped provider failure")
        return AgentModelResponse(
            request_id=request.request_id,
            text=f"ok:{self.capabilities.provider_id}",
            provider_id=self.capabilities.provider_id,
            provider_kind=self.capabilities.kind,
            model=request.model or "fake",
            usage=AgentModelUsage(total_tokens=1),
        )


class CrossRepoFoundationTests(unittest.TestCase):
    def test_retry_is_fail_closed_by_default(self):
        policy = AgentRetryPolicy(
            max_retries=2,
            retryable_error_codes=frozenset({AgentErrorCode.TIMEOUT}),
        )
        failed = AgentResult(
            outcome=AgentOutcome.FAILED,
            error="timeout",
            error_code=AgentErrorCode.TIMEOUT,
        )
        self.assertFalse(policy.should_retry(failed, retries_used=0))

    def test_retry_can_use_explicit_fresh_policy(self):
        policy = AgentRetryPolicy(
            max_retries=2,
            retryable_error_codes=frozenset({AgentErrorCode.TIMEOUT}),
            base_delay_seconds=1,
            allow_fresh_retry=True,
        )
        failed = AgentResult(
            outcome=AgentOutcome.FAILED,
            error="timeout",
            error_code=AgentErrorCode.TIMEOUT,
        )
        self.assertTrue(policy.should_retry(failed, retries_used=0))
        self.assertEqual(policy.delay_seconds(retry_number=2), 2)

    def test_tool_argument_fingerprint_is_canonical(self):
        one = chess_tool_arguments_fingerprint({"b": 2, "a": "é"})
        two = chess_tool_arguments_fingerprint({"a": "e\u0301", "b": 2})
        self.assertEqual(one, two)

    def test_external_tool_fails_closed_without_guard(self):
        async def handler(arguments):
            return {"done": True}

        async def run():
            executor = ChessToolExecutor()
            executor.register(
                ChessToolSpec(
                    "media.external",
                    "External effect",
                    risk=ChessToolRisk.EXTERNAL_SIDE_EFFECT,
                ),
                handler,
            )
            return await executor.execute(
                ChessToolCall("call-1", "media.external", {}, task_id="task-1")
            )

        result = asyncio.run(run())
        self.assertFalse(result.ok)
        self.assertIn("durable effect guard", result.error or "")

    def test_read_only_tool_executes(self):
        async def handler(arguments):
            return {"square": arguments["square"], "piece": "white knight"}

        async def run():
            executor = ChessToolExecutor()
            executor.register(
                ChessToolSpec("board.square", "Read a square"),
                handler,
            )
            return await executor.execute(
                ChessToolCall("call-1", "board.square", {"square": "f3"})
            )

        result = asyncio.run(run())
        self.assertTrue(result.ok)
        self.assertEqual(result.output["square"], "f3")

    def test_model_gateway_blocks_private_route_to_nonprivate_provider(self):
        gateway = AgentModelGateway()
        gateway.register(
            FakeProvider("public-cloud", AgentProviderKind.CLOUD, private=False, behavior="ok"),
            default=True,
        )
        request = AgentModelRequest(
            "req-1",
            (AgentModelMessage("user", "private chess lesson"),),
            privacy=AgentPrivacyClass.PRIVATE,
        )
        with self.assertRaises(AgentModelGatewayError):
            asyncio.run(gateway.complete(request))

    def test_model_gateway_safe_fallback(self):
        gateway = AgentModelGateway()
        gateway.register(
            FakeProvider("local-a", AgentProviderKind.LOCAL, private=True, behavior="timeout"),
            default=True,
        )
        gateway.register(
            FakeProvider("local-b", AgentProviderKind.LOCAL, private=True, behavior="ok")
        )
        request = AgentModelRequest(
            "req-2",
            (AgentModelMessage("user", "explain"),),
            provider_id="local-a",
            fallback_provider_ids=("local-b",),
        )
        response = asyncio.run(gateway.complete(request))
        self.assertEqual(response.provider_id, "local-b")

    def test_checkpoint_roundtrip_and_tamper_detection(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = FileCheckpointStore(tmp)
            saved = store.save(job_id="media-1", stage="frames", payload={"cursor": 17})
            loaded = store.load("media-1")
            self.assertEqual(loaded, saved)

            path = store.path_for("media-1")
            body = json.loads(path.read_text(encoding="utf-8"))
            body["payload"]["cursor"] = 18
            path.write_text(json.dumps(body), encoding="utf-8")
            with self.assertRaises(CheckpointCorruptError):
                store.load("media-1")

    def test_wav_inspection(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "sample.wav"
            with wave.open(str(path), "wb") as handle:
                handle.setnchannels(1)
                handle.setsampwidth(2)
                handle.setframerate(16000)
                frames = b"".join(
                    int(value).to_bytes(2, "little", signed=True)
                    for value in (0, 100, -250, 12)
                )
                handle.writeframes(frames)
            result = inspect_pcm16_wav(
                path,
                policy=AudioInspectionPolicy(max_frames=10),
            )
            self.assertEqual(result.sample_rate_hz, 16000)
            self.assertEqual(result.channels, 1)
            self.assertEqual(result.frames, 4)
            self.assertEqual(result.peak_pcm16, 250)
            self.assertFalse(result.is_silent())

    def test_reconciler_prefers_structured_legal_move(self):
        result = ChessStateReconciler().reconcile(
            current_position_id="p0",
            legal_transitions={"Nf3": "p1", "e4": "p2"},
            structured_move_id="Nf3",
            observed_position_id="p1",
        )
        self.assertEqual(result.status, ReconciliationStatus.VERIFIED)
        self.assertEqual(result.position_id, "p1")

    def test_reconciler_rejects_conflicting_evidence(self):
        result = ChessStateReconciler().reconcile(
            current_position_id="p0",
            legal_transitions={"Nf3": "p1"},
            structured_move_id="Nf3",
            observed_position_id="wrong",
        )
        self.assertEqual(result.status, ReconciliationStatus.AMBIGUOUS)

    def test_reconciler_uses_high_confidence_unique_legal_transition(self):
        result = ChessStateReconciler().reconcile(
            current_position_id="p0",
            legal_transitions={"Nf3": "p1", "e4": "p2"},
            observed_position_id="p2",
            observed_confidence=0.97,
        )
        self.assertEqual(result.status, ReconciliationStatus.INFERRED)
        self.assertEqual(result.move_id, "e4")

    def test_timeline_lookup_and_navigation(self):
        timeline = MediaPositionTimeline(
            (
                TimelineEntry(
                    0,
                    1000,
                    "main",
                    "n0",
                    "p0",
                    ReconciliationStatus.VERIFIED,
                ),
                TimelineEntry(
                    1000,
                    2000,
                    "main",
                    "n1",
                    "p1",
                    ReconciliationStatus.VERIFIED,
                ),
            )
        )
        self.assertEqual(timeline.at(1500).position_id, "p1")
        self.assertEqual(timeline.previous(1500).position_id, "p0")
        self.assertIsNone(timeline.next(1500))

    def test_timeline_rejects_entry_after_open_ended_entry(self):
        with self.assertRaises(ValueError):
            MediaPositionTimeline(
                (
                    TimelineEntry(
                        0,
                        None,
                        "main",
                        "n0",
                        "p0",
                        ReconciliationStatus.VERIFIED,
                    ),
                    TimelineEntry(
                        1000,
                        2000,
                        "main",
                        "n1",
                        "p1",
                        ReconciliationStatus.VERIFIED,
                    ),
                )
            )

    def test_reconciler_rejects_invalid_confidence(self):
        with self.assertRaises(ValueError):
            ChessStateReconciler().reconcile(
                current_position_id="p0",
                legal_transitions={"Nf3": "p1"},
                observed_position_id="p1",
                observed_confidence=1.5,
            )

    def test_model_gateway_does_not_fallback_after_unsafe_timeout(self):
        gateway = AgentModelGateway()
        gateway.register(
            FakeProvider(
                "local-a",
                AgentProviderKind.LOCAL,
                private=True,
                behavior="timeout",
                hard_cancel=False,
            ),
            default=True,
        )
        gateway.register(
            FakeProvider("local-b", AgentProviderKind.LOCAL, private=True, behavior="ok")
        )
        request = AgentModelRequest(
            "req-unsafe-timeout",
            (AgentModelMessage("user", "explain"),),
            provider_id="local-a",
            fallback_provider_ids=("local-b",),
        )
        with self.assertRaises(AgentModelGatewayError) as ctx:
            asyncio.run(gateway.complete(request))
        self.assertEqual(ctx.exception.code, AgentModelErrorCode.TIMEOUT)

class ProductCompositionTests(unittest.TestCase):
    @staticmethod
    def _board_service() -> BoardCommandService:
        pieces = [None] * 64
        pieces[6] = "N"  # g1
        board = BoardSnapshot(
            pieces=tuple(pieces),
            turn="w",
            legal_moves=(MoveView(6, 21, san="Nf3"),),
        )
        return BoardCommandService(board)

    @staticmethod
    def _timeline() -> MediaPositionTimeline:
        return MediaPositionTimeline(
            (
                TimelineEntry(
                    0,
                    1000,
                    "main",
                    "node-0",
                    "position-0",
                    ReconciliationStatus.VERIFIED,
                ),
                TimelineEntry(
                    1000,
                    2000,
                    "main",
                    "node-1",
                    "position-1",
                    ReconciliationStatus.VERIFIED,
                ),
            )
        )

    def test_media_application_restore_uses_canonical_position_publisher(self):
        published: list[str] = []
        service = MediaApplicationService(
            MediaSession(
                "media-1",
                "fixture",
                "recorded-1",
                state=MediaPlaybackState.PAUSED,
                current_ms=1200,
            ),
            self._timeline(),
            publish_position=published.append,
        )
        service.detach_for_analysis()
        restored = asyncio.run(service.restore_media_position())
        self.assertEqual(restored.position_id, "position-1")
        self.assertEqual(published, ["position-1"])
        self.assertFalse(service.analysis_detached)

    def test_agent_board_tool_reads_existing_board_command_service(self):
        tools = UniversalChessAgentTools(self._board_service)
        result = asyncio.run(
            tools.execute(
                ChessToolCall(
                    "call-board-square",
                    "board.square",
                    {"square": "g1"},
                )
            )
        )
        self.assertTrue(result.ok)
        self.assertEqual(result.output, {"square": "g1", "piece": "N"})

    def test_agent_legal_moves_are_from_existing_board_service(self):
        tools = UniversalChessAgentTools(self._board_service)
        result = asyncio.run(
            tools.execute(
                ChessToolCall(
                    "call-board-moves",
                    "board.legal_moves",
                    {"square": "g1"},
                )
            )
        )
        self.assertTrue(result.ok)
        self.assertEqual(result.output["moves"][0]["san"], "Nf3")

    def test_agent_media_restore_calls_real_media_application_service(self):
        published: list[str] = []
        media = MediaApplicationService(
            MediaSession(
                "media-1",
                "fixture",
                "recorded-1",
                state=MediaPlaybackState.PAUSED,
                current_ms=1200,
            ),
            self._timeline(),
            publish_position=published.append,
        )
        media.detach_for_analysis()
        tools = UniversalChessAgentTools(self._board_service, media_service=media)
        result = asyncio.run(
            tools.execute(
                ChessToolCall(
                    "call-media-restore",
                    "media.restore_position",
                    {},
                )
            )
        )
        self.assertTrue(result.ok)
        self.assertEqual(result.output["position_id"], "position-1")
        self.assertEqual(published, ["position-1"])
        self.assertFalse(media.analysis_detached)

class MediaTimelinePersistenceTests(unittest.TestCase):
    def test_timeline_store_roundtrip(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = MediaTimelineStore(tmp)
            timeline = ProductCompositionTests._timeline()
            store.save("media-1", timeline)
            loaded = store.load("media-1")
            self.assertIsNotNone(loaded)
            self.assertEqual(
                tuple((x.start_ms, x.position_id) for x in loaded.entries),
                ((0, "position-0"), (1000, "position-1")),
            )

    def test_corrupt_current_recovers_last_valid_backup(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = MediaTimelineStore(tmp)
            first = MediaPositionTimeline(
                (
                    TimelineEntry(
                        0,
                        1000,
                        "main",
                        "node-0",
                        "position-0",
                        ReconciliationStatus.VERIFIED,
                    ),
                )
            )
            second = ProductCompositionTests._timeline()
            target = store.save("media-1", first)
            store.save("media-1", second)
            target.write_text("{broken", encoding="utf-8")
            recovered = store.load("media-1")
            self.assertIsNotNone(recovered)
            self.assertEqual(len(recovered.entries), 1)
            self.assertEqual(recovered.entries[0].position_id, "position-0")

    def test_duplicate_json_keys_are_rejected_and_not_published_as_truth(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = MediaTimelineStore(tmp)
            target = store.save("media-1", ProductCompositionTests._timeline())
            raw = target.read_text(encoding="utf-8")
            raw = raw.replace(
                '"version":1',
                '"version":1,"version":1',
                1,
            )
            target.write_text(raw, encoding="utf-8")
            self.assertIsNone(store.load("media-1"))

    def test_playback_sync_preserves_detached_analysis(self):
        published: list[str] = []
        service = MediaApplicationService(
            MediaSession(
                "media-1",
                "fixture",
                "recorded-1",
                state=MediaPlaybackState.PLAYING,
                current_ms=100,
            ),
            ProductCompositionTests._timeline(),
            publish_position=published.append,
        )
        service.detach_for_analysis()
        entry = asyncio.run(service.sync_playback_timestamp(1200))
        self.assertEqual(entry.position_id, "position-1")
        self.assertTrue(service.analysis_detached)
        self.assertEqual(published, [])
        restored = asyncio.run(service.restore_media_position())
        self.assertEqual(restored.position_id, "position-1")
        self.assertEqual(published, ["position-1"])
        self.assertFalse(service.analysis_detached)


if __name__ == "__main__":
    unittest.main()
