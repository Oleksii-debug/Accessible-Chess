from __future__ import annotations

"""Strict browser-command boundary for the Universal Chess Agent surface."""

from collections.abc import Mapping

from .agent_webview_projection import AgentConversationEvent, AgentConversationProjection


class AgentConversationWebViewBridge:
    def __init__(self, projection: AgentConversationProjection) -> None:
        if not isinstance(projection, AgentConversationProjection):
            raise TypeError("projection must be AgentConversationProjection")
        self._projection = projection

    @property
    def projection(self) -> AgentConversationProjection:
        return self._projection

    @staticmethod
    def _payload(value: object | None) -> dict[str, object]:
        if value is None:
            return {}
        if not isinstance(value, Mapping):
            raise TypeError("agent browser payload must be a mapping")
        if len(value) > 1:
            raise ValueError("agent browser payload has too many fields")
        result: dict[str, object] = {}
        for key, item in value.items():
            if type(key) is not str or not key or len(key) > 40 or "\x00" in key:
                raise ValueError("agent browser payload key is invalid")
            result[key] = item
        return result

    @staticmethod
    def _command(value: object) -> str:
        if type(value) is not str:
            raise TypeError("agent browser command must be text")
        token = value.strip()
        if not token or len(token) > 80 or "\x00" in token:
            raise ValueError("agent browser command is invalid")
        return token

    @staticmethod
    def _exact(payload: Mapping[str, object], expected: set[str]) -> None:
        if set(payload) != expected:
            raise ValueError("agent browser payload fields are invalid")

    def dispatch(
        self,
        command: object,
        payload: Mapping[str, object] | None = None,
    ) -> AgentConversationEvent:
        try:
            command_id = self._command(command)
            data = self._payload(payload)
            if command_id == "agent.snapshot":
                self._exact(data, set())
                return AgentConversationEvent("render", {"snapshot": self._projection.snapshot()})
            if command_id == "agent.status":
                self._exact(data, set())
                return AgentConversationEvent(
                    "status",
                    {"snapshot": self._projection.status_snapshot()},
                )
            if command_id == "agent.submit":
                self._exact(data, {"text"})
                return self._projection.submit(data["text"])
            if command_id == "agent.cancel":
                self._exact(data, set())
                return self._projection.cancel()
            raise ValueError("unsupported agent browser command")
        except Exception:
            return self._projection.generic_error()


__all__ = ["AgentConversationWebViewBridge"]
