"""Strict connect/resume/leave control envelopes for remote lessons."""
from __future__ import annotations

import hashlib
import json

from .remote_connectivity import (
    AuthenticatedPrincipal,
    RemoteConnectionContext,
    RemoteEnvelope,
    RemoteMessageKind,
)


class RemoteControlError(ValueError):
    """Raised when a control exchange cannot be proven canonical."""


def control_request(
    kind: RemoteMessageKind,
    principal: AuthenticatedPrincipal,
    sequence: int,
    snapshot_digest: str,
    *,
    purpose: str,
) -> RemoteEnvelope:
    if kind not in {RemoteMessageKind.RESUME, RemoteMessageKind.LEAVE}:
        raise RemoteControlError("remote control message kind is invalid")
    if purpose not in {"connect", "reconnect", "leave"}:
        raise RemoteControlError("remote control purpose is invalid")
    return RemoteEnvelope(
        1,
        kind,
        operation_id(
            kind.value,
            principal.session_id,
            principal.person_id,
            principal.role.value,
            sequence,
            snapshot_digest,
            purpose,
        ),
        principal.session_id,
        principal.person_id,
        principal.role,
        sequence,
        {"purpose": purpose},
        snapshot_digest,
    )


def acknowledgement_for(request: RemoteEnvelope) -> RemoteEnvelope:
    if not isinstance(request, RemoteEnvelope) or request.kind not in {
        RemoteMessageKind.EVENT,
        RemoteMessageKind.RESUME,
        RemoteMessageKind.LEAVE,
    }:
        raise RemoteControlError("remote message cannot be acknowledged")
    return RemoteEnvelope(
        request.version,
        RemoteMessageKind.ACK,
        operation_id("ack", request.message_id),
        request.session_id,
        request.actor_id,
        request.role,
        request.sequence,
        {"request_id": request.message_id},
        request.checkpoint_digest,
    )


def require_ack(
    request: RemoteEnvelope,
    response: RemoteEnvelope,
    context: RemoteConnectionContext,
) -> None:
    if not isinstance(context, RemoteConnectionContext):
        raise RemoteControlError("remote connection context is invalid")
    principal = context.principal
    if (
        not isinstance(response, RemoteEnvelope)
        or response.kind is not RemoteMessageKind.ACK
        or response.session_id != request.session_id
        or response.actor_id != principal.person_id
        or response.role is not principal.role
        or response.sequence != request.sequence
        or response.checkpoint_digest != request.checkpoint_digest
        or dict(response.payload) != {"request_id": request.message_id}
    ):
        raise RemoteControlError("remote acknowledgement does not match request")


def operation_id(*parts: object) -> str:
    try:
        encoded = json.dumps(
            parts,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
        ).encode("utf-8")
    except (TypeError, ValueError, UnicodeError) as exc:
        raise RemoteControlError("remote operation identity cannot be derived") from exc
    return "remote:" + hashlib.sha256(encoded).hexdigest()
