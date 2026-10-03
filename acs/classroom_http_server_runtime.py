from __future__ import annotations

"""Trusted deployment composition for classroom chat + file HTTP services.

This module owns startup ordering only. Chat/file authorization, persistence,
retention policy, scanning, object storage, RPC semantics, HTTP framing and
authentication remain in their existing canonical owners.
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from .classroom_collaboration import FileQuotaPolicy
from .classroom_collaboration_chat_server import (
    ClassroomChatAuthorizationPort,
    ClassroomChatServerService,
    ClassroomChatServerSQLiteStore,
)
from .classroom_chat_rpc import ClassroomChatRpcService
from .classroom_file_rpc import MAX_RPC_UPLOAD_BYTES, ClassroomFileRpcService
from .classroom_file_server import (
    ClassroomFileAuthorizationPort,
    ClassroomFileObjectStorePort,
    ClassroomFileScannerPort,
    ClassroomFileServerService,
    ClassroomFileServerSQLiteStore,
)
from .classroom_http_application import (
    ClassroomCollaborationHttpApplication,
    ClassroomCollaborationHttpAuthenticatorPort,
)


@dataclass(frozen=True, slots=True, repr=False)
class ClassroomCollaborationHttpServerRuntime:
    """One fully recovered trusted collaboration deployment."""

    chat_store: ClassroomChatServerSQLiteStore
    file_store: ClassroomFileServerSQLiteStore
    chat_service: ClassroomChatServerService
    file_service: ClassroomFileServerService
    chat_rpc: ClassroomChatRpcService
    file_rpc: ClassroomFileRpcService
    application: ClassroomCollaborationHttpApplication

    def __repr__(self) -> str:
        return "ClassroomCollaborationHttpServerRuntime(<bound>)"


def _require_callable(owner: object, name: str, label: str) -> None:
    if owner is None or not callable(getattr(owner, name, None)):
        raise TypeError(f"{label} must provide {name}()")


def _database_path(value: str | Path, label: str) -> str:
    if not isinstance(value, (str, Path)):
        raise TypeError(f"{label} must be str or pathlib.Path")
    result = str(value)
    if not result or result == ":memory:":
        raise ValueError(f"{label} must be a durable filesystem path")
    target = Path(result)
    parent = target.parent
    if not parent.exists() or not parent.is_dir():
        raise ValueError(f"{label} parent directory must already exist")
    if target.exists() and target.is_dir():
        raise ValueError(f"{label} must identify a database file")
    return result


def build_classroom_collaboration_http_server_runtime(
    *,
    chat_database_path: str | Path,
    file_database_path: str | Path,
    authenticator: ClassroomCollaborationHttpAuthenticatorPort,
    chat_authorization: ClassroomChatAuthorizationPort,
    file_authorization: ClassroomFileAuthorizationPort,
    file_scanner: ClassroomFileScannerPort,
    file_object_store: ClassroomFileObjectStorePort,
    clock_unix_ms: Callable[[], int],
    chat_retention_policy: Callable[[str], str] | None = None,
    file_quota: FileQuotaPolicy = FileQuotaPolicy(),
    allow_insecure_loopback: bool = False,
) -> ClassroomCollaborationHttpServerRuntime:
    """Build a recovered server runtime before exposing its ASGI application.

    Invalid adapters are rejected before either database is opened. Durable
    state is then integrity-checked; abandoned file uploads are rolled back and
    prior pending deletions are drained. Any incomplete recovery aborts the
    build, so callers cannot accidentally expose an ambiguous deployment.
    """

    # Validate injected capabilities before any durable side effect.
    _require_callable(authenticator, "authenticate_bearer", "authenticator")
    for method in (
        "authorize_chat_send",
        "authorize_chat_history",
        "authorize_chat_moderation",
    ):
        _require_callable(chat_authorization, method, "chat authorization")
    _require_callable(
        file_authorization,
        "authorize_file_action",
        "file authorization",
    )
    _require_callable(file_scanner, "scan", "file scanner")
    for method in ("stored_sha256", "put", "issue_read_token", "delete"):
        _require_callable(file_object_store, method, "file object store")
    if not callable(clock_unix_ms):
        raise TypeError("clock_unix_ms must be callable")
    if chat_retention_policy is not None and not callable(chat_retention_policy):
        raise TypeError("chat_retention_policy must be callable or None")
    if type(file_quota) is not FileQuotaPolicy:
        raise TypeError("file_quota must be FileQuotaPolicy")
    if file_quota.max_file_bytes > MAX_RPC_UPLOAD_BYTES:
        raise ValueError("file_quota exceeds authenticated RPC upload limit")
    if type(allow_insecure_loopback) is not bool:
        raise TypeError("allow_insecure_loopback must be bool")

    chat_path = _database_path(chat_database_path, "chat_database_path")
    file_path = _database_path(file_database_path, "file_database_path")
    if (
        Path(chat_path).resolve(strict=False)
        == Path(file_path).resolve(strict=False)
    ):
        raise ValueError("chat and file databases must use distinct paths")

    chat_store = ClassroomChatServerSQLiteStore(chat_path)
    file_store = ClassroomFileServerSQLiteStore(file_path)

    # Prove durable authority before recovery mutates file lifecycle state.
    chat_store.integrity_check()
    file_store.integrity_check()

    chat_service = ClassroomChatServerService(
        store=chat_store,
        authorization=chat_authorization,
        clock_unix_ms=clock_unix_ms,
        retention_policy=chat_retention_policy,
    )
    file_service = ClassroomFileServerService(
        store=file_store,
        authorization=file_authorization,
        scanner=file_scanner,
        object_store=file_object_store,
        quota=file_quota,
    )

    # Startup is a trusted quiescent boundary. Do not expose the application
    # until every ambiguous upload and pending physical deletion is reconciled.
    file_service.rollback_pending_uploads()
    file_service.drain_pending_deletions()
    file_service.integrity_check()

    chat_rpc = ClassroomChatRpcService(backend=chat_service)
    file_rpc = ClassroomFileRpcService(
        backend=file_service,
        max_upload_bytes=file_quota.max_file_bytes,
    )
    application = ClassroomCollaborationHttpApplication(
        chat_service=chat_rpc,
        file_service=file_rpc,
        authenticator=authenticator,
        allow_insecure_loopback=allow_insecure_loopback,
    )

    return ClassroomCollaborationHttpServerRuntime(
        chat_store=chat_store,
        file_store=file_store,
        chat_service=chat_service,
        file_service=file_service,
        chat_rpc=chat_rpc,
        file_rpc=file_rpc,
        application=application,
    )


__all__ = [
    "ClassroomCollaborationHttpServerRuntime",
    "build_classroom_collaboration_http_server_runtime",
]
