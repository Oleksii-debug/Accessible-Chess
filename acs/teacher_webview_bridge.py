from __future__ import annotations

"""Strict browser bridge for the Teacher visual overlay.

Pointer, hover and selection are presentation events only.  This bridge offers
no move command and accepts no FEN, position, permission identity or session
identity from browser content.
"""

from collections.abc import Mapping

from .full_product_ui_shell import UILanguage, concise_user_error
from .teacher_webview_projection import TeacherWebViewEvent, TeacherWebViewProjection


class TeacherWebViewBridge:
    def __init__(
        self,
        projection: TeacherWebViewProjection,
        *,
        language: UILanguage = UILanguage.UA,
    ) -> None:
        if not isinstance(projection, TeacherWebViewProjection):
            raise TypeError("projection must be TeacherWebViewProjection")
        if not isinstance(language, UILanguage):
            raise TypeError("language must be UILanguage")
        self._projection = projection
        self._language = language

    @property
    def projection(self) -> TeacherWebViewProjection:
        return self._projection

    @staticmethod
    def _payload(value: object) -> dict[str, object]:
        if not isinstance(value, Mapping):
            raise TypeError("teacher browser payload must be a mapping")
        if len(value) > 4:
            raise ValueError("teacher browser payload has too many fields")
        result: dict[str, object] = {}
        for key, item in value.items():
            if type(key) is not str:
                raise TypeError("teacher browser payload keys must be text")
            if not key or len(key) > 40 or "\x00" in key:
                raise ValueError("invalid teacher browser payload key")
            result[key] = item
        return result

    @staticmethod
    def _exact(payload: Mapping[str, object], allowed: set[str]) -> None:
        if set(payload) != allowed:
            raise ValueError("teacher browser payload fields are invalid")

    @staticmethod
    def _text(value: object, *, name: str, limit: int) -> str:
        if type(value) is not str:
            raise TypeError(f"teacher {name} must be text")
        token = value.strip()
        if not token or len(token) > limit or "\x00" in token:
            raise ValueError(f"teacher {name} is invalid")
        return token

    def _error(self) -> TeacherWebViewEvent:
        return TeacherWebViewEvent(
            "error",
            {"message": concise_user_error("", language=self._language)},
        )

    def dispatch(
        self,
        command: object,
        payload: object | None = None,
    ) -> TeacherWebViewEvent:
        try:
            command_id = self._text(command, name="command", limit=80)
            data = self._payload({} if payload is None else payload)
            if command_id == "teacher.snapshot":
                self._exact(data, set())
                return TeacherWebViewEvent(
                    "render",
                    {
                        "snapshot": self._projection.snapshot(language=self._language.value),
                        "focus_target": "",
                    },
                )
            if command_id == "teacher.pointer_input":
                self._exact(data, {"coordinate"})
                coordinate = self._text(data["coordinate"], name="coordinate", limit=8)
                event = self._projection.type_pointer_text(coordinate)
                return TeacherWebViewEvent(
                    "render-pointer",
                    {
                        "snapshot": self._projection.snapshot(language=self._language.value),
                        "square": event.payload["square"],
                        "clear_editor": True,
                        "focus_target": "teacher-pointer-input",
                        "announcement": "",
                    },
                )
            if command_id == "teacher.orientation.toggle":
                self._exact(data, set())
                event = self._projection.toggle_orientation()
                return TeacherWebViewEvent(
                    "render-visual",
                    {
                        "orientation": event.payload["orientation"],
                        "snapshot": self._projection.snapshot(language=self._language.value),
                        "focus_target": "teacher-orientation-toggle",
                        "announcement": "",
                    },
                )
            if command_id == "teacher.student_event":
                self._exact(data, {"kind", "square", "piece_name"})
                kind = self._text(data["kind"], name="event kind", limit=16)
                square = self._text(data["square"], name="event square", limit=16)
                piece_name = data["piece_name"]
                if type(piece_name) is not str or len(piece_name) > 80 or "\x00" in piece_name:
                    raise ValueError("teacher piece name is invalid")
                return self._projection.record_student_event(
                    kind,
                    square,
                    piece_name=piece_name.strip(),
                    language=self._language.value,
                )
            raise ValueError("unsupported teacher browser command")
        except Exception:
            return self._error()
