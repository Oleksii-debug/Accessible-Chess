"""Accessible Classes/Students/Assignments and remote-lesson presentation adapters.

This module owns no classroom persistence, authentication, transport, chess state,
or progress calculation. It consumes neutral backend snapshots and emits stable
application actions, while keeping keyboard selection and concise NVDA projection
inside the Windows/WebView2 presentation boundary.
"""
from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from enum import Enum
from typing import Any

from .full_product_ui_shell import UILanguage, concise_user_error

CommandDispatch = Callable[[str, Mapping[str, object]], Any]


def _generic_action_failure(language: UILanguage) -> str:
    return (
        "Не вдалося виконати дію."
        if language is UILanguage.UA
        else "The action could not be completed."
    )


class RecordKind(str, Enum):
    CLASS = "class"
    STUDENT = "student"
    LESSON = "lesson"
    ASSIGNMENT = "assignment"


class RemoteStatus(str, Enum):
    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    RECONNECTING = "reconnecting"
    ERROR = "error"


@dataclass(frozen=True, slots=True)
class ManagementRecord:
    record_id: str
    kind: RecordKind
    label: str
    secondary: str = ""
    status: str = ""

    def __post_init__(self) -> None:
        record_id = self.record_id.strip()
        label = self.label.strip()
        if not record_id or not label:
            raise ValueError("management record requires stable id and label")
        if not isinstance(self.kind, RecordKind):
            raise TypeError("management record kind must be RecordKind")
        object.__setattr__(self, "record_id", record_id)
        object.__setattr__(self, "label", label)
        object.__setattr__(self, "secondary", self.secondary.strip())
        object.__setattr__(self, "status", self.status.strip())


@dataclass(frozen=True, slots=True)
class ManagementView:
    kind: RecordKind
    records: tuple[ManagementRecord, ...]
    selected_id: str | None
    message: str = ""


_OPEN_ACTIONS = {
    RecordKind.CLASS: "classes.open",
    RecordKind.STUDENT: "classes.student_open",
    RecordKind.LESSON: "classes.lesson_open",
    RecordKind.ASSIGNMENT: "classes.assignment_open",
}


class ManagementListPresenter:
    """Keyboard-stable presentation over externally owned management records."""

    def __init__(
        self,
        kind: RecordKind,
        *,
        language: UILanguage = UILanguage.UA,
    ) -> None:
        if not isinstance(kind, RecordKind):
            raise TypeError("management list kind must be RecordKind")
        self._kind = kind
        self._language = language
        self._records: tuple[ManagementRecord, ...] = ()
        self._selected_id: str | None = None
        self._message = ""

    @property
    def selected_id(self) -> str | None:
        return self._selected_id

    def set_language(self, language: UILanguage) -> None:
        if not isinstance(language, UILanguage):
            raise TypeError("language must be UILanguage")
        self._language = language

    def replace(self, records: Iterable[ManagementRecord]) -> ManagementView:
        normalized = tuple(records)
        if any(item.kind is not self._kind for item in normalized):
            raise ValueError("management list contains wrong record kind")
        ids = [item.record_id for item in normalized]
        if len(ids) != len(set(ids)):
            raise ValueError("management list requires unique stable record ids")
        self._records = normalized
        if self._selected_id not in set(ids):
            self._selected_id = ids[0] if ids else None
        self._message = ""
        return self.view()

    def select(self, record_id: str) -> ManagementView:
        if record_id not in {item.record_id for item in self._records}:
            raise LookupError("management record is not present")
        self._selected_id = record_id
        return self.view()

    def move_selection(self, delta: int) -> ManagementView:
        if type(delta) is not int or delta not in {-1, 1}:
            raise ValueError("selection delta must be -1 or 1")
        if not self._records:
            raise LookupError("management list is empty")
        index = next(
            (i for i, item in enumerate(self._records) if item.record_id == self._selected_id),
            0,
        )
        target = index + delta
        if not 0 <= target < len(self._records):
            raise LookupError("management list boundary")
        self._selected_id = self._records[target].record_id
        return self.view()

    def selected(self) -> ManagementRecord | None:
        if self._selected_id is None:
            return None
        return next(
            (item for item in self._records if item.record_id == self._selected_id),
            None,
        )

    def open_selected(self, dispatch: CommandDispatch) -> Any:
        record = self.selected()
        if record is None:
            raise LookupError("no management record is selected")
        if not callable(dispatch):
            raise TypeError("management dispatcher must be callable")
        return dispatch(
            _OPEN_ACTIONS[self._kind],
            {"record_id": record.record_id},
        )

    def set_error(self, error: object) -> ManagementView:
        self._message = concise_user_error(error, language=self._language)
        return self.view()

    def view(self) -> ManagementView:
        return ManagementView(
            kind=self._kind,
            records=self._records,
            selected_id=self._selected_id,
            message=self._message,
        )


