from __future__ import annotations

from dataclasses import dataclass

from acs.agent_webview_bridge import AgentConversationWebViewBridge
from acs.agent_webview_projection import (
    AgentConversationProjection,
    MAX_AGENT_PROMPT_CHARS,
)


def test_unavailable_surface_is_reachable_but_fails_closed():
    projection = AgentConversationProjection(language="uk")
    bridge = AgentConversationWebViewBridge(projection)
    snapshot = projection.snapshot()
    assert snapshot["available"] is False
    assert snapshot["state"] == "unavailable"
    assert snapshot["focus_target"] == "agent-input"
    result = bridge.dispatch("agent.submit", {"text": "Поясни позицію"})
    assert result.kind == "error"
    assert projection.snapshot()["transcript"] == []


def test_submit_completion_and_runtime_status_are_copyable_and_bounded():
    starts = []
    cancels = []
    projection = AgentConversationProjection(
        start_run=lambda run_id, text: starts.append((run_id, text)),
        cancel_run=lambda run_id: cancels.append(run_id),
        language="en",
    )
    bridge = AgentConversationWebViewBridge(projection)
    result = bridge.dispatch("agent.submit", {"text": "  Describe the current board.  "})
    assert result.kind == "accepted"
    assert starts == [("agent-ui-1", "Describe the current board.")]
    running = projection.snapshot()
    assert running["state"] == "running"
    assert running["can_submit"] is False
    assert running["can_cancel"] is True
    assert running["transcript"][0]["text"] == "Describe the current board."

    assert projection.update_runtime_status(
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
    status = projection.snapshot()["status_text"]
    assert "fixture-model" in status
    assert "board.current" in status

    assert projection.complete(
        "agent-ui-1",
        "White to move.\nThere are 20 legal moves.",
        model_calls=2,
        tool_calls=1,
        steps=2,
    )
    done = projection.snapshot()
    assert done["state"] == "completed"
    assert done["can_submit"] is True
    assert done["can_cancel"] is False
    assert done["transcript"][-1]["role"] == "assistant"
    assert done["transcript"][-1]["text"] == "White to move.\nThere are 20 legal moves."
    assert "Model calls: 2" in done["status_text"]


def test_only_active_run_may_publish_or_cancel_and_stale_completion_is_ignored():
    starts = []
    cancels = []
    projection = AgentConversationProjection(
        start_run=lambda run_id, text: starts.append((run_id, text)),
        cancel_run=lambda run_id: cancels.append(run_id),
    )
    bridge = AgentConversationWebViewBridge(projection)
    bridge.dispatch("agent.submit", {"text": "Перший запит"})
    busy = bridge.dispatch("agent.submit", {"text": "Другий запит"})
    assert busy.kind == "error"
    assert len(starts) == 1
    assert projection.complete("wrong-run", "stale") is False
    assert projection.snapshot()["state"] == "running"
    stopped = bridge.dispatch("agent.cancel", {})
    assert stopped.kind == "cancel-requested"
    assert cancels == ["agent-ui-1"]
    assert projection.snapshot()["state"] == "cancelling"
    assert projection.mark_cancelled("agent-ui-1") is True
    assert projection.snapshot()["state"] == "cancelled"
    assert projection.complete("agent-ui-1", "late completion") is False


def test_prompt_validation_and_bridge_schema_do_not_echo_private_or_malformed_input():
    projection = AgentConversationProjection(start_run=lambda *_: None, cancel_run=lambda *_: None)
    bridge = AgentConversationWebViewBridge(projection)
    secret = "S" * (MAX_AGENT_PROMPT_CHARS + 1)
    result = bridge.dispatch("agent.submit", {"text": secret})
    assert result.kind == "error"
    assert secret not in str(result.payload)
    assert projection.snapshot()["transcript"] == []
    malformed = bridge.dispatch("agent.submit", {"text": "ok", "extra": secret})
    assert malformed.kind == "error"
    assert secret not in str(malformed.payload)
    unsupported = bridge.dispatch("agent.private_debug", {})
    assert unsupported.kind == "error"


def test_start_failure_and_runtime_failure_never_expose_internal_exception_text():
    def fail_start(_run_id, _text):
        raise RuntimeError(r"C:\\Users\\owner\\private-model-token")

    projection = AgentConversationProjection(start_run=fail_start, cancel_run=lambda *_: None, language="en")
    result = projection.submit("Analyze")
    assert result.kind == "error"
    assert "private-model-token" not in str(result.payload)
    assert projection.snapshot()["state"] == "failed"


@dataclass
class Result:
    text: str
    model_calls: int
    tool_calls: int
    steps: int


def test_complete_result_accepts_the_existing_agent_run_result_shape_without_owning_runtime():
    starts = []
    projection = AgentConversationProjection(
        start_run=lambda run_id, text: starts.append((run_id, text)),
        cancel_run=lambda _run_id: None,
    )
    projection.submit("Поясни матеріал")
    result = Result("Матеріал рівний.", 2, 1, 2)
    assert projection.complete_result("agent-ui-1", result)
    snapshot = projection.snapshot()
    assert snapshot["transcript"][-1]["text"] == "Матеріал рівний."
    assert snapshot["state"] == "completed"


def test_language_switch_changes_ui_labels_without_mutating_transcript_text():
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
    assert snapshot["heading"] == "Chess assistant"
    assert snapshot["transcript"][0]["label"] == "You"
    assert snapshot["transcript"][0]["text"] == "e4 чи d4?"
    assert snapshot["transcript"][1]["text"] == "Both are playable."
