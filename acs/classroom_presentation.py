from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Mapping

from .classroom import ClassroomParticipant, ClassroomRoster
from .classroom_collaboration_storage import (
    AttachmentMetadata,
    ChatMessageMetadata,
    safe_display_filename,
)
from .local_profile import LocalProfile, LocalProfileStore
from .usage_statistics import UsageStatisticsSnapshot


@dataclass(frozen=True)
class CollaborationAnnouncement:
    text: str
    focus_target: str | None = None


class ClassroomPresentationState:
    """Accessible presentation-only state for teaching collaboration.

    This layer projects existing classroom/profile/collaboration contracts into
    concise UI data. It owns no realtime transport, media bytes, chess state,
    file execution, or analytics upload. Incoming chat/file metadata is supplied
    by composition from the transport/storage lane.
    """

    def __init__(
        self,
        *,
        roster: ClassroomRoster | None = None,
        profile_store: LocalProfileStore | None = None,
        profile: LocalProfile | None = None,
        statistics: UsageStatisticsSnapshot | None = None,
        room_id: str = "",
    ) -> None:
        self.roster = roster or ClassroomRoster()
        self.profile_store = profile_store
        self.profile = profile
        self.statistics = statistics
        self.room_id = str(room_id).strip()
        self._messages: list[tuple[ChatMessageMetadata, str]] = []
        self._attachments: list[tuple[AttachmentMetadata, str]] = []
        self._unread_message_ids: set[str] = set()
        self._last_announcement = CollaborationAnnouncement("")

    @property
    def last_announcement(self) -> CollaborationAnnouncement:
        return self._last_announcement

    def snapshot(self) -> dict[str, Any]:
        return {
            "profile": self._profile_view(),
            "statistics": self._statistics_view(),
            "room": {
                "roomId": self.room_id,
                "participants": [self._participant_view(p) for p in self.roster.snapshot()],
                "mediaCapability": {
                    "microphone": True,
                    "camera": False,
                    "cameraMissingContract": "ClassroomParticipant camera permission/publication state is not yet present in the shared classroom contract.",
                },
            },
            "chat": {
                "messages": [self._message_view(item, sender) for item, sender in self._messages],
                "unreadCount": len(self._unread_message_ids),
            },
            "files": {
                "items": [self._attachment_view(item, sender) for item, sender in self._attachments],
            },
        }

    def ensure_profile(self) -> dict[str, Any]:
        if self.profile is None and self.profile_store is not None:
            self.profile = self.profile_store.load_or_create()
        return self._profile_view()

    def set_display_name(self, value: str | None) -> dict[str, Any]:
        if self.profile_store is None:
            raise RuntimeError("profile store is not configured")
        if self.profile is None:
            self.profile = self.profile_store.load_or_create()
        self.profile = self.profile_store.set_display_name(self.profile, value)
        self._last_announcement = CollaborationAnnouncement(
            f"Ім'я: {self.profile.display_name}."
        )
        return self._profile_view()

    def append_message(
        self,
        message: ChatMessageMetadata,
        *,
        sender_display_name: str,
        incoming: bool = True,
    ) -> dict[str, Any]:
        if self.room_id and message.room_id != self.room_id:
            raise ValueError("message belongs to another room")
        if any(existing.message_id == message.message_id for existing, _ in self._messages):
            return self._message_view(message, sender_display_name)
        sender = str(sender_display_name).strip() or message.sender_id
        self._messages.append((message, sender))
        self._messages.sort(key=lambda row: row[0].sequence_no)
        if incoming and not message.hidden:
            self._unread_message_ids.add(message.message_id)
            self._last_announcement = CollaborationAnnouncement(
                f"Нове повідомлення від {sender}.",
                focus_target=None,
            )
        return self._message_view(message, sender)

    def mark_chat_read(self) -> dict[str, Any]:
        self._unread_message_ids.clear()
        return {"ok": True, "unreadCount": 0}

    def register_attachment(
        self,
        attachment: AttachmentMetadata,
        *,
        sender_display_name: str,
    ) -> dict[str, Any]:
        if self.room_id and attachment.room_id != self.room_id:
            raise ValueError("attachment belongs to another room")
        safe_name = safe_display_filename(attachment.display_name)
        if safe_name != attachment.display_name:
            raise ValueError("unsafe attachment display name")
        sender = str(sender_display_name).strip() or attachment.sender_id
        if not any(existing.attachment_id == attachment.attachment_id for existing, _ in self._attachments):
            self._attachments.append((attachment, sender))
            self._attachments.sort(key=lambda row: row[0].sequence_no)
        self._last_announcement = CollaborationAnnouncement(
            f"Файл від {sender}: {safe_name}."
        )
        return self._attachment_view(attachment, sender)

    @staticmethod
    def _participant_view(participant: ClassroomParticipant) -> dict[str, Any]:
        if participant.microphone_hard_locked:
            microphone = "locked"
        elif participant.microphone_muted:
            microphone = "muted"
        else:
            microphone = "on"
        return {
            "id": participant.identity.room_identity,
            "displayName": participant.identity.display_name,
            "role": participant.role.value,
            "connected": participant.connected,
            "microphone": microphone,
            "canPublishMicrophone": participant.permissions.can_publish_microphone,
            "boardControl": participant.permissions.board_control.value,
            "canPoint": participant.permissions.can_point,
            "canAnnotate": participant.permissions.can_annotate,
            "canModerate": participant.permissions.can_moderate,
        }

    def _profile_view(self) -> dict[str, Any]:
        if self.profile is None:
            return {
                "available": self.profile_store is not None,
                "needsPrompt": self.profile_store is not None,
                "displayName": "",
                "generatedAlias": False,
                "syncState": "local_only",
            }
        return {
            "available": True,
            "needsPrompt": self.profile.generated_alias,
            "displayName": self.profile.display_name,
            "generatedAlias": self.profile.generated_alias,
            "syncState": "local_only",
        }

    def _statistics_view(self) -> dict[str, Any]:
        if self.statistics is None:
            return {
                "available": False,
                "syncState": "local_only",
                "privacyText": "Статистика синхронізації не налаштована; сирі партії, чат, аудіо, відео та файли не надсилаються як звичайна телеметрія.",
            }
        return {
            "available": True,
            "syncState": "local_only",
            "sessionsStarted": self.statistics.sessions_started,
            "sessionSeconds": self.statistics.session_seconds,
            "gamesStarted": self.statistics.games_started,
            "gamesCompleted": self.statistics.games_completed,
            "exercisesAttempted": self.statistics.exercises_attempted,
            "exercisesCompleted": self.statistics.exercises_completed,
            "classroomSessions": self.statistics.classroom_sessions,
            "classroomSeconds": self.statistics.classroom_seconds,
            "privacyText": "Локальні агреговані лічильники. Сирі партії, чат, аудіо, відео та файли не є звичайною телеметрією.",
        }

    def _message_view(self, message: ChatMessageMetadata, sender: str) -> dict[str, Any]:
        return {
            "id": message.message_id,
            "senderId": message.sender_id,
            "senderDisplayName": sender,
            "body": message.body,
            "sequence": message.sequence_no,
            "hidden": message.hidden,
            "unread": message.message_id in self._unread_message_ids,
            "accessibleText": f"{sender}: {message.body}",
        }

    @staticmethod
    def _attachment_view(attachment: AttachmentMetadata, sender: str) -> dict[str, Any]:
        size = attachment.size_bytes
        return {
            "id": attachment.attachment_id,
            "senderId": attachment.sender_id,
            "senderDisplayName": sender,
            "name": attachment.display_name,
            "sizeBytes": size,
            "mimeType": attachment.mime_type or "application/octet-stream",
            "progressPercent": 100 if attachment.transfer_state == "stored" else 0,
            "status": attachment.transfer_state,
            "scanState": attachment.scan_state,
            "canSave": attachment.transfer_state == "stored" and attachment.scan_state in {"clean", "not_required"},
            "canOpen": False,
            "accessibleText": f"{sender}: {attachment.display_name}, {size} байт, стан {attachment.transfer_state}.",
        }
