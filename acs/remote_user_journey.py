"""Accessible end-user bridge for one authenticated remote lesson.

This module deliberately owns presentation reachability only. Canonical remote
history stays in RemoteSessionLog, lifecycle/authentication stays in
RemoteLessonController, and durable publication stays in RemoteEventDelivery.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from .remote_controller import (
    RemoteControllerError,
    RemoteLessonController,
    RemoteLifecycleStatus,
)
from .remote_event_delivery import RemoteEventDelivery, RemoteEventDeliveryError
from .remote_session import RemoteSessionEvent


class RemoteUserJourneyError(RuntimeError):
    """Raised when an end-user remote action cannot be completed safely."""


class RemoteUserCommand(str, Enum):
    CONNECT = "connect"
    RECONNECT = "reconnect"
    PUBLISH_EVENT = "publish_event"
    LEAVE = "leave"


@dataclass(frozen=True)
class RemoteUserSnapshot:
    """Secret-free semantic state suitable for UIA, keyboard and screen readers."""

    status: str
    status_text: str
    session_id: str
    teacher_label: str
    student_label: str
    last_sequence: int
    last_activity_text: str
    accepting_mutations: bool
    available_commands: tuple[str, ...]
    notice: str


class RemoteLessonUserJourney:
    """Presentation-neutral command bridge over the canonical remote authorities."""

    def __init__(
        self,
        controller: RemoteLessonController,
        *,
        teacher_label: str = "",
        student_label: str = "",
    ) -> None:
        if not isinstance(controller, RemoteLessonController):
            raise RemoteUserJourneyError("remote lesson controller is unavailable")
        presentation = controller.presentation_state(
            teacher_label=teacher_label,
            student_label=student_label,
        )
        self._controller = controller
        self._delivery = RemoteEventDelivery(controller)
        self._teacher_label = str(presentation["teacher_label"])
        self._student_label = str(presentation["student_label"])
        self._closed = self._durably_closed()
        self._notice = "Remote lesson is ready."

    @property
    def controller(self) -> RemoteLessonController:
        return self._controller

    def snapshot(self) -> RemoteUserSnapshot:
        presentation = self._controller.presentation_state(
            teacher_label=self._teacher_label,
            student_label=self._student_label,
        )
        status = RemoteLifecycleStatus(str(presentation["status"]))
        last_sequence = int(presentation["last_sequence"])
        return RemoteUserSnapshot(
            status=status.value,
            status_text=_status_text(status),
            session_id=str(presentation["session_id"]),
            teacher_label=self._teacher_label,
            student_label=self._student_label,
            last_sequence=last_sequence,
            last_activity_text=self._last_activity_text(),
            accepting_mutations=bool(self._controller.accepting_mutations),
            available_commands=self._available_commands(status, last_sequence),
            notice=self._notice,
        )

    def invoke(
        self,
        command: RemoteUserCommand | str,
        *,
        event: RemoteSessionEvent | None = None,
        closed_at: str | None = None,
    ) -> RemoteUserSnapshot:
        try:
            parsed = RemoteUserCommand(command)
        except (TypeError, ValueError) as exc:
            raise RemoteUserJourneyError("remote command is unsupported") from exc

        if parsed is RemoteUserCommand.CONNECT:
            self._require_no_payload(event, closed_at)
            return self._run(parsed, self._controller.connect)
        if parsed is RemoteUserCommand.RECONNECT:
            self._require_no_payload(event, closed_at)
            return self._run(parsed, self._controller.reconnect)
        if parsed is RemoteUserCommand.PUBLISH_EVENT:
            if not isinstance(event, RemoteSessionEvent) or closed_at is not None:
                raise RemoteUserJourneyError(
                    "remote activity requires one canonical event"
                )
            return self._run(parsed, lambda: self._delivery.publish(event))
        if event is not None or type(closed_at) is not str or not closed_at.strip():
            raise RemoteUserJourneyError("remote leave requires a close timestamp")
        return self._run(parsed, lambda: self._controller.leave(closed_at.strip()))

    def _run(self, command: RemoteUserCommand, action) -> RemoteUserSnapshot:
        try:
            action()
        except (RemoteControllerError, RemoteEventDeliveryError) as exc:
            self._notice = _failure_notice(command)
            raise RemoteUserJourneyError(self._notice) from exc

        if command is RemoteUserCommand.LEAVE:
            self._closed = True
        elif command in (RemoteUserCommand.CONNECT, RemoteUserCommand.RECONNECT):
            self._closed = False
        self._notice = _success_notice(command)
        return self.snapshot()

    def _available_commands(
        self,
        status: RemoteLifecycleStatus,
        last_sequence: int,
    ) -> tuple[str, ...]:
        if self._closed:
            return ()
        if status is RemoteLifecycleStatus.CONNECTED:
            commands = [RemoteUserCommand.LEAVE.value]
            if self._controller.accepting_mutations:
                commands.insert(0, RemoteUserCommand.PUBLISH_EVENT.value)
            return tuple(commands)
        if status in (RemoteLifecycleStatus.CONNECTING, RemoteLifecycleStatus.RECONNECTING):
            return ()
        if self._resume_available(last_sequence):
            return (RemoteUserCommand.RECONNECT.value,)
        return (RemoteUserCommand.CONNECT.value,)

    def _resume_available(self, last_sequence: int) -> bool:
        try:
            point = self._controller.durability.current()
        except Exception:
            return last_sequence > 0
        return bool(point is not None and not point.closed) or last_sequence > 0

    def _durably_closed(self) -> bool:
        try:
            point = self._controller.durability.current()
        except Exception:
            return False
        return bool(point is not None and point.closed)

    def _last_activity_text(self) -> str:
        if not self._controller.log.events:
            return "No remote activity yet."
        event = self._controller.log.events[-1]
        kind = event.kind.value.replace("_", " ")
        return f"{kind}; sequence {event.sequence}."

    @staticmethod
    def _require_no_payload(
        event: RemoteSessionEvent | None,
        closed_at: str | None,
    ) -> None:
        if event is not None or closed_at is not None:
            raise RemoteUserJourneyError("remote command payload is not allowed")


def _status_text(status: RemoteLifecycleStatus) -> str:
    return {
        RemoteLifecycleStatus.DISCONNECTED: "Remote lesson disconnected.",
        RemoteLifecycleStatus.CONNECTING: "Remote lesson connecting.",
        RemoteLifecycleStatus.CONNECTED: "Remote lesson connected.",
        RemoteLifecycleStatus.RECONNECTING: "Remote lesson reconnecting.",
        RemoteLifecycleStatus.ERROR: "Remote lesson needs recovery.",
    }[status]


def _success_notice(command: RemoteUserCommand) -> str:
    return {
        RemoteUserCommand.CONNECT: "Remote lesson connected.",
        RemoteUserCommand.RECONNECT: "Remote lesson resumed.",
        RemoteUserCommand.PUBLISH_EVENT: "Remote activity delivered.",
        RemoteUserCommand.LEAVE: "Remote lesson closed.",
    }[command]


def _failure_notice(command: RemoteUserCommand) -> str:
    return {
        RemoteUserCommand.CONNECT: "Remote connection failed.",
        RemoteUserCommand.RECONNECT: "Remote recovery failed.",
        RemoteUserCommand.PUBLISH_EVENT: (
            "Remote activity delivery is uncertain. Reconnect before continuing."
        ),
        RemoteUserCommand.LEAVE: "Remote lesson could not be closed safely.",
    }[command]
