"""Canonical event publication over an active remote lesson controller."""
from __future__ import annotations

from .remote_connectivity import RemoteEnvelope, event_envelope
from .remote_controller import (
    RemoteControllerError,
    RemoteLessonController,
    RemoteLifecycleStatus,
)
from .remote_protocol_control import operation_id, require_ack
from .remote_session import RemoteSessionEvent


class RemoteEventDeliveryError(RuntimeError):
    """Delivery is unproven; caller must use explicit resume/recovery."""


class RemoteEventDelivery:
    def __init__(self, controller: RemoteLessonController) -> None:
        if not isinstance(controller, RemoteLessonController):
            raise RemoteEventDeliveryError("remote lesson controller is unavailable")
        self._controller = controller

    def publish(self, event: RemoteSessionEvent) -> None:
        controller = self._controller
        if (
            controller.status is not RemoteLifecycleStatus.CONNECTED
            or not controller.accepting_mutations
            or controller.provider is None
            or controller.context is None
        ):
            raise RemoteEventDeliveryError("remote session is not accepting changes")
        if not isinstance(event, RemoteSessionEvent):
            raise RemoteEventDeliveryError("remote event is invalid")
        principal = controller.principal
        if event.session_id != principal.session_id or event.actor_id != principal.person_id:
            raise RemoteEventDeliveryError("remote event identity is not authorized")

        try:
            if controller.authorizer.authorize(principal) is not True:
                raise RemoteEventDeliveryError("remote participant is not authorized")
            known = {item.event_id for item in controller.log.events}
            if event.event_id in known:
                if not controller.log.events or controller.log.events[-1].event_id != event.event_id:
                    raise RemoteEventDeliveryError("only the latest exact event can be retried")
            else:
                controller.log.append(event)
            digest = controller.log.to_snapshot()["digest"]
            base = event_envelope(event, principal)
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
            response = controller.provider.exchange(request)
            require_ack(request, response, controller.context)
            point = controller.durability.checkpoint(
                controller.log,
                operation_id=operation_id(event.event_id, digest),
            )
            if point.last_sequence != event.sequence or point.snapshot_digest != digest:
                raise RemoteEventDeliveryError("remote event checkpoint is inconsistent")
        except Exception as exc:
            controller.mark_uncertain()
            if isinstance(exc, RemoteEventDeliveryError):
                raise
            raise RemoteEventDeliveryError(
                "remote event delivery is uncertain; resume is required"
            ) from exc
