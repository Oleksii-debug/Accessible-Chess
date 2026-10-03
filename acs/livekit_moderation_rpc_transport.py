from __future__ import annotations

"""LiveKit realtime RPC binding for the canonical classroom moderation service.

The realtime SDK supplies caller identity. The payload remains untrusted and is
passed unchanged to ClassroomModerationRpcService, which owns parsing,
room/actor matching, authorization, replay suppression, and provider effects.
This module only registers the canonical LiveKit RPC method, preserves trusted
room/caller context, maps safe service failures onto the RPC wire, and
unregisters the handler deterministically.
"""

from importlib import metadata
import importlib
import re
import threading
from types import ModuleType
from weakref import WeakKeyDictionary

from .classroom_moderation_rpc import (
    ClassroomModerationRpcError,
    MAX_IDENTIFIER_LENGTH,
    MAX_RPC_PAYLOAD_BYTES,
)


LIVEKIT_RTC_DISTRIBUTION = "livekit"
LIVEKIT_RTC_VERSION = "1.1.19"
MODERATION_RPC_METHOD = "accessible-chess.classroom.moderation.v1"
MODERATION_RPC_ERROR_CODE = 2000
MAX_RPC_ERROR_MESSAGE_BYTES = 256

_IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_REGISTRATION_LOCK = threading.Lock()
_REGISTRATIONS: WeakKeyDictionary[object, set[str]] = WeakKeyDictionary()
_SAFE_CLIENT_SERVICE_MESSAGES = frozenset(
    {
        "moderation actor does not match trusted caller",
        "moderation RPC room identity mismatch",
        "moderation request is not authorized",
    }
)


class LiveKitModerationRpcTransportError(RuntimeError):
    """Sanitized local lifecycle/configuration failure for the RPC binding."""


class LiveKitModerationRpcTransport:
    """Bind one connected trusted participant to the canonical moderation RPC."""

    __slots__ = (
        "_participant",
        "_room_id",
        "_service",
        "_rtc",
        "_handler",
        "_closed",
    )

    def __init__(
        self,
        *,
        participant: object,
        room_id: str,
        service: object,
        rtc_module: ModuleType | object,
        handler: object,
    ) -> None:
        self._participant = participant
        self._room_id = room_id
        self._service = service
        self._rtc = rtc_module
        self._handler = handler
        self._closed = False

    @classmethod
    def bind(
        cls,
        *,
        local_participant: object,
        trusted_room_id: str,
        moderation_participant_identity: str,
        service: object,
        rtc_module: ModuleType | object | None = None,
        sdk_version: str | None = None,
    ) -> "LiveKitModerationRpcTransport":
        room_id = _identifier(trusted_room_id, "trusted room id")
        expected_identity = _identifier(
            moderation_participant_identity,
            "moderation participant identity",
        )
        if service is None or not callable(getattr(service, "handle_rpc", None)):
            raise LiveKitModerationRpcTransportError(
                "moderation RPC service is unavailable"
            )
        if local_participant is None:
            raise LiveKitModerationRpcTransportError(
                "LiveKit local participant is required"
            )
        actual_identity = getattr(local_participant, "identity", None)
        if actual_identity != expected_identity:
            raise LiveKitModerationRpcTransportError(
                "LiveKit moderation participant identity mismatch"
            )
        register = getattr(local_participant, "register_rpc_method", None)
        unregister = getattr(local_participant, "unregister_rpc_method", None)
        if not callable(register) or not callable(unregister):
            raise LiveKitModerationRpcTransportError(
                "LiveKit participant RPC API is unavailable"
            )
        rtc = _load_rtc(rtc_module=rtc_module, sdk_version=sdk_version)

        transport: LiveKitModerationRpcTransport | None = None

        async def handler(invocation: object) -> str:
            if transport is None:
                raise _rpc_error(rtc, "moderation RPC transport is unavailable")
            return await transport._handle_invocation(invocation)

        _reserve_registration(local_participant)
        try:
            register(MODERATION_RPC_METHOD, handler)
            transport = cls(
                participant=local_participant,
                room_id=room_id,
                service=service,
                rtc_module=rtc,
                handler=handler,
            )
            return transport
        except Exception:
            _release_registration(local_participant)
            raise LiveKitModerationRpcTransportError(
                "LiveKit moderation RPC registration failed"
            ) from None

    def __repr__(self) -> str:
        state = "closed" if self._closed else "bound"
        return (
            "LiveKitModerationRpcTransport("
            f"method={MODERATION_RPC_METHOD!r}, state={state!r}, "
            "room=<redacted>, participant=<redacted>)"
        )

    @property
    def closed(self) -> bool:
        return self._closed

    @property
    def method(self) -> str:
        return MODERATION_RPC_METHOD

    async def _handle_invocation(self, invocation: object) -> str:
        if self._closed:
            raise _rpc_error(self._rtc, "moderation RPC transport is unavailable")

        caller = getattr(invocation, "caller_identity", None)
        if (
            type(caller) is not str
            or not caller
            or len(caller) > MAX_IDENTIFIER_LENGTH
            or _IDENTIFIER_RE.fullmatch(caller) is None
        ):
            raise _rpc_error(self._rtc, "moderation caller identity is invalid")

        payload = getattr(invocation, "payload", None)
        if type(payload) is not str:
            raise _rpc_error(self._rtc, "moderation RPC payload must be text")
        try:
            encoded = payload.encode("utf-8")
        except UnicodeEncodeError:
            raise _rpc_error(
                self._rtc,
                "moderation RPC payload is not valid UTF-8 text",
            ) from None
        if not encoded or len(encoded) > MAX_RPC_PAYLOAD_BYTES:
            raise _rpc_error(self._rtc, "moderation RPC payload size is invalid")

        try:
            response = await self._service.handle_rpc(
                trusted_room_id=self._room_id,
                trusted_caller_identity=caller,
                payload=payload,
            )
        except ClassroomModerationRpcError as error:
            raise _rpc_error(self._rtc, _safe_service_message(error)) from None
        except Exception:
            raise _rpc_error(self._rtc, "moderation request failed") from None

        if type(response) is not str:
            raise _rpc_error(self._rtc, "moderation acknowledgement is invalid")
        try:
            response_bytes = response.encode("utf-8")
        except UnicodeEncodeError:
            raise _rpc_error(self._rtc, "moderation acknowledgement is invalid") from None
        if not response_bytes or len(response_bytes) > MAX_RPC_PAYLOAD_BYTES:
            raise _rpc_error(self._rtc, "moderation acknowledgement is invalid")
        return response

    def close(self) -> None:
        if self._closed:
            return
        unregister = getattr(self._participant, "unregister_rpc_method", None)
        if not callable(unregister):
            raise LiveKitModerationRpcTransportError(
                "LiveKit participant RPC API is unavailable"
            )
        try:
            unregister(MODERATION_RPC_METHOD)
        except Exception:
            raise LiveKitModerationRpcTransportError(
                "LiveKit moderation RPC unregister failed"
            ) from None
        self._closed = True
        _release_registration(self._participant)


