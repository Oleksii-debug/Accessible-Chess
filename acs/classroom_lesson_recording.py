from __future__ import annotations

"""Consent-gated, provider-neutral lesson recording history.

This module stores recording authority and history only. It never captures media,
holds provider credentials, uploads raw audio/video, or owns classroom/chess state.
Concrete recording providers remain behind RecordingProviderPort.
"""

from dataclasses import dataclass, replace
from datetime import datetime, timezone
from enum import Enum
import hashlib
import json
import re
from typing import Mapping, Protocol

MAX_ID = 128
MAX_PROVIDER_REF = 512
MAX_RETENTION_DAYS = 3650
_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")


class LessonRecordingError(ValueError):
    pass


class RecordingState(str, Enum):
    RECORDING = "recording"
    STOPPED = "stopped"
    DELETED = "deleted"


@dataclass(frozen=True, slots=True)
class RecordingPolicy:
    storage_region: str
    retention_days: int
    allow_audio: bool = True
    allow_video: bool = False
    allow_chat_transcript: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "storage_region", _id(self.storage_region, "storage region"))
        if type(self.retention_days) is not int or not 1 <= self.retention_days <= MAX_RETENTION_DAYS:
            raise LessonRecordingError("retention days are invalid")
        for value, label in (
            (self.allow_audio, "allow audio"),
            (self.allow_video, "allow video"),
            (self.allow_chat_transcript, "allow chat transcript"),
        ):
            if type(value) is not bool:
                raise LessonRecordingError(f"{label} must be boolean")
        if not (self.allow_audio or self.allow_video or self.allow_chat_transcript):
            raise LessonRecordingError("recording policy must permit at least one data class")


@dataclass(frozen=True, slots=True)
class ParticipantConsent:
    participant_id: str
    policy_digest: str
    granted: bool
    recorded_at: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "participant_id", _id(self.participant_id, "participant id"))
        object.__setattr__(self, "policy_digest", _digest_text(self.policy_digest))
        if type(self.granted) is not bool:
            raise LessonRecordingError("consent decision must be boolean")
        object.__setattr__(self, "recorded_at", _timestamp(self.recorded_at))


@dataclass(frozen=True, slots=True)
class LessonRecording:
    recording_id: str
    room_id: str
    lesson_id: str
    provider_ref: str
    policy: RecordingPolicy
    participant_ids: tuple[str, ...]
    consents: tuple[ParticipantConsent, ...]
    started_at: str
    stopped_at: str | None = None
    state: RecordingState = RecordingState.RECORDING

    def __post_init__(self) -> None:
        object.__setattr__(self, "recording_id", _id(self.recording_id, "recording id"))
        object.__setattr__(self, "room_id", _id(self.room_id, "room id"))
        object.__setattr__(self, "lesson_id", _id(self.lesson_id, "lesson id"))
        if type(self.provider_ref) is not str or not self.provider_ref or len(self.provider_ref) > MAX_PROVIDER_REF:
            raise LessonRecordingError("provider reference is invalid")
        if any(ord(ch) < 0x20 for ch in self.provider_ref):
            raise LessonRecordingError("provider reference contains control characters")
        if not isinstance(self.policy, RecordingPolicy):
            raise LessonRecordingError("recording policy is invalid")
        participants = tuple(_id(item, "participant id") for item in self.participant_ids)
        if not participants or len(set(participants)) != len(participants):
            raise LessonRecordingError("participants must be non-empty and unique")
        object.__setattr__(self, "participant_ids", participants)
        consents = tuple(self.consents)
        if len(consents) != len(participants):
            raise LessonRecordingError("every participant requires one consent decision")
        by_id = {item.participant_id: item for item in consents}
        if set(by_id) != set(participants):
            raise LessonRecordingError("consent participants do not match recording participants")
        expected = policy_digest(self.policy)
        if any((not item.granted) or item.policy_digest != expected for item in consents):
            raise LessonRecordingError("recording requires explicit consent to the exact policy")
        object.__setattr__(self, "consents", tuple(by_id[item] for item in participants))
        object.__setattr__(self, "started_at", _timestamp(self.started_at))
        if self.stopped_at is not None:
            object.__setattr__(self, "stopped_at", _timestamp(self.stopped_at))
        state = RecordingState(self.state)
        object.__setattr__(self, "state", state)
        if state is RecordingState.RECORDING and self.stopped_at is not None:
            raise LessonRecordingError("active recording cannot have stopped_at")
        if state is not RecordingState.RECORDING and self.stopped_at is None:
            raise LessonRecordingError("terminal recording requires stopped_at")

    @property
    def digest(self) -> str:
        return _sha(self.to_record(include_digest=False))

    def to_record(self, *, include_digest: bool = True) -> dict[str, object]:
        record: dict[str, object] = {
            "version": 1,
            "recording_id": self.recording_id,
            "room_id": self.room_id,
            "lesson_id": self.lesson_id,
            "provider_ref": self.provider_ref,
            "policy": {
                "storage_region": self.policy.storage_region,
                "retention_days": self.policy.retention_days,
                "allow_audio": self.policy.allow_audio,
                "allow_video": self.policy.allow_video,
                "allow_chat_transcript": self.policy.allow_chat_transcript,
            },
            "participant_ids": list(self.participant_ids),
            "consents": [
                {
                    "participant_id": item.participant_id,
                    "policy_digest": item.policy_digest,
                    "granted": item.granted,
                    "recorded_at": item.recorded_at,
                }
                for item in self.consents
            ],
            "started_at": self.started_at,
            "stopped_at": self.stopped_at,
            "state": self.state.value,
        }
        if include_digest:
            record["digest"] = _sha(record)
        return record


