"""Accessible WebView projection for classroom chat and file collaboration.

This module is presentation-only. It composes the canonical collaboration
controller and metadata store from classroom_collaboration; it does not own
room membership, transport, persistence, file bytes, chess state, or provider
credentials. Browser callers never receive local paths, storage object keys,
hashes, download tokens, participant ids, or authority to mint collaboration
identities.
"""
from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from hashlib import sha256
import hmac
from pathlib import Path
import secrets

from .classroom_collaboration import (
    MAX_CHAT_BODY_CHARS,
    ClassroomCollaborationController,
    PreparedFile,
)
from .classroom_collaboration_storage import (
    AttachmentMetadata,
    ChatMessageMetadata,
    ClassroomCollaborationSQLiteStore,
)
from .full_product_ui_shell import UILanguage


@dataclass(frozen=True, slots=True)
class ClassroomCollaborationWebViewEvent:
    kind: str
    payload: Mapping[str, object]


_GENERIC_FAILURE = {
    UILanguage.UA: "Не вдалося виконати дію.",
    UILanguage.EN: "The action could not be completed.",
}
_GENERIC_PARTICIPANT = {
    UILanguage.UA: "Учасник",
    UILanguage.EN: "Participant",
}
_LABELS = {
    UILanguage.UA: {
        "heading": "Співпраця в класі",
        "chat": "Чат",
        "message": "Повідомлення",
        "send": "Надіслати",
        "sync": "Оновити чат",
        "mark_read": "Позначити прочитаним",
        "no_messages": "Повідомлень немає.",
        "files": "Файли",
        "choose_upload": "Вибрати й надіслати файл",
        "no_files": "Файлів немає.",
        "save": "Зберегти",
        "retry": "Повторити",
        "cancel": "Скасувати",
        "sent": "Повідомлення надіслано.",
        "read": "Повідомлення позначено прочитаними.",
        "file_sent": "Файл надіслано.",
        "file_saved": "Файл передано до безпечного збереження.",
        "file_cancelled": "Передавання файлу скасовано.",
        "file_retried": "Повторне передавання завершено.",
        "new_many": "Нових повідомлень: {count}.",
        "unread": "Непрочитаних: {count}",
        "type": "Тип",
        "size": "Розмір",
        "status": "Стан",
        "scan": "Перевірка",
    },
    UILanguage.EN: {
        "heading": "Classroom collaboration",
        "chat": "Chat",
        "message": "Message",
        "send": "Send",
        "sync": "Refresh chat",
        "mark_read": "Mark read",
        "no_messages": "No messages.",
        "files": "Files",
        "choose_upload": "Choose and send file",
        "no_files": "No files.",
        "save": "Save",
        "retry": "Retry",
        "cancel": "Cancel",
        "sent": "Message sent.",
        "read": "Messages marked read.",
        "file_sent": "File sent.",
        "file_saved": "File passed to safe save.",
        "file_cancelled": "File transfer cancelled.",
        "file_retried": "File retry completed.",
        "new_many": "New messages: {count}.",
        "unread": "Unread: {count}",
        "type": "Type",
        "size": "Size",
        "status": "Status",
        "scan": "Scan",
    },
}
_TRANSFER_LABELS = {
    UILanguage.UA: {
        "pending": "очікує",
        "uploading": "надсилається",
        "stored": "збережено",
        "failed": "помилка",
        "deleted": "скасовано",
    },
    UILanguage.EN: {
        "pending": "pending",
        "uploading": "sending",
        "stored": "stored",
        "failed": "failed",
        "deleted": "cancelled",
    },
}
_SCAN_LABELS = {
    UILanguage.UA: {
        "pending": "очікує",
        "clean": "безпечний",
        "blocked": "заблоковано",
        "failed": "помилка",
        "not_required": "не потрібна",
    },
    UILanguage.EN: {
        "pending": "pending",
        "clean": "clean",
        "blocked": "blocked",
        "failed": "failed",
        "not_required": "not required",
    },
}


def _default_id(prefix: str) -> str:
    return f"{prefix}-{secrets.token_hex(16)}"


