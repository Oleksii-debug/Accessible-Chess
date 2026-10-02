from __future__ import annotations

"""Trusted LiveKit room lifecycle for the classroom moderation service.

This runtime is deliberately narrower than authentication, roster, media policy,
or provider administration. Deployment supplies one short-lived service token.
The runtime owns the realtime Room connection, proves that LiveKit connected the
expected moderation participant to the expected room, binds the existing
LiveKitModerationRpcTransport, and retains cleanup authority after failures.

The wrapper does not duplicate the service token into its own fields: it passes
the token directly to the provider Room.connect call. The provider SDK owns its
connection state while active. After successful teardown this wrapper drops the
Room handle; after cleanup failure it deliberately retains that handle only so
cleanup can be retried. Provider details are redacted from diagnostics.
"""

import importlib
from importlib import metadata
import ipaddress
import re
from types import ModuleType
from urllib.parse import urlsplit

from .classroom_moderation_rpc import MAX_IDENTIFIER_LENGTH
from .livekit_moderation_rpc_transport import (
    LIVEKIT_RTC_DISTRIBUTION,
    LIVEKIT_RTC_VERSION,
    LiveKitModerationRpcTransport,
)


MAX_LIVEKIT_REALTIME_URL_CHARS = 2048
MAX_MODERATION_SERVICE_TOKEN_CHARS = 32 * 1024
_IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")


class LiveKitModerationServiceRuntimeError(RuntimeError):
    """Sanitized lifecycle/configuration failure for the trusted service."""


