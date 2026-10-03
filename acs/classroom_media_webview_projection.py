from __future__ import annotations

"""Accessible WebView projection over the canonical classroom media controller.

This module owns presentation state only. Membership, roles, board permission,
media policy, provider calls, room identity, and chess state remain owned by
ClassroomMediaController and its canonical ports. The browser receives opaque
participant keys rather than roster identifiers and never supplies moderation
operation ids.
"""

from collections.abc import Callable, Mapping
from dataclasses import dataclass
import hashlib
import hmac
import re
import secrets

from .classroom_realtime_media import (
    ClassroomMediaController,
    ClassroomRole,
    MediaSource,
    ParticipantMediaPolicy,
)
from .full_product_ui_shell import UILanguage, concise_user_error


ParticipantLabelsProvider = Callable[[], Mapping[str, str]]
OperationIdFactory = Callable[[], str]

_MAX_PARTICIPANTS = 5000
_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_OPERATION_RE = _ID_RE


_TEXT = {
    UILanguage.UA: {
        "heading": "Аудіо та відео заняття",
        "connected": "Медіазв’язок підключено.",
        "disconnected": "Медіазв’язок не підключено.",
        "participants": "Учасники та дозволи",
        "own_controls": "Ваш мікрофон і камера",
        "teacher_controls": "Керування медіа учнів",
        "microphone": "Мікрофон",
        "camera": "Камера",
        "on": "увімкнено",
        "off": "вимкнено",
        "allowed": "дозволено",
        "locked": "заблоковано",
        "soft_muted": "м’яко вимкнено",
        "not_soft_muted": "не вимкнено",
        "board_allowed": "керування дошкою дозволено",
        "board_denied": "керування дошкою заборонено",
        "removed": "видалено з кімнати",
        "blocked": "заблоковано в кімнаті",
        "role_teacher": "викладач",
        "role_co_teacher": "співвикладач",
        "role_student": "учень",
        "role_observer": "спостерігач",
        "turn_on_microphone": "Увімкнути мікрофон",
        "turn_off_microphone": "Вимкнути мікрофон",
        "turn_on_camera": "Увімкнути камеру",
        "turn_off_camera": "Вимкнути камеру",
        "soft_mute": "М’яко вимкнути мікрофон",
        "clear_soft_mute": "Дозволити самостійно ввімкнути мікрофон",
        "lock_microphone": "Заблокувати публікацію мікрофона",
        "allow_microphone": "Дозволити публікацію мікрофона",
        "lock_camera": "Заблокувати публікацію камери",
        "allow_camera": "Дозволити публікацію камери",
        "remove": "Видалити з кімнати",
        "block": "Видалити й заблокувати",
        "mute_all": "М’яко вимкнути мікрофони всіх учнів",
        "unmute_all": "Скасувати м’яке вимкнення для всіх учнів",
        "lock_all_microphones": "Заблокувати мікрофони всіх учнів",
        "allow_all_microphones": "Дозволити мікрофони всім учням",
        "lock_all_cameras": "Заблокувати камери всіх учнів",
        "allow_all_cameras": "Дозволити камери всім учням",
        "changed": "Стан медіа оновлено.",
    },
    UILanguage.EN: {
        "heading": "Lesson audio and video",
        "connected": "Media connection is connected.",
        "disconnected": "Media connection is not connected.",
        "participants": "Participants and permissions",
        "own_controls": "Your microphone and camera",
        "teacher_controls": "Student media controls",
        "microphone": "Microphone",
        "camera": "Camera",
        "on": "on",
        "off": "off",
        "allowed": "allowed",
        "locked": "locked",
        "soft_muted": "soft muted",
        "not_soft_muted": "not soft muted",
        "board_allowed": "board control allowed",
        "board_denied": "board control denied",
        "removed": "removed from room",
        "blocked": "blocked from room",
        "role_teacher": "teacher",
        "role_co_teacher": "co-teacher",
        "role_student": "student",
        "role_observer": "observer",
        "turn_on_microphone": "Turn microphone on",
        "turn_off_microphone": "Turn microphone off",
        "turn_on_camera": "Turn camera on",
        "turn_off_camera": "Turn camera off",
        "soft_mute": "Soft mute microphone",
        "clear_soft_mute": "Allow participant to unmute microphone",
        "lock_microphone": "Lock microphone publishing",
        "allow_microphone": "Allow microphone publishing",
        "lock_camera": "Lock camera publishing",
        "allow_camera": "Allow camera publishing",
        "remove": "Remove from room",
        "block": "Remove and block",
        "mute_all": "Soft mute all students",
        "unmute_all": "Clear soft mute for all students",
        "lock_all_microphones": "Lock all student microphones",
        "allow_all_microphones": "Allow all student microphones",
        "lock_all_cameras": "Lock all student cameras",
        "allow_all_cameras": "Allow all student cameras",
        "changed": "Media state updated.",
    },
}


