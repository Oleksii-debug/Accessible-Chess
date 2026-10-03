from __future__ import annotations

"""Authenticated, provider-neutral RPC boundary for classroom file collaboration.

This is a wire adapter, not a second file authority. Durable metadata, quota,
malware scanning, object storage and authorization remain owned by
classroom_file_server. File content stays opaque bytes at this boundary so a
concrete binary/multipart transport need not base64-expand large files.
"""

from collections.abc import Mapping
import hashlib
from pathlib import Path
import re
from typing import Callable, Protocol

from .classroom_collaboration import (
    AttachmentHistoryPage,
    FileTransferProgress,
    MAX_DOWNLOAD_TOKEN_CHARS,
    MAX_FILE_BYTES_DEFAULT,
    MAX_SYNC_ATTACHMENTS,
    PreparedFile,
    _canonical_object_key,
)
from .classroom_collaboration_storage import (
    AttachmentMetadata,
    AttachmentStateUpdate,
    _safe_object_key,
)
from .classroom_domain import MAX_WIRE_INTEGER


RPC_VERSION = 1
MAX_RPC_UPLOAD_BYTES = MAX_FILE_BYTES_DEFAULT
_RPC_READ_CHUNK_BYTES = 1024 * 1024
_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")


class ClassroomFileRpcError(ValueError):
    """Safe public failure for malformed, unauthorized or failed file RPC."""


class ClassroomFileRpcCallPort(Protocol):
    """Authenticated binary-capable request transport used by the desktop."""

    def call(
        self,
        request: Mapping[str, object],
        *,
        on_upload_progress: Callable[[int], None] | None = None,
    ) -> Mapping[str, object]:
        """Call the authenticated transport and report actual upload bytes sent."""
        ...


class ClassroomFileRpcServerPort(Protocol):
    """Trusted server authority invoked with separately authenticated identity."""

    def upload(
        self,
        *,
        trusted_caller_identity: str,
        metadata: AttachmentMetadata,
        content: bytes,
    ) -> AttachmentMetadata:
        ...

    def cancel(
        self,
        *,
        trusted_caller_identity: str,
        attachment_id: str,
        expected_room_id: str | None = None,
    ) -> None:
        ...

    def history_after(
        self,
        *,
        trusted_caller_identity: str,
        room_id: str,
        after_sequence: int | None,
        limit: int,
    ) -> AttachmentHistoryPage:
        ...

    def state_updates_after(
        self,
        *,
        trusted_caller_identity: str,
        room_id: str,
        after_revision: int | None,
        limit: int,
    ) -> tuple[AttachmentStateUpdate, ...]:
        ...

    def issue_read_token(
        self,
        *,
        trusted_caller_identity: str,
        object_key: str,
        ttl_seconds: int,
        expected_room_id: str | None = None,
    ) -> str:
        ...

    def delete_object(
        self,
        *,
        trusted_caller_identity: str,
        object_key: str,
        expected_room_id: str | None = None,
    ) -> None:
        ...