def _load_rtc(
    *,
    rtc_module: ModuleType | object | None,
    sdk_version: str | None,
) -> object:
    if rtc_module is None:
        try:
            installed = metadata.version(LIVEKIT_RTC_DISTRIBUTION)
        except metadata.PackageNotFoundError:
            raise LiveKitModerationRpcTransportError(
                "Pinned LiveKit realtime SDK is unavailable"
            ) from None
        if installed != LIVEKIT_RTC_VERSION:
            raise LiveKitModerationRpcTransportError(
                "LiveKit realtime SDK version is not approved"
            )
        try:
            rtc_module = importlib.import_module("livekit.rtc")
        except Exception:
            raise LiveKitModerationRpcTransportError(
                "Pinned LiveKit realtime SDK is unavailable"
            ) from None
    elif sdk_version != LIVEKIT_RTC_VERSION:
        raise LiveKitModerationRpcTransportError(
            "LiveKit realtime SDK version is not approved"
        )

    if not callable(getattr(rtc_module, "RpcError", None)):
        raise LiveKitModerationRpcTransportError(
            "LiveKit realtime RPC error API is unavailable"
        )
    return rtc_module


def _identifier(value: object, label: str) -> str:
    if (
        type(value) is not str
        or not value
        or len(value) > MAX_IDENTIFIER_LENGTH
        or _IDENTIFIER_RE.fullmatch(value) is None
    ):
        raise LiveKitModerationRpcTransportError(f"{label} is invalid")
    return value


def _safe_service_message(error: ClassroomModerationRpcError) -> str:
    message = str(error)
    if message not in _SAFE_CLIENT_SERVICE_MESSAGES:
        return "moderation request failed"
    try:
        encoded = message.encode("utf-8")
    except UnicodeEncodeError:
        return "moderation request failed"
    if (
        not encoded
        or len(encoded) > MAX_RPC_ERROR_MESSAGE_BYTES
        or any(ord(character) < 32 for character in message)
    ):
        return "moderation request failed"
    return message


def _rpc_error(rtc: object, message: str) -> BaseException:
    error_type = getattr(rtc, "RpcError", None)
    if not callable(error_type):
        return LiveKitModerationRpcTransportError(
            "LiveKit RPC error API is unavailable"
        )
    return error_type(MODERATION_RPC_ERROR_CODE, message)


def _reserve_registration(participant: object) -> None:
    with _REGISTRATION_LOCK:
        try:
            methods = _REGISTRATIONS.setdefault(participant, set())
        except (TypeError, ValueError):
            raise LiveKitModerationRpcTransportError(
                "LiveKit participant cannot own RPC registration"
            ) from None
        if MODERATION_RPC_METHOD in methods:
            raise LiveKitModerationRpcTransportError(
                "LiveKit moderation RPC method is already bound"
            )
        methods.add(MODERATION_RPC_METHOD)


def _release_registration(participant: object) -> None:
    with _REGISTRATION_LOCK:
        try:
            methods = _REGISTRATIONS.get(participant)
        except (TypeError, ValueError):
            return
        if methods is None:
            return
        methods.discard(MODERATION_RPC_METHOD)
        if not methods:
            try:
                del _REGISTRATIONS[participant]
            except (KeyError, TypeError):
                pass


__all__ = [
    "LIVEKIT_RTC_VERSION",
    "LiveKitModerationRpcTransport",
    "LiveKitModerationRpcTransportError",
    "MAX_RPC_ERROR_MESSAGE_BYTES",
    "MODERATION_RPC_ERROR_CODE",
    "MODERATION_RPC_METHOD",
]
