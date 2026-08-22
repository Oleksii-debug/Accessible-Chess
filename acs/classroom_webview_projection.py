"""WebView-facing Classes/Students/Lessons/Assignments and remote-lesson projection.

This is a DEV1 presentation boundary only. It consumes the existing
``ManagementListPresenter`` and ``RemoteLessonPresenter`` objects and delegates
application commands through the provided dispatcher. It owns no classroom
persistence, consent policy, progress calculation, transport, authentication,
shared chess state, or chess rules.
"""
from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from hashlib import sha256
from typing import Any

from .classroom_presentation import (
    ManagementListPresenter,
    ManagementView,
    RecordKind,
    RemoteLessonPresenter,
    RemoteLessonView,
    RemoteStatus,
)
from .full_product_ui_shell import UILanguage, concise_user_error

CommandDispatch = Callable[[str, Mapping[str, object]], Any]

_MANAGEMENT_ORDER = (
    RecordKind.CLASS,
    RecordKind.STUDENT,
    RecordKind.LESSON,
    RecordKind.ASSIGNMENT,
)

_LABELS = {
    UILanguage.UA: {
        "class": "Класи",
        "student": "Учні",
        "lesson": "Заняття",
        "assignment": "Завдання",
        "empty": "Записів немає.",
        "remote": "Спільне заняття",
        "teacher": "Викладач",
        "student_label": "Учень",
        "connect": "Підключитися",
        "reconnect": "Підключитися знову",
        "leave": "Залишити заняття",
        "lesson_id": "Ідентифікатор заняття",
        "disconnected": "Не підключено",
        "connecting": "Підключення",
        "connected": "Підключено",
        "reconnecting": "Повторне підключення",
        "error": "Помилка підключення",
        "selected": "Вибрано",
    },
    UILanguage.EN: {
        "class": "Classes",
        "student": "Students",
        "lesson": "Lessons",
        "assignment": "Assignments",
        "empty": "No records.",
        "remote": "Shared lesson",
        "teacher": "Teacher",
        "student_label": "Student",
        "connect": "Connect",
        "reconnect": "Reconnect",
        "leave": "Leave lesson",
        "lesson_id": "Lesson identifier",
        "disconnected": "Disconnected",
        "connecting": "Connecting",
        "connected": "Connected",
        "reconnecting": "Reconnecting",
        "error": "Connection error",
        "selected": "Selected",
    },
}


def _bounded_text(value: object, *, limit: int = 240) -> str:
    if value is None:
        return ""
    if not isinstance(value, str):
        raise TypeError("classroom presentation text must be text")
    return value.strip()[:limit]


def _dom_token(prefix: str, stable_id: str) -> str:
    digest = sha256(stable_id.encode("utf-8")).hexdigest()[:16]
    return f"{prefix}-{digest}"


@dataclass(frozen=True, slots=True)
class ClassroomWebViewEvent:
    kind: str
    payload: Mapping[str, object]