class ClassroomFileRpcClient:
    """Room/participant-bound desktop adapter for canonical file operations."""

    def __init__(
        self,
        *,
        room_id: str,
        participant_id: str,
        transport: ClassroomFileRpcCallPort,
        max_upload_bytes: int = MAX_RPC_UPLOAD_BYTES,
    ) -> None:
        self.room_id = _opaque_id(room_id, "room id")
        self.participant_id = _opaque_id(participant_id, "participant id")
        self._transport = transport
        self._max_upload_bytes = _upload_limit(max_upload_bytes)

    def upload(
        self,
        prepared: PreparedFile,
        *,
        on_progress: Callable[[FileTransferProgress], None] | None = None,
    ) -> AttachmentMetadata:
        return self._upload(prepared, on_progress=on_progress)

    def retry(
        self,
        prepared: PreparedFile,
        *,
        on_progress: Callable[[FileTransferProgress], None] | None = None,
    ) -> AttachmentMetadata:
        return self._upload(prepared, on_progress=on_progress)

    def _upload(
        self,
        prepared: PreparedFile,
        *,
        on_progress: Callable[[FileTransferProgress], None] | None,
    ) -> AttachmentMetadata:
        metadata, content = self._read_prepared(prepared)
        observe_transport, require_complete_progress = self._progress_observer(
            metadata,
            on_progress,
        )
        response = self._call(
            {
                "v": RPC_VERSION,
                "op": "upload",
                "room_id": self.room_id,
                "participant_id": self.participant_id,
                "metadata": _attachment_to_wire(metadata),
                "content": content,
            },
            on_upload_progress=observe_transport,
        )
        require_complete_progress()
        _exact_keys(response, {"v", "ok", "attachment"}, "upload response")
        _version_ok(response)
        if response["ok"] is not True:
            raise ClassroomFileRpcError("file upload failed")
        delivered = _attachment_from_wire(response["attachment"])
        _validate_upload_result(metadata, delivered)
        return delivered

    def _read_prepared(
        self,
        prepared: PreparedFile,
    ) -> tuple[AttachmentMetadata, bytes]:
        if type(prepared) is not PreparedFile:
            raise ClassroomFileRpcError("file upload requires PreparedFile")
        metadata = prepared.metadata
        _validate_upload_metadata(
            metadata,
            room_id=self.room_id,
            participant_id=self.participant_id,
            max_upload_bytes=self._max_upload_bytes,
        )
        remaining = metadata.size_bytes
        digest = hashlib.sha256()
        content = bytearray()
        extra = b""
        try:
            with prepared.local_path.open("rb") as source:
                while remaining:
                    chunk = source.read(min(_RPC_READ_CHUNK_BYTES, remaining))
                    if not chunk:
                        break
                    content.extend(chunk)
                    digest.update(chunk)
                    remaining -= len(chunk)
                extra = source.read(1)
        except OSError:
            raise ClassroomFileRpcError(
                "selected file could not be read for upload"
            ) from None
        if (
            remaining != 0
            or extra
            or digest.hexdigest() != metadata.sha256
        ):
            raise ClassroomFileRpcError(
                "selected file changed before RPC upload"
            )
        return metadata, bytes(content)

    @staticmethod
    def _progress_observer(
        metadata: AttachmentMetadata,
        consumer: Callable[[FileTransferProgress], None] | None,
    ) -> tuple[Callable[[int], None], Callable[[], None]]:
        if consumer is not None and not callable(consumer):
            raise ClassroomFileRpcError("file progress consumer must be callable")
        last_transferred = -1

        def observe(transferred_bytes: int) -> None:
            nonlocal last_transferred
            if (
                type(transferred_bytes) is not int
                or not 0 <= transferred_bytes <= metadata.size_bytes
            ):
                raise ClassroomFileRpcError(
                    "file RPC transport returned invalid upload progress"
                )
            if transferred_bytes < last_transferred:
                raise ClassroomFileRpcError(
                    "file RPC transport progress moved backwards"
                )
            if transferred_bytes == last_transferred:
                return
            last_transferred = transferred_bytes
            if consumer is not None:
                try:
                    consumer(
                        FileTransferProgress(
                            metadata.attachment_id,
                            transferred_bytes,
                            metadata.size_bytes,
                        )
                    )
                except Exception:
                    # UI/NVDA presentation is an observer. A broken callback
                    # cannot turn an otherwise valid remote upload ambiguous.
                    pass

        def require_complete() -> None:
            if metadata.size_bytes == 0:
                if last_transferred not in {-1, 0}:
                    raise ClassroomFileRpcError(
                        "file RPC transport returned invalid upload progress"
                    )
                return
            if last_transferred != metadata.size_bytes:
                raise ClassroomFileRpcError(
                    "file RPC transport omitted final upload progress"
                )

        return observe, require_complete

    def cancel(self, *, attachment_id: str) -> None:
        attachment = _opaque_id(attachment_id, "attachment id")
        response = self._call(
            {
                "v": RPC_VERSION,
                "op": "cancel",
                "room_id": self.room_id,
                "participant_id": self.participant_id,
                "attachment_id": attachment,
            }
        )
        _exact_keys(response, {"v", "ok"}, "cancel response")
        _version_ok(response)
        if response["ok"] is not True:
            raise ClassroomFileRpcError("file cancellation failed")

    def history_after(
        self,
        *,
        room_id: str,
        after_sequence: int | None,
        limit: int,
    ) -> AttachmentHistoryPage:
        room = _opaque_id(room_id, "room id")
        if room != self.room_id:
            raise ClassroomFileRpcError("file history crossed bound room")
        after = _optional_cursor(after_sequence, "after_sequence")
        bounded = _sync_limit(limit, "history limit")
        response = self._call(
            {
                "v": RPC_VERSION,
                "op": "history",
                "room_id": room,
                "participant_id": self.participant_id,
                "after_sequence": after,
                "limit": bounded,
            }
        )
        _exact_keys(
            response,
            {"v", "ok", "attachments", "snapshot_state_revision"},
            "history response",
        )
        _version_ok(response)
        if response["ok"] is not True:
            raise ClassroomFileRpcError("file history failed")
        raw = response["attachments"]
        if type(raw) is not list or len(raw) > bounded:
            raise ClassroomFileRpcError("file history response is invalid")
        result = tuple(_attachment_from_wire(item) for item in raw)
        _validate_history(
            result,
            room_id=room,
            after_sequence=after,
            limit=bounded,
        )
        watermark = _optional_cursor(
            response["snapshot_state_revision"],
            "snapshot_state_revision",
        )
        return AttachmentHistoryPage(result, watermark)

    def state_updates_after(
        self,
        *,
        room_id: str,
        after_revision: int | None,
        limit: int,
    ) -> tuple[AttachmentStateUpdate, ...]:
        room = _opaque_id(room_id, "room id")
        if room != self.room_id:
            raise ClassroomFileRpcError("file state crossed bound room")
        after = _optional_cursor(after_revision, "after_revision")
        bounded = _sync_limit(limit, "state history limit")
        response = self._call(
            {
                "v": RPC_VERSION,
                "op": "state",
                "room_id": room,
                "participant_id": self.participant_id,
                "after_revision": after,
                "limit": bounded,
            }
        )
        _exact_keys(response, {"v", "ok", "updates"}, "state response")
        _version_ok(response)
        if response["ok"] is not True:
            raise ClassroomFileRpcError("file state sync failed")
        raw = response["updates"]
        if type(raw) is not list or len(raw) > bounded:
            raise ClassroomFileRpcError("file state response is invalid")
        result = tuple(_state_from_wire(item) for item in raw)
        _validate_state_updates(
            result,
            room_id=room,
            after_revision=after,
            limit=bounded,
        )
        return result

    def issue_read_token(
        self,
        *,
        object_key: str,
        participant_id: str,
        ttl_seconds: int,
    ) -> str:
        participant = _opaque_id(participant_id, "participant id")
        if participant != self.participant_id:
            raise ClassroomFileRpcError(
                "download participant does not match bound caller"
            )
        key = _room_object_key(object_key, self.room_id)
        ttl = _token_ttl(ttl_seconds)
        response = self._call(
            {
                "v": RPC_VERSION,
                "op": "read_token",
                "room_id": self.room_id,
                "participant_id": self.participant_id,
                "object_key": key,
                "ttl_seconds": ttl,
            }
        )
        _exact_keys(response, {"v", "ok", "token"}, "read-token response")
        _version_ok(response)
        if response["ok"] is not True:
            raise ClassroomFileRpcError("file read-token request failed")
        return _read_token(response["token"])

    def delete(self, *, object_key: str) -> None:
        key = _room_object_key(object_key, self.room_id)
        response = self._call(
            {
                "v": RPC_VERSION,
                "op": "delete",
                "room_id": self.room_id,
                "participant_id": self.participant_id,
                "object_key": key,
            }
        )
        _exact_keys(response, {"v", "ok"}, "delete response")
        _version_ok(response)
        if response["ok"] is not True:
            raise ClassroomFileRpcError("file deletion failed")

    def _call(
        self,
        request: Mapping[str, object],
        *,
        on_upload_progress: Callable[[int], None] | None = None,
    ) -> dict[str, object]:
        try:
            response = self._transport.call(
                request,
                on_upload_progress=on_upload_progress,
            )
        except ClassroomFileRpcError:
            raise
        except Exception:
            raise ClassroomFileRpcError(
                "classroom file service unavailable"
            ) from None
        if type(response) is not dict:
            raise ClassroomFileRpcError("classroom file response is invalid")
        return response


