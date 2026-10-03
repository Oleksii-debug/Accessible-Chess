from __future__ import annotations

"""Trusted desktop composition for authenticated classroom collaboration.

This module owns wiring only. Chat/file protocol semantics, durable server
authority, room membership, authorization, persistence, scanning, object storage
and browser presentation remain in their existing canonical owners.
"""

from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import cast

from .classroom_chat_http_endpoint import ClassroomChatHttpRpcCall
from .classroom_chat_outbox import SecretStoreChatOutbox
from .classroom_chat_rpc import ClassroomChatRpcClient
from .classroom_collaboration import (
    ClassroomCollaborationController,
    FileQuotaPolicy,
)
from .classroom_collaboration_storage import ClassroomCollaborationSQLiteStore
from .classroom_collaboration_webview import (
    ClassroomCollaborationWebView,
    ClassroomCollaborationWebViewEvent,
)
from .classroom_file_http_transport import ClassroomFileHttpRpcCall
from .classroom_file_rpc import ClassroomFileRpcClient, MAX_RPC_UPLOAD_BYTES
from .classroom_realtime_media import ClassroomMediaController, ClassroomRosterPort
from .full_product_ui_shell import UILanguage
from .secret_store import SecretStore


class _DeferredCollaborationStore:
    """One-shot proxy that keeps canonical binding validation side-effect free.

    ClassroomCollaborationController owns the roster/member validation contract.
    The controller is therefore constructed against this unbound proxy first. Its
    constructor may validate identity/roster state but cannot touch durable local
    metadata. Only after that canonical constructor succeeds do we materialize the
    SQLite store and bind this proxy to it for the controller's normal lifetime.
    """

    __slots__ = ("_target",)

    def __init__(self) -> None:
        self._target: ClassroomCollaborationSQLiteStore | None = None

    def bind(self, target: ClassroomCollaborationSQLiteStore) -> None:
        if not isinstance(target, ClassroomCollaborationSQLiteStore):
            raise TypeError("deferred collaboration store requires SQLite target")
        if self._target is not None:
            raise RuntimeError("deferred collaboration store is already bound")
        self._target = target

    def __getattr__(self, name: str) -> object:
        target = self._target
        if target is None:
            raise RuntimeError(
                "durable collaboration store is unavailable during binding validation"
            )
        return getattr(target, name)


@dataclass(frozen=True, slots=True)
class ClassroomCollaborationRuntime:
    """Owned local objects for one authenticated room/participant binding."""

    store: ClassroomCollaborationSQLiteStore = field(repr=False)
    controller: ClassroomCollaborationController = field(repr=False)
    webview: ClassroomCollaborationWebView = field(repr=False)
    chat_client: ClassroomChatRpcClient = field(repr=False)
    file_client: ClassroomFileRpcClient = field(repr=False)
    chat_outbox: SecretStoreChatOutbox | None = field(default=None, repr=False)

    def __repr__(self) -> str:
        return "ClassroomCollaborationRuntime(<bound>)"


