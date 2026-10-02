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
from datetime import datetime, timedelta, timezone
from hashlib import sha256
import hmac
from pathlib import Path
import secrets
import unicodedata

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
from .classroom_realtime_media import ClassroomMediaController
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
        "timestamp": "Час повідомлення",
        "hide": "Приховати повідомлення",
        "mute_sender": "Заборонити надсилання автору",
        "allow_sender": "Дозволити надсилання автору",
        "remove_sender": "Видалити учасника",
        "block_sender": "Видалити й заблокувати учасника",
        "mute_all": "Заборонити чат усім учням",
        "allow_all": "Дозволити чат усім учням",
        "no_messages": "Повідомлень немає.",
        "files": "Файли",
        "sync_files": "Оновити файли",
        "choose_upload": "Вибрати й надіслати файл",
        "no_files": "Файлів немає.",
        "save": "Зберегти",
        "open": "Відкрити",
        "retry": "Повторити",
        "cancel": "Скасувати",
        "sent": "Повідомлення надіслано.",
        "read": "Повідомлення позначено прочитаними.",
        "hidden": "Повідомлення приховано з активного класу.",
        "muted": "Надсилання повідомлень заборонено.",
        "allowed": "Надсилання повідомлень дозволено.",
        "removed": "Учасника видалено з кімнати.",
        "blocked": "Учасника видалено й заблоковано.",
        "muted_all": "Чат для учнів вимкнено.",
        "allowed_all": "Чат для учнів увімкнено.",
        "file_sent": "Файл надіслано.",
        "file_saved": "Файл передано до безпечного збереження.",
        "file_opened": "Файл передано до явного відкриття.",
        "file_cancelled": "Передавання файлу скасовано.",
        "file_retried": "Повторне передавання завершено.",
        "new_file": "Новий файл: {name}.",
        "new_many_files": "Нових файлів: {count}.",
        "file_state_updated": "Стан файла оновлено: {name}.",
        "file_states_updated": "Оновлено стан файлів: {count}.",
        "new_many": "Нових повідомлень: {count}.",
        "unread": "Непрочитаних: {count}",
        "type": "Тип",
        "size": "Розмір",
        "status": "Стан",
        "scan": "Перевірка",
        "unavailable": "Співпраця в класі тимчасово недоступна.",
    },
    UILanguage.EN: {
        "heading": "Classroom collaboration",
        "chat": "Chat",
        "message": "Message",
        "send": "Send",
        "sync": "Refresh chat",
        "mark_read": "Mark read",
        "timestamp": "Message time",
        "hide": "Hide message",
        "mute_sender": "Mute sender",
        "allow_sender": "Allow sender",
        "remove_sender": "Remove participant",
        "block_sender": "Remove and block participant",
        "mute_all": "Mute all students",
        "allow_all": "Allow all students",
        "no_messages": "No messages.",
        "files": "Files",
        "sync_files": "Refresh files",
        "choose_upload": "Choose and send file",
        "no_files": "No files.",
        "save": "Save",
        "open": "Open",
        "retry": "Retry",
        "cancel": "Cancel",
        "sent": "Message sent.",
        "read": "Messages marked read.",
        "hidden": "Message hidden from the active classroom view.",
        "muted": "Message sending disabled for the participant.",
        "allowed": "Message sending enabled for the participant.",
        "removed": "Participant removed from the room.",
        "blocked": "Participant removed and blocked.",
        "muted_all": "Student chat disabled.",
        "allowed_all": "Student chat enabled.",
        "file_sent": "File sent.",
        "file_saved": "File passed to safe save.",
        "file_opened": "File passed to explicit open.",
        "file_cancelled": "File transfer cancelled.",
        "file_retried": "File retry completed.",
        "new_file": "New file: {name}.",
        "new_many_files": "New files: {count}.",
        "file_state_updated": "File status updated: {name}.",
        "file_states_updated": "File statuses updated: {count}.",
        "new_many": "New messages: {count}.",
        "unread": "Unread: {count}",
        "type": "Type",
        "size": "Size",
        "status": "Status",
        "scan": "Scan",
        "unavailable": "Classroom collaboration is temporarily unavailable.",
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
        file_opener: Callable[[str, str], object] | None = None,
        moderation_allowed: Callable[[], bool] | None = None,
        participant_moderation: ClassroomMediaController | None = None,
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
        if file_opener is not None and not callable(file_opener):
            raise TypeError("file_opener must be callable")
        if moderation_allowed is not None and not callable(moderation_allowed):
            raise TypeError("moderation_allowed must be callable")
        if participant_moderation is not None and not isinstance(
            participant_moderation, ClassroomMediaController
        ):
            raise TypeError("participant_moderation must be ClassroomMediaController")
        if not callable(id_factory):
            raise TypeError("id_factory must be callable")
        self._controller = controller
        self._store = store
        self._participant_label = participant_label
        self._language = language
        self._file_picker = file_picker
        self._file_saver = file_saver
        self._file_opener = file_opener
        self._moderation_allowed = moderation_allowed
        self._participant_moderation = participant_moderation
        self._id_factory = id_factory
        self._action_secret = secrets.token_bytes(32)
        self._unread_message_ids: set[str] = set()
        self._removed_participant_ids: set[str] = set()
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
        safe = "".join(
            ch for ch in unicodedata.normalize("NFC", raw)
            if not unicodedata.category(ch).startswith("C")
        )
        label = " ".join(safe.split())[:120]
        return label or _GENERIC_PARTICIPANT[self._language]

    def _moderator(self) -> bool:
        if self._moderation_allowed is None:
            return False
        try:
            return (
                self._moderation_allowed() is True
                and self._controller.can_moderate_chat()
            )
        except Exception:
            return False

    def _participant_moderation_ready(self) -> bool:
        moderation = self._participant_moderation
        if moderation is None:
            return False
        try:
            state = moderation.state
        except Exception:
            return False
        if state.participant_id != self._controller.local_participant_id:
            return False
        return state.room_id in {None, self._controller.room_id}

    def _message_key(self, message_id: str) -> str:
        material = f"{self._controller.room_id}\\0message\\0{message_id}".encode("utf-8")
        return hmac.new(self._action_secret, material, sha256).hexdigest()

    def _message_for_key(self, message_key: object) -> ChatMessageMetadata:
        if type(message_key) is not str or len(message_key) != 64:
            raise ValueError("invalid message action key")
        for item in self._store.room_messages(self._controller.room_id):
            if hmac.compare_digest(self._message_key(item.message_id), message_key):
                return item
        raise LookupError("message action key is not current")

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

    @staticmethod
    def _message_timestamp(sent_at_unix_ms: int) -> tuple[str, str]:
        instant = datetime(1970, 1, 1, tzinfo=timezone.utc) + timedelta(
            milliseconds=sent_at_unix_ms
        )
        return (
            instant.strftime("%Y-%m-%d %H:%M:%S UTC"),
            instant.isoformat(timespec="seconds").replace("+00:00", "Z"),
        )

    @staticmethod
    def _announcement_body(value: str) -> str:
        normalized = unicodedata.normalize("NFC", value)
        safe = "".join(
            " " if ch.isspace() else ""
            if unicodedata.category(ch).startswith("C")
            else ch
            for ch in normalized
        )
        return " ".join(safe.split())[:160]

    def _message_view(self, item: ChatMessageMetadata) -> dict[str, object]:
        moderator = self._moderator()
        sender_active = (
            item.sender_id not in self._removed_participant_ids
            and self._controller.is_current_participant(item.sender_id)
        )
        sender_moderatable = (
            sender_active
            and self._controller.can_moderate_chat_participant(item.sender_id)
        )
        view: dict[str, object] = {
            "dom_id": "collaboration-message-" + sha256(item.message_id.encode("utf-8")).hexdigest()[:16],
            "sender": self._label(item.sender_id),
            "body": item.body,
            "unread": item.message_id in self._unread_message_ids,
            "can_hide": moderator,
            "can_moderate_sender": moderator and sender_moderatable,
            "can_remove_sender": (
                moderator
                and sender_moderatable
                and self._participant_moderation_ready()
            ),
        }
        if item.sent_at_unix_ms is not None:
            timestamp_text, timestamp_datetime = self._message_timestamp(item.sent_at_unix_ms)
            view["timestamp_text"] = timestamp_text
            view["timestamp_datetime"] = timestamp_datetime
        if moderator:
            view["message_key"] = self._message_key(item.message_id)
        return view

    def _file_view(self, item: AttachmentMetadata) -> dict[str, object]:
        labels = _LABELS[self._language]
        can_save = (
            item.transfer_state == "stored"
            and item.scan_state == "clean"
            and self._file_saver is not None
        )
        can_open = (
            item.transfer_state == "stored"
            and item.scan_state == "clean"
            and self._file_opener is not None
        )
        can_retry = (
            item.transfer_state == "failed"
            and item.scan_state != "blocked"
            and item.attachment_id in self._prepared
        )
        can_cancel = (
            item.sender_id == self._controller.local_participant_id
            and item.transfer_state in {"pending", "uploading", "failed"}
        )
        view: dict[str, object] = {
            "dom_id": "collaboration-file-" + sha256(item.attachment_id.encode("utf-8")).hexdigest()[:16],
            "sender": self._label(item.sender_id),
            "name": item.display_name,
            "type_label": f"{labels['type']}: {item.mime_type or '—'}",
            "size_label": f"{labels['size']}: {self._size_label(item.size_bytes)}",
            "status_label": f"{labels['status']}: {_TRANSFER_LABELS[self._language][item.transfer_state]}",
            "scan_label": f"{labels['scan']}: {_SCAN_LABELS[self._language][item.scan_state]}",
            "can_save": can_save,
            "can_open": can_open,
            "can_retry": can_retry,
            "can_cancel": can_cancel,
        }
        if can_save or can_open or can_retry or can_cancel:
            view["file_key"] = self._file_key(item.attachment_id)
        return view

    def unavailable_snapshot(self) -> dict[str, object]:
        labels = _LABELS[self._language]
        return {
            "available": False,
            "heading": labels["heading"],
            "status_message": labels["unavailable"],
            "chat": {
                "heading": labels["chat"],
                "messages": (),
                "unread_count": 0,
            },
            "files": {
                "heading": labels["files"],
                "items": (),
            },
        }

    def safe_snapshot(self) -> dict[str, object]:
        try:
            return self.snapshot()
        except Exception:
            return self.unavailable_snapshot()

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
            "available": True,
            "heading": labels["heading"],
            "chat": {
                "heading": labels["chat"],
                "composer_label": labels["message"],
                "send_label": labels["send"],
                "sync_label": labels["sync"],
                "mark_read_label": labels["mark_read"],
                "timestamp_label": labels["timestamp"],
                "hide_label": labels["hide"],
                "mute_sender_label": labels["mute_sender"],
                "allow_sender_label": labels["allow_sender"],
                "remove_sender_label": labels["remove_sender"],
                "block_sender_label": labels["block_sender"],
                "mute_all_label": labels["mute_all"],
                "allow_all_label": labels["allow_all"],
                "moderation_available": self._moderator(),
                "empty_message": labels["no_messages"],
                "unread_label": labels["unread"].format(count=unread_count),
                "unread_count": unread_count,
                "max_body_chars": MAX_CHAT_BODY_CHARS,
                "messages": tuple(self._message_view(item) for item in messages),
            },
            "files": {
                "heading": labels["files"],
                "sync_label": labels["sync_files"],
                "choose_upload_label": labels["choose_upload"],
                "empty_message": labels["no_files"],
                "save_label": labels["save"],
                "open_label": labels["open"],
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
        payload: dict[str, object] = {"collaboration": self.safe_snapshot()}
        if announcement:
            payload["announcement"] = announcement
        if focus_target:
            payload["focus_target"] = focus_target
        return ClassroomCollaborationWebViewEvent(kind, payload)

    def _error(self) -> ClassroomCollaborationWebViewEvent:
        payload: dict[str, object] = {"message": _GENERIC_FAILURE[self._language]}
        payload["collaboration"] = self.safe_snapshot()
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
            compact_body = self._announcement_body(item.body)
            announcement = f"{self._label(item.sender_id)}: {compact_body}"
        elif len(new_remote) > 1:
            announcement = _LABELS[self._language]["new_many"].format(count=len(new_remote))
        return self._event("collaboration.chat.synced", announcement=announcement)

    def _sync_files(self) -> ClassroomCollaborationWebViewEvent:
        before = {
            item.attachment_id: (item.transfer_state, item.scan_state)
            for item in self._store.room_attachments(self._controller.room_id)
        }
        incoming = self._controller.sync_files()
        after_items = self._store.room_attachments(self._controller.room_id)
        new_remote = tuple(
            item
            for item in incoming
            if item.sender_id != self._controller.local_participant_id
        )
        changed = tuple(
            item
            for item in after_items
            if item.attachment_id in before
            and before[item.attachment_id] != (item.transfer_state, item.scan_state)
        )
        announcement = ""
        if len(new_remote) == 1:
            announcement = _LABELS[self._language]["new_file"].format(
                name=new_remote[0].display_name
            )
        elif len(new_remote) > 1:
            announcement = _LABELS[self._language]["new_many_files"].format(
                count=len(new_remote)
            )
        elif len(changed) == 1:
            announcement = _LABELS[self._language]["file_state_updated"].format(
                name=changed[0].display_name
            )
        elif len(changed) > 1:
            announcement = _LABELS[self._language]["file_states_updated"].format(
                count=len(changed)
            )
        return self._event("collaboration.files.synced", announcement=announcement)

    def _mark_read(self) -> ClassroomCollaborationWebViewEvent:
        self._unread_message_ids.clear()
        return self._event(
            "collaboration.chat.read",
            announcement=_LABELS[self._language]["read"],
            focus_target="collaboration-chat-sync",
        )

    def _hide_message(self, message_key: object) -> ClassroomCollaborationWebViewEvent:
        message = self._message_for_key(message_key)
        self._controller.hide_message(
            actor_id=self._controller.local_participant_id,
            message_id=message.message_id,
            operation_id=self._id_factory("operation"),
        )
        self._unread_message_ids.discard(message.message_id)
        return self._event(
            "collaboration.chat.hidden",
            announcement=_LABELS[self._language]["hidden"],
            focus_target="collaboration-chat-sync",
        )

    def _set_sender_allowed(
        self,
        message_key: object,
        allowed: bool,
    ) -> ClassroomCollaborationWebViewEvent:
        message = self._message_for_key(message_key)
        self._controller.set_chat_send_permission(
            actor_id=self._controller.local_participant_id,
            target_id=message.sender_id,
            allowed=allowed,
            operation_id=self._id_factory("operation"),
        )
        return self._event(
            "collaboration.chat.permission",
            announcement=_LABELS[self._language]["allowed" if allowed else "muted"],
        )

    def _set_all_students_allowed(self, allowed: bool) -> ClassroomCollaborationWebViewEvent:
        self._controller.set_all_students_chat_send_permission(
            actor_id=self._controller.local_participant_id,
            allowed=allowed,
            operation_id=self._id_factory("operation"),
        )
        return self._event(
            "collaboration.chat.permission",
            announcement=_LABELS[self._language]["allowed_all" if allowed else "muted_all"],
        )

    def _remove_sender(
        self,
        message_key: object,
        *,
        block: bool,
    ) -> ClassroomCollaborationWebViewEvent:
        if not self._participant_moderation_ready():
            raise RuntimeError("participant moderation is unavailable")
        message = self._message_for_key(message_key)
        assert self._participant_moderation is not None
        self._participant_moderation.remove_participant(
            actor_id=self._controller.local_participant_id,
            target_id=message.sender_id,
            block=block,
            operation_id=self._id_factory("operation"),
        )
        self._removed_participant_ids.add(message.sender_id)
        return self._event(
            "collaboration.participant.removed",
            announcement=_LABELS[self._language]["blocked" if block else "removed"],
            focus_target="collaboration-chat-sync",
        )

    def _choose_upload(self) -> ClassroomCollaborationWebViewEvent:
        if self._file_picker is None:
            raise RuntimeError("file picker is unavailable")
        selected = self._file_picker()
        if selected is None:
            return self._event("collaboration.file.cancelled")
        if not isinstance(selected, Path):
            raise TypeError("file picker must return pathlib.Path or None")
        attachments = self._store.room_attachments(self._controller.room_id)
        sequence = 0 if not attachments else max(item.sequence_no for item in attachments) + 1
        prepared = self._controller.prepare_file(
            attachment_id=self._id_factory("attachment"),
            local_path=selected,
            sequence_no=sequence,
        )
        try:
            uploaded = self._controller.upload_file(prepared)
        except Exception:
            # Keep the local source path only when canonical durable metadata
            # proves there is a failed transfer that the user can retry.
            try:
                retriable = any(
                    item.attachment_id == prepared.metadata.attachment_id
                    and item.transfer_state == "failed"
                    and item.scan_state != "blocked"
                    for item in self._store.room_attachments(self._controller.room_id)
                )
            except Exception:
                retriable = False
            if retriable:
                self._prepared[prepared.metadata.attachment_id] = prepared
            else:
                self._prepared.pop(prepared.metadata.attachment_id, None)
            raise
        if uploaded.transfer_state == "failed":
            if uploaded.scan_state != "blocked":
                self._prepared[uploaded.attachment_id] = prepared
            else:
                self._prepared.pop(uploaded.attachment_id, None)
            return self._error()
        self._prepared.pop(uploaded.attachment_id, None)
        return self._event(
            "collaboration.file.sent",
            announcement=_LABELS[self._language]["file_sent"],
        )

    def _open_file(self, file_key: object) -> ClassroomCollaborationWebViewEvent:
        if self._file_opener is None:
            raise RuntimeError("file open adapter is unavailable")
        attachment = self._attachment_for_key(file_key)
        token = self._controller.issue_download_token(attachment_id=attachment.attachment_id)
        self._file_opener(token, attachment.display_name)
        return self._event(
            "collaboration.file.opened",
            announcement=_LABELS[self._language]["file_opened"],
        )

    def _retry_file(self, file_key: object) -> ClassroomCollaborationWebViewEvent:
        attachment = self._attachment_for_key(file_key)
        prepared = self._prepared.get(attachment.attachment_id)
        if prepared is None:
            raise RuntimeError("retry source is unavailable")
        retried = self._controller.retry_file(prepared)
        if retried.transfer_state == "failed":
            if retried.scan_state == "blocked":
                self._prepared.pop(retried.attachment_id, None)
            return self._error()
        self._prepared.pop(retried.attachment_id, None)
        return self._event(
            "collaboration.file.retried",
            announcement=_LABELS[self._language]["file_retried"],
            focus_target="collaboration-file-choose",
        )

    def _cancel_file(self, file_key: object) -> ClassroomCollaborationWebViewEvent:
        attachment = self._attachment_for_key(file_key)
        self._controller.cancel_file(attachment.attachment_id)
        self._prepared.pop(attachment.attachment_id, None)
        return self._event(
            "collaboration.file.cancelled",
            announcement=_LABELS[self._language]["file_cancelled"],
            focus_target="collaboration-file-choose",
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
            if command in {
                "collaboration.chat.hide",
                "collaboration.chat.mute_sender",
                "collaboration.chat.allow_sender",
                "collaboration.participant.remove_sender",
                "collaboration.participant.block_sender",
            }:
                if set(data) != {"message_key"}:
                    raise ValueError("chat moderation fields are invalid")
                if command.endswith("hide"):
                    return self._hide_message(data["message_key"])
                if command.startswith("collaboration.participant."):
                    return self._remove_sender(
                        data["message_key"],
                        block=command.endswith("block_sender"),
                    )
                return self._set_sender_allowed(
                    data["message_key"],
                    allowed=command.endswith("allow_sender"),
                )
            if command in {
                "collaboration.chat.mute_all_students",
                "collaboration.chat.allow_all_students",
            }:
                if data:
                    raise ValueError("global chat moderation accepts no fields")
                return self._set_all_students_allowed(
                    allowed=command.endswith("allow_all_students")
                )
            if command == "collaboration.file.sync":
                if data:
                    raise ValueError("file sync accepts no browser fields")
                return self._sync_files()
            if command == "collaboration.file.choose_upload":
                if data:
                    raise ValueError("file picker accepts no browser fields")
                return self._choose_upload()
            if command in {
                "collaboration.file.retry",
                "collaboration.file.cancel",
                "collaboration.file.save",
                "collaboration.file.open",
            }:
                if set(data) != {"file_key"}:
                    raise ValueError("file action fields are invalid")
                if command.endswith("retry"):
                    return self._retry_file(data["file_key"])
                if command.endswith("cancel"):
                    return self._cancel_file(data["file_key"])
                if command.endswith("open"):
                    return self._open_file(data["file_key"])
                return self._save_file(data["file_key"])
            raise ValueError("unsupported collaboration browser command")
        except Exception:
            return self._error()


__all__ = [
    "ClassroomCollaborationWebView",
    "ClassroomCollaborationWebViewEvent",
]