class ClassroomFileRpcService:
    """Strict authenticated endpoint over one canonical trusted file server."""

    def __init__(
        self,
        *,
        backend: ClassroomFileRpcServerPort,
        max_upload_bytes: int = MAX_RPC_UPLOAD_BYTES,
    ) -> None:
        if backend is None:
            raise TypeError("trusted classroom file server backend is required")
        self._backend = backend
        self._max_upload_bytes = _upload_limit(max_upload_bytes)

    def handle(
        self,
        request: Mapping[str, object],
        *,
        authenticated_room_id: str,
        authenticated_participant_id: str,
    ) -> dict[str, object]:
        if type(request) is not dict:
            raise ClassroomFileRpcError("file request must be an object")
        room = _opaque_id(authenticated_room_id, "authenticated room id")
        participant = _opaque_id(
            authenticated_participant_id,
            "authenticated participant id",
        )
        _version_ok(request)
        op = request.get("op")
        if op == "upload":
            return self._handle_upload(request, room=room, participant=participant)
        if op == "cancel":
            return self._handle_cancel(request, room=room, participant=participant)
        if op == "history":
            return self._handle_history(request, room=room, participant=participant)
        if op == "state":
            return self._handle_state(request, room=room, participant=participant)
        if op == "read_token":
            return self._handle_read_token(
                request,
                room=room,
                participant=participant,
            )
        if op == "delete":
            return self._handle_delete(request, room=room, participant=participant)
        raise ClassroomFileRpcError("unsupported file RPC operation")

    def _handle_upload(
        self,
        request: dict[str, object],
        *,
        room: str,
        participant: str,
    ) -> dict[str, object]:
        _exact_keys(
            request,
            {"v", "op", "room_id", "participant_id", "metadata", "content"},
            "upload request",
        )
        _require_authenticated_identity(request, room=room, participant=participant)
        metadata = _attachment_from_wire(request["metadata"])
        _validate_upload_metadata(
            metadata,
            room_id=room,
            participant_id=participant,
            max_upload_bytes=self._max_upload_bytes,
        )
        content = request["content"]
        if type(content) is not bytes:
            raise ClassroomFileRpcError("file upload content must be opaque bytes")
        if len(content) != metadata.size_bytes:
            raise ClassroomFileRpcError("file upload byte length changed in transit")
        if hashlib.sha256(content).hexdigest() != metadata.sha256:
            raise ClassroomFileRpcError("file upload hash changed in transit")
        try:
            result = self._backend.upload(
                trusted_caller_identity=participant,
                metadata=metadata,
                content=content,
            )
        except Exception:
            raise ClassroomFileRpcError("classroom file backend failed") from None
        if type(result) is not AttachmentMetadata:
            raise ClassroomFileRpcError(
                "classroom file backend returned invalid attachment"
            )
        _validate_upload_result(metadata, result)
        return {
            "v": RPC_VERSION,
            "ok": True,
            "attachment": _attachment_to_wire(result),
        }

    def _handle_cancel(
        self,
        request: dict[str, object],
        *,
        room: str,
        participant: str,
    ) -> dict[str, object]:
        _exact_keys(
            request,
            {"v", "op", "room_id", "participant_id", "attachment_id"},
            "cancel request",
        )
        _require_authenticated_identity(request, room=room, participant=participant)
        attachment = _opaque_id(request["attachment_id"], "attachment id")
        try:
            self._backend.cancel(
                trusted_caller_identity=participant,
                attachment_id=attachment,
                expected_room_id=room,
            )
        except Exception:
            raise ClassroomFileRpcError("classroom file backend failed") from None
        return {"v": RPC_VERSION, "ok": True}

    def _handle_history(
        self,
        request: dict[str, object],
        *,
        room: str,
        participant: str,
    ) -> dict[str, object]:
        _exact_keys(
            request,
            {
                "v",
                "op",
                "room_id",
                "participant_id",
                "after_sequence",
                "limit",
            },
            "history request",
        )
        _require_authenticated_identity(request, room=room, participant=participant)
        after = _optional_cursor(request["after_sequence"], "after_sequence")
        limit = _sync_limit(request["limit"], "history limit")
        try:
            page = self._backend.history_after(
                trusted_caller_identity=participant,
                room_id=room,
                after_sequence=after,
                limit=limit,
            )
        except Exception:
            raise ClassroomFileRpcError("classroom file backend failed") from None
        if type(page) is not AttachmentHistoryPage:
            raise ClassroomFileRpcError(
                "classroom file backend returned invalid history page"
            )
        _validate_history(
            page.attachments,
            room_id=room,
            after_sequence=after,
            limit=limit,
        )
        watermark = _optional_cursor(
            page.snapshot_state_revision,
            "snapshot_state_revision",
        )
        return {
            "v": RPC_VERSION,
            "ok": True,
            "attachments": [
                _attachment_to_wire(item) for item in page.attachments
            ],
            "snapshot_state_revision": watermark,
        }

    def _handle_state(
        self,
        request: dict[str, object],
        *,
        room: str,
        participant: str,
    ) -> dict[str, object]:
        _exact_keys(
            request,
            {
                "v",
                "op",
                "room_id",
                "participant_id",
                "after_revision",
                "limit",
            },
            "state request",
        )
        _require_authenticated_identity(request, room=room, participant=participant)
        after = _optional_cursor(request["after_revision"], "after_revision")
        limit = _sync_limit(request["limit"], "state history limit")
        try:
            updates = self._backend.state_updates_after(
                trusted_caller_identity=participant,
                room_id=room,
                after_revision=after,
                limit=limit,
            )
        except Exception:
            raise ClassroomFileRpcError("classroom file backend failed") from None
        if type(updates) is not tuple:
            raise ClassroomFileRpcError(
                "classroom file backend returned invalid state history"
            )
        _validate_state_updates(
            updates,
            room_id=room,
            after_revision=after,
            limit=limit,
        )
        return {
            "v": RPC_VERSION,
            "ok": True,
            "updates": [_state_to_wire(item) for item in updates],
        }

    def _handle_read_token(
        self,
        request: dict[str, object],
        *,
        room: str,
        participant: str,
    ) -> dict[str, object]:
        _exact_keys(
            request,
            {
                "v",
                "op",
                "room_id",
                "participant_id",
                "object_key",
                "ttl_seconds",
            },
            "read-token request",
        )
        _require_authenticated_identity(request, room=room, participant=participant)
        key = _room_object_key(request["object_key"], room)
        ttl = _token_ttl(request["ttl_seconds"])
        try:
            token = self._backend.issue_read_token(
                trusted_caller_identity=participant,
                object_key=key,
                ttl_seconds=ttl,
                expected_room_id=room,
            )
        except Exception:
            raise ClassroomFileRpcError("classroom file backend failed") from None
        return {"v": RPC_VERSION, "ok": True, "token": _read_token(token)}

    def _handle_delete(
        self,
        request: dict[str, object],
        *,
        room: str,
        participant: str,
    ) -> dict[str, object]:
        _exact_keys(
            request,
            {"v", "op", "room_id", "participant_id", "object_key"},
            "delete request",
        )
        _require_authenticated_identity(request, room=room, participant=participant)
        key = _room_object_key(request["object_key"], room)
        try:
            self._backend.delete_object(
                trusted_caller_identity=participant,
                object_key=key,
                expected_room_id=room,
            )
        except Exception:
            raise ClassroomFileRpcError("classroom file backend failed") from None
        return {"v": RPC_VERSION, "ok": True}