@dataclass(frozen=True, slots=True)
class RemoteLessonView:
    status: RemoteStatus
    session_id: str | None
    teacher_label: str
    student_label: str
    last_sequence: int | None
    can_connect: bool
    can_reconnect: bool
    can_leave: bool
    message: str = ""


class RemoteLessonPresenter:
    """Presentation-only remote lesson status and recovery actions."""

    _FORBIDDEN_KEYS = frozenset(
        {
            "token",
            "access_token",
            "refresh_token",
            "password",
            "secret",
            "authorization",
            "cookie",
            "fen",
            "position",
        }
    )

    def __init__(
        self,
        state_provider: Callable[[], Mapping[str, object]],
        dispatch: CommandDispatch,
        *,
        language: UILanguage = UILanguage.UA,
    ) -> None:
        if not callable(state_provider):
            raise TypeError("remote state provider must be callable")
        if not callable(dispatch):
            raise TypeError("remote dispatcher must be callable")
        self._state_provider = state_provider
        self._dispatch = dispatch
        self._language = language
        self._message = ""

    def set_language(self, language: UILanguage) -> None:
        if not isinstance(language, UILanguage):
            raise TypeError("language must be UILanguage")
        self._language = language

    def _snapshot(self) -> dict[str, object]:
        raw = self._state_provider()
        if not isinstance(raw, Mapping):
            raise TypeError("remote lesson state must be a mapping")
        state = dict(raw)
        forbidden = self._FORBIDDEN_KEYS.intersection(key.casefold() for key in state)
        if forbidden:
            raise ValueError("remote lesson presentation received secret or chess state")
        return state

    @staticmethod
    def _optional_text(value: object) -> str:
        if value is None:
            return ""
        if not isinstance(value, str):
            raise TypeError("remote presentation labels must be text")
        return value.strip()[:120]

    def view(self) -> RemoteLessonView:
        try:
            state = self._snapshot()
            status = RemoteStatus(state.get("status", RemoteStatus.DISCONNECTED.value))
            session_id_value = state.get("session_id")
            session_id = None if session_id_value is None else self._optional_text(session_id_value)
            if session_id == "":
                session_id = None
            sequence = state.get("last_sequence")
            if sequence is not None and (type(sequence) is not int or sequence < 0):
                raise ValueError("remote sequence must be a non-negative integer")
            teacher = self._optional_text(state.get("teacher_label"))
            student = self._optional_text(state.get("student_label"))
        except Exception:
            # Provider/schema failures are internal boundary failures. Never
            # project validation wording, secret-field names, transport details,
            # or local paths into normal NVDA speech.
            return RemoteLessonView(
                status=RemoteStatus.ERROR,
                session_id=None,
                teacher_label="",
                student_label="",
                last_sequence=None,
                can_connect=True,
                can_reconnect=False,
                can_leave=False,
                message=_generic_action_failure(self._language),
            )
        return RemoteLessonView(
            status=status,
            session_id=session_id,
            teacher_label=teacher,
            student_label=student,
            last_sequence=sequence,
            can_connect=status in {RemoteStatus.DISCONNECTED, RemoteStatus.ERROR},
            can_reconnect=status is RemoteStatus.ERROR and session_id is not None,
            can_leave=status in {
                RemoteStatus.CONNECTING,
                RemoteStatus.CONNECTED,
                RemoteStatus.RECONNECTING,
            },
            message=self._message,
        )

    def connect(self, *, lesson_id: str) -> Any:
        lesson = lesson_id.strip()
        if not lesson:
            raise ValueError("lesson id is required")
        self._message = ""
        return self._dispatch("remote.connect", {"lesson_id": lesson})

    def reconnect(self) -> Any:
        view = self.view()
        if not view.can_reconnect or view.session_id is None:
            raise RuntimeError("remote lesson cannot reconnect from current state")
        self._message = ""
        return self._dispatch("remote.reconnect", {"session_id": view.session_id})

    def leave(self) -> Any:
        view = self.view()
        if not view.can_leave or view.session_id is None:
            raise RuntimeError("remote lesson is not active")
        self._message = ""
        return self._dispatch("remote.leave", {"session_id": view.session_id})

    def project_failure(self, error: object) -> RemoteLessonView:
        self._message = concise_user_error(error, language=self._language)
        state = self.view()
        return RemoteLessonView(
            status=RemoteStatus.ERROR,
            session_id=state.session_id,
            teacher_label=state.teacher_label,
            student_label=state.student_label,
            last_sequence=state.last_sequence,
            can_connect=True,
            can_reconnect=state.session_id is not None,
            can_leave=False,
            message=self._message,
        )