@dataclass(frozen=True, slots=True)
class ClassroomMediaWebViewEvent:
    kind: str
    payload: Mapping[str, object]


class ClassroomMediaWebViewProjection:
    """Project and mutate media only through ClassroomMediaController."""

    def __init__(
        self,
        controller: ClassroomMediaController,
        participant_labels_provider: ParticipantLabelsProvider,
        *,
        language: UILanguage = UILanguage.UA,
        operation_id_factory: OperationIdFactory | None = None,
    ) -> None:
        if not isinstance(controller, ClassroomMediaController):
            raise TypeError("media projection requires ClassroomMediaController")
        if not callable(participant_labels_provider):
            raise TypeError("participant labels provider must be callable")
        if not isinstance(language, UILanguage):
            raise TypeError("language must be UILanguage")
        if operation_id_factory is not None and not callable(operation_id_factory):
            raise TypeError("operation id factory must be callable")
        self._controller = controller
        self._participant_labels_provider = participant_labels_provider
        self._language = language
        self._operation_id_factory = operation_id_factory or (
            lambda: "ui-" + secrets.token_hex(16)
        )
        self._key_secret = secrets.token_bytes(32)

    @property
    def language(self) -> UILanguage:
        return self._language

    @property
    def controller(self) -> ClassroomMediaController:
        return self._controller

    def set_language(self, language: UILanguage | str) -> ClassroomMediaWebViewEvent:
        if isinstance(language, str):
            try:
                language = UILanguage(language.strip().lower())
            except ValueError:
                raise ValueError("unsupported UI language") from None
        if not isinstance(language, UILanguage):
            raise TypeError("language must be UILanguage")
        self._language = language
        return ClassroomMediaWebViewEvent("render", {"snapshot": self.snapshot()})

    def _labels(self) -> dict[str, str]:
        raw = self._participant_labels_provider()
        if not isinstance(raw, Mapping) or len(raw) > _MAX_PARTICIPANTS:
            raise TypeError("participant labels must be a bounded mapping")
        result: dict[str, str] = {}
        for participant_id, label in raw.items():
            if (
                type(participant_id) is not str
                or _ID_RE.fullmatch(participant_id) is None
                or participant_id in result
            ):
                raise ValueError("participant labels contain invalid identity")
            if type(label) is not str:
                raise TypeError("participant display label must be text")
            visible = label.strip()
            if (
                not visible
                or len(visible) > 120
                or any(ord(ch) < 32 or ord(ch) == 127 for ch in visible)
            ):
                raise ValueError("participant display label is invalid")
            result[participant_id] = visible
        local_id = self._controller.state.participant_id
        if local_id not in result:
            raise ValueError("local participant is missing from display labels")
        return result

    def _participant_key(self, participant_id: str) -> str:
        return hmac.new(
            self._key_secret,
            participant_id.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()

    def _resolve_participant_key(self, participant_key: str) -> str:
        if type(participant_key) is not str or not re.fullmatch(r"[0-9a-f]{64}", participant_key):
            raise ValueError("participant key is invalid")
        matches = [
            participant_id
            for participant_id in self._labels()
            if hmac.compare_digest(self._participant_key(participant_id), participant_key)
        ]
        if len(matches) != 1:
            raise LookupError("participant key is stale")
        return matches[0]

    def _operation_id(self) -> str:
        value = self._operation_id_factory()
        if type(value) is not str or _OPERATION_RE.fullmatch(value) is None:
            raise ValueError("operation id factory returned invalid identity")
        return value

    def _can_moderate(
        self,
        local: ParticipantMediaPolicy,
        target: ParticipantMediaPolicy,
    ) -> bool:
        if not self._controller.state.connected or target.removed or target.blocked:
            return False
        if local.participant_id == target.participant_id:
            return False
        if local.role is ClassroomRole.TEACHER:
            return target.role is not ClassroomRole.TEACHER
        if local.role is ClassroomRole.CO_TEACHER:
            return target.role in {ClassroomRole.STUDENT, ClassroomRole.OBSERVER}
        return False

    def _source_snapshot(
        self,
        policy: ParticipantMediaPolicy,
        source: MediaSource,
        *,
        is_local: bool,
    ) -> dict[str, object]:
        source_policy = policy.source(source)
        return {
            "publish_allowed": source_policy.publish_allowed,
            "soft_muted": (
                source_policy.soft_muted if source is MediaSource.MICROPHONE else False
            ),
            "local_enabled": (
                source in self._controller.state.desired_sources if is_local else None
            ),
        }

    def _role_label(self, role: ClassroomRole) -> str:
        return _TEXT[self._language]["role_" + role.value]

    def _summary(
        self,
        label: str,
        policy: ParticipantMediaPolicy,
        *,
        is_local: bool,
    ) -> str:
        text = _TEXT[self._language]
        microphone = self._source_snapshot(
            policy, MediaSource.MICROPHONE, is_local=is_local
        )
        camera = self._source_snapshot(policy, MediaSource.CAMERA, is_local=is_local)
        parts = [label, self._role_label(policy.role)]
        if is_local:
            parts.append(
                f"{text['microphone']}: "
                f"{text['on'] if microphone['local_enabled'] else text['off']}"
            )
            parts.append(
                f"{text['camera']}: "
                f"{text['on'] if camera['local_enabled'] else text['off']}"
            )
        parts.extend(
            (
                f"{text['microphone']} "
                f"{text['allowed'] if microphone['publish_allowed'] else text['locked']}",
                (
                    text["soft_muted"]
                    if microphone["soft_muted"]
                    else text["not_soft_muted"]
                ),
                f"{text['camera']} "
                f"{text['allowed'] if camera['publish_allowed'] else text['locked']}",
                (
                    text["board_allowed"]
                    if policy.board_control_allowed
                    else text["board_denied"]
                ),
            )
        )
        if policy.blocked:
            parts.append(text["blocked"])
        elif policy.removed:
            parts.append(text["removed"])
        return ". ".join(parts)

    def _local_actions(self, policy: ParticipantMediaPolicy) -> tuple[dict[str, object], ...]:
        if not self._controller.state.connected or policy.removed or policy.blocked:
            return ()
        text = _TEXT[self._language]
        result: list[dict[str, object]] = []
        for source, prefix in (
            (MediaSource.MICROPHONE, "microphone"),
            (MediaSource.CAMERA, "camera"),
        ):
            source_policy = policy.source(source)
            enabled = source in self._controller.state.desired_sources
            target_enabled = not enabled
            if target_enabled and not source_policy.publish_allowed:
                continue
            result.append(
                {
                    "id": f"media-own-{prefix}-toggle",
                    "command": "media.local_source",
                    "label": text[
                        "turn_off_" + prefix if enabled else "turn_on_" + prefix
                    ],
                    "payload": {
                        "source": source.value,
                        "enabled": target_enabled,
                    },
                }
            )
        return tuple(result)

    def _moderation_actions(
        self,
        target_key: str,
        target: ParticipantMediaPolicy,
    ) -> tuple[dict[str, object], ...]:
        text = _TEXT[self._language]
        microphone = target.source(MediaSource.MICROPHONE)
        camera = target.source(MediaSource.CAMERA)
        prefix = f"media-participant-{target_key}"
        return (
            {
                "id": prefix + "-soft-mute",
                "command": "media.soft_mute",
                "label": text[
                    "clear_soft_mute" if microphone.soft_muted else "soft_mute"
                ],
                "payload": {
                    "participant_key": target_key,
                    "muted": not microphone.soft_muted,
                },
            },
            {
                "id": prefix + "-mic-permission",
                "command": "media.publish_permission",
                "label": text[
                    "lock_microphone"
                    if microphone.publish_allowed
                    else "allow_microphone"
                ],
                "payload": {
                    "participant_key": target_key,
                    "source": MediaSource.MICROPHONE.value,
                    "allowed": not microphone.publish_allowed,
                },
            },
            {
                "id": prefix + "-camera-permission",
                "command": "media.publish_permission",
                "label": text[
                    "lock_camera" if camera.publish_allowed else "allow_camera"
                ],
                "payload": {
                    "participant_key": target_key,
                    "source": MediaSource.CAMERA.value,
                    "allowed": not camera.publish_allowed,
                },
            },
            {
                "id": prefix + "-remove",
                "command": "media.remove",
                "label": text["remove"],
                "payload": {"participant_key": target_key, "block": False},
            },
            {
                "id": prefix + "-block",
                "command": "media.remove",
                "label": text["block"],
                "payload": {"participant_key": target_key, "block": True},
            },
        )

    def _all_student_actions(
        self,
        local: ParticipantMediaPolicy,
    ) -> tuple[dict[str, object], ...]:
        if (
            not self._controller.state.connected
            or local.removed
            or local.blocked
            or local.role not in {ClassroomRole.TEACHER, ClassroomRole.CO_TEACHER}
        ):
            return ()
        text = _TEXT[self._language]
        return (
            {
                "id": "media-all-soft-mute",
                "command": "media.all_soft_mute",
                "label": text["mute_all"],
                "payload": {"muted": True},
            },
            {
                "id": "media-all-clear-soft-mute",
                "command": "media.all_soft_mute",
                "label": text["unmute_all"],
                "payload": {"muted": False},
            },
            {
                "id": "media-all-mic-lock",
                "command": "media.all_publish_permission",
                "label": text["lock_all_microphones"],
                "payload": {
                    "source": MediaSource.MICROPHONE.value,
                    "allowed": False,
                },
            },
            {
                "id": "media-all-mic-allow",
                "command": "media.all_publish_permission",
                "label": text["allow_all_microphones"],
                "payload": {
                    "source": MediaSource.MICROPHONE.value,
                    "allowed": True,
                },
            },
            {
                "id": "media-all-camera-lock",
                "command": "media.all_publish_permission",
                "label": text["lock_all_cameras"],
                "payload": {
                    "source": MediaSource.CAMERA.value,
                    "allowed": False,
                },
            },
            {
                "id": "media-all-camera-allow",
                "command": "media.all_publish_permission",
                "label": text["allow_all_cameras"],
                "payload": {
                    "source": MediaSource.CAMERA.value,
                    "allowed": True,
                },
            },
        )

    def snapshot(self) -> dict[str, object]:
        labels = self._labels()
        local_id = self._controller.state.participant_id
        local = self._controller.participant_policy(local_id)
        participants: list[dict[str, object]] = []
        own: dict[str, object] | None = None

        # A generic Mapping does not promise a stable presentation order.
        # Sort by visible label, then canonical opaque identity, so repeated
        # rerenders cannot move NVDA users to a different participant merely
        # because the provider returned the same roster in another iteration
        # order. The canonical identity is never emitted to the browser.
        for participant_id in sorted(
            labels,
            key=lambda item: (labels[item].casefold(), item),
        ):
            label = labels[participant_id]
            policy = self._controller.participant_policy(participant_id)
            key = self._participant_key(participant_id)
            is_local = participant_id == local_id
            row = {
                "participant_key": key,
                "dom_id": "media-participant-" + key,
                "label": label,
                "role": policy.role.value,
                "role_label": self._role_label(policy.role),
                "is_local": is_local,
                "microphone": self._source_snapshot(
                    policy, MediaSource.MICROPHONE, is_local=is_local
                ),
                "camera": self._source_snapshot(
                    policy, MediaSource.CAMERA, is_local=is_local
                ),
                "board_control_allowed": policy.board_control_allowed,
                "removed": policy.removed,
                "blocked": policy.blocked,
                "summary": self._summary(label, policy, is_local=is_local),
                "actions": (
                    self._moderation_actions(key, policy)
                    if self._can_moderate(local, policy)
                    else ()
                ),
            }
            participants.append(row)
            if is_local:
                own = dict(row)
                own["actions"] = self._local_actions(policy)

        if own is None:
            raise ValueError("local participant projection is unavailable")

        text = _TEXT[self._language]
        return {
            "document": {
                "lang": self._language.value,
                "heading": text["heading"],
            },
            "connected": self._controller.state.connected,
            "connection_text": (
                text["connected"]
                if self._controller.state.connected
                else text["disconnected"]
            ),
            "own_heading": text["own_controls"],
            "participants_heading": text["participants"],
            "teacher_controls_heading": text["teacher_controls"],
            "own": own,
            "participants": tuple(participants),
            "all_student_actions": self._all_student_actions(local),
        }

    def _success(self, *, focus_target: str = "") -> ClassroomMediaWebViewEvent:
        try:
            snapshot: dict[str, object] | None = self.snapshot()
        except Exception:
            # The controller/provider mutation has already committed. A fallible
            # presentation-label read must not turn that success into a false
            # failure that invites a duplicate user retry. Retire stale controls
            # until a later full snapshot can project the canonical state again.
            snapshot = None
            focus_target = "classroom-media-heading"
        return ClassroomMediaWebViewEvent(
            "media-updated",
            {
                "snapshot": snapshot,
                "announcement": _TEXT[self._language]["changed"],
                "focus_target": focus_target,
                "recovery_required": snapshot is None,
            },
        )

    def _error(self, *, focus_target: str = "") -> ClassroomMediaWebViewEvent:
        return ClassroomMediaWebViewEvent(
            "error",
            {
                "message": concise_user_error("", language=self._language),
                "focus_target": focus_target,
            },
        )

    @staticmethod
    def _source(value: MediaSource | str) -> MediaSource:
        try:
            source = MediaSource(value)
        except (TypeError, ValueError):
            raise ValueError("unsupported browser media source") from None
        if source not in {MediaSource.MICROPHONE, MediaSource.CAMERA}:
            raise ValueError("screen sharing has no browser control in this slice")
        return source

    def set_local_source(
        self,
        source: MediaSource | str,
        enabled: bool,
        *,
        focus_target: str = "",
    ) -> ClassroomMediaWebViewEvent:
        try:
            if type(enabled) is not bool:
                raise TypeError("media enabled must be boolean")
            self._controller.set_local_source(self._source(source), enabled)
            return self._success(focus_target=focus_target)
        except Exception:
            return self._error(focus_target=focus_target)

    def set_publish_permission(
        self,
        participant_key: str,
        source: MediaSource | str,
        allowed: bool,
        *,
        focus_target: str = "",
    ) -> ClassroomMediaWebViewEvent:
        try:
            if type(allowed) is not bool:
                raise TypeError("publish permission must be boolean")
            target_id = self._resolve_participant_key(participant_key)
            self._controller.set_publish_permission(
                actor_id=self._controller.state.participant_id,
                target_id=target_id,
                source=self._source(source),
                allowed=allowed,
                operation_id=self._operation_id(),
            )
            return self._success(focus_target=focus_target)
        except Exception:
            return self._error(focus_target=focus_target)

    def set_soft_mute(
        self,
        participant_key: str,
        muted: bool,
        *,
        focus_target: str = "",
    ) -> ClassroomMediaWebViewEvent:
        try:
            if type(muted) is not bool:
                raise TypeError("soft mute must be boolean")
            target_id = self._resolve_participant_key(participant_key)
            self._controller.set_soft_mute(
                actor_id=self._controller.state.participant_id,
                target_id=target_id,
                muted=muted,
                operation_id=self._operation_id(),
            )
            return self._success(focus_target=focus_target)
        except Exception:
            return self._error(focus_target=focus_target)

    def set_all_students_publish_permission(
        self,
        source: MediaSource | str,
        allowed: bool,
        *,
        focus_target: str = "",
    ) -> ClassroomMediaWebViewEvent:
        try:
            if type(allowed) is not bool:
                raise TypeError("publish permission must be boolean")
            self._controller.set_all_students_publish_permission(
                actor_id=self._controller.state.participant_id,
                source=self._source(source),
                allowed=allowed,
                operation_id=self._operation_id(),
            )
            return self._success(focus_target=focus_target)
        except Exception:
            return self._error(focus_target=focus_target)

    def set_all_students_soft_mute(
        self,
        muted: bool,
        *,
        focus_target: str = "",
    ) -> ClassroomMediaWebViewEvent:
        try:
            if type(muted) is not bool:
                raise TypeError("soft mute must be boolean")
            self._controller.set_all_students_soft_mute(
                actor_id=self._controller.state.participant_id,
                muted=muted,
                operation_id=self._operation_id(),
            )
            return self._success(focus_target=focus_target)
        except Exception:
            return self._error(focus_target=focus_target)

    def remove_participant(
        self,
        participant_key: str,
        block: bool,
        *,
        focus_target: str = "",
    ) -> ClassroomMediaWebViewEvent:
        try:
            if type(block) is not bool:
                raise TypeError("block must be boolean")
            target_id = self._resolve_participant_key(participant_key)
            self._controller.remove_participant(
                actor_id=self._controller.state.participant_id,
                target_id=target_id,
                block=block,
                operation_id=self._operation_id(),
            )
            return self._success(focus_target=focus_target)
        except Exception:
            return self._error(focus_target=focus_target)


__all__ = [
    "ClassroomMediaWebViewEvent",
    "ClassroomMediaWebViewProjection",
    "ParticipantLabelsProvider",
]