def _attachment_to_wire(metadata: AttachmentMetadata) -> dict[str, object]:
    if type(metadata) is not AttachmentMetadata:
        raise ClassroomFileRpcError("attachment metadata is invalid")
    return {
        "attachment_id": metadata.attachment_id,
        "room_id": metadata.room_id,
        "sender_id": metadata.sender_id,
        "sequence_no": metadata.sequence_no,
        "display_name": metadata.display_name,
        "mime_type": metadata.mime_type,
        "size_bytes": metadata.size_bytes,
        "sha256": metadata.sha256,
        "object_key": metadata.object_key,
        "transfer_state": metadata.transfer_state,
        "retention": metadata.retention,
        "scan_state": metadata.scan_state,
    }


def _attachment_from_wire(value: object) -> AttachmentMetadata:
    if type(value) is not dict:
        raise ClassroomFileRpcError("attachment metadata must be an object")
    _exact_keys(
        value,
        {
            "attachment_id",
            "room_id",
            "sender_id",
            "sequence_no",
            "display_name",
            "mime_type",
            "size_bytes",
            "sha256",
            "object_key",
            "transfer_state",
            "retention",
            "scan_state",
        },
        "attachment metadata",
    )
    try:
        return AttachmentMetadata(
            attachment_id=value["attachment_id"],
            room_id=value["room_id"],
            sender_id=value["sender_id"],
            sequence_no=value["sequence_no"],
            display_name=value["display_name"],
            mime_type=value["mime_type"],
            size_bytes=value["size_bytes"],
            sha256=value["sha256"],
            object_key=value["object_key"],
            transfer_state=value["transfer_state"],
            retention=value["retention"],
            scan_state=value["scan_state"],
        )
    except Exception:
        raise ClassroomFileRpcError("attachment metadata is invalid") from None


