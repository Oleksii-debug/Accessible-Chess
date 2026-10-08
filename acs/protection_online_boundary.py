from __future__ import annotations

"""Public R15-R18 online-access boundary for the private protection runtime.

The public product never receives passwords, refresh tokens, client secrets,
account identifiers, device identifiers, PKCE verifiers, authorization codes, or
backend signing material.  It may only ask the private runtime to begin a
system-browser login/registration flow and poll that opaque flow until the
private runtime has completed account/session handling.
"""

from dataclasses import dataclass
import re
from typing import Callable
from urllib.parse import urlsplit
import webbrowser

from .protection_boundary import (
    ONLINE_RUNTIME_API_VERSION,
    ProtectionBoundaryError,
    ProtectionRuntimeClient,
)

_FLOW_ID = re.compile(r"^[A-Za-z0-9_-]{16,128}$")
_ALLOWED_MODES = frozenset({"login", "register"})
_ALLOWED_POLL_STATES = frozenset({"pending", "completed", "denied", "expired"})
_MAX_REASON = 256
_MIN_FLOW_TTL_SECONDS = 30
_MAX_FLOW_TTL_SECONDS = 1800


class ProtectionOnlineError(ProtectionBoundaryError):
    pass


@dataclass(frozen=True)
class OnlineAccessFlow:
    mode: str
    flow_id: str
    expires_in_seconds: int


@dataclass(frozen=True)
class OnlineAccessPoll:
    state: str
    reason: str

    @property
    def completed(self) -> bool:
        return self.state == "completed"


def _runtime_v2(client: ProtectionRuntimeClient):
    try:
        return client.runtime_extension(minimum_api_version=ONLINE_RUNTIME_API_VERSION)
    except ProtectionBoundaryError as exc:
        raise ProtectionOnlineError(str(exc)) from exc


def _validate_flow_id(value: object) -> str:
    if not isinstance(value, str) or not _FLOW_ID.fullmatch(value):
        raise ProtectionOnlineError("private online flow id is invalid")
    return value


def _validate_authorization_url(value: object) -> str:
    if not isinstance(value, str) or len(value) > 4096:
        raise ProtectionOnlineError("private authorization URL is invalid")
    parsed = urlsplit(value)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.fragment
    ):
        raise ProtectionOnlineError("private authorization URL is unsafe")
    return value


def _validate_begin_result(value: object, *, mode: str) -> tuple[str, str, int]:
    if not isinstance(value, dict) or set(value) != {
        "api_version", "flow_id", "authorization_url", "expires_in_seconds"
    }:
        raise ProtectionOnlineError("private online flow schema is invalid")
    if value.get("api_version") != ONLINE_RUNTIME_API_VERSION:
        raise ProtectionOnlineError("private online flow API version is unsupported")
    flow_id = _validate_flow_id(value.get("flow_id"))
    authorization_url = _validate_authorization_url(value.get("authorization_url"))
    expires = value.get("expires_in_seconds")
    if (
        not isinstance(expires, int)
        or isinstance(expires, bool)
        or not _MIN_FLOW_TTL_SECONDS <= expires <= _MAX_FLOW_TTL_SECONDS
    ):
        raise ProtectionOnlineError("private online flow expiry is invalid")
    return flow_id, authorization_url, expires


def _validate_poll_result(value: object) -> OnlineAccessPoll:
    if not isinstance(value, dict) or set(value) != {"api_version", "state", "reason"}:
        raise ProtectionOnlineError("private online poll schema is invalid")
    if value.get("api_version") != ONLINE_RUNTIME_API_VERSION:
        raise ProtectionOnlineError("private online poll API version is unsupported")
    state = value.get("state")
    reason = value.get("reason")
    if state not in _ALLOWED_POLL_STATES:
        raise ProtectionOnlineError("private online poll state is invalid")
    if not isinstance(reason, str) or not reason or len(reason) > _MAX_REASON:
        raise ProtectionOnlineError("private online poll reason is invalid")
    if state in {"pending", "completed"} and reason != "none":
        raise ProtectionOnlineError("private online poll result is inconsistent")
    if state in {"denied", "expired"} and reason == "none":
        raise ProtectionOnlineError("private online poll result is inconsistent")
    return OnlineAccessPoll(state=state, reason=reason)


class ProtectionOnlineClient:
    """Opaque online login/registration bridge; all security state stays private."""

    def __init__(
        self,
        client: ProtectionRuntimeClient,
        *,
        browser_open: Callable[[str], object] = webbrowser.open,
    ) -> None:
        if not isinstance(client, ProtectionRuntimeClient):
            raise TypeError("client must be a ProtectionRuntimeClient")
        if not callable(browser_open):
            raise TypeError("browser_open must be callable")
        self.client = client
        self._browser_open = browser_open

    def begin(self, *, mode: str) -> OnlineAccessFlow:
        if mode not in _ALLOWED_MODES:
            raise ProtectionOnlineError("online access mode is invalid")
        runtime = _runtime_v2(self.client)
        begin = getattr(runtime, "begin_online_access", None)
        if not callable(begin):
            raise ProtectionOnlineError("private online access operation is unavailable")
        try:
            value = begin(
                package_root=self.client.application_dir,
                state_root=self.client.state_root,
                mode=mode,
            )
        except Exception as exc:
            raise ProtectionOnlineError("private online access could not start") from exc
        flow_id, authorization_url, expires = _validate_begin_result(value, mode=mode)
        try:
            opened = self._browser_open(authorization_url)
        except Exception as exc:
            raise ProtectionOnlineError("system browser could not be opened") from exc
        if opened is False:
            raise ProtectionOnlineError("system browser could not be opened")
        return OnlineAccessFlow(
            mode=mode,
            flow_id=flow_id,
            expires_in_seconds=expires,
        )

    def poll(self, *, flow_id: str) -> OnlineAccessPoll:
        flow = _validate_flow_id(flow_id)
        runtime = _runtime_v2(self.client)
        poll = getattr(runtime, "poll_online_access", None)
        if not callable(poll):
            raise ProtectionOnlineError("private online poll operation is unavailable")
        try:
            value = poll(
                package_root=self.client.application_dir,
                state_root=self.client.state_root,
                flow_id=flow,
            )
        except Exception as exc:
            raise ProtectionOnlineError("private online access poll failed") from exc
        return _validate_poll_result(value)


__all__ = [
    "OnlineAccessFlow",
    "OnlineAccessPoll",
    "ProtectionOnlineClient",
    "ProtectionOnlineError",
]
