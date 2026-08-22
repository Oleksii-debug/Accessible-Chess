"""Strict browser-command boundary for the DEV1 Training WebView surface."""
from __future__ import annotations

from collections.abc import Mapping

from .full_product_ui_shell import concise_user_error
from .training_webview_projection import TrainingWebViewEvent, TrainingWebViewProjection


class TrainingWebViewBridge:
    def __init__(self, projection: TrainingWebViewProjection) -> None:
        if not isinstance(projection, TrainingWebViewProjection):
            raise TypeError("projection must be TrainingWebViewProjection")
        self._projection = projection

    @property
    def projection(self) -> TrainingWebViewProjection:
        return self._projection

    def _error(self) -> TrainingWebViewEvent:
        return TrainingWebViewEvent(
            "error",
            {"message": concise_user_error("", language=self._projection.language)},
        )

    @staticmethod
    def _payload(value: object) -> dict[str, object]:
        if value is None:
            return {}
        if not isinstance(value, Mapping) or len(value) > 1:
            raise ValueError("invalid training browser payload")
        result: dict[str, object] = {}
        for key, item in value.items():
            if not isinstance(key, str) or not key.strip() or len(key.strip()) > 64:
                raise ValueError("invalid training browser payload key")
            token = key.strip()
            if token in result:
                raise ValueError("duplicate training browser payload key")
            result[token] = item
        return result

    @staticmethod
    def _exact(data: Mapping[str, object], fields: set[str]) -> None:
        if set(data) != fields:
            raise ValueError("invalid training browser payload fields")

    @staticmethod
    def _answer(value: object) -> str:
        if not isinstance(value, str):
            raise ValueError("training answer must be text")
        if "\x00" in value or len(value) > 256:
            raise ValueError("invalid training answer")
        answer = " ".join(value.strip().split())
        if not answer:
            raise ValueError("training answer must not be empty")
        return answer

    def dispatch(
        self,
        command: object,
        payload: Mapping[str, object] | None = None,
    ) -> TrainingWebViewEvent:
        try:
            if not isinstance(command, str) or not command.strip() or len(command.strip()) > 64:
                raise ValueError("invalid training browser command")
            command_id = command.strip()
            data = self._payload(payload)
            if command_id == "training.submit":
                self._exact(data, {"answer"})
                answer = self._answer(data["answer"])
                return self._projection.safe_call(lambda: self._projection.submit(answer))
            no_payload = {
                "training.hint": self._projection.hint,
                "training.reveal": self._projection.reveal,
                "training.retry": self._projection.retry,
                "training.reset": self._projection.reset,
            }
            if command_id in no_payload:
                self._exact(data, set())
                return self._projection.safe_call(no_payload[command_id])
            if command_id == "training.language":
                self._exact(data, {"language"})
                language = data["language"]
                if not isinstance(language, str) or len(language) > 8:
                    raise ValueError("invalid language")
                return self._projection.safe_call(lambda: self._projection.set_language(language))
            raise ValueError("unsupported training browser command")
        except Exception:
            # Never reflect submitted answer text, accepted moves, source identity,
            # FEN, or arbitrary service exception details into browser/NVDA errors.
            return self._error()