def _state_to_wire(update: AttachmentStateUpdate) -> dict[str, object]:
    if type(update) is not AttachmentStateUpdate:
        raise ClassroomFileRpcError("attachment state update is invalid")
    return {
        "room_id": update.room_id,
        "attachment_id": update.attachment_id,
        "revision": update.revision,
        "transfer_state": update.transfer_state,
        "scan_state": update.scan_state,
    }


def _state_from_wire(value: object) -> AttachmentStateUpdate:
    if type(value) is not dict:
        raise ClassroomFileRpcError("attachment state update must be an object")
    _exact_keys(
        value,
        {
            "room_id",
            "attachment_id",
            "revision",
            "transfer_state",
            "scan_state",
        },
        "attachment state update",
    )
    try:
        return AttachmentStateUpdate(
            room_id=value["room_id"],
            attachment_id=value["attachment_id"],
            revision=value["revision"],
            transfer_state=value["transfer_state"],
            scan_state=value["scan_state"],
        )
    except Exception:
        raise ClassroomFileRpcError(
            "attachment state update is invalid"
        ) from None


def _validate_upload_metadata(
    metadata: AttachmentMetadata,
    *,
    room_id: str,
    participant_id: str,
    max_upload_bytes: int,
) -> None:
    if type(metadata) is not AttachmentMetadata:
        raise ClassroomFileRpcError("file upload metadata is invalid")
    if metadata.room_id != room_id or metadata.sender_id != participant_id:
        raise ClassroomFileRpcError("file upload crossed bound identity")
    if metadata.object_key != _canonical_object_key(
        room_id,
        metadata.attachment_id,
    ):
        raise ClassroomFileRpcError(
            "file upload crossed canonical attachment namespace"
        )
    if metadata.transfer_state not in {"pending", "uploading"}:
        raise ClassroomFileRpcError("file upload metadata must be provisional")
    if metadata.size_bytes > max_upload_bytes:
        raise ClassroomFileRpcError("file exceeds RPC upload limit")


