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
    FileTransferProgress,
    PreparedFile,
)
from .classroom_collaboration_storage import (
    AttachmentMetadata,
    ChatMessageMetadata,
    ClassroomCollaborationSQLiteStore,
)
from .classroom_realtime_media import ClassroomMediaController
from .classroom_domain import MAX_WIRE_INTEGER
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
        "send_pending": "Надсилання повідомлення…",
        "sync": "Оновити чат",
        "mark_read": "Позначити прочитаним",
        "older_messages": "Старіші повідомлення",
        "newer_messages": "Новіші повідомлення",
        "history_page": "Історія повідомлень: сторінка {current} з {total}",
        "history_empty": "Історія повідомлень порожня",
        "timestamp": "Час повідомлення",
        "retention": "Зберігання",
        "chat_retention_policy": "Зберігання нових повідомлень: {value}",
        "file_retention_policy": "Зберігання нових файлів: {value}",
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
        "sync_files_pending": "Оновлення файлів…",
        "choose_upload": "Вибрати й надіслати файл",
        "choose_upload_pending": "Вибір або надсилання файла…",
        "save_pending": "Підготовка збереження файла…",
        "open_pending": "Підготовка відкриття файла…",
        "retry_pending": "Повторне передавання файла…",
        "cancel_pending": "Скасування передавання файла…",
        "older_files": "Старіші файли",
        "newer_files": "Новіші файли",
        "file_page": "Історія файлів: сторінка {current} з {total}",
        "file_history_empty": "Історія файлів порожня",
        "no_files": "Файлів немає.",
        "save": "Зберегти",
        "open": "Відкрити",
        "retry": "Повторити",
        "cancel": "Скасувати",
        "sent": "Повідомлення надіслано.",
        "send_failed": "Не вдалося підтвердити надсилання повідомлення. Повторіть або оновіть чат.",
        "chat_sync_failed": "Не вдалося оновити чат.",
        "read": "Повідомлення позначено прочитаними.",
        "hidden": "Повідомлення приховано з активного класу.",
        "muted": "Надсилання повідомлень заборонено.",
        "allowed": "Надсилання повідомлень дозволено.",
        "removed": "Учасника видалено з кімнати.",
        "blocked": "Учасника видалено й заблоковано.",
        "muted_all": "Чат для учнів вимкнено.",
        "allowed_all": "Чат для учнів увімкнено.",
        "file_selection_cancelled": "Вибір файла скасовано.",
        "file_selection_failed": "Не вдалося вибрати файл.",
        "file_sent": "Файл надіслано: {name}.",
        "file_saved": "Файл передано до безпечного збереження: {name}.",
        "file_opened": "Файл передано до явного відкриття: {name}.",
        "file_cancelled": "Передавання файлу скасовано: {name}.",
        "file_retried": "Повторне передавання завершено: {name}.",
        "file_upload_failed": "Не вдалося передати файл: {name}.",
        "file_retry_failed": "Не вдалося повторити передавання файла: {name}.",
        "file_save_failed": "Не вдалося підготувати безпечне збереження файла: {name}.",
        "file_open_failed": "Не вдалося підготувати відкриття файла: {name}.",
        "file_cancel_failed": "Не вдалося скасувати передавання файла: {name}.",
        "file_sync_failed": "Не вдалося оновити файли.",
        "file_progress": "Передано {done} з {total}: {name}.",
        "file_progress_finalizing": "Усі байти передано; завершується передавання: {name}.",
        "file_progress_label": "Прогрес передавання файла",
        "new_file": "Новий файл: {name}.",
        "new_many_files": "Нових файлів: {count}.",
        "file_state_updated": "Стан файла оновлено: {name}.",
        "file_states_updated": "Оновлено стан файлів: {count}.",
        "new_many": "Нових повідомлень: {count}.",
        "unread": "Непрочитаних: {count}",
        "unread_message": "Непрочитане",
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
        "send_pending": "Sending message…",
        "sync": "Refresh chat",
        "mark_read": "Mark read",
        "older_messages": "Older messages",
        "newer_messages": "Newer messages",
        "history_page": "Message history page {current} of {total}",
        "history_empty": "Message history is empty",
        "timestamp": "Message time",
        "retention": "Retention",
        "chat_retention_policy": "New message retention: {value}",
        "file_retention_policy": "New file retention: {value}",
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
        "sync_files_pending": "Refreshing files…",
        "choose_upload": "Choose and send file",
        "choose_upload_pending": "Choosing or sending file…",
        "save_pending": "Preparing file save…",
        "open_pending": "Preparing file open…",
        "retry_pending": "Retrying file transfer…",
        "cancel_pending": "Cancelling file transfer…",
        "older_files": "Older files",
        "newer_files": "Newer files",
        "file_page": "File history page {current} of {total}",
        "file_history_empty": "File history is empty",
        "no_files": "No files.",
        "save": "Save",
        "open": "Open",
        "retry": "Retry",
        "cancel": "Cancel",
        "sent": "Message sent.",
        "send_failed": "Message send was not confirmed. Retry or refresh chat.",
        "chat_sync_failed": "Chat refresh failed.",
        "read": "Messages marked read.",
        "hidden": "Message hidden from the active classroom view.",
        "muted": "Message sending disabled for the participant.",
        "allowed": "Message sending enabled for the participant.",
        "removed": "Participant removed from the room.",
        "blocked": "Participant removed and blocked.",
        "muted_all": "Student chat disabled.",
        "allowed_all": "Student chat enabled.",
        "file_selection_cancelled": "File selection cancelled.",
        "file_selection_failed": "Could not choose file.",
        "file_sent": "File sent: {name}.",
        "file_saved": "File passed to safe save: {name}.",
        "file_opened": "File passed to explicit open: {name}.",
        "file_cancelled": "File transfer cancelled: {name}.",
        "file_retried": "File retry completed: {name}.",
        "file_upload_failed": "File transfer failed: {name}.",
        "file_retry_failed": "File retry failed: {name}.",
        "file_save_failed": "Could not prepare safe file save: {name}.",
        "file_open_failed": "Could not prepare file open: {name}.",
        "file_cancel_failed": "Could not cancel file transfer: {name}.",
        "file_sync_failed": "File refresh failed.",
        "file_progress": "Transferred {done} of {total}: {name}.",
        "file_progress_finalizing": "All bytes transferred; finalizing transfer: {name}.",
        "file_progress_label": "File transfer progress",
        "new_file": "New file: {name}.",
        "new_many_files": "New files: {count}.",
        "file_state_updated": "File status updated: {name}.",
        "file_states_updated": "File statuses updated: {count}.",
        "new_many": "New messages: {count}.",
        "unread": "Unread: {count}",
        "unread_message": "Unread",
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
_RETENTION_LABELS = {
    UILanguage.UA: {
        "transient": "transient (тимчасове)",
        "session": "session (сесійне)",
        "persistent": "persistent (постійне)",
    },
    UILanguage.EN: {
        "transient": "transient",
        "session": "session",
        "persistent": "persistent",
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


_CHAT_HISTORY_BUCKET_SIZE = 50
_FILE_HISTORY_BUCKET_SIZE = 50
_MAX_PENDING_CHAT_DRAFTS = 32


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
        file_progress_event_sink: Callable[[ClassroomCollaborationWebViewEvent], object] | None = None,
        moderation_allowed: Callable[[], bool] | None = None,
        participant_moderation: ClassroomMediaController | None = None,
        chat_retention: str = "session",
        file_retention: str = "session",
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
        if file_progress_event_sink is not None and not callable(file_progress_event_sink):
            raise TypeError("file_progress_event_sink must be callable")
        if moderation_allowed is not None and not callable(moderation_allowed):
            raise TypeError("moderation_allowed must be callable")
        if participant_moderation is not None and not isinstance(
            participant_moderation, ClassroomMediaController
        ):
            raise TypeError("participant_moderation must be ClassroomMediaController")
        if type(chat_retention) is not str or chat_retention not in {"transient", "session", "persistent"}:
            raise ValueError("chat_retention must be transient, session, or persistent")
        if type(file_retention) is not str or file_retention not in {"transient", "session", "persistent"}:
            raise ValueError("file_retention must be transient, session, or persistent")
        if not callable(id_factory):
            raise TypeError("id_factory must be callable")
        self._controller = controller
        self._store = store
        self._participant_label = participant_label
        self._language = language
        self._file_picker = file_picker
        self._file_saver = file_saver
        self._file_opener = file_opener
        self._file_progress_event_sink = file_progress_event_sink
        self._moderation_allowed = moderation_allowed
        self._participant_moderation = participant_moderation
        self._chat_retention = chat_retention
        self._file_retention = file_retention
        self._id_factory = id_factory
        self._action_secret = secrets.token_bytes(32)
        self._browser_session_key = secrets.token_hex(16)
        self._unread_message_ids: set[str] = set()
        # Ambiguous chat sends are host recovery state, not browser capability
        # state. Keep only keyed fingerprints -> stable message IDs so multiple
        # unresolved drafts cannot overwrite one another and raw draft text is
        # not retained outside the browser.
        self._pending_chat_secret = secrets.token_bytes(32)
        self._pending_chat: dict[str, str] = {}
        self._chat_page_bucket: int | None = None
        self._file_page_bucket: int | None = None
        self._removed_participant_ids: set[str] = set()
        self._prepared: dict[str, PreparedFile] = {}
        # Ephemeral presentation state only. Durable transfer truth remains in the
        # canonical collaboration store/provider; this merely survives DOM redraws.
        self._file_progress: tuple[str, str, int, int, bool] | None = None
        self._file_progress_attempt_token: bytes | None = None
        self._file_progress_revision = 0

    @property
    def language(self) -> UILanguage:
        return self._language

    def set_language(self, language: UILanguage) -> None:
        if not isinstance(language, UILanguage):
            raise TypeError("language must be UILanguage")
        if language is not self._language and self._file_progress is not None:
            # Progress revision orders the complete browser projection, not just
            # byte counters. A language change therefore supersedes any delayed
            # event carrying the old localized label/text for the same transfer.
            self._advance_file_progress_revision()
        self._language = language

    def set_file_progress_event_sink(
        self,
        sink: Callable[[ClassroomCollaborationWebViewEvent], object] | None,
    ) -> None:
        """Bind a trusted-host observer for incremental file-transfer UI events."""

        if sink is not None and not callable(sink):
            raise TypeError("file progress event sink must be callable")
        self._file_progress_event_sink = sink

    def _advance_file_progress_revision(self) -> None:
        if self._file_progress_revision >= MAX_WIRE_INTEGER:
            raise RuntimeError("file progress presentation revision exhausted")
        self._file_progress_revision += 1

    def _clear_file_progress(self) -> None:
        """Clear presentation progress and advance its session-local ordering."""

        if self._file_progress is not None:
            self._advance_file_progress_revision()
        self._file_progress = None
        self._file_progress_attempt_token = None

    def retire_browser_session(self) -> None:
        """Invalidate browser capabilities and release session-only UI state.

        Durable chat/file metadata remains owned by the collaboration store. This
        method retires browser capabilities, unread/page state and sensitive local
        file retry paths. Ambiguous chat-send IDs remain host recovery state across
        a browser rebind so reconnect cannot mint a duplicate logical message; raw
        draft text is never retained here.
        """

        # The progress observer belongs to the retiring host/browser session.
        # Clear it before rotating browser capabilities so a reused WebView
        # cannot send later file metadata to the previous host channel.
        self._file_progress_event_sink = None
        self._action_secret = secrets.token_bytes(32)
        self._browser_session_key = secrets.token_hex(16)
        self._unread_message_ids.clear()
        self._chat_page_bucket = None
        self._file_page_bucket = None
        self._removed_participant_ids.clear()
        self._prepared.clear()
        self._file_progress = None
        self._file_progress_attempt_token = None
        self._file_progress_revision = 0

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

    def _dom_id(self, kind: str, identity: str) -> str:
        material = (
            f"{self._controller.room_id}\0dom\0{kind}\0{identity}"
        ).encode("utf-8")
        digest = hmac.new(self._action_secret, material, sha256).hexdigest()[:24]
        return f"collaboration-{kind}-{digest}"

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

    def _progress_key(self, attachment_id: str) -> str:
        """Return a per-attempt session-bound identity with no action authority."""

        token = self._file_progress_attempt_token
        if token is None:
            raise RuntimeError("file progress attempt is not active")
        material = (
            f"{self._controller.room_id}\0progress\0{attachment_id}"
        ).encode("utf-8") + b"\0" + token
        return hmac.new(self._action_secret, material, sha256).hexdigest()

    def _file_progress_callback(self) -> Callable[[FileTransferProgress], None]:
        """Bind progress delivery to the exact browser-session transfer attempt."""

        attempt_token = self._file_progress_attempt_token
        if attempt_token is None:
            raise RuntimeError("file progress attempt is not active")

        def publish(sample: FileTransferProgress) -> None:
            current = self._file_progress_attempt_token
            if current is None or not hmac.compare_digest(current, attempt_token):
                # A retired browser session or a newer upload/retry attempt has
                # superseded this callback. Late synchronous provider samples
                # must not resurrect presentation state in the new session.
                return
            self._publish_file_progress(sample)

        return publish

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

    def _chat_draft_fingerprint(self, value: str) -> str:
        return hmac.new(
            self._pending_chat_secret,
            value.encode("utf-8"),
            sha256,
        ).hexdigest()

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

    def _message_view(
        self,
        item: ChatMessageMetadata,
        *,
        moderator: bool,
    ) -> dict[str, object]:
        sender_moderatable = (
            moderator
            and item.sender_id not in self._removed_participant_ids
            and self._controller.can_moderate_chat_participant(item.sender_id)
        )
        sender_label = self._label(item.sender_id)
        action_sender = self._announcement_body(sender_label)
        action_message = self._announcement_body(
            f"{sender_label}: {item.body}"
        )
        view: dict[str, object] = {
            "dom_id": self._dom_id("message", item.message_id),
            "sender": sender_label,
            "action_sender": action_sender,
            "action_message": action_message,
            "body": item.body,
            "retention_label": (
                f"{_LABELS[self._language]['retention']}: "
                f"{_RETENTION_LABELS[self._language][item.retention]}"
            ),
            "unread": item.message_id in self._unread_message_ids,
            "can_hide": moderator,
            "can_moderate_sender": sender_moderatable,
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
            "dom_id": self._dom_id("file", item.attachment_id),
            "sender": self._label(item.sender_id),
            "name": item.display_name,
            "type_label": f"{labels['type']}: {item.mime_type or '—'}",
            "size_label": f"{labels['size']}: {self._size_label(item.size_bytes)}",
            "status_label": f"{labels['status']}: {_TRANSFER_LABELS[self._language][item.transfer_state]}",
            "scan_label": f"{labels['scan']}: {_SCAN_LABELS[self._language][item.scan_state]}",
            "retention_label": (
                f"{labels['retention']}: "
                f"{_RETENTION_LABELS[self._language][item.retention]}"
            ),
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
            "session_key": self._browser_session_key,
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

    def _chat_page_projection(
        self,
        messages: tuple[ChatMessageMetadata, ...],
    ) -> tuple[tuple[ChatMessageMetadata, ...], int, int, bool, bool]:
        if not messages:
            self._chat_page_bucket = None
            return (), 0, 0, False, False
        buckets = tuple(
            sorted({item.sequence_no // _CHAT_HISTORY_BUCKET_SIZE for item in messages})
        )
        bucket = self._chat_page_bucket
        if bucket is None:
            bucket = buckets[-1]
        elif bucket not in buckets:
            lower = tuple(item for item in buckets if item < bucket)
            bucket = lower[-1] if lower else buckets[0]
            self._chat_page_bucket = None if bucket == buckets[-1] else bucket
        index = buckets.index(bucket)
        page = tuple(
            item
            for item in messages
            if item.sequence_no // _CHAT_HISTORY_BUCKET_SIZE == bucket
        )
        return page, index, len(buckets), index > 0, index < len(buckets) - 1

    def _move_chat_page(self, direction: int) -> ClassroomCollaborationWebViewEvent:
        if direction not in {-1, 1}:
            raise ValueError("chat history direction is invalid")
        messages = self._store.room_messages(self._controller.room_id)
        _, index, page_count, can_older, can_newer = self._chat_page_projection(messages)
        if not page_count:
            raise ValueError("chat history is empty")
        if direction < 0 and not can_older:
            raise ValueError("older chat history is unavailable")
        if direction > 0 and not can_newer:
            raise ValueError("newer chat history is unavailable")
        buckets = tuple(
            sorted({item.sequence_no // _CHAT_HISTORY_BUCKET_SIZE for item in messages})
        )
        target_index = index + direction
        target_bucket = buckets[target_index]
        self._chat_page_bucket = None if target_index == len(buckets) - 1 else target_bucket
        target_can_older = target_index > 0
        target_can_newer = target_index < len(buckets) - 1
        if direction < 0:
            focus_target = (
                "collaboration-chat-older"
                if target_can_older
                else "collaboration-chat-newer"
            )
        else:
            focus_target = (
                "collaboration-chat-newer"
                if target_can_newer
                else "collaboration-chat-older"
            )
        return self._event(
            "collaboration.chat.page",
            announcement=_LABELS[self._language]["history_page"].format(
                current=target_index + 1,
                total=len(buckets),
            ),
            focus_target=focus_target,
        )

    def _file_page_projection(
        self,
        attachments: tuple[AttachmentMetadata, ...],
    ) -> tuple[tuple[AttachmentMetadata, ...], int, int, bool, bool]:
        if not attachments:
            self._file_page_bucket = None
            return (), 0, 0, False, False
        buckets = tuple(
            sorted({item.sequence_no // _FILE_HISTORY_BUCKET_SIZE for item in attachments})
        )
        bucket = self._file_page_bucket
        if bucket is None:
            bucket = buckets[-1]
        elif bucket not in buckets:
            lower = tuple(item for item in buckets if item < bucket)
            bucket = lower[-1] if lower else buckets[0]
            self._file_page_bucket = None if bucket == buckets[-1] else bucket
        index = buckets.index(bucket)
        page = tuple(
            item
            for item in attachments
            if item.sequence_no // _FILE_HISTORY_BUCKET_SIZE == bucket
        )
        return page, index, len(buckets), index > 0, index < len(buckets) - 1

    def _move_file_page(self, direction: int) -> ClassroomCollaborationWebViewEvent:
        if direction not in {-1, 1}:
            raise ValueError("file history direction is invalid")
        attachments = tuple(
            item
            for item in self._store.room_attachments(self._controller.room_id)
            if item.transfer_state != "deleted"
        )
        _, index, page_count, can_older, can_newer = self._file_page_projection(attachments)
        if not page_count:
            raise ValueError("file history is empty")
        if direction < 0 and not can_older:
            raise ValueError("older file history is unavailable")
        if direction > 0 and not can_newer:
            raise ValueError("newer file history is unavailable")
        buckets = tuple(
            sorted({item.sequence_no // _FILE_HISTORY_BUCKET_SIZE for item in attachments})
        )
        target_index = index + direction
        target_bucket = buckets[target_index]
        self._file_page_bucket = None if target_index == len(buckets) - 1 else target_bucket
        target_can_older = target_index > 0
        target_can_newer = target_index < len(buckets) - 1
        if direction < 0:
            focus_target = (
                "collaboration-file-older"
                if target_can_older
                else "collaboration-file-newer"
            )
        else:
            focus_target = (
                "collaboration-file-newer"
                if target_can_newer
                else "collaboration-file-older"
            )
        return self._event(
            "collaboration.file.page",
            announcement=_LABELS[self._language]["file_page"].format(
                current=target_index + 1,
                total=len(buckets),
            ),
            focus_target=focus_target,
        )

    def snapshot(self) -> dict[str, object]:
        labels = _LABELS[self._language]
        messages = self._store.room_messages(self._controller.room_id)
        (
            message_page,
            message_page_index,
            message_page_count,
            can_older_messages,
            can_newer_messages,
        ) = self._chat_page_projection(messages)
        attachments = tuple(
            item
            for item in self._store.room_attachments(self._controller.room_id)
            if item.transfer_state != "deleted"
        )
        (
            attachment_page,
            attachment_page_index,
            attachment_page_count,
            can_older_files,
            can_newer_files,
        ) = self._file_page_projection(attachments)
        visible_ids = {item.message_id for item in messages}
        self._unread_message_ids.intersection_update(visible_ids)
        unread_count = len(self._unread_message_ids)
        moderation_available = self._moderator()
        return {
            "available": True,
            "session_key": self._browser_session_key,
            "heading": labels["heading"],
            "chat": {
                "heading": labels["chat"],
                "composer_label": labels["message"],
                "send_label": labels["send"],
                "send_pending_label": labels["send_pending"],
                "sync_label": labels["sync"],
                "mark_read_label": labels["mark_read"],
                "older_label": labels["older_messages"],
                "newer_label": labels["newer_messages"],
                "page_label": (
                    labels["history_page"].format(
                        current=message_page_index + 1,
                        total=message_page_count,
                    )
                    if message_page_count
                    else labels["history_empty"]
                ),
                "can_older": can_older_messages,
                "can_newer": can_newer_messages,
                "timestamp_label": labels["timestamp"],
                "retention_label": labels["retention"],
                "retention_policy_label": labels["chat_retention_policy"].format(
                    value=_RETENTION_LABELS[self._language][self._chat_retention]
                ),
                "hide_label": labels["hide"],
                "mute_sender_label": labels["mute_sender"],
                "allow_sender_label": labels["allow_sender"],
                "remove_sender_label": labels["remove_sender"],
                "block_sender_label": labels["block_sender"],
                "mute_all_label": labels["mute_all"],
                "allow_all_label": labels["allow_all"],
                "moderation_available": moderation_available,
                "empty_message": labels["no_messages"],
                "unread_label": labels["unread"].format(count=unread_count),
                "unread_message_label": labels["unread_message"],
                "unread_count": unread_count,
                "max_body_chars": MAX_CHAT_BODY_CHARS,
                "messages": tuple(
                    self._message_view(item, moderator=moderation_available)
                    for item in message_page
                ),
            },
            "files": {
                "heading": labels["files"],
                "sync_label": labels["sync_files"],
                "sync_pending_label": labels["sync_files_pending"],
                "choose_upload_label": labels["choose_upload"],
                "choose_upload_pending_label": labels["choose_upload_pending"],
                "save_pending_label": labels["save_pending"],
                "open_pending_label": labels["open_pending"],
                "retry_pending_label": labels["retry_pending"],
                "cancel_pending_label": labels["cancel_pending"],
                "retention_policy_label": labels["file_retention_policy"].format(
                    value=_RETENTION_LABELS[self._language][self._file_retention]
                ),
                "older_label": labels["older_files"],
                "newer_label": labels["newer_files"],
                "page_label": (
                    labels["file_page"].format(
                        current=attachment_page_index + 1,
                        total=attachment_page_count,
                    )
                    if attachment_page_count
                    else labels["file_history_empty"]
                ),
                "can_older": can_older_files,
                "can_newer": can_newer_files,
                "empty_message": labels["no_files"],
                "save_label": labels["save"],
                "open_label": labels["open"],
                "retry_label": labels["retry"],
                "cancel_label": labels["cancel"],
                "progress_label": labels["file_progress_label"],
                "progress_revision": self._file_progress_revision,
                "transfer_progress": self._file_progress_view(),
                "can_choose_upload": self._file_picker is not None,
                "items": tuple(self._file_view(item) for item in attachment_page),
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

    def _error(
        self,
        *,
        message: str = "",
        focus_target: str = "",
    ) -> ClassroomCollaborationWebViewEvent:
        payload: dict[str, object] = {
            "message": message or _GENERIC_FAILURE[self._language]
        }
        payload["collaboration"] = self.safe_snapshot()
        if focus_target:
            payload["focus_target"] = focus_target
        return ClassroomCollaborationWebViewEvent("error", payload)

    def _file_progress_view(self) -> dict[str, object] | None:
        progress = self._file_progress
        if progress is None:
            return None
        _attachment_id, name, transferred_bytes, total_bytes, complete = progress
        labels = _LABELS[self._language]
        return {
            "transfer_key": self._progress_key(_attachment_id),
            "progress_revision": self._file_progress_revision,
            "name": name,
            "transferred_bytes": transferred_bytes,
            "total_bytes": total_bytes,
            "complete": complete,
            "label": labels["file_progress_label"],
            "text": (
                labels["file_progress_finalizing"].format(name=name)
                if transferred_bytes == total_bytes and not complete
                else labels["file_progress"].format(
                    done=self._size_label(transferred_bytes),
                    total=self._size_label(total_bytes),
                    name=name,
                )
            ),
        }

    def _publish_file_progress(self, sample: FileTransferProgress) -> None:
        """Forward a secret-safe, session-bound progress event to the trusted host."""

        if type(sample) is not FileTransferProgress:
            raise TypeError("file transfer progress must be FileTransferProgress")
        attachment = next(
            (
                item
                for item in self._store.room_attachments(self._controller.room_id)
                if item.attachment_id == sample.attachment_id
            ),
            None,
        )
        if attachment is None or attachment.size_bytes != sample.total_bytes:
            raise RuntimeError("file transfer progress no longer matches local metadata")
        self._advance_file_progress_revision()
        self._file_progress = (
            attachment.attachment_id,
            attachment.display_name,
            sample.transferred_bytes,
            sample.total_bytes,
            sample.complete,
        )
        sink = self._file_progress_event_sink
        if sink is None:
            return
        progress = self._file_progress_view()
        if progress is None:
            return
        sink(
            ClassroomCollaborationWebViewEvent(
                "collaboration.file.progress",
                {
                    "file_progress": {
                        "session_key": self._browser_session_key,
                        **progress,
                    }
                },
            )
        )

    def _file_announcement(self, label: str, display_name: str) -> str:
        return _LABELS[self._language][label].format(
            name=self._announcement_body(display_name)
        )

    def _send_chat(self, body: object) -> ClassroomCollaborationWebViewEvent:
        if type(body) is not str:
            raise TypeError("chat body must be text")
        if (
            not body
            or not body.strip()
            or len(body) > MAX_CHAT_BODY_CHARS
            or "\x00" in body
            or any(0xD800 <= ord(ch) <= 0xDFFF for ch in body)
        ):
            raise ValueError("chat body is outside the browser safety boundary")
        fingerprint = self._chat_draft_fingerprint(body)
        message_id = self._pending_chat.get(fingerprint)
        if message_id is None:
            if len(self._pending_chat) >= _MAX_PENDING_CHAT_DRAFTS:
                return self._error(
                    message=_LABELS[self._language]["send_failed"],
                    focus_target="collaboration-chat-input",
                )
            message_id = self._id_factory("message")
            self._pending_chat[fingerprint] = message_id
        try:
            self._controller.send_chat(
                message_id=message_id,
                body=body,
                retention=self._chat_retention,
            )
        except Exception:
            return self._error(
                message=_LABELS[self._language]["send_failed"],
                focus_target="collaboration-chat-input",
            )
        self._pending_chat.pop(fingerprint, None)
        self._chat_page_bucket = None
        return self._event(
            "collaboration.chat.sent",
            announcement=_LABELS[self._language]["sent"],
            focus_target="collaboration-chat-input",
        )

    def receive_chat(
        self,
        message: ChatMessageMetadata,
    ) -> ClassroomCollaborationWebViewEvent:
        """Project a trusted-host live chat delivery into the current UI session."""

        if type(message) is ChatMessageMetadata:
            pending_fingerprints = tuple(
                fingerprint
                for fingerprint, message_id in self._pending_chat.items()
                if message_id == message.message_id
            )
            if pending_fingerprints:
                fingerprint = self._chat_draft_fingerprint(message.body)
                if (
                    fingerprint not in pending_fingerprints
                    or message.sender_id != self._controller.local_participant_id
                    or message.retention != self._chat_retention
                ):
                    raise ValueError(
                        "live chat conflicts with pending send identity"
                    )

        before_ids = {
            item.message_id
            for item in self._store.room_messages(
                self._controller.room_id,
                include_hidden=True,
            )
        }
        received = self._controller.receive_chat(message)
        is_new = received.message_id not in before_ids
        recovered_fingerprints = tuple(
            fingerprint
            for fingerprint, message_id in self._pending_chat.items()
            if message_id == received.message_id
        )
        pending_recovered = bool(recovered_fingerprints)
        for fingerprint in recovered_fingerprints:
            self._pending_chat.pop(fingerprint, None)

        if received.hidden:
            self._unread_message_ids.discard(received.message_id)

        announcement = ""
        if (
            is_new
            and not received.hidden
            and received.sender_id != self._controller.local_participant_id
        ):
            self._unread_message_ids.add(received.message_id)
            announcement = (
                f"{self._label(received.sender_id)}: "
                f"{self._announcement_body(received.body)}"
            )
        elif pending_recovered:
            announcement = _LABELS[self._language]["sent"]
        return self._event(
            "collaboration.chat.received",
            announcement=announcement,
        )

    def refresh_chat(self) -> ClassroomCollaborationWebViewEvent:
        """Refresh canonical chat/history state after a trusted host notification."""

        return self._sync_chat()

    def _sync_chat(self) -> ClassroomCollaborationWebViewEvent:
        before = {
            item.message_id
            for item in self._store.room_messages(self._controller.room_id, include_hidden=True)
        }
        try:
            incoming = self._controller.sync_chat()
        except Exception:
            return self._error(
                message=_LABELS[self._language]["chat_sync_failed"],
                focus_target="collaboration-chat-sync",
            )
        current_messages = self._store.room_messages(
            self._controller.room_id,
            include_hidden=True,
        )
        current_by_id = {
            item.message_id: item
            for item in current_messages
        }
        visible_message_ids = {
            item.message_id
            for item in current_messages
            if not item.hidden
        }
        self._unread_message_ids.intersection_update(visible_message_ids)
        recovered_fingerprints: list[str] = []
        pending_conflict = False
        for fingerprint, message_id in self._pending_chat.items():
            item = current_by_id.get(message_id)
            if item is None:
                continue
            if (
                item.sender_id == self._controller.local_participant_id
                and item.retention == self._chat_retention
                and self._chat_draft_fingerprint(item.body) == fingerprint
            ):
                recovered_fingerprints.append(fingerprint)
            else:
                pending_conflict = True
        for fingerprint in recovered_fingerprints:
            self._pending_chat.pop(fingerprint, None)
        if pending_conflict:
            return self._error(
                message=_LABELS[self._language]["send_failed"],
                focus_target="collaboration-chat-sync",
            )
        pending_recovered = bool(recovered_fingerprints)
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
        elif pending_recovered:
            announcement = _LABELS[self._language]["sent"]
        return self._event("collaboration.chat.synced", announcement=announcement)

    def refresh_files(self) -> ClassroomCollaborationWebViewEvent:
        """Refresh canonical file/history state after a trusted host notification."""

        return self._sync_files()

    def _sync_files(self) -> ClassroomCollaborationWebViewEvent:
        try:
            before = {
                item.attachment_id: (item.transfer_state, item.scan_state)
                for item in self._store.room_attachments(self._controller.room_id)
            }
            incoming = self._controller.sync_files()
            after_items = self._store.room_attachments(self._controller.room_id)
        except Exception:
            return self._error(
                message=_LABELS[self._language]["file_sync_failed"],
                focus_target="collaboration-file-sync",
            )
        active_attachment_ids = {
            item.attachment_id
            for item in after_items
            if item.transfer_state != "deleted"
        }
        if (
            self._file_progress is not None
            and self._file_progress[0] not in active_attachment_ids
        ):
            # Durable sync is authoritative over presentation-only terminal
            # progress. Do not keep announcing a completed transfer for an
            # attachment that has since been tombstoned or removed.
            self._clear_file_progress()
        retriable_local_ids = {
            item.attachment_id
            for item in after_items
            if item.sender_id == self._controller.local_participant_id
            and item.transfer_state == "failed"
            and item.scan_state != "blocked"
        }
        for attachment_id in tuple(self._prepared):
            if attachment_id not in retriable_local_ids:
                self._prepared.pop(attachment_id, None)
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
            announcement = self._file_announcement(
                "new_file",
                new_remote[0].display_name,
            )
        elif len(new_remote) > 1:
            announcement = _LABELS[self._language]["new_many_files"].format(
                count=len(new_remote)
            )
        elif len(changed) == 1:
            announcement = self._file_announcement(
                "file_state_updated",
                changed[0].display_name,
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
        try:
            selected = self._file_picker()
        except Exception:
            return self._error(
                message=_LABELS[self._language]["file_selection_failed"],
                focus_target="collaboration-file-choose",
            )
        if selected is None:
            return self._event(
                "collaboration.file.selection_cancelled",
                announcement=_LABELS[self._language]["file_selection_cancelled"],
                focus_target="collaboration-file-choose",
            )
        if not isinstance(selected, Path):
            raise TypeError("file picker must return pathlib.Path or None")
        self._clear_file_progress()
        attachments = self._store.room_attachments(self._controller.room_id)
        sequence = 0 if not attachments else max(item.sequence_no for item in attachments) + 1
        prepared = self._controller.prepare_file(
            attachment_id=self._id_factory("attachment"),
            local_path=selected,
            sequence_no=sequence,
            retention=self._file_retention,
        )
        self._file_progress_attempt_token = secrets.token_bytes(16)
        try:
            uploaded = self._controller.upload_file(
                prepared,
                on_progress=self._file_progress_callback(),
            )
        except Exception:
            # Progress is presentation-only. The failed command result redraws
            # the collaboration surface and must not preserve a stale partial
            # meter into a later retry sequence.
            self._clear_file_progress()
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
            return self._error(
                message=self._file_announcement(
                    "file_upload_failed",
                    prepared.metadata.display_name,
                )
            )
        if uploaded.transfer_state == "failed":
            self._clear_file_progress()
            if uploaded.scan_state != "blocked":
                self._prepared[uploaded.attachment_id] = prepared
            else:
                self._prepared.pop(uploaded.attachment_id, None)
            return self._error(
                message=self._file_announcement(
                    "file_upload_failed",
                    uploaded.display_name,
                )
            )
        self._prepared.pop(uploaded.attachment_id, None)
        self._file_page_bucket = None
        return self._event(
            "collaboration.file.sent",
            announcement=self._file_announcement("file_sent", uploaded.display_name),
        )

    def _open_file(self, file_key: object) -> ClassroomCollaborationWebViewEvent:
        if self._file_opener is None:
            raise RuntimeError("file open adapter is unavailable")
        attachment = self._attachment_for_key(file_key)
        try:
            token = self._controller.issue_download_token(
                attachment_id=attachment.attachment_id
            )
            self._file_opener(token, attachment.display_name)
        except Exception:
            return self._error(
                message=self._file_announcement(
                    "file_open_failed",
                    attachment.display_name,
                )
            )
        return self._event(
            "collaboration.file.opened",
            announcement=self._file_announcement("file_opened", attachment.display_name),
        )

    def receive_file(
        self,
        attachment: AttachmentMetadata,
    ) -> ClassroomCollaborationWebViewEvent:
        """Project a trusted-host live file delivery into the current UI session."""

        before = {
            item.attachment_id: (item.transfer_state, item.scan_state)
            for item in self._store.room_attachments(self._controller.room_id)
        }
        received = self._controller.receive_file(attachment)
        prior_state = before.get(received.attachment_id)
        if received.sender_id == self._controller.local_participant_id:
            if received.transfer_state != "failed" or received.scan_state == "blocked":
                self._prepared.pop(received.attachment_id, None)

        announcement = ""
        if (
            received.attachment_id not in before
            and received.sender_id != self._controller.local_participant_id
        ):
            announcement = self._file_announcement(
                "new_file",
                received.display_name,
            )
        elif (
            received.sender_id == self._controller.local_participant_id
            and prior_state is not None
            and prior_state[0] in {"uploading", "failed"}
            and received.transfer_state == "stored"
        ):
            announcement = self._file_announcement(
                "file_sent",
                received.display_name,
            )
        return self._event(
            "collaboration.file.received",
            announcement=announcement,
        )

    def _retry_file(self, file_key: object) -> ClassroomCollaborationWebViewEvent:
        attachment = self._attachment_for_key(file_key)
        if attachment.transfer_state != "failed" or attachment.scan_state == "blocked":
            self._prepared.pop(attachment.attachment_id, None)
            raise RuntimeError("retry source is unavailable")
        prepared = self._prepared.get(attachment.attachment_id)
        if prepared is None:
            raise RuntimeError("retry source is unavailable")
        self._clear_file_progress()
        self._file_progress_attempt_token = secrets.token_bytes(16)
        try:
            retried = self._controller.retry_file(
                prepared,
                on_progress=self._file_progress_callback(),
            )
        except Exception:
            self._clear_file_progress()
            return self._error(
                message=self._file_announcement(
                    "file_retry_failed",
                    attachment.display_name,
                )
            )
        if retried.transfer_state == "failed":
            self._clear_file_progress()
            if retried.scan_state == "blocked":
                self._prepared.pop(retried.attachment_id, None)
            return self._error(
                message=self._file_announcement(
                    "file_retry_failed",
                    retried.display_name,
                )
            )
        self._prepared.pop(retried.attachment_id, None)
        return self._event(
            "collaboration.file.retried",
            announcement=self._file_announcement("file_retried", retried.display_name),
            focus_target="collaboration-file-choose",
        )

    def _cancel_file(self, file_key: object) -> ClassroomCollaborationWebViewEvent:
        attachment = self._attachment_for_key(file_key)
        try:
            self._controller.cancel_file(attachment.attachment_id)
        except Exception:
            return self._error(
                message=self._file_announcement(
                    "file_cancel_failed",
                    attachment.display_name,
                )
            )
        self._prepared.pop(attachment.attachment_id, None)
        if self._file_progress is not None and self._file_progress[0] == attachment.attachment_id:
            self._clear_file_progress()
        return self._event(
            "collaboration.file.cancelled",
            announcement=self._file_announcement("file_cancelled", attachment.display_name),
            focus_target="collaboration-file-choose",
        )

    def _save_file(self, file_key: object) -> ClassroomCollaborationWebViewEvent:
        if self._file_saver is None:
            raise RuntimeError("file save adapter is unavailable")
        attachment = self._attachment_for_key(file_key)
        try:
            token = self._controller.issue_download_token(
                attachment_id=attachment.attachment_id
            )
            self._file_saver(token, attachment.display_name)
        except Exception:
            return self._error(
                message=self._file_announcement(
                    "file_save_failed",
                    attachment.display_name,
                )
            )
        return self._event(
            "collaboration.file.saved",
            announcement=self._file_announcement("file_saved", attachment.display_name),
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
            if command in {"collaboration.chat.older", "collaboration.chat.newer"}:
                if data:
                    raise ValueError("chat history paging accepts no fields")
                return self._move_chat_page(-1 if command.endswith("older") else 1)
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
            if command in {"collaboration.file.older", "collaboration.file.newer"}:
                if data:
                    raise ValueError("file history paging accepts no fields")
                return self._move_file_page(-1 if command.endswith("older") else 1)
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