def build_classroom_collaboration_http_runtime(
    *,
    room_id: str,
    participant_id: str,
    roster: ClassroomRosterPort,
    store_path: str | Path,
    chat_endpoint_url: str,
    file_endpoint_url: str,
    chat_bearer_token_provider: Callable[[], str],
    file_bearer_token_provider: Callable[[], str],
    participant_label: Callable[[str], str],
    language: UILanguage = UILanguage.UA,
    chat_secret_store: SecretStore | None = None,
    file_picker: Callable[[], Path | None] | None = None,
    file_saver: Callable[[str, str], object] | None = None,
    file_opener: Callable[[str, str], object] | None = None,
    file_progress_event_sink: (
        Callable[[ClassroomCollaborationWebViewEvent], object] | None
    ) = None,
    moderation_allowed: Callable[[], bool] | None = None,
    participant_moderation: ClassroomMediaController | None = None,
    chat_retention: str = "session",
    file_retention: str = "session",
    local_quota: FileQuotaPolicy | None = None,
    chat_timeout_seconds: float = 15.0,
    file_timeout_seconds: float = 30.0,
    allow_insecure_loopback: bool = False,
) -> ClassroomCollaborationRuntime:
    """Compose the existing HTTPS/RPC/core/UI owners without adding authority.

    Bearer suppliers are injected separately and are called only by the HTTP
    transports for an actual request. No ambient environment credential is read
    or retained by this composition layer. The file RPC client supplies both the
    canonical transfer and short-lived read/delete store ports; server-side
    authority remains the trusted file server behind that RPC.
    """

    if not callable(chat_bearer_token_provider):
        raise TypeError("chat bearer token provider must be callable")
    if not callable(file_bearer_token_provider):
        raise TypeError("file bearer token provider must be callable")
    if not all(
        callable(getattr(roster, attribute, None))
        for attribute in ("participant_ids", "role_for", "board_control_allowed")
    ):
        raise TypeError("roster must implement ClassroomRosterPort")
    if not callable(participant_label):
        raise TypeError("participant_label must be callable")
    if chat_secret_store is not None and not (
        callable(getattr(chat_secret_store, "read", None))
        and callable(getattr(chat_secret_store, "write", None))
        and callable(getattr(chat_secret_store, "delete", None))
    ):
        raise TypeError("chat_secret_store must implement SecretStore")
    for label, callback in (
        ("file_picker", file_picker),
        ("file_saver", file_saver),
        ("file_opener", file_opener),
        ("file_progress_event_sink", file_progress_event_sink),
        ("moderation_allowed", moderation_allowed),
    ):
        if callback is not None and not callable(callback):
            raise TypeError(f"{label} must be callable")
    if participant_moderation is not None and not isinstance(
        participant_moderation,
        ClassroomMediaController,
    ):
        raise TypeError(
            "participant_moderation must be ClassroomMediaController"
        )
    if type(chat_retention) is not str or chat_retention not in {
        "transient",
        "session",
        "persistent",
    }:
        raise ValueError(
            "chat_retention must be transient, session, or persistent"
        )
    if type(file_retention) is not str or file_retention not in {
        "transient",
        "session",
        "persistent",
    }:
        raise ValueError(
            "file_retention must be transient, session, or persistent"
        )
    if not isinstance(language, UILanguage):
        raise TypeError("language must be UILanguage")
    if type(allow_insecure_loopback) is not bool:
        raise TypeError("allow_insecure_loopback must be bool")
    if local_quota is not None and not isinstance(local_quota, FileQuotaPolicy):
        raise TypeError("local_quota must be FileQuotaPolicy")
    quota = local_quota or FileQuotaPolicy()
    if quota.max_file_bytes > MAX_RPC_UPLOAD_BYTES:
        raise ValueError(
            "local file quota exceeds the authenticated RPC upload limit"
        )

    if isinstance(store_path, Path):
        path = store_path
    elif type(store_path) is str and store_path:
        path = Path(store_path)
    else:
        raise TypeError("store_path must be a non-empty path")
    if str(path) == ":memory:":
        raise ValueError(
            "store_path must use durable filesystem storage, not SQLite memory"
        )
    try:
        path = path.resolve(strict=False)
        if path.exists() and not path.is_file():
            raise ValueError("store_path must reference a file, not a directory")
        if not path.parent.is_dir():
            raise ValueError("store_path parent directory must already exist")
    except (OSError, RuntimeError) as exc:
        raise ValueError("store_path could not be validated") from exc

    # Validate network inputs before any local persistence is created.
    chat_call = ClassroomChatHttpRpcCall(
        endpoint_url=chat_endpoint_url,
        bearer_token_provider=chat_bearer_token_provider,
        timeout_seconds=chat_timeout_seconds,
        allow_insecure_loopback=allow_insecure_loopback,
    )
    chat_client = ClassroomChatRpcClient(
        room_id=room_id,
        participant_id=participant_id,
        transport=chat_call,
    )
    file_call = ClassroomFileHttpRpcCall(
        endpoint_url=file_endpoint_url,
        bearer_token_provider=file_bearer_token_provider,
        timeout_seconds=file_timeout_seconds,
        allow_insecure_loopback=allow_insecure_loopback,
    )
    file_client = ClassroomFileRpcClient(
        room_id=room_id,
        participant_id=participant_id,
        transport=file_call,
        max_upload_bytes=quota.max_file_bytes,
    )

    # Reuse the canonical controller constructor as the sole roster/member
    # authority, but keep its store side-effect free until that validation passes.
    deferred_store = _DeferredCollaborationStore()
    controller = ClassroomCollaborationController(
        room_id=room_id,
        local_participant_id=participant_id,
        roster=roster,
        chat=chat_client,
        files=file_client,
        store=cast(ClassroomCollaborationSQLiteStore, deferred_store),
        file_store=file_client,
        quota=quota,
    )

    chat_outbox = (
        None
        if chat_secret_store is None
        else SecretStoreChatOutbox(
            chat_secret_store,
            room_id,
            participant_id,
        )
    )
    if chat_outbox is not None:
        # Corrupt/unreadable secure recovery state must fail before local
        # collaboration metadata is materialized and before any network call.
        chat_outbox.entries()

    store = ClassroomCollaborationSQLiteStore(str(path))
    deferred_store.bind(store)
    webview = ClassroomCollaborationWebView(
        controller,
        store,
        participant_label,
        chat_outbox=chat_outbox,
        language=language,
        file_picker=file_picker,
        file_saver=file_saver,
        file_opener=file_opener,
        file_progress_event_sink=file_progress_event_sink,
        moderation_allowed=moderation_allowed,
        participant_moderation=participant_moderation,
        chat_retention=chat_retention,
        file_retention=file_retention,
    )
    return ClassroomCollaborationRuntime(
        store=store,
        controller=controller,
        webview=webview,
        chat_client=chat_client,
        file_client=file_client,
        chat_outbox=chat_outbox,
    )


__all__ = [
    "ClassroomCollaborationRuntime",
    "build_classroom_collaboration_http_runtime",
]
