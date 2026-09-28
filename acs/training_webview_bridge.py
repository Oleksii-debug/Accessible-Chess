"""Strict browser-command bridge for the accessible Training WebView surface."""
from __future__ import annotations

from collections.abc import Callable, Mapping

from .training_webview_projection import TrainingWebViewEvent, TrainingWebViewProjection


class TrainingWebViewBridge:
    def __init__(
        self,
        projection: TrainingWebViewProjection,
        *,
        continue_callback: Callable[[], TrainingWebViewEvent] | None = None,
    ) -> None:
        if not isinstance(projection, TrainingWebViewProjection):
            raise TypeError("projection must be TrainingWebViewProjection")
        if continue_callback is not None and not callable(continue_callback):
            raise TypeError("continue_callback must be callable or None")
        self._projection = projection
        self._continue_callback = continue_callback

    @property
    def projection(self) -> TrainingWebViewProjection:
        return self._projection

    @staticmethod
    def _payload(value: object) -> dict[str, object]:
        if value is None:
            return {}
        if not isinstance(value, Mapping):
            raise TypeError("training browser payload must be a mapping")
        if len(value) > 2:
            raise ValueError("training browser payload has too many fields")
        out: dict[str, object] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise TypeError("training browser payload keys must be text")
            token = key.strip()
            if not token or len(token) > 64 or token in out:
                raise ValueError("invalid training browser payload key")
            out[token] = item
        return out

    @staticmethod
    def _exact(payload: Mapping[str, object], allowed: set[str]) -> None:
        if set(payload) != allowed:
            raise ValueError("training browser payload fields are invalid")

    def dispatch(
        self,
        command: object,
        payload: Mapping[str, object] | None = None,
    ) -> TrainingWebViewEvent:
        try:
            if not isinstance(command, str):
                raise TypeError("training browser command must be text")
            command_id = command.strip()
            if not command_id or len(command_id) > 64:
                raise ValueError("invalid training browser command")
            data = self._payload(payload)

            if command_id == "training.submit":
                self._exact(data, {"answer"})
                return self._projection.submit(data["answer"])
            no_payload = {
                "training.hint": self._projection.hint,
                "training.reveal": self._projection.reveal,
                "training.retry": self._projection.retry,
            }
            callback = no_payload.get(command_id)
            if callback is not None:
                self._exact(data, set())
                return callback()
            if command_id == "training.continue":
                self._exact(data, set())
                if self._continue_callback is None:
                    raise ValueError("training continuation is unavailable")
                return self._continue_callback()
            if command_id == "training.reset":
                self._exact(data, {"confirmed"})
                return self._projection.reset(confirmed=data["confirmed"])
            if command_id == "training.language":
                self._exact(data, {"language"})
                return self._projection.set_language(data["language"])
            raise ValueError("unsupported training browser command")
        except Exception:
            # Never echo answers, accepted moves, FEN, source ids or internals.
            return self._projection.generic_error()
