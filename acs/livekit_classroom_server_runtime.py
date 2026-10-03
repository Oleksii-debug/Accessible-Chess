from __future__ import annotations

"""Server-only lifecycle owner for LiveKit classroom moderation.

The desktop/browser never constructs this object. Deployment code injects the
provider endpoint and credentials explicitly. The runtime owns exactly one
LiveKitAPI client, exposes only the already-bounded moderation adapter, and
closes the provider session deterministically.
"""

import asyncio
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

    def __init__(
        self,
        message: str,
        *,
        cleanup_runtime: "LiveKitClassroomServerRuntime | None" = None,
    ) -> None:
        super().__init__(message)
        self._cleanup_runtime = cleanup_runtime

    @property
    def cleanup_runtime(self) -> "LiveKitClassroomServerRuntime | None":
        """Return only the redacted retryable cleanup owner, never the raw client."""

        return self._cleanup_runtime


class LiveKitClassroomServerCleanupCancelled(asyncio.CancelledError):
    """Cancelled failed-open cleanup that still preserves the only retry owner."""

    def __init__(self, cleanup_runtime: "LiveKitClassroomServerRuntime") -> None:
        super().__init__("LiveKit server initialization cleanup was cancelled")
        self._cleanup_runtime = cleanup_runtime

    @property
    def cleanup_runtime(self) -> "LiveKitClassroomServerRuntime":
        return self._cleanup_runtime


class LiveKitClassroomServerRuntime:
    """Own one explicit-credential LiveKitAPI client for server moderation."""

    __slots__ = (
        "_client",
        "_moderation_admin",
        "_closed",
        "_closing",
        "_cleanup_required",
    )

    def __init__(
        self,
        *,
        client: object,
        moderation_admin: LiveKitClassroomModerationAdmin | None,
        cleanup_required: bool = False,
    ) -> None:
        if type(cleanup_required) is not bool:
            raise TypeError("cleanup_required must be bool")
        if moderation_admin is None and not cleanup_required:
            raise TypeError(
                "moderation_admin is required unless runtime is cleanup-only"
            )
        self._client = client
        self._moderation_admin = moderation_admin
        self._closed = False
        self._closing = False
        self._cleanup_required = cleanup_required

    @classmethod
    def _cleanup_owner(cls, client: object) -> "LiveKitClassroomServerRuntime":
        return cls(
            client=client,
            moderation_admin=None,
            cleanup_required=True,
        )

    @classmethod
    async def _cleanup_after_failed_open(
        cls,
        client: object,
    ) -> "LiveKitClassroomServerRuntime | None":
        try:
            cleaned = await _close_failed_client(client)
        except asyncio.CancelledError:
            raise LiveKitClassroomServerCleanupCancelled(
                cls._cleanup_owner(client)
            ) from None
        return None if cleaned else cls._cleanup_owner(client)

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
        except LiveKitClassroomServerRuntimeError as error:
            cleanup_runtime = (
                None
                if client is None
                else await cls._cleanup_after_failed_open(client)
            )
            if cleanup_runtime is not None:
                raise LiveKitClassroomServerRuntimeError(
                    str(error),
                    cleanup_runtime=cleanup_runtime,
                ) from None
            raise
        except Exception:
            cleanup_runtime = (
                None
                if client is None
                else await cls._cleanup_after_failed_open(client)
            )
            if cleanup_runtime is not None:
                raise LiveKitClassroomServerRuntimeError(
                    "LiveKit server runtime initialization failed",
                    cleanup_runtime=cleanup_runtime,
                ) from None
            raise LiveKitClassroomServerRuntimeError(
                "LiveKit server runtime initialization failed"
            ) from None

    def __repr__(self) -> str:
        state = (
            "closed"
            if self._closed
            else "closing"
            if self._closing
            else "cleanup_required"
            if self._cleanup_required
            else "open"
        )
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
        if self._closing:
            raise LiveKitClassroomServerRuntimeError(
                "LiveKit server runtime is closing"
            )
        if self._cleanup_required:
            raise LiveKitClassroomServerRuntimeError(
                "LiveKit server runtime requires cleanup"
            )
        moderation_admin = self._moderation_admin
        if moderation_admin is None:
            raise LiveKitClassroomServerRuntimeError(
                "LiveKit server moderation authority is unavailable"
            )
        return moderation_admin

    @property
    def closed(self) -> bool:
        return self._closed

    async def aclose(self) -> None:
        if self._closed:
            return
        if self._closing:
            raise LiveKitClassroomServerRuntimeError(
                "LiveKit server runtime close is already in progress"
            )
        close = getattr(self._client, "aclose", None)
        if not callable(close):
            self._cleanup_required = True
            raise LiveKitClassroomServerRuntimeError(
                "LiveKit server client lifecycle API is unavailable"
            )
        self._closing = True
        try:
            await close()
        except asyncio.CancelledError:
            # Cancellation leaves provider shutdown outcome unknown. Retain the
            # only cleanup handle but never republish moderation authority until
            # a later close attempt completes successfully.
            self._closing = False
            self._cleanup_required = True
            raise
        except Exception:
            # Provider close may have partially taken effect. Keep the runtime as
            # the retryable cleanup owner, but fail closed for moderation use.
            self._closing = False
            self._cleanup_required = True
            raise LiveKitClassroomServerRuntimeError(
                "LiveKit server runtime close failed"
            ) from None
        self._closing = False
        self._cleanup_required = False
        self._closed = True

    async def __aenter__(self) -> "LiveKitClassroomServerRuntime":
        if self._closed:
            raise LiveKitClassroomServerRuntimeError(
                "LiveKit server runtime is closed"
            )
        if self._closing:
            raise LiveKitClassroomServerRuntimeError(
                "LiveKit server runtime is closing"
            )
        if self._cleanup_required:
            raise LiveKitClassroomServerRuntimeError(
                "LiveKit server runtime requires cleanup"
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
        or any(character.isspace() or ord(character) < 32 for character in value)
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
        or (port is None and ":" in parts.netloc.rsplit("]", 1)[-1])
        or (port is not None and port == 0)
        or any(character.isspace() for character in (parts.hostname or ""))
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
    # Plain HTTP is a development-only escape hatch. Require a literal IP so
    # DNS/hosts-file rebinding cannot redirect explicit backend credentials.
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
        or any(character.isspace() or ord(character) < 32 for character in value)
    ):
        raise LiveKitClassroomServerRuntimeError(f"{label} is invalid")
    return value


async def _close_failed_client(client: object) -> bool:
    """Best-effort initialization cleanup; False means a retry owner is required."""

    close = getattr(client, "aclose", None)
    if not callable(close):
        return False
    try:
        await close()
    except asyncio.CancelledError:
        raise
    except Exception:
        return False
    return True


__all__ = [
    "LiveKitClassroomServerCleanupCancelled",
    "LiveKitClassroomServerRuntime",
    "LiveKitClassroomServerRuntimeError",
    "MAX_PROVIDER_CREDENTIAL_CHARS",
    "MAX_PROVIDER_ENDPOINT_CHARS",
]
