from __future__ import annotations

"""Presentation-only conversation state for the Universal Chess Agent.

The projection never owns chess state, model execution, tool execution, or a
worker scheduler. A trusted host supplies non-blocking start/cancel callbacks
and publishes runtime completion/status back into this object. This preserves
the existing UniversalChessAgentRuntime and canonical application services as
the only execution authorities while giving WebView/NVDA a deterministic,
copyable conversation surface.
"""

from collections import deque
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from threading import RLock


MAX_AGENT_PROMPT_CHARS = 8_000
MAX_AGENT_RESPONSE_CHARS = 32_000
MAX_AGENT_TRANSCRIPT_TURNS = 64


@dataclass(frozen=True, slots=True)
class AgentConversationEvent:
    kind: str
    payload: Mapping[str, object]


@dataclass(frozen=True, slots=True)
class AgentConversationTurn:
    turn_id: str
    role: str
    text: str


_TEXT = {
    "uk": {
        "heading": "Шаховий помічник",
        "description": "Запитуйте про поточну позицію, аналіз, бібліотеку та підключені медіа. Помічник використовує лише канонічні інструменти Accessible Chess.",
        "transcript": "Розмова",
        "empty": "Розмова ще порожня.",
        "input": "Ваш запит",
        "placeholder": "Введіть запит до шахового помічника",
        "send": "Надіслати",
        "stop": "Зупинити",
        "you": "Ви",
        "agent": "Помічник",
        "status": "Стан помічника",
        "idle": "Готовий до запиту.",
        "unavailable": "Шаховий помічник поки не підключений до виконавчого середовища.",
        "running": "Помічник працює над запитом.",
        "cancelling": "Зупинення запиту…",
        "completed": "Відповідь готова.",
        "failed": "Не вдалося завершити запит.",
        "cancelled": "Запит зупинено.",
        "busy": "Дочекайтеся завершення або зупиніть поточний запит.",
        "invalid": "Запит порожній або завеликий.",
        "error": "Не вдалося виконати дію помічника.",
        "provider": "Провайдер",
        "model": "Модель",
        "tool": "Поточний інструмент",
        "steps": "Кроки",
        "model_calls": "Виклики моделі",
        "tool_calls": "Виклики інструментів",
        "none": "немає",
    },
    "en": {
        "heading": "Chess assistant",
        "description": "Ask about the current position, analysis, Library, and attached media. The assistant uses only canonical Accessible Chess tools.",
        "transcript": "Conversation",
        "empty": "The conversation is empty.",
        "input": "Your request",
        "placeholder": "Enter a request for the chess assistant",
        "send": "Send",
        "stop": "Stop",
        "you": "You",
        "agent": "Assistant",
        "status": "Assistant status",
        "idle": "Ready for a request.",
        "unavailable": "The chess assistant is not connected to an execution host yet.",
        "running": "The assistant is working on the request.",
        "cancelling": "Stopping the request…",
        "completed": "The answer is ready.",
        "failed": "The request could not be completed.",
        "cancelled": "The request was stopped.",
        "busy": "Wait for the current request to finish or stop it first.",
        "invalid": "The request is empty or too large.",
        "error": "The assistant action could not be completed.",
        "provider": "Provider",
        "model": "Model",
        "tool": "Current tool",
        "steps": "Steps",
        "model_calls": "Model calls",
        "tool_calls": "Tool calls",
        "none": "none",
    },
}


def _language(value: object) -> str:
    if type(value) is not str:
        raise TypeError("agent conversation language must be text")
    token = value.strip().lower()
    if token not in _TEXT:
        raise ValueError("unsupported agent conversation language")
    return token


def _bounded_text(value: object, *, name: str, limit: int, allow_empty: bool = False) -> str:
    if type(value) is not str:
        raise TypeError(f"{name} must be text")
    text = value.replace("\r\n", "\n").replace("\r", "\n").strip()
    if not allow_empty and not text:
        raise ValueError(f"{name} must not be empty")
    if len(text) > limit:
        raise ValueError(f"{name} exceeds its size bound")
    if "\x00" in text or any(ord(ch) < 32 and ch not in "\n\t" for ch in text):
        raise ValueError(f"{name} contains unsupported control characters")
    return text


def _status_field(value: object, *, limit: int = 160) -> str:
    if value is None:
        return ""
    try:
        text = str(value).strip()
    except Exception:
        return ""
    if not text or len(text) > limit or "\x00" in text:
        return ""
    if any(ord(ch) < 32 for ch in text):
        return ""
    return text


def _non_negative_int(value: object) -> int | None:
    return value if type(value) is int and value >= 0 else None


