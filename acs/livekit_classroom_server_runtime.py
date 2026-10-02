from __future__ import annotations

"""Server-only lifecycle owner for LiveKit classroom moderation.

The desktop/browser never constructs this object. Deployment code injects the
provider endpoint and credentials explicitly. The runtime owns exactly one
LiveKitAPI client, exposes only the already-bounded moderation adapter, and
closes the provider session deterministically.
"""

from importlib import metadata
import importlib
import ipaddress
from types import ModuleType
from urllib.parse import urlsplit

from .livekit_classroom_moderation_admin import (
    LIVEKIT_API_DISTRIBUTION,
    LIVEKIT_API_VERSION,
    LiveKitClassroomModerationAdmin,
)


MAX_PROVIDER_ENDPOINT_CHARS = 2048
MAX_PROVIDER_CREDENTIAL_CHARS = 4096


class LiveKitClassroomServerRuntimeError(RuntimeError):
    """Sanitized failure at the trusted provider-client lifecycle boundary."""


class LiveKitClassroomServerRuntime:
    """Own one explicit-credential LiveKitAPI client for server moderation."""

    __slots__ = ("_client", "_moderation_admin", "_closed")

    def __init__(
        self,
        *,
        client: object,
        moderation_admin: LiveKitClassroomModerationAdmin,
    ) -> None:
        self._client = client
        self._moderation_admin = moderation_admin
        self._closed = False

    @classmethod
    async def open(
        cls,
        *,
        endpoint: str,
        api_key: str,
        api_secret: str,
        api_module: ModuleType | object | None = None,
        sdk_version: str | None = None,
    ) -> "LiveKitClassroomServerRuntime":
        provider_endpoint = _endpoint(endpoint)
        key = _credential(api_key, "LiveKit API key")
        secret = _credential(api_secret, "LiveKit API secret")
        api = _load_api(api_module=api_module, sdk_version=sdk_version)

        client: object | None = None
        try:
            client = api.LiveKitAPI(
                provider_endpoint,
                api_key=key,
                api_secret=secret,
            )
            close = getattr(client, "aclose", None)
            room = getattr(client, "room", None)
            if not callable(close) or room is None:
                raise LiveKitClassroomServerRuntimeError(
                    "LiveKit server client lifecycle API is unavailable"
                )
            moderation_admin = LiveKitClassroomModerationAdmin(
                room_service=room,
                api_module=api,
                sdk_version=LIVEKIT_API_VERSION,
            )
            return cls(
                client=client,
                moderation_admin=moderation_admin,
            )
        except LiveKitClassroomServerRuntimeError:
            if client is not None:
                await _close_failed_client(client)
            raise
        except Exception:
            if client is not None:
                await _close_failed_client(client)
            raise LiveKitClassroomServerRuntimeError(
                "LiveKit server runtime initialization failed"
            ) from None

    def __repr__(self) -> str:
        state = "closed" if self._closed else "open"
        return (
            "LiveKitClassroomServerRuntime("
            f"sdk_version={LIVEKIT_API_VERSION!r}, state={state!r}, "
            "endpoint=<redacted>, credentials=<redacted>)"
        )

    @property
    def moderation_admin(self) -> LiveKitClassroomModerationAdmin:
        if self._closed:
            raise LiveKitClassroomServerRuntimeError(
                "LiveKit server runtime is closed"
            )
        return self._moderation_admin

    @property
    def closed(self) -> bool:
        return self._closed

    async def aclose(self) -> None:
        if self._closed:
            return
        self._closed = True
        close = getattr(self._client, "aclose", None)
        if not callable(close):
            raise LiveKitClassroomServerRuntimeError(
                "LiveKit server client lifecycle API is unavailable"
            )
        try:
            await close()
        except Exception:
            raise LiveKitClassroomServerRuntimeError(
                "LiveKit server runtime close failed"
            ) from None

    async def __aenter__(self) -> "LiveKitClassroomServerRuntime":
        if self._closed:
            raise LiveKitClassroomServerRuntimeError(
                "LiveKit server runtime is closed"
            )
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        await self.aclose()


def _load_api(
    *,
    api_module: ModuleType | object | None,
    sdk_version: str | None,
) -> object:
    if api_module is None:
        try:
            installed = metadata.version(LIVEKIT_API_DISTRIBUTION)
        except metadata.PackageNotFoundError:
            raise LiveKitClassroomServerRuntimeError(
                "Pinned LiveKit server SDK is unavailable"
            ) from None
        if installed != LIVEKIT_API_VERSION:
            raise LiveKitClassroomServerRuntimeError(
                "LiveKit server SDK version is not approved"
            )
        try:
            api_module = importlib.import_module("livekit.api")
        except Exception:
            raise LiveKitClassroomServerRuntimeError(
                "Pinned LiveKit server SDK is unavailable"
            ) from None
    elif sdk_version != LIVEKIT_API_VERSION:
        raise LiveKitClassroomServerRuntimeError(
            "LiveKit server SDK version is not approved"
        )

    if not callable(getattr(api_module, "LiveKitAPI", None)):
        raise LiveKitClassroomServerRuntimeError(
            "LiveKit server client API is unavailable"
        )
    return api_module


def _endpoint(value: object) -> str:
    if (
        type(value) is not str
        or not value
        or len(value) > MAX_PROVIDER_ENDPOINT_CHARS
        or value != value.strip()
        or any(character in value for character in ("\x00", "\r", "\n"))
    ):
        raise LiveKitClassroomServerRuntimeError(
            "LiveKit server endpoint is invalid"
        )
    try:
        parts = urlsplit(value)
        port = parts.port
    except ValueError:
        raise LiveKitClassroomServerRuntimeError(
            "LiveKit server endpoint is invalid"
        ) from None

    if (
        parts.scheme not in {"https", "http"}
        or not parts.hostname
        or parts.username is not None
        or parts.password is not None
        or parts.query
        or parts.fragment
        or parts.path not in {"", "/"}
        or port is None and ":" in parts.netloc.rsplit("]", 1)[-1]
    ):
        raise LiveKitClassroomServerRuntimeError(
            "LiveKit server endpoint is invalid"
        )
    if parts.scheme == "http" and not _loopback_host(parts.hostname):
        raise LiveKitClassroomServerRuntimeError(
            "LiveKit server endpoint must use HTTPS"
        )
    return value[:-1] if value.endswith("/") else value


def _loopback_host(host: str) -> bool:
    if host.lower() == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def _credential(value: object, label: str) -> str:
    if (
        type(value) is not str
        or not value
        or len(value) > MAX_PROVIDER_CREDENTIAL_CHARS
        or value != value.strip()
        or any(character in value for character in ("\x00", "\r", "\n"))
    ):
        raise LiveKitClassroomServerRuntimeError(f"{label} is invalid")
    return value


async def _close_failed_client(client: object) -> None:
    close = getattr(client, "aclose", None)
    if not callable(close):
        return
    try:
        await close()
    except Exception:
        pass


__all__ = [
    "LiveKitClassroomServerRuntime",
    "LiveKitClassroomServerRuntimeError",
    "MAX_PROVIDER_CREDENTIAL_CHARS",
    "MAX_PROVIDER_ENDPOINT_CHARS",
]