def _validate_upload_result(
    requested: AttachmentMetadata,
    delivered: AttachmentMetadata,
) -> None:
    immutable = (
        "attachment_id",
        "room_id",
        "sender_id",
        "display_name",
        "mime_type",
        "size_bytes",
        "sha256",
        "object_key",
        "retention",
    )
    if any(
        getattr(requested, field) != getattr(delivered, field)
        for field in immutable
    ):
        raise ClassroomFileRpcError(
            "file backend changed immutable attachment identity"
        )
    if delivered.transfer_state not in {"stored", "failed"}:
        raise ClassroomFileRpcError(
            "file backend returned non-terminal upload state"
        )
    if (
        delivered.transfer_state == "failed"
        and delivered.sequence_no != requested.sequence_no
    ):
        raise ClassroomFileRpcError(
            "failed file result changed provisional sequence"
        )
    if (
        delivered.transfer_state == "stored"
        and delivered.scan_state != "clean"
    ):
        raise ClassroomFileRpcError(
            "stored file result is not cleared by authoritative scan"
        )


def _validate_history(
    attachments: tuple[AttachmentMetadata, ...],
    *,
    room_id: str,
    after_sequence: int | None,
    limit: int,
) -> None:
    if len(attachments) > limit:
        raise ClassroomFileRpcError("file history exceeds requested limit")
    previous = after_sequence
    seen: set[str] = set()
    for attachment in attachments:
        if type(attachment) is not AttachmentMetadata:
            raise ClassroomFileRpcError(
                "file history contains invalid attachment"
            )
        if attachment.room_id != room_id:
            raise ClassroomFileRpcError("file history crossed room boundary")
        if attachment.object_key != _canonical_object_key(
            room_id,
            attachment.attachment_id,
        ):
            raise ClassroomFileRpcError(
                "file history crossed canonical attachment namespace"
            )
        if attachment.transfer_state not in {"stored", "deleted"}:
            raise ClassroomFileRpcError(
                "file history contains non-terminal attachment"
            )
        expected = 0 if previous is None else previous + 1
        if attachment.sequence_no != expected:
            raise ClassroomFileRpcError(
                "file history has an unresolved sequence gap"
            )
        if attachment.attachment_id in seen:
            raise ClassroomFileRpcError(
                "file history contains duplicate attachment identity"
            )
        seen.add(attachment.attachment_id)
        previous = attachment.sequence_no