class AgentConversationProjection:
    """Thread-safe presentation state around a host-owned agent execution loop."""

    def __init__(
        self,
        *,
        start_run: Callable[[str, str], object] | None = None,
        cancel_run: Callable[[str], object] | None = None,
        language: str = "uk",
    ) -> None:
        if start_run is not None and not callable(start_run):
            raise TypeError("start_run must be callable or None")
        if cancel_run is not None and not callable(cancel_run):
            raise TypeError("cancel_run must be callable or None")
        if (start_run is None) != (cancel_run is None):
            raise ValueError("start_run and cancel_run must be bound together")
        self._start_run = start_run
        self._cancel_run = cancel_run
        self._language = _language(language)
        self._lock = RLock()
        self._turns: deque[AgentConversationTurn] = deque(maxlen=MAX_AGENT_TRANSCRIPT_TURNS)
        self._turn_sequence = 0
        self._run_sequence = 0
        self._active_run_id: str | None = None
        self._state = "idle" if start_run is not None else "unavailable"
        self._provider = ""
        self._model = ""
        self._tool = ""
        self._steps = 0
        self._model_calls = 0
        self._tool_calls = 0

    @property
    def available(self) -> bool:
        return self._start_run is not None and self._cancel_run is not None

    @property
    def language(self) -> str:
        with self._lock:
            return self._language

    def set_language(self, language: str) -> None:
        token = _language(language)
        with self._lock:
            self._language = token

    def _labels(self) -> Mapping[str, str]:
        return _TEXT[self._language]

    def _append_turn(self, role: str, text: str) -> None:
        if role not in {"user", "assistant"}:
            raise ValueError("agent conversation role is invalid")
        self._turn_sequence += 1
        self._turns.append(
            AgentConversationTurn(
                turn_id=f"agent-turn-{self._turn_sequence}",
                role=role,
                text=text,
            )
        )

    def _reset_runtime_status(self) -> None:
        self._provider = ""
        self._model = ""
        self._tool = ""
        self._steps = 0
        self._model_calls = 0
        self._tool_calls = 0

    def _status_lines(self, labels: Mapping[str, str]) -> list[str]:
        lines = [labels[self._state]]
        if self._provider:
            lines.append(f"{labels['provider']}: {self._provider}")
        if self._model:
            lines.append(f"{labels['model']}: {self._model}")
        if self._tool:
            lines.append(f"{labels['tool']}: {self._tool}")
        if self._steps:
            lines.append(f"{labels['steps']}: {self._steps}")
        if self._model_calls:
            lines.append(f"{labels['model_calls']}: {self._model_calls}")
        if self._tool_calls:
            lines.append(f"{labels['tool_calls']}: {self._tool_calls}")
        return lines

    def _snapshot_locked(self, *, include_transcript: bool) -> dict[str, object]:
        labels = self._labels()
        active = self._active_run_id is not None
        result: dict[str, object] = {
            "language": self._language,
            "heading": labels["heading"],
            "description": labels["description"],
            "transcript_heading": labels["transcript"],
            "empty_transcript": labels["empty"],
            "input_label": labels["input"],
            "input_placeholder": labels["placeholder"],
            "send_label": labels["send"],
            "stop_label": labels["stop"],
            "status_heading": labels["status"],
            "state": self._state,
            "available": self.available,
            "can_submit": self.available and not active,
            "can_cancel": self.available and active,
            "run_id": self._active_run_id or "",
            "live_status": labels[self._state],
            "status_text": "\n".join(self._status_lines(labels)),
            "focus_target": "agent-stop" if active else "agent-input",
        }
        if include_transcript:
            result["transcript"] = [
                {
                    "id": turn.turn_id,
                    "role": turn.role,
                    "label": labels["you"] if turn.role == "user" else labels["agent"],
                    "text": turn.text,
                }
                for turn in self._turns
            ]
        return result

    def snapshot(self) -> dict[str, object]:
        with self._lock:
            return self._snapshot_locked(include_transcript=True)

    def status_snapshot(self) -> dict[str, object]:
        """Return the lightweight polling view without retransmitting transcript."""

        with self._lock:
            return self._snapshot_locked(include_transcript=False)

    def _event(self, kind: str, *, message: str = "", focus_target: str = "") -> AgentConversationEvent:
        payload: dict[str, object] = {"snapshot": self.snapshot()}
        if message:
            payload["message"] = message
        if focus_target:
            payload["focus_target"] = focus_target
        return AgentConversationEvent(kind, payload)

    def generic_error(self) -> AgentConversationEvent:
        with self._lock:
            message = self._labels()["error"]
        return self._event("error", message=message)

    def submit(self, user_text: object) -> AgentConversationEvent:
        try:
            text = _bounded_text(
                user_text,
                name="agent user request",
                limit=MAX_AGENT_PROMPT_CHARS,
            )
        except Exception:
            with self._lock:
                message = self._labels()["invalid"]
            return self._event("error", message=message, focus_target="agent-input")

        with self._lock:
            labels = self._labels()
            if not self.available:
                return self._event("error", message=labels["unavailable"], focus_target="agent-input")
            if self._active_run_id is not None:
                return self._event("error", message=labels["busy"], focus_target="agent-stop")
            self._run_sequence += 1
            run_id = f"agent-ui-{self._run_sequence}"
            self._active_run_id = run_id
            self._state = "running"
            self._reset_runtime_status()
            self._append_turn("user", text)
            start = self._start_run

        assert start is not None
        try:
            start(run_id, text)
        except Exception:
            self.fail(run_id)
            with self._lock:
                message = self._labels()["error"]
            return self._event("error", message=message, focus_target="agent-input")
        with self._lock:
            focus_target = (
                "agent-stop"
                if self._active_run_id == run_id
                else "agent-input"
            )
        return self._event("accepted", focus_target=focus_target)

    def cancel(self) -> AgentConversationEvent:
        with self._lock:
            labels = self._labels()
            run_id = self._active_run_id
            if not self.available:
                return self._event("error", message=labels["unavailable"], focus_target="agent-input")
            if run_id is None:
                return self._event("error", message=labels["idle"], focus_target="agent-input")
            cancel = self._cancel_run

        assert cancel is not None
        try:
            cancel(run_id)
        except Exception:
            return self.generic_error()
        with self._lock:
            if self._active_run_id == run_id:
                self._state = "cancelling"
                focus_target = "agent-stop"
            else:
                focus_target = "agent-input"
        return self._event("cancel-requested", focus_target=focus_target)

    def update_runtime_status(self, run_id: object, status: Mapping[str, object]) -> bool:
        try:
            token = _bounded_text(run_id, name="agent run id", limit=180)
        except Exception:
            return False
        if not isinstance(status, Mapping):
            return False
        with self._lock:
            if self._active_run_id != token:
                return False
            self._provider = _status_field(status.get("provider_id"))
            self._model = _status_field(status.get("model"))
            self._tool = _status_field(status.get("tool_id"))
            for attr, key in (("_steps", "steps"), ("_model_calls", "model_calls"), ("_tool_calls", "tool_calls")):
                value = _non_negative_int(status.get(key))
                if value is not None:
                    setattr(self, attr, value)
            return True

    def complete(
        self,
        run_id: object,
        response_text: object,
        *,
        model_calls: object = 0,
        tool_calls: object = 0,
        steps: object = 0,
    ) -> bool:
        try:
            token = _bounded_text(run_id, name="agent run id", limit=180)
        except Exception:
            return False
        with self._lock:
            if self._active_run_id != token:
                return False
        try:
            text = _bounded_text(
                response_text,
                name="agent response",
                limit=MAX_AGENT_RESPONSE_CHARS,
            )
        except Exception:
            # A trusted host published an unusable result for the active run.
            # Fail closed and release the UI instead of leaving Stop/Send stuck.
            with self._lock:
                if self._active_run_id == token:
                    self._active_run_id = None
                    self._state = "failed"
                    self._tool = ""
            return False
        with self._lock:
            if self._active_run_id != token:
                return False
            self._model_calls = _non_negative_int(model_calls) or 0
            self._tool_calls = _non_negative_int(tool_calls) or 0
            self._steps = _non_negative_int(steps) or 0
            self._tool = ""
            self._append_turn("assistant", text)
            self._active_run_id = None
            self._state = "completed"
            return True

    def complete_result(self, run_id: object, result: object) -> bool:
        return self.complete(
            run_id,
            getattr(result, "text", None),
            model_calls=getattr(result, "model_calls", 0),
            tool_calls=getattr(result, "tool_calls", 0),
            steps=getattr(result, "steps", 0),
        )

    def fail(self, run_id: object) -> bool:
        try:
            token = _bounded_text(run_id, name="agent run id", limit=180)
        except Exception:
            return False
        with self._lock:
            if self._active_run_id != token:
                return False
            self._active_run_id = None
            self._state = "failed"
            self._tool = ""
            return True

    def mark_cancelled(self, run_id: object) -> bool:
        try:
            token = _bounded_text(run_id, name="agent run id", limit=180)
        except Exception:
            return False
        with self._lock:
            if self._active_run_id != token:
                return False
            self._active_run_id = None
            self._state = "cancelled"
            self._tool = ""
            return True


__all__ = [
    "AgentConversationEvent",
    "AgentConversationProjection",
    "AgentConversationTurn",
    "MAX_AGENT_PROMPT_CHARS",
    "MAX_AGENT_RESPONSE_CHARS",
    "MAX_AGENT_TRANSCRIPT_TURNS",
]
