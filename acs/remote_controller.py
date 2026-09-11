"""Fail-closed lifecycle for one remote lesson."""
from __future__ import annotations
from enum import Enum

from .remote_connectivity import (
    AuthenticatedPrincipal,
    RemoteEnvelope,
    RemoteMessageKind,
    event_envelope,
)
from .remote_durability import RemoteDurabilityError, RemoteDurablePoint
from .remote_protocol_control import (
    control_request,
    operation_id,
    require_ack,
    require_ack_checkpoint,
)
from .remote_provider import RemoteConnector
from .remote_session import RemoteSessionLog


class RemoteControllerError(RuntimeError):
    pass


class RemoteLifecycleStatus(str, Enum):
    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    RECONNECTING = "reconnecting"
    ERROR = "error"


class RemoteLessonController:
    def __init__(self, principal, log, connector, authorizer, durability) -> None:
        if not isinstance(principal, AuthenticatedPrincipal):
            raise RemoteControllerError("remote identity is unavailable")
        if not isinstance(log, RemoteSessionLog) or log.state.session_id != principal.session_id:
            raise RemoteControllerError("remote replay authority is unavailable")
        if not isinstance(connector, RemoteConnector):
            raise RemoteControllerError("remote provider is unavailable")
        if not callable(getattr(authorizer, "authorize", None)):
            raise RemoteControllerError("remote membership authority is unavailable")
        if (
            getattr(durability, "session_id", None) != principal.session_id
            or not callable(getattr(durability, "current", None))
            or not callable(getattr(durability, "checkpoint", None))
        ):
            raise RemoteControllerError("remote durability authority is unavailable")
        self.principal = principal
        self.log = log
        self.connector = connector
        self.authorizer = authorizer
        self.durability = durability
        self.provider = None
        self.context = None
        self.status = RemoteLifecycleStatus.DISCONNECTED
        self.accepting_mutations = False

    def presentation_state(self, teacher_label="", student_label="") -> dict[str, object]:
        return {
            "status": self.status.value,
            "session_id": self.principal.session_id,
            "teacher_label": _label(teacher_label),
            "student_label": _label(student_label),
            "last_sequence": self.log.state.last_sequence,
        }

    def connect(self) -> None:
        if self.provider is not None:
            raise RemoteControllerError("remote session is already active")
        if self.log.state.last_sequence != 0:
            raise RemoteControllerError("remote session requires resume")
        try:
            point = self.durability.current()
        except RemoteDurabilityError as exc:
            self._fail("remote durable checkpoint is unavailable", exc)
        if point is not None:
            raise RemoteControllerError(
                "closed remote session cannot be reopened" if point.closed
                else "remote session requires resume"
            )
        self.status = RemoteLifecycleStatus.CONNECTING
        self._open("connect")
        digest = self._digest()
        try:
            point = self.durability.checkpoint(
                self.log,
                operation_id=operation_id("connect", digest),
            )
        except RemoteDurabilityError as exc:
            self._drop()
            self._fail("remote initial checkpoint could not be published", exc)
        if point.last_sequence != 0 or point.snapshot_digest != digest:
            self._drop()
            self._fail("remote initial checkpoint is inconsistent")
        self.status = RemoteLifecycleStatus.CONNECTED
        self.accepting_mutations = True

    def reconnect(self) -> None:
        self._drop()
        self.status = RemoteLifecycleStatus.RECONNECTING
        self.accepting_mutations = False
        try:
            point = self.durability.current()
            if point is None or point.closed:
                raise RemoteControllerError("remote resume point is unavailable")
            self._verify_prefix(point)
        except (RemoteDurabilityError, RemoteControllerError) as exc:
            self._fail("remote resume point is invalid", exc)

        local_sequence = self.log.state.last_sequence
        local_digest = self._digest()
        peer_sequence, peer_digest = self._open(
            "reconnect",
            sequence=point.last_sequence,
            digest=point.snapshot_digest,
            accept_peer_checkpoint=True,
        )
        peer_matches_local = (
            peer_sequence == local_sequence and peer_digest == local_digest
        )
        peer_matches_durable = (
            peer_sequence == point.last_sequence
            and peer_digest == point.snapshot_digest
        )
        if peer_matches_local:
            pass
        elif peer_matches_durable:
            try:
                self._replay_uncheckpointed(point)
            except Exception as exc:
                self._drop()
                self._fail("remote pending event replay failed", exc)
        else:
            self._drop()
            self._fail("remote peer history conflicts with local recovery state")

        if point.last_sequence != local_sequence or point.snapshot_digest != local_digest:
            try:
                point = self.durability.checkpoint(
                    self.log,
                    operation_id=operation_id("resume", local_digest),
                )
            except RemoteDurabilityError as exc:
                self._drop()
                self._fail("remote resumed state could not be published", exc)
        if point.last_sequence != local_sequence or point.snapshot_digest != local_digest:
            self._drop()
            self._fail("remote durable resume point is inconsistent")
        self.status = RemoteLifecycleStatus.CONNECTED
        self.accepting_mutations = True

    def leave(self, closed_at: str) -> None:
        if self.status is not RemoteLifecycleStatus.CONNECTED or self.provider is None:
            raise RemoteControllerError("remote session is not connected")
        self.accepting_mutations = False
        try:
            request = control_request(
                RemoteMessageKind.LEAVE,
                self.principal,
                self.log.state.last_sequence,
                self._digest(),
                purpose="leave",
            )
            require_ack(request, self.provider.exchange(request), self.context)
            point = self.durability.checkpoint(
                self.log,
                operation_id=operation_id("leave", self._digest(), closed_at),
                closed_at=closed_at,
            )
            if not point.closed:
                raise RemoteControllerError("remote durable close is incomplete")
        except Exception as exc:
            self._drop()
            self._fail("remote session could not be closed durably", exc)
        self._drop()
        self.status = RemoteLifecycleStatus.DISCONNECTED

    def mark_uncertain(self) -> None:
        self._drop()
        self.status = RemoteLifecycleStatus.ERROR
        self.accepting_mutations = False

    def _open(
        self,
        purpose: str,
        *,
        sequence: int | None = None,
        digest: str | None = None,
        accept_peer_checkpoint: bool = False,
    ) -> tuple[int, str]:
        connected = None
        try:
            connected = self.connector.connect(self.principal)
            if self.authorizer.authorize(self.principal) is not True:
                raise RemoteControllerError("remote participant is not authorized")
            request_sequence = (
                self.log.state.last_sequence if sequence is None else sequence
            )
            request_digest = self._digest() if digest is None else digest
            request = control_request(
                RemoteMessageKind.RESUME,
                self.principal,
                request_sequence,
                request_digest,
                purpose=purpose,
            )
            response = connected.provider.exchange(request)
            if accept_peer_checkpoint:
                peer_checkpoint = require_ack_checkpoint(
                    request, response, connected.context
                )
            else:
                require_ack(request, response, connected.context)
                peer_checkpoint = request_sequence, request_digest
        except Exception as exc:
            if connected is not None:
                try:
                    connected.provider.close()
                except Exception:
                    pass
            self._fail("remote connection could not be established", exc)
        self.provider = connected.provider
        self.context = connected.context
        return peer_checkpoint

    def _replay_uncheckpointed(self, point: RemoteDurablePoint) -> None:
        if self.provider is None or self.context is None:
            raise RemoteControllerError("remote recovery provider is unavailable")
        prefix = RemoteSessionLog(self.principal.session_id)
        prefix.extend(self.log.events[: point.last_sequence])
        if prefix.to_snapshot()["digest"] != point.snapshot_digest:
            raise RemoteControllerError("remote durable prefix changed during recovery")
        for event in self.log.events[point.last_sequence :]:
            prefix.append(event)
            digest = prefix.to_snapshot()["digest"]
            base = event_envelope(event, self.principal)
            request = RemoteEnvelope(
                base.version,
                base.kind,
                base.message_id,
                base.session_id,
                base.actor_id,
                base.role,
                base.sequence,
                base.payload,
                digest,
            )
            require_ack(request, self.provider.exchange(request), self.context)
        if (
            prefix.state.last_sequence != self.log.state.last_sequence
            or prefix.to_snapshot()["digest"] != self._digest()
        ):
            raise RemoteControllerError("remote pending replay does not match local history")

    def _verify_prefix(self, point: RemoteDurablePoint) -> None:
        if point.last_sequence > self.log.state.last_sequence:
            raise RemoteControllerError("local remote history is older than durable checkpoint")
        prefix = RemoteSessionLog(self.principal.session_id)
        prefix.extend(self.log.events[: point.last_sequence])
        if prefix.to_snapshot()["digest"] != point.snapshot_digest:
            raise RemoteControllerError("local remote history diverges from durable checkpoint")

    def _digest(self) -> str:
        return self.log.to_snapshot()["digest"]

    def _drop(self) -> None:
        provider, self.provider, self.context = self.provider, None, None
        if provider is not None:
            try:
                provider.close()
            except Exception:
                pass

    def _fail(self, message: str, cause=None) -> None:
        self.status = RemoteLifecycleStatus.ERROR
        self.accepting_mutations = False
        raise RemoteControllerError(message) from cause


def _label(value: object) -> str:
    if type(value) is not str:
        raise RemoteControllerError("remote presentation label is invalid")
    return value.strip()[:120]