class ClassroomCollaborationWebView:
    """Trusted-host presentation and command boundary for Issue #29 collaboration."""

    def __init__(
        self,
        controller: ClassroomCollaborationController,
        store: ClassroomCollaborationSQLiteStore,
        participant_label: Callable[[str], str],
        *,
        language: UILanguage = UILanguage.UA,
        file_picker: Callable[[], Path | None] | None = None,
        file_saver: Callable[[str, str], object] | None = None,
        id_factory: Callable[[str], str] = _default_id,
    ) -> None:
        if not isinstance(controller, ClassroomCollaborationController):
            raise TypeError("controller must be ClassroomCollaborationController")
        if not isinstance(store, ClassroomCollaborationSQLiteStore):
            raise TypeError("store must be ClassroomCollaborationSQLiteStore")
        if not callable(participant_label):
            raise TypeError("participant_label must be callable")
        if not isinstance(language, UILanguage):
            raise TypeError("language must be UILanguage")
        if file_picker is not None and not callable(file_picker):
            raise TypeError("file_picker must be callable")
        if file_saver is not None and not callable(file_saver):
            raise TypeError("file_saver must be callable")
        if not callable(id_factory):
            raise TypeError("id_factory must be callable")
        self._controller = controller
        self._store = store
        self._participant_label = participant_label
        self._language = language
        self._file_picker = file_picker
        self._file_saver = file_saver
        self._id_factory = id_factory
        self._action_secret = secrets.token_bytes(32)
        self._unread_message_ids: set[str] = set()
        self._prepared: dict[str, PreparedFile] = {}

    @property
    def language(self) -> UILanguage:
        return self._language

    def set_language(self, language: UILanguage) -> None:
        if not isinstance(language, UILanguage):
            raise TypeError("language must be UILanguage")
        self._language = language

    def _label(self, participant_id: str) -> str:
        try:
            raw = self._participant_label(participant_id)
        except Exception:
            return _GENERIC_PARTICIPANT[self._language]
        if type(raw) is not str:
            return _GENERIC_PARTICIPANT[self._language]
        label = " ".join(raw.split())[:120]
        return label or _GENERIC_PARTICIPANT[self._language]

    def _file_key(self, attachment_id: str) -> str:
        material = f"{self._controller.room_id}\0{attachment_id}".encode("utf-8")
        return hmac.new(self._action_secret, material, sha256).hexdigest()

    def _attachment_for_key(self, file_key: object) -> AttachmentMetadata:
        if type(file_key) is not str or len(file_key) != 64:
            raise ValueError("invalid file action key")
        for item in self._store.room_attachments(self._controller.room_id):
            if hmac.compare_digest(self._file_key(item.attachment_id), file_key):
                return item
        raise LookupError("file action key is not current")

    @staticmethod
    def _size_label(size_bytes: int) -> str:
        if size_bytes < 1024:
            return f"{size_bytes} B"
        if size_bytes < 1024 * 1024:
            return f"{size_bytes / 1024:.1f} KB"
        return f"{size_bytes / (1024 * 1024):.1f} MB"

    def _message_view(self, item: ChatMessageMetadata) -> dict[str, object]:
        return {
            "dom_id": "collaboration-message-" + sha256(item.message_id.encode("utf-8")).hexdigest()[:16],
            "sender": self._label(item.sender_id),
            "body": item.body,
            "unread": item.message_id in self._unread_message_ids,
        }

    def _file_view(self, item: AttachmentMetadata) -> dict[str, object]:
        labels = _LABELS[self._language]
        return {
            "dom_id": "collaboration-file-" + sha256(item.attachment_id.encode("utf-8")).hexdigest()[:16],
            "file_key": self._file_key(item.attachment_id),
            "sender": self._label(item.sender_id),
            "name": item.display_name,
            "type_label": f"{labels['type']}: {item.mime_type or '—'}",
            "size_label": f"{labels['size']}: {self._size_label(item.size_bytes)}",
            "status_label": f"{labels['status']}: {_TRANSFER_LABELS[self._language][item.transfer_state]}",
            "scan_label": f"{labels['scan']}: {_SCAN_LABELS[self._language][item.scan_state]}",
            "can_save": (
                item.transfer_state == "stored"
                and item.scan_state == "clean"
                and self._file_saver is not None
            ),
            "can_retry": item.transfer_state == "failed" and item.attachment_id in self._prepared,
            "can_cancel": item.transfer_state in {"pending", "uploading", "failed"},
        }

    def snapshot(self) -> dict[str, object]:
        labels = _LABELS[self._language]
        messages = self._store.room_messages(self._controller.room_id)
        attachments = tuple(
            item
            for item in self._store.room_attachments(self._controller.room_id)
            if item.transfer_state != "deleted"
        )
        visible_ids = {item.message_id for item in messages}
        self._unread_message_ids.intersection_update(visible_ids)
        unread_count = len(self._unread_message_ids)
        return {
            "heading": labels["heading"],
            "chat": {
                "heading": labels["chat"],
                "composer_label": labels["message"],
                "send_label": labels["send"],
                "sync_label": labels["sync"],
                "mark_read_label": labels["mark_read"],
                "empty_message": labels["no_messages"],
                "unread_label": labels["unread"].format(count=unread_count),
                "unread_count": unread_count,
                "max_body_chars": MAX_CHAT_BODY_CHARS,
                "messages": tuple(self._message_view(item) for item in messages),
            },
            "files": {
                "heading": labels["files"],
                "choose_upload_label": labels["choose_upload"],
                "empty_message": labels["no_files"],
                "save_label": labels["save"],
                "retry_label": labels["retry"],
                "cancel_label": labels["cancel"],
                "can_choose_upload": self._file_picker is not None,
                "items": tuple(self._file_view(item) for item in attachments),
            },
        }

    def _event(
        self,
        kind: str,
        *,
        announcement: str = "",
        focus_target: str = "",
    ) -> ClassroomCollaborationWebViewEvent:
        payload: dict[str, object] = {"collaboration": self.snapshot()}
        if announcement:
            payload["announcement"] = announcement
        if focus_target:
            payload["focus_target"] = focus_target
        return ClassroomCollaborationWebViewEvent(kind, payload)

    def _error(self) -> ClassroomCollaborationWebViewEvent:
        payload: dict[str, object] = {"message": _GENERIC_FAILURE[self._language]}
        try:
            payload["collaboration"] = self.snapshot()
        except Exception:
            pass
        return ClassroomCollaborationWebViewEvent("error", payload)

    def _send_chat(self, body: object) -> ClassroomCollaborationWebViewEvent:
        if type(body) is not str:
            raise TypeError("chat body must be text")
        self._controller.send_chat(
            message_id=self._id_factory("message"),
            body=body,
        )
        return self._event(
            "collaboration.chat.sent",
            announcement=_LABELS[self._language]["sent"],
            focus_target="collaboration-chat-input",
        )

    def _sync_chat(self) -> ClassroomCollaborationWebViewEvent:
        before = {
            item.message_id
            for item in self._store.room_messages(self._controller.room_id, include_hidden=True)
        }
        incoming = self._controller.sync_chat()
        new_remote = tuple(
            item
            for item in incoming
            if item.message_id not in before
            and not item.hidden
            and item.sender_id != self._controller.local_participant_id
        )
        self._unread_message_ids.update(item.message_id for item in new_remote)
        announcement = ""
        if len(new_remote) == 1:
            item = new_remote[0]
            compact_body = " ".join(item.body.split())[:160]
            announcement = f"{self._label(item.sender_id)}: {compact_body}"
        elif len(new_remote) > 1:
            announcement = _LABELS[self._language]["new_many"].format(count=len(new_remote))
        return self._event("collaboration.chat.synced", announcement=announcement)

    def _mark_read(self) -> ClassroomCollaborationWebViewEvent:
        self._unread_message_ids.clear()
        return self._event(
            "collaboration.chat.read",
            announcement=_LABELS[self._language]["read"],
        )

    def _choose_upload(self) -> ClassroomCollaborationWebViewEvent:
        if self._file_picker is None:
            raise RuntimeError("file picker is unavailable")
        selected = self._file_picker()
        if selected is None:
            return self._event("collaboration.file.cancelled")
        if type(selected) is not Path:
            raise TypeError("file picker must return pathlib.Path or None")
        attachments = self._store.room_attachments(self._controller.room_id)
        sequence = 0 if not attachments else max(item.sequence_no for item in attachments) + 1
        prepared = self._controller.prepare_file(
            attachment_id=self._id_factory("attachment"),
            local_path=selected,
            sequence_no=sequence,
        )
        self._prepared[prepared.metadata.attachment_id] = prepared
        uploaded = self._controller.upload_file(prepared)
        if uploaded.transfer_state != "failed":
            self._prepared.pop(uploaded.attachment_id, None)
        return self._event(
            "collaboration.file.sent",
            announcement=_LABELS[self._language]["file_sent"],
        )

    def _retry_file(self, file_key: object) -> ClassroomCollaborationWebViewEvent:
        attachment = self._attachment_for_key(file_key)
        prepared = self._prepared.get(attachment.attachment_id)
        if prepared is None:
            raise RuntimeError("retry source is unavailable")
        retried = self._controller.retry_file(prepared)
        if retried.transfer_state != "failed":
            self._prepared.pop(retried.attachment_id, None)
        return self._event(
            "collaboration.file.retried",
            announcement=_LABELS[self._language]["file_retried"],
        )

    def _cancel_file(self, file_key: object) -> ClassroomCollaborationWebViewEvent:
        attachment = self._attachment_for_key(file_key)
        self._controller.cancel_file(attachment.attachment_id)
        self._prepared.pop(attachment.attachment_id, None)
        return self._event(
            "collaboration.file.cancelled",
            announcement=_LABELS[self._language]["file_cancelled"],
        )

    def _save_file(self, file_key: object) -> ClassroomCollaborationWebViewEvent:
        if self._file_saver is None:
            raise RuntimeError("file save adapter is unavailable")
        attachment = self._attachment_for_key(file_key)
        token = self._controller.issue_download_token(attachment_id=attachment.attachment_id)
        self._file_saver(token, attachment.display_name)
        return self._event(
            "collaboration.file.saved",
            announcement=_LABELS[self._language]["file_saved"],
        )

    @staticmethod
    def _payload(value: Mapping[str, object] | None) -> dict[str, object]:
        if value is None:
            return {}
        if not isinstance(value, Mapping) or len(value) > 2:
            raise TypeError("collaboration browser payload is invalid")
        normalized: dict[str, object] = {}
        for key, item in value.items():
            if type(key) is not str or not key or len(key) > 64:
                raise ValueError("collaboration browser payload key is invalid")
            normalized[key] = item
        return normalized

    def dispatch(
        self,
        command: object,
        payload: Mapping[str, object] | None = None,
    ) -> ClassroomCollaborationWebViewEvent:
        try:
            if type(command) is not str or not command.startswith("collaboration.") or len(command) > 80:
                raise ValueError("unsupported collaboration browser command")
            data = self._payload(payload)
            if command == "collaboration.chat.send":
                if set(data) != {"body"}:
                    raise ValueError("chat send fields are invalid")
                return self._send_chat(data["body"])
            if command == "collaboration.chat.sync":
                if data:
                    raise ValueError("chat sync accepts no fields")
                return self._sync_chat()
            if command == "collaboration.chat.mark_read":
                if data:
                    raise ValueError("mark read accepts no fields")
                return self._mark_read()
            if command == "collaboration.file.choose_upload":
                if data:
                    raise ValueError("file picker accepts no browser fields")
                return self._choose_upload()
            if command in {
                "collaboration.file.retry",
                "collaboration.file.cancel",
                "collaboration.file.save",
            }:
                if set(data) != {"file_key"}:
                    raise ValueError("file action fields are invalid")
                if command.endswith("retry"):
                    return self._retry_file(data["file_key"])
                if command.endswith("cancel"):
                    return self._cancel_file(data["file_key"])
                return self._save_file(data["file_key"])
            raise ValueError("unsupported collaboration browser command")
        except Exception:
            return self._error()


__all__ = [
    "ClassroomCollaborationWebView",
    "ClassroomCollaborationWebViewEvent",
]