class LiveKitModerationServiceRuntime:
    """Own one moderation-service participant connection for one room.

    Construction retains the Room handle before any network effect. Callers then
    invoke connect() with a fresh server-side token. If connect/binding cleanup
    fails, the same runtime remains the retryable cleanup owner.
    """

    __slots__ = (
        "_url",
        "_room_id",
        "_identity",
        "_service",
        "_rtc",
        "_room",
        "_transport",
        "_connected",
        "_closing",
        "_cleanup_required",
        "_closed",
    )

    def __init__(
        self,
        *,
        provider_url: str,
        trusted_room_id: str,
        moderation_participant_identity: str,
        service: object,
        rtc_module: ModuleType | object | None = None,
        sdk_version: str | None = None,
    ) -> None:
        self._url = _provider_url(provider_url)
        self._room_id = _identifier(trusted_room_id, "trusted room id")
        self._identity = _identifier(
            moderation_participant_identity,
            "moderation participant identity",
        )
        if service is None or not callable(getattr(service, "handle_rpc", None)):
            raise LiveKitModerationServiceRuntimeError(
                "moderation RPC service is unavailable"
            )
        self._service = service
        self._rtc = _load_rtc(
            rtc_module=rtc_module,
            sdk_version=sdk_version,
        )
        try:
            self._room: object | None = self._rtc.Room()
        except Exception:
            raise LiveKitModerationServiceRuntimeError(
                "LiveKit moderation service room initialization failed"
            ) from None
        self._transport: LiveKitModerationRpcTransport | None = None
        self._connected = False
        self._closing = False
        self._cleanup_required = False
        self._closed = False

    def __repr__(self) -> str:
        if self._closed:
            state = "closed"
        elif self._closing:
            state = "closing"
        elif self._cleanup_required:
            state = "cleanup_required"
        elif self.ready:
            state = "ready"
        elif self._connected:
            state = "connected"
        else:
            state = "created"
        return (
            "LiveKitModerationServiceRuntime("
            f"sdk_version={LIVEKIT_RTC_VERSION!r}, state={state!r}, "
            "provider_url=<redacted>, room=<redacted>, "
            "participant=<redacted>, token=<not-stored>)"
        )

    @property
    def closed(self) -> bool:
        return self._closed

    @property
    def cleanup_required(self) -> bool:
        return self._cleanup_required

    @property
    def connected(self) -> bool:
        return self._connected and _room_is_connected(self._room)

    @property
    def ready(self) -> bool:
        return (
            not self._closed
            and not self._closing
            and not self._cleanup_required
            and self.connected
            and self._transport is not None
            and not self._transport.closed
        )

    @property
    def moderation_transport(self) -> LiveKitModerationRpcTransport:
        if not self.ready or self._transport is None:
            raise LiveKitModerationServiceRuntimeError(
                "LiveKit moderation service runtime is not ready"
            )
        return self._transport

    async def connect(self, *, service_token: str) -> None:
        """Connect once using a fresh service token and bind canonical RPC."""

        if self._closed:
            raise LiveKitModerationServiceRuntimeError(
                "LiveKit moderation service runtime is closed"
            )
        if self._closing:
            raise LiveKitModerationServiceRuntimeError(
                "LiveKit moderation service runtime is closing"
            )
        if self._cleanup_required:
            raise LiveKitModerationServiceRuntimeError(
                "LiveKit moderation service runtime requires cleanup"
            )
        if self._connected or self._transport is not None:
            raise LiveKitModerationServiceRuntimeError(
                "LiveKit moderation service runtime is already connected"
            )

        token = _service_token(service_token)
        try:
            options = self._rtc.RoomOptions(auto_subscribe=False)
        except Exception:
            self._closed = True
            raise LiveKitModerationServiceRuntimeError(
                "LiveKit realtime room options are unavailable"
            ) from None

        try:
            room = self._room
            if room is None:
                raise LiveKitModerationServiceRuntimeError(
                    "LiveKit moderation service room is unavailable"
                )
            await room.connect(
                self._url,
                token,
                options=options,
            )
            self._connected = True
        except Exception:
            await self._cleanup_failed_connection(
                "LiveKit moderation service connection failed"
            )
            raise LiveKitModerationServiceRuntimeError(
                "LiveKit moderation service connection failed"
            ) from None

        try:
            room = self._room
            if room is None:
                raise LiveKitModerationServiceRuntimeError(
                    "LiveKit moderation service room is unavailable"
                )
            actual_room = getattr(room, "name")
            local_participant = getattr(room, "local_participant")
            actual_identity = getattr(local_participant, "identity", None)
            if actual_room != self._room_id:
                raise LiveKitModerationServiceRuntimeError(
                    "LiveKit moderation service room identity mismatch"
                )
            if actual_identity != self._identity:
                raise LiveKitModerationServiceRuntimeError(
                    "LiveKit moderation service participant identity mismatch"
                )
            self._transport = LiveKitModerationRpcTransport.bind(
                local_participant=local_participant,
                trusted_room_id=self._room_id,
                moderation_participant_identity=self._identity,
                service=self._service,
                rtc_module=self._rtc,
                sdk_version=LIVEKIT_RTC_VERSION,
            )
        except LiveKitModerationServiceRuntimeError as error:
            message = str(error)
            await self._cleanup_failed_connection(message)
            raise LiveKitModerationServiceRuntimeError(message) from None
        except Exception:
            await self._cleanup_failed_connection(
                "LiveKit moderation service RPC binding failed"
            )
            raise LiveKitModerationServiceRuntimeError(
                "LiveKit moderation service RPC binding failed"
            ) from None

    async def _cleanup_failed_connection(self, message: str) -> None:
        """Best-effort cleanup while retaining this object on failure."""

        room = self._room
        if room is None:
            self._connected = False
            self._closed = True
            self._cleanup_required = False
            return
        try:
            await room.disconnect()
        except Exception:
            self._cleanup_required = True
            raise LiveKitModerationServiceRuntimeError(
                message + "; cleanup is required"
            ) from None
        self._connected = False
        self._room = None
        self._closed = True
        self._cleanup_required = False

    async def aclose(self) -> None:
        if self._closed:
            return
        if self._closing:
            raise LiveKitModerationServiceRuntimeError(
                "LiveKit moderation service close is already in progress"
            )

        self._closing = True
        transport_failed = False
        disconnect_failed = False
        try:
            if self._transport is not None and not self._transport.closed:
                try:
                    self._transport.close()
                except Exception:
                    transport_failed = True
                else:
                    self._transport = None

            room = self._room
            if room is not None and (self._connected or self._cleanup_required):
                try:
                    await room.disconnect()
                except Exception:
                    disconnect_failed = True
                else:
                    self._connected = False
                    self._room = None

            if transport_failed or disconnect_failed:
                self._cleanup_required = True
                raise LiveKitModerationServiceRuntimeError(
                    "LiveKit moderation service cleanup failed"
                ) from None

            self._transport = None
            self._room = None
            self._cleanup_required = False
            self._closed = True
        finally:
            self._closing = False

    async def __aenter__(self) -> "LiveKitModerationServiceRuntime":
        if not self.ready:
            raise LiveKitModerationServiceRuntimeError(
                "LiveKit moderation service runtime is not ready"
            )
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        await self.aclose()


