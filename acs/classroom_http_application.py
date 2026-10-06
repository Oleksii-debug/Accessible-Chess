from __future__ import annotations

"""Deployment composition for authenticated classroom chat + file HTTP RPC.

This module is routing/composition only. Authentication is injected once and is
shared by both canonical endpoints. Chat/file RPC semantics, room authorization,
durable persistence, scanning, object storage and desktop credentials remain in
their existing owners.
"""

from collections.abc import Awaitable, Callable, Mapping
import json
from typing import Protocol

from .classroom_chat_http_endpoint import (
    CHAT_RPC_PATH,
    ClassroomChatHttpEndpoint,
)
from .classroom_chat_rpc import ClassroomChatRpcService
from .classroom_file_http_transport import (
    FILE_RPC_PATH,
    ClassroomFileHttpEndpoint,
)
from .classroom_file_rpc import ClassroomFileRpcService


Receive = Callable[[], Awaitable[dict[str, object]]]
Send = Callable[[dict[str, object]], Awaitable[None]]


class ClassroomCollaborationHttpAuthenticatorPort(Protocol):
    """One deployment identity authority shared by chat and file routes."""

    async def authenticate_bearer(self, bearer_token: str) -> tuple[str, str]:
        ...


class ClassroomCollaborationHttpApplication:
    """One ASGI app exposing the canonical chat and file RPC endpoints."""

    __slots__ = ("_chat", "_files", "_authenticator")

    def __init__(
        self,
        *,
        chat_service: ClassroomChatRpcService,
        file_service: ClassroomFileRpcService,
        authenticator: ClassroomCollaborationHttpAuthenticatorPort,
        allow_insecure_loopback: bool = False,
    ) -> None:
        if not isinstance(chat_service, ClassroomChatRpcService):
            raise TypeError("classroom HTTP app requires ClassroomChatRpcService")
        if not isinstance(file_service, ClassroomFileRpcService):
            raise TypeError("classroom HTTP app requires ClassroomFileRpcService")
        if authenticator is None or not callable(
            getattr(authenticator, "authenticate_bearer", None)
        ):
            raise TypeError("classroom HTTP app requires an authenticator")
        if type(allow_insecure_loopback) is not bool:
            raise TypeError("allow_insecure_loopback must be bool")
        self._authenticator = authenticator
        self._chat = ClassroomChatHttpEndpoint(
            service=chat_service,
            authenticator=authenticator,
            allow_insecure_loopback=allow_insecure_loopback,
        )
        self._files = ClassroomFileHttpEndpoint(
            service=file_service,
            authenticator=authenticator,
            allow_insecure_loopback=allow_insecure_loopback,
        )

    def __repr__(self) -> str:
        return "ClassroomCollaborationHttpApplication(<bound>)"

    async def __call__(
        self,
        scope: Mapping[str, object],
        receive: Receive,
        send: Send,
    ) -> None:
        if not isinstance(scope, Mapping):
            raise TypeError("ASGI scope must be a mapping")
        scope_type = scope.get("type")
        if scope_type == "lifespan":
            await self._lifespan(receive, send)
            return
        if scope_type != "http":
            raise RuntimeError("classroom HTTP application supports HTTP only")

        path = scope.get("path")
        if path == CHAT_RPC_PATH:
            await self._chat(scope, receive, send)
            return
        if path == FILE_RPC_PATH:
            await self._files(scope, receive, send)
            return
        await _send_not_found(send)

    async def _lifespan(self, receive: Receive, send: Send) -> None:
        while True:
            event = await receive()
            if type(event) is not dict:
                raise RuntimeError("invalid ASGI lifespan event")
            event_type = event.get("type")
            if event_type == "lifespan.startup":
                await send({"type": "lifespan.startup.complete"})
                continue
            if event_type == "lifespan.shutdown":
                await send({"type": "lifespan.shutdown.complete"})
                return
            raise RuntimeError("unsupported ASGI lifespan event")


async def _send_not_found(send: Send) -> None:
    payload = json.dumps(
        {"error": "not_found"},
        ensure_ascii=True,
        separators=(",", ":"),
    ).encode("ascii")
    headers = [
        (b"content-type", b"application/json; charset=utf-8"),
        (b"content-length", str(len(payload)).encode("ascii")),
        (b"cache-control", b"no-store"),
        (b"pragma", b"no-cache"),
        (b"x-content-type-options", b"nosniff"),
    ]
    try:
        await send(
            {
                "type": "http.response.start",
                "status": 404,
                "headers": headers,
            }
        )
        await send(
            {
                "type": "http.response.body",
                "body": payload,
                "more_body": False,
            }
        )
    except Exception:
        raise RuntimeError("classroom HTTP response delivery failed") from None


__all__ = [
    "ClassroomCollaborationHttpApplication",
    "ClassroomCollaborationHttpAuthenticatorPort",
]
