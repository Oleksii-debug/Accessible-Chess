from __future__ import annotations

"""Strict browser command bridge for classroom media controls."""

from collections.abc import Mapping
import re

from .classroom_media_webview_projection import (
    ClassroomMediaWebViewEvent,
    ClassroomMediaWebViewProjection,
)
from .full_product_ui_shell import concise_user_error


_KEY_RE = re.compile(r"^[0-9a-f]{64}$")


class ClassroomMediaWebViewBridge:
    def __init__(self, projection: ClassroomMediaWebViewProjection) -> None:
        if not isinstance(projection, ClassroomMediaWebViewProjection):
            raise TypeError("projection must be ClassroomMediaWebViewProjection")
        self._projection = projection

    @property
    def projection(self) -> ClassroomMediaWebViewProjection:
        return self._projection

    def _error(self) -> ClassroomMediaWebViewEvent:
        return ClassroomMediaWebViewEvent(
            "error",
            {"message": concise_user_error("", language=self._projection.language)},
        )

    @staticmethod
    def _payload(value: object) -> dict[str, object]:
        if value is None:
            return {}
        if not isinstance(value, Mapping) or len(value) > 3:
            raise ValueError("media browser payload is invalid")
        result: dict[str, object] = {}
        for key, item in value.items():
            if type(key) is not str or not key or len(key) > 40 or "\x00" in key:
                raise ValueError("media browser payload key is invalid")
            if key in result:
                raise ValueError("duplicate media browser payload key")
            result[key] = item
        return result

    @staticmethod
    def _exact(payload: Mapping[str, object], expected: set[str]) -> None:
        if set(payload) != expected:
            raise ValueError("media browser payload fields are invalid")

    @staticmethod
    def _command(value: object) -> str:
        if type(value) is not str or not value or len(value) > 80:
            raise ValueError("media browser command is invalid")
        if value != value.strip():
            raise ValueError("media browser command is invalid")
        return value

    @staticmethod
    def _key(value: object) -> str:
        if type(value) is not str or _KEY_RE.fullmatch(value) is None:
            raise ValueError("media participant key is invalid")
        return value

    @staticmethod
    def _source(value: object) -> str:
        if value not in {"microphone", "camera"}:
            raise ValueError("media source is invalid")
        return str(value)

    @staticmethod
    def _boolean(value: object) -> bool:
        if type(value) is not bool:
            raise TypeError("media browser boolean is invalid")
        return value

    def dispatch(
        self,
        command: object,
        payload: Mapping[str, object] | None = None,
    ) -> ClassroomMediaWebViewEvent:
        try:
            command_id = self._command(command)
            data = self._payload(payload)

            if command_id == "media.snapshot":
                self._exact(data, set())
                return ClassroomMediaWebViewEvent(
                    "render", {"snapshot": self._projection.snapshot()}
                )

            if command_id == "media.local_source":
                self._exact(data, {"source", "enabled"})
                source = self._source(data["source"])
                return self._projection.set_local_source(
                    source,
                    self._boolean(data["enabled"]),
                    focus_target=f"media-own-{source}-toggle",
                )

            if command_id == "media.publish_permission":
                self._exact(data, {"participant_key", "source", "allowed"})
                participant_key = self._key(data["participant_key"])
                source = self._source(data["source"])
                return self._projection.set_publish_permission(
                    participant_key,
                    source,
                    self._boolean(data["allowed"]),
                    focus_target=(
                        f"media-participant-{participant_key}-"
                        f"{'mic' if source == 'microphone' else 'camera'}-permission"
                    ),
                )

            if command_id == "media.soft_mute":
                self._exact(data, {"participant_key", "muted"})
                participant_key = self._key(data["participant_key"])
                return self._projection.set_soft_mute(
                    participant_key,
                    self._boolean(data["muted"]),
                    focus_target=f"media-participant-{participant_key}-soft-mute",
                )

            if command_id == "media.all_publish_permission":
                self._exact(data, {"source", "allowed"})
                source = self._source(data["source"])
                allowed = self._boolean(data["allowed"])
                return self._projection.set_all_students_publish_permission(
                    source,
                    allowed,
                    focus_target=(
                        f"media-all-{'mic' if source == 'microphone' else 'camera'}-"
                        f"{'allow' if allowed else 'lock'}"
                    ),
                )

            if command_id == "media.all_soft_mute":
                self._exact(data, {"muted"})
                muted = self._boolean(data["muted"])
                return self._projection.set_all_students_soft_mute(
                    muted,
                    focus_target=(
                        "media-all-soft-mute"
                        if muted
                        else "media-all-clear-soft-mute"
                    ),
                )

            if command_id == "media.remove":
                self._exact(data, {"participant_key", "block"})
                participant_key = self._key(data["participant_key"])
                block = self._boolean(data["block"])
                return self._projection.remove_participant(
                    participant_key,
                    block,
                    # Remove/block intentionally retires the action buttons.
                    # Return focus to the stable participant row so keyboard/NVDA
                    # users are not dropped to the document after rerender.
                    focus_target=f"media-participant-{participant_key}",
                )

            raise ValueError("unsupported media browser command")
        except Exception:
            return self._error()


__all__ = ["ClassroomMediaWebViewBridge"]