class ClassroomWebViewProjection:
    """JSON-ready management and remote-session presentation.

    Management labels are projected as text only; stable backend identifiers are
    kept in action payloads and are not reused as raw DOM ids. Remote session ids,
    transport/auth details, and chess state are never exposed to the browser
    snapshot. Reconnect/leave remain methods on ``RemoteLessonPresenter`` so the
    browser cannot forge those identifiers.
    """

    def __init__(
        self,
        management: Mapping[RecordKind, ManagementListPresenter],
        remote: RemoteLessonPresenter,
        dispatch: CommandDispatch,
        *,
        language: UILanguage = UILanguage.UA,
    ) -> None:
        if not isinstance(management, Mapping):
            raise TypeError("management presenters must be a mapping")
        normalized = dict(management)
        if set(normalized) != set(_MANAGEMENT_ORDER):
            raise ValueError("all four management presenter kinds are required")
        for kind in _MANAGEMENT_ORDER:
            presenter = normalized.get(kind)
            if not isinstance(presenter, ManagementListPresenter):
                raise TypeError("management mapping contains invalid presenter")
            view = presenter.view()
            if view.kind is not kind:
                raise ValueError("management presenter kind does not match mapping key")
        if not isinstance(remote, RemoteLessonPresenter):
            raise TypeError("remote must be RemoteLessonPresenter")
        if not callable(dispatch):
            raise TypeError("classroom dispatcher must be callable")
        if not isinstance(language, UILanguage):
            raise TypeError("language must be UILanguage")
        self._management = normalized
        self._remote = remote
        self._dispatch = dispatch
        self._language = language
        self.set_language(language)

    @property
    def language(self) -> UILanguage:
        return self._language

    def set_language(self, language: UILanguage | str) -> ClassroomWebViewEvent:
        if isinstance(language, str):
            try:
                language = UILanguage(language.strip().lower())
            except ValueError:
                raise ValueError("unsupported UI language") from None
        if not isinstance(language, UILanguage):
            raise TypeError("language must be UILanguage")
        self._language = language
        for presenter in self._management.values():
            presenter.set_language(language)
        self._remote.set_language(language)
        return ClassroomWebViewEvent("render", self.snapshot())

    def _management_snapshot_from_view(self, view: ManagementView) -> dict[str, object]:
        labels = _LABELS[self._language]
        items: list[dict[str, object]] = []
        selected_dom_id = ""
        for record in view.records:
            dom_id = _dom_token(f"management-{view.kind.value}", record.record_id)
            selected = record.record_id == view.selected_id
            if selected:
                selected_dom_id = dom_id
            items.append(
                {
                    "dom_id": dom_id,
                    "record_id": record.record_id,
                    "label": _bounded_text(record.label, limit=160),
                    "secondary": _bounded_text(record.secondary, limit=200),
                    "status": _bounded_text(record.status, limit=120),
                    "selected": selected,
                    "aria_current": "true" if selected else "false",
                }
            )
        return {
            "kind": view.kind.value,
            "heading": labels[view.kind.value],
            "role": "listbox",
            "items": tuple(items),
            "selected_id": view.selected_id or "",
            "focus_target": selected_dom_id,
            "empty_message": labels["empty"] if not items else "",
            "message": _bounded_text(view.message, limit=240),
        }

    def management_snapshot(self, kind: RecordKind | str) -> dict[str, object]:
        parsed = self._parse_kind(kind)
        return self._management_snapshot_from_view(self._management[parsed].view())

    def _remote_snapshot_from_view(self, view: RemoteLessonView) -> dict[str, object]:
        labels = _LABELS[self._language]
        status_text = labels[view.status.value]
        teacher = _bounded_text(view.teacher_label, limit=120)
        student = _bounded_text(view.student_label, limit=120)
        accessible_parts = [status_text]
        if teacher:
            accessible_parts.append(f"{labels['teacher']}: {teacher}")
        if student:
            accessible_parts.append(f"{labels['student_label']}: {student}")
        if view.message:
            accessible_parts.append(_bounded_text(view.message, limit=240))
        return {
            "heading": labels["remote"],
            "status": view.status.value,
            "status_text": status_text,
            "teacher_label": teacher,
            "student_label": student,
            "last_sequence": view.last_sequence,
            "accessible_status": ". ".join(accessible_parts),
            "message": _bounded_text(view.message, limit=240),
            "lesson_input": {
                "id": "remote-lesson-id",
                "label": labels["lesson_id"],
                "editable": True,
            },
            "actions": (
                {
                    "action": "remote.connect",
                    "label": labels["connect"],
                    "enabled": view.can_connect,
                },
                {
                    "action": "remote.reconnect",
                    "label": labels["reconnect"],
                    "enabled": view.can_reconnect,
                },
                {
                    "action": "remote.leave",
                    "label": labels["leave"],
                    "enabled": view.can_leave,
                },
            ),
        }

    def remote_snapshot(self) -> dict[str, object]:
        # Remote presenter performs one provider read for this browser projection.
        return self._remote_snapshot_from_view(self._remote.view())

    def snapshot(self) -> dict[str, object]:
        return {
            "document": {
                "lang": self._language.value,
                "landmark": "main",
                "heading": _LABELS[self._language]["class"],
            },
            "management": tuple(
                self._management_snapshot_from_view(self._management[kind].view())
                for kind in _MANAGEMENT_ORDER
            ),
            "remote": self.remote_snapshot(),
        }

    @staticmethod
    def _parse_kind(kind: RecordKind | str) -> RecordKind:
        if isinstance(kind, RecordKind):
            return kind
        if not isinstance(kind, str):
            raise TypeError("management kind must be text or RecordKind")
        try:
            return RecordKind(kind.strip().lower())
        except ValueError:
            raise ValueError("unsupported management kind") from None

    def _safe_error(self, exc: Exception) -> ClassroomWebViewEvent:
        return ClassroomWebViewEvent(
            "error",
            {"message": concise_user_error(exc, language=self._language)},
        )

    def select(self, kind: RecordKind | str, record_id: str) -> ClassroomWebViewEvent:
        try:
            parsed = self._parse_kind(kind)
            view = self._management[parsed].select(record_id)
            snapshot = self._management_snapshot_from_view(view)
        except Exception as exc:
            return self._safe_error(exc)
        return ClassroomWebViewEvent(
            "selection",
            {
                "kind": parsed.value,
                "focus_target": snapshot["focus_target"],
                "snapshot": snapshot,
                "announcement": _LABELS[self._language]["selected"],
            },
        )

    def move_selection(self, kind: RecordKind | str, delta: int) -> ClassroomWebViewEvent:
        try:
            parsed = self._parse_kind(kind)
            view = self._management[parsed].move_selection(delta)
            snapshot = self._management_snapshot_from_view(view)
        except Exception as exc:
            return self._safe_error(exc)
        return ClassroomWebViewEvent(
            "selection",
            {
                "kind": parsed.value,
                "focus_target": snapshot["focus_target"],
                "snapshot": snapshot,
                # Keyboard navigation changes focus; do not duplicate every row in
                # a second live-region announcement. NVDA will read the focused row.
                "announcement": "",
            },
        )

    def open_selected(self, kind: RecordKind | str) -> ClassroomWebViewEvent:
        try:
            parsed = self._parse_kind(kind)
            value = self._management[parsed].open_selected(self._dispatch)
        except Exception as exc:
            return self._safe_error(exc)
        return ClassroomWebViewEvent(
            "delegated",
            {"kind": parsed.value, "value": value},
        )

    def new_class(self) -> ClassroomWebViewEvent:
        try:
            value = self._dispatch("classes.new", {})
        except Exception as exc:
            return self._safe_error(exc)
        return ClassroomWebViewEvent("delegated", {"action": "classes.new", "value": value})

    def connect(self, lesson_id: str) -> ClassroomWebViewEvent:
        try:
            value = self._remote.connect(lesson_id=lesson_id)
        except Exception as exc:
            return self._safe_error(exc)
        return ClassroomWebViewEvent("remote-action", {"action": "remote.connect", "value": value})

    def reconnect(self) -> ClassroomWebViewEvent:
        try:
            value = self._remote.reconnect()
        except Exception as exc:
            return self._safe_error(exc)
        return ClassroomWebViewEvent("remote-action", {"action": "remote.reconnect", "value": value})

    def leave(self) -> ClassroomWebViewEvent:
        try:
            value = self._remote.leave()
        except Exception as exc:
            return self._safe_error(exc)
        return ClassroomWebViewEvent("remote-action", {"action": "remote.leave", "value": value})
