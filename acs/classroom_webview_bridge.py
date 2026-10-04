"""Strict browser-command bridge for the classroom/remote WebView surface.

The JavaScript asset talks only to this presentation entrypoint. The bridge maps
small UI command ids to :class:`ClassroomWebViewProjection` methods; it never
routes arbitrary application/chess commands and never returns raw backend data.
"""
from __future__ import annotations

from collections.abc import Mapping

from .classroom_webview_projection import (
    ClassroomWebViewEvent,
    ClassroomWebViewProjection,
)
from .full_product_ui_shell import concise_user_error


class ClassroomWebViewBridge:
    def __init__(self, projection: ClassroomWebViewProjection) -> None:
        if not isinstance(projection, ClassroomWebViewProjection):
            raise TypeError("projection must be ClassroomWebViewProjection")
        self._projection = projection

    @property
    def projection(self) -> ClassroomWebViewProjection:
        return self._projection

    def _generic_error(self) -> ClassroomWebViewEvent:
        return ClassroomWebViewEvent(
            "error",
            {
                "message": concise_user_error(
                    "",
                    language=self._projection.language,
                )
            },
        )

    @staticmethod
    def _payload(value: object) -> dict[str, object]:
        if value is None:
            return {}
        if not isinstance(value, Mapping):
            raise TypeError("browser command payload must be a mapping")
        if len(value) > 8:
            raise ValueError("browser command payload has too many fields")
        normalized: dict[str, object] = {}
        for key, item in value.items():
            if not isinstance(key, str) or not key.strip():
                raise TypeError("browser command payload keys must be text")
            token = key.strip()
            if len(token) > 64 or token in normalized:
                raise ValueError("invalid browser command payload key")
            normalized[token] = item
        return normalized

    @staticmethod
    def _exact_fields(payload: Mapping[str, object], allowed: set[str]) -> None:
        if set(payload) != allowed:
            raise ValueError("browser command payload fields are invalid")

    @staticmethod
    def _identifier(value: object, *, name: str, limit: int = 512) -> str:
        if not isinstance(value, str):
            raise TypeError(f"{name} must be text")
        token = value.strip()
        if not token or len(token) > limit:
            raise ValueError(f"{name} is invalid")
        return token

    def dispatch(
        self,
        command: object,
        payload: Mapping[str, object] | None = None,
    ) -> ClassroomWebViewEvent:
        try:
            if not isinstance(command, str):
                raise TypeError("browser command must be text")
            command_id = command.strip()
            if not command_id or len(command_id) > 64:
                raise ValueError("browser command is invalid")
            data = self._payload(payload)

            if command_id == "management.select":
                self._exact_fields(data, {"kind", "record_id"})
                return self._projection.select(
                    self._identifier(data["kind"], name="management kind", limit=32),
                    self._identifier(data["record_id"], name="record id"),
                )
            if command_id == "management.move":
                self._exact_fields(data, {"kind", "delta"})
                delta = data["delta"]
                if type(delta) is not int or delta not in {-1, 1}:
                    raise ValueError("selection delta must be -1 or 1")
                return self._projection.move_selection(
                    self._identifier(data["kind"], name="management kind", limit=32),
                    delta,
                )
            if command_id == "management.open":
                self._exact_fields(data, {"kind"})
                return self._projection.open_selected(
                    self._identifier(data["kind"], name="management kind", limit=32)
                )
            if command_id == "classes.new":
                self._exact_fields(data, set())
                return self._projection.new_class()
            if command_id == "remote.connect":
                self._exact_fields(data, {"lesson_id"})
                return self._projection.connect(
                    self._identifier(data["lesson_id"], name="lesson id", limit=256)
                )
            if command_id == "remote.reconnect":
                self._exact_fields(data, set())
                return self._projection.reconnect()
            if command_id == "remote.leave":
                self._exact_fields(data, set())
                return self._projection.leave()
            raise ValueError("unsupported classroom browser command")
        except Exception:
            # Browser command validation is an internal seam. Never echo command
            # text, identifiers, local paths, transport data, or validation detail.
            return self._generic_error()