def _validate_state_updates(
    updates: tuple[AttachmentStateUpdate, ...],
    *,
    room_id: str,
    after_revision: int | None,
    limit: int,
) -> None:
    if len(updates) > limit:
        raise ClassroomFileRpcError(
            "file state history exceeds requested limit"
        )
    previous = after_revision
    for update in updates:
        if type(update) is not AttachmentStateUpdate:
            raise ClassroomFileRpcError(
                "file state history contains invalid update"
            )
        if update.room_id != room_id:
            raise ClassroomFileRpcError(
                "file state history crossed room boundary"
            )
        expected = 0 if previous is None else previous + 1
        if update.revision != expected:
            raise ClassroomFileRpcError(
                "file state history has an unresolved revision gap"
            )
        previous = update.revision


def _version_ok(value: Mapping[str, object]) -> None:
    if value.get("v") != RPC_VERSION or type(value.get("v")) is not int:
        raise ClassroomFileRpcError("unsupported file RPC version")


def _require_authenticated_identity(
    request: Mapping[str, object],
    *,
    room: str,
    participant: str,
) -> None:
    try:
        requested_room = _opaque_id(request["room_id"], "room id")
        requested_participant = _opaque_id(
            request["participant_id"],
            "participant id",
        )
    except KeyError:
        raise ClassroomFileRpcError(
            "file request identity is missing"
        ) from None
    if requested_room != room or requested_participant != participant:
        raise ClassroomFileRpcError(
            "file request identity does not match authenticated transport"
        )


def _exact_keys(
    value: Mapping[str, object],
    expected: set[str],
    label: str,
) -> None:
    if type(value) is not dict or set(value) != expected:
        raise ClassroomFileRpcError(f"{label} fields are invalid")


def _opaque_id(value: object, label: str) -> str:
    if type(value) is not str or _ID_RE.fullmatch(value) is None:
        raise ClassroomFileRpcError(
            f"{label} must be a canonical opaque identifier"
        )
    return value


def _optional_cursor(value: object, label: str) -> int | None:
    if value is None:
        return None
    if type(value) is not int or not 0 <= value <= MAX_WIRE_INTEGER:
        raise ClassroomFileRpcError(
            f"{label} must be null or bounded non-negative integer"
        )
    return value


def _sync_limit(value: object, label: str) -> int:
    if type(value) is not int or not 1 <= value <= MAX_SYNC_ATTACHMENTS:
        raise ClassroomFileRpcError(f"{label} is invalid")
    return value


def _upload_limit(value: object) -> int:
    if type(value) is not int or not 1 <= value <= MAX_WIRE_INTEGER:
        raise ValueError(
            "max_upload_bytes must be a positive bounded integer"
        )
    return value


def _token_ttl(value: object) -> int:
    if type(value) is not int or not 1 <= value <= 3600:
        raise ClassroomFileRpcError("download token TTL is invalid")
    return value


def _read_token(value: object) -> str:
    if (
        type(value) is not str
        or not value
        or len(value) > MAX_DOWNLOAD_TOKEN_CHARS
        or any(
            ch.isspace() or ord(ch) < 32 or ord(ch) == 127
            for ch in value
        )
    ):
        raise ClassroomFileRpcError(
            "download token response is invalid"
        )
    return value


def _room_object_key(value: object, room_id: str) -> str:
    try:
        key = _safe_object_key(value)
    except Exception:
        raise ClassroomFileRpcError("object key is invalid") from None
    canonical = _canonical_object_key(room_id, "rpc-probe")
    prefix = canonical.rsplit("/", 1)[0] + "/"
    if not key.startswith(prefix) or len(key.split("/")) != 3:
        raise ClassroomFileRpcError(
            "object key crossed authenticated room namespace"
        )
    return key


__all__ = [
    "ClassroomFileRpcCallPort",
    "ClassroomFileRpcClient",
    "ClassroomFileRpcError",
    "ClassroomFileRpcServerPort",
    "ClassroomFileRpcService",
    "MAX_RPC_UPLOAD_BYTES",
    "RPC_VERSION",
]