def _load_rtc(
    *,
    rtc_module: ModuleType | object | None,
    sdk_version: str | None,
) -> object:
    if rtc_module is None:
        try:
            installed = metadata.version(LIVEKIT_RTC_DISTRIBUTION)
        except metadata.PackageNotFoundError:
            raise LiveKitModerationServiceRuntimeError(
                "Pinned LiveKit realtime SDK is unavailable"
            ) from None
        if installed != LIVEKIT_RTC_VERSION:
            raise LiveKitModerationServiceRuntimeError(
                "LiveKit realtime SDK version is not approved"
            )
        try:
            rtc_module = importlib.import_module("livekit.rtc")
        except Exception:
            raise LiveKitModerationServiceRuntimeError(
                "Pinned LiveKit realtime SDK is unavailable"
            ) from None
    elif sdk_version != LIVEKIT_RTC_VERSION:
        raise LiveKitModerationServiceRuntimeError(
            "LiveKit realtime SDK version is not approved"
        )

    for name in ("Room", "RoomOptions", "RpcError"):
        if not callable(getattr(rtc_module, name, None)):
            raise LiveKitModerationServiceRuntimeError(
                "LiveKit realtime room API is unavailable"
            )
    return rtc_module


def _provider_url(value: object) -> str:
    if (
        type(value) is not str
        or not value
        or len(value) > MAX_LIVEKIT_REALTIME_URL_CHARS
        or value != value.strip()
        or any(character.isspace() or ord(character) < 32 for character in value)
    ):
        raise LiveKitModerationServiceRuntimeError(
            "LiveKit realtime provider URL is invalid"
        )
    try:
        parts = urlsplit(value)
        port = parts.port
    except ValueError:
        raise LiveKitModerationServiceRuntimeError(
            "LiveKit realtime provider URL is invalid"
        ) from None
    if (
        parts.scheme not in {"wss", "ws"}
        or not parts.hostname
        or parts.username is not None
        or parts.password is not None
        or parts.query
        or parts.fragment
        or parts.path not in {"", "/"}
        or (port is None and ":" in parts.netloc.rsplit("]", 1)[-1])
        or (port is not None and port == 0)
    ):
        raise LiveKitModerationServiceRuntimeError(
            "LiveKit realtime provider URL is invalid"
        )
    if parts.scheme == "ws" and not _loopback_host(parts.hostname):
        raise LiveKitModerationServiceRuntimeError(
            "LiveKit realtime provider URL must use WSS"
        )
    return value[:-1] if value.endswith("/") else value


def _loopback_host(host: str) -> bool:
    if host.lower() == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def _identifier(value: object, label: str) -> str:
    if (
        type(value) is not str
        or not value
        or len(value) > MAX_IDENTIFIER_LENGTH
        or _IDENTIFIER_RE.fullmatch(value) is None
    ):
        raise LiveKitModerationServiceRuntimeError(f"{label} is invalid")
    return value


def _service_token(value: object) -> str:
    if (
        type(value) is not str
        or not value
        or len(value) > MAX_MODERATION_SERVICE_TOKEN_CHARS
        or value != value.strip()
        or any(character.isspace() or ord(character) < 32 for character in value)
    ):
        raise LiveKitModerationServiceRuntimeError(
            "LiveKit moderation service token is invalid"
        )
    return value


def _room_is_connected(room: object) -> bool:
    probe = getattr(room, "isconnected", None)
    if not callable(probe):
        return False
    try:
        value = probe()
    except Exception:
        return False
    return type(value) is bool and value


__all__ = [
    "LiveKitModerationServiceRuntime",
    "LiveKitModerationServiceRuntimeError",
    "MAX_LIVEKIT_REALTIME_URL_CHARS",
    "MAX_MODERATION_SERVICE_TOKEN_CHARS",
]
