from __future__ import annotations

from dataclasses import dataclass
import unittest

from acs.agent_webview_bridge import AgentConversationWebViewBridge
from acs.agent_webview_projection import (
    AgentConversationProjection,
    MAX_AGENT_PROMPT_CHARS,
    MAX_AGENT_RESPONSE_CHARS,
)


@dataclass
class Result:
    text: str
    model_calls: int
    tool_calls: int
    steps: int


class AgentWebViewSurfaceTests(unittest.TestCase):
    def test_unavailable_surface_is_reachable_but_fails_closed(self):
        projection = AgentConversationProjection(language="uk")
        bridge = AgentConversationWebViewBridge(projection)
        snapshot = projection.snapshot()
        self.assertIs(snapshot["available"], False)
        self.assertEqual(snapshot["state"], "unavailable")
        self.assertEqual(snapshot["focus_target"], "agent-input")
        result = bridge.dispatch("agent.submit", {"text": "Поясни позицію"})
        self.assertEqual(result.kind, "error")
        self.assertEqual(projection.snapshot()["transcript"], [])

    def test_submit_completion_and_runtime_status_are_copyable_and_bounded(self):
        starts = []
        cancels = []
        projection = AgentConversationProjection(
            start_run=lambda run_id, text: starts.append((run_id, text)),
            cancel_run=lambda run_id: cancels.append(run_id),
            language="en",
        )
        bridge = AgentConversationWebViewBridge(projection)
        result = bridge.dispatch("agent.submit", {"text": "  Describe the current board.  "})
        self.assertEqual(result.kind, "accepted")
        self.assertEqual(starts, [("agent-ui-1", "Describe the current board.")])
        running = projection.snapshot()
        self.assertEqual(running["state"], "running")
        self.assertIs(running["can_submit"], False)
        self.assertIs(running["can_cancel"], True)
        self.assertEqual(running["transcript"][0]["text"], "Describe the current board.")

        self.assertTrue(
            projection.update_runtime_status(
                "agent-ui-1",
                {
                    "provider_id": "fixture",
                    "model": "fixture-model",
                    "tool_id": "board.current",
                    "steps": 1,
                    "model_calls": 1,
                    "tool_calls": 1,
                },
            )
        )
        status = projection.snapshot()["status_text"]
        self.assertIn("fixture-model", status)
        self.assertIn("board.current", status)

        self.assertTrue(
            projection.complete(
                "agent-ui-1",
                "White to move.\nThere are 20 legal moves.",
                model_calls=2,
                tool_calls=1,
                steps=2,
            )
        )
        done = projection.snapshot()
        self.assertEqual(done["state"], "completed")
        self.assertIs(done["can_submit"], True)
        self.assertIs(done["can_cancel"], False)
        self.assertEqual(done["transcript"][-1]["role"], "assistant")
        self.assertEqual(
            done["transcript"][-1]["text"],
            "White to move.\nThere are 20 legal moves.",
        )
        self.assertIn("Model calls: 2", done["status_text"])

    def test_status_snapshot_is_lightweight_and_completion_failure_releases_ui(self):
        starts = []
        projection = AgentConversationProjection(
            start_run=lambda run_id, text: starts.append((run_id, text)),
            cancel_run=lambda _run_id: None,
            language="en",
        )
        projection.submit("Analyze")
        status = projection.status_snapshot()
        self.assertNotIn("transcript", status)
        self.assertEqual(status["state"], "running")
        self.assertEqual(status["run_id"], "agent-ui-1")

        self.assertFalse(
            projection.complete(
                "agent-ui-1",
                "X" * (MAX_AGENT_RESPONSE_CHARS + 1),
            )
        )
        failed = projection.snapshot()
        self.assertEqual(failed["state"], "failed")
        self.assertEqual(failed["run_id"], "")
        self.assertIs(failed["can_submit"], True)
        self.assertIs(failed["can_cancel"], False)
        self.assertEqual(len(failed["transcript"]), 1)

    def test_synchronous_host_completion_restores_input_focus_target(self):
        holder = {}
        def start(run_id, _text):
            holder["projection"].complete(run_id, "Immediate answer")

        projection = AgentConversationProjection(
            start_run=start,
            cancel_run=lambda _run_id: None,
            language="en",
        )
        holder["projection"] = projection
        event = projection.submit("Immediate?")
        self.assertEqual(event.kind, "accepted")
        self.assertEqual(event.payload["focus_target"], "agent-input")
        self.assertEqual(event.payload["snapshot"]["state"], "completed")
        self.assertEqual(
            event.payload["snapshot"]["transcript"][-1]["text"],
            "Immediate answer",
        )

    def test_only_active_run_may_publish_or_cancel_and_stale_completion_is_ignored(self):
        starts = []
        cancels = []
        projection = AgentConversationProjection(
            start_run=lambda run_id, text: starts.append((run_id, text)),
            cancel_run=lambda run_id: cancels.append(run_id),
        )
        bridge = AgentConversationWebViewBridge(projection)
        bridge.dispatch("agent.submit", {"text": "Перший запит"})
        busy = bridge.dispatch("agent.submit", {"text": "Другий запит"})
        self.assertEqual(busy.kind, "error")
        self.assertEqual(len(starts), 1)
        self.assertIs(projection.complete("wrong-run", "stale"), False)
        self.assertEqual(projection.snapshot()["state"], "running")
        stopped = bridge.dispatch("agent.cancel", {})
        self.assertEqual(stopped.kind, "cancel-requested")
        self.assertEqual(cancels, ["agent-ui-1"])
        self.assertEqual(projection.snapshot()["state"], "cancelling")
        self.assertIs(projection.mark_cancelled("agent-ui-1"), True)
        self.assertEqual(projection.snapshot()["state"], "cancelled")
        self.assertIs(projection.complete("agent-ui-1", "late completion"), False)

    def test_prompt_validation_and_bridge_schema_do_not_echo_private_or_malformed_input(self):
        projection = AgentConversationProjection(
            start_run=lambda *_: None,
            cancel_run=lambda *_: None,
        )
        bridge = AgentConversationWebViewBridge(projection)
        secret = "S" * (MAX_AGENT_PROMPT_CHARS + 1)
        result = bridge.dispatch("agent.submit", {"text": secret})
        self.assertEqual(result.kind, "error")
        self.assertNotIn(secret, str(result.payload))
        self.assertEqual(projection.snapshot()["transcript"], [])
        malformed = bridge.dispatch("agent.submit", {"text": "ok", "extra": secret})
        self.assertEqual(malformed.kind, "error")
        self.assertNotIn(secret, str(malformed.payload))
        unsupported = bridge.dispatch("agent.private_debug", {})
        self.assertEqual(unsupported.kind, "error")

    def test_start_failure_never_exposes_internal_exception_text(self):
        def fail_start(_run_id, _text):
            raise RuntimeError(r"C:\\Users\\owner\\private-model-token")

        projection = AgentConversationProjection(
            start_run=fail_start,
            cancel_run=lambda *_: None,
            language="en",
        )
        result = projection.submit("Analyze")
        self.assertEqual(result.kind, "error")
        self.assertNotIn("private-model-token", str(result.payload))
        self.assertEqual(result.payload["focus_target"], "agent-input")
        self.assertEqual(projection.snapshot()["state"], "failed")

    def test_synchronous_cancel_completion_restores_input_focus_target(self):
        holder = {}
        def cancel(run_id):
            holder["projection"].mark_cancelled(run_id)

        projection = AgentConversationProjection(
            start_run=lambda _run_id, _text: None,
            cancel_run=cancel,
            language="en",
        )
        holder["projection"] = projection
        projection.submit("Cancel me")
        event = projection.cancel()
        self.assertEqual(event.kind, "cancel-requested")
        self.assertEqual(event.payload["focus_target"], "agent-input")
        self.assertEqual(event.payload["snapshot"]["state"], "cancelled")

    def test_complete_result_accepts_existing_agent_run_result_shape(self):
        starts = []
        projection = AgentConversationProjection(
            start_run=lambda run_id, text: starts.append((run_id, text)),
            cancel_run=lambda _run_id: None,
        )
        projection.submit("Поясни матеріал")
        result = Result("Матеріал рівний.", 2, 1, 2)
        self.assertTrue(projection.complete_result("agent-ui-1", result))
        snapshot = projection.snapshot()
        self.assertEqual(snapshot["transcript"][-1]["text"], "Матеріал рівний.")
        self.assertEqual(snapshot["state"], "completed")

    def test_language_switch_changes_labels_without_mutating_transcript(self):
        starts = []
        projection = AgentConversationProjection(
            start_run=lambda run_id, text: starts.append((run_id, text)),
            cancel_run=lambda _run_id: None,
            language="uk",
        )
        projection.submit("e4 чи d4?")
        projection.complete("agent-ui-1", "Both are playable.")
        projection.set_language("en")
        snapshot = projection.snapshot()
        self.assertEqual(snapshot["heading"], "Chess assistant")
        self.assertEqual(snapshot["transcript"][0]["label"], "You")
        self.assertEqual(snapshot["transcript"][0]["text"], "e4 чи d4?")
        self.assertEqual(snapshot["transcript"][1]["text"], "Both are playable.")


if __name__ == "__main__":
    unittest.main()