class RecordingProviderPort(Protocol):
    def start(self, *, room_id: str, lesson_id: str, policy: RecordingPolicy) -> str: ...
    def stop(self, *, provider_ref: str) -> None: ...
    def delete(self, *, provider_ref: str) -> None: ...


class LessonRecordingLedger:
    def __init__(self, records: tuple[LessonRecording, ...] = ()) -> None:
        ids = [item.recording_id for item in records]
        if len(set(ids)) != len(ids):
            raise LessonRecordingError("duplicate recording id")
        self._records = tuple(records)

    @property
    def records(self) -> tuple[LessonRecording, ...]:
        return self._records

    def get(self, recording_id: str) -> LessonRecording:
        key = _id(recording_id, "recording id")
        for item in self._records:
            if item.recording_id == key:
                return item
        raise LessonRecordingError("recording not found")

    def start(
        self,
        *,
        recording_id: str,
        room_id: str,
        lesson_id: str,
        policy: RecordingPolicy,
        participant_ids: tuple[str, ...],
        consents: tuple[ParticipantConsent, ...],
        provider: RecordingProviderPort,
        started_at: str,
    ) -> LessonRecording:
        recording_id = _id(recording_id, "recording id")
        if any(item.recording_id == recording_id for item in self._records):
            raise LessonRecordingError("recording id already exists")
        expected = policy_digest(policy)
        consent_map = {item.participant_id: item for item in consents}
        participant_ids = tuple(_id(item, "participant id") for item in participant_ids)
        if set(consent_map) != set(participant_ids) or any(
            not consent_map[item].granted or consent_map[item].policy_digest != expected
            for item in participant_ids
        ):
            raise LessonRecordingError("provider start is forbidden without exact explicit consent")
        provider_ref = provider.start(room_id=room_id, lesson_id=lesson_id, policy=policy)
        record = LessonRecording(
            recording_id=recording_id,
            room_id=room_id,
            lesson_id=lesson_id,
            provider_ref=provider_ref,
            policy=policy,
            participant_ids=participant_ids,
            consents=consents,
            started_at=started_at,
        )
        self._records += (record,)
        return record

    def stop(self, recording_id: str, *, provider: RecordingProviderPort, stopped_at: str) -> LessonRecording:
        current = self.get(recording_id)
        if current.state is not RecordingState.RECORDING:
            return current
        provider.stop(provider_ref=current.provider_ref)
        updated = replace(current, state=RecordingState.STOPPED, stopped_at=stopped_at)
        self._replace(updated)
        return updated

    def delete(self, recording_id: str, *, provider: RecordingProviderPort, deleted_at: str) -> LessonRecording:
        current = self.get(recording_id)
        if current.state is RecordingState.DELETED:
            return current
        provider.delete(provider_ref=current.provider_ref)
        updated = replace(current, state=RecordingState.DELETED, stopped_at=current.stopped_at or deleted_at)
        self._replace(updated)
        return updated

    def _replace(self, updated: LessonRecording) -> None:
        self._records = tuple(updated if item.recording_id == updated.recording_id else item for item in self._records)

    def to_json(self) -> str:
        payload = {"version": 1, "records": [item.to_record() for item in self._records]}
        return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def policy_digest(policy: RecordingPolicy) -> str:
    if not isinstance(policy, RecordingPolicy):
        raise LessonRecordingError("recording policy is invalid")
    return _sha({
        "storage_region": policy.storage_region,
        "retention_days": policy.retention_days,
        "allow_audio": policy.allow_audio,
        "allow_video": policy.allow_video,
        "allow_chat_transcript": policy.allow_chat_transcript,
    })


def _id(value: object, label: str) -> str:
    if type(value) is not str or not _ID_RE.fullmatch(value):
        raise LessonRecordingError(f"{label} is invalid")
    return value


def _timestamp(value: object) -> str:
    if type(value) is not str:
        raise LessonRecordingError("timestamp is invalid")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise LessonRecordingError("timestamp is invalid") from None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise LessonRecordingError("timestamp must include timezone")
    return parsed.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _digest_text(value: object) -> str:
    if type(value) is not str or not re.fullmatch(r"[0-9a-f]{64}", value):
        raise LessonRecordingError("policy digest is invalid")
    return value


def _sha(value: object) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()
