from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
import hashlib
import json
from typing import Any, Iterable, Mapping

from .chesscore import Board
from .squares import normalize_square


REMOTE_SESSION_VERSION = 1
MAX_REMOTE_EVENTS = 10000
MAX_REMOTE_SNAPSHOT_BYTES = 2_000_000
MAX_TEXT = 512


class RemoteSessionError(ValueError):
    """Raised when a remote-session payload is ambiguous, corrupt, or stale."""


class RemoteEventKind(str, Enum):
    POSITION = "position"
    POINTER = "pointer"
    HIGHLIGHT = "highlight"
    CLEAR_ANNOTATIONS = "clear_annotations"
    STUDENT_ANSWER = "student_answer"
    ACTIVE_STUDENT = "active_student"
    SPECTATOR = "spectator"
    DEMO = "demo"


@dataclass(frozen=True)
class RemoteAnnotation:
    square: str
    tag: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "square", _square(self.square, "annotation square"))
        object.__setattr__(self, "tag", _optional_text(self.tag, "annotation tag"))


@dataclass(frozen=True)
class StudentAnswer:
    student_id: str
    answer_type: str
    value: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "student_id", _text(self.student_id, "student id"))
        object.__setattr__(self, "answer_type", _text(self.answer_type, "answer type"))
        object.__setattr__(self, "value", _text(self.value, "answer value"))


@dataclass(frozen=True)
class RemoteSessionEvent:
    session_id: str
    sequence: int
    kind: RemoteEventKind
    payload: Mapping[str, Any]
    actor_id: str | None = None
    version: int = REMOTE_SESSION_VERSION
    event_id: str = field(init=False)

    def __post_init__(self) -> None:
        _version(self.version)
        session_id = _text(self.session_id, "session id")
        sequence = _positive_int(self.sequence, "sequence")
        actor_id = _optional_text(self.actor_id, "actor id")
        try:
            kind = RemoteEventKind(self.kind)
        except (TypeError, ValueError) as exc:
            raise RemoteSessionError(f"unsupported remote event kind: {self.kind!r}") from exc
        payload = _canonical_payload(kind, self.payload)
        canonical = {
            "version": self.version,
            "session_id": session_id,
            "sequence": sequence,
            "kind": kind.value,
            "actor_id": actor_id,
            "payload": payload,
        }
        event_id = hashlib.sha256(
            json.dumps(canonical, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        object.__setattr__(self, "session_id", session_id)
        object.__setattr__(self, "sequence", sequence)
        object.__setattr__(self, "kind", kind)
        object.__setattr__(self, "actor_id", actor_id)
        object.__setattr__(self, "payload", payload)
        object.__setattr__(self, "event_id", event_id)

    def to_record(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "event_id": self.event_id,
            "session_id": self.session_id,
            "sequence": self.sequence,
            "kind": self.kind.value,
            "actor_id": self.actor_id,
            "payload": _copy_json(self.payload),
        }

    @classmethod
    def from_record(cls, record: Mapping[str, Any]) -> "RemoteSessionEvent":
        data = _mapping(record, "event record")
        _exact_keys(
            data,
            {"version", "event_id", "session_id", "sequence", "kind", "actor_id", "payload"},
            "event record",
        )
        supplied_event_id = _text(data["event_id"], "event id")
        event = cls(
            version=data["version"],
            session_id=data["session_id"],
            sequence=data["sequence"],
            kind=data["kind"],
            actor_id=data["actor_id"],
            payload=data["payload"],
        )
        if supplied_event_id != event.event_id:
            raise RemoteSessionError("event id does not match canonical event content")
        return event


@dataclass(frozen=True)
class RemoteSessionState:
    session_id: str
    last_sequence: int = 0
    position_fen: str = Board.START
    pointer_square: str | None = None
    annotations: tuple[RemoteAnnotation, ...] = ()
    last_answer: StudentAnswer | None = None
    active_student_id: str | None = None
    spectator: bool = False
    demo: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "session_id", _text(self.session_id, "session id"))
        if type(self.last_sequence) is not int or self.last_sequence < 0:
            raise RemoteSessionError("last sequence must be a non-negative integer")
        object.__setattr__(self, "position_fen", _fen(self.position_fen))
        if self.pointer_square is not None:
            object.__setattr__(self, "pointer_square", _square(self.pointer_square, "pointer square"))
        annotations = tuple(self.annotations)
        if any(not isinstance(item, RemoteAnnotation) for item in annotations):
            raise RemoteSessionError("annotations must contain RemoteAnnotation values")
        object.__setattr__(self, "annotations", annotations)
        if self.last_answer is not None and not isinstance(self.last_answer, StudentAnswer):
            raise RemoteSessionError("last answer must be StudentAnswer or null")
        object.__setattr__(self, "active_student_id", _optional_text(self.active_student_id, "active student id"))
        if type(self.spectator) is not bool or type(self.demo) is not bool:
            raise RemoteSessionError("spectator and demo must be booleans")


class RemoteSessionLog:
    """Deterministic, presentation-neutral replay log for one shared lesson session.

    Transport, authentication, persistence and UI are deliberately outside this
    object. Canonical chess position validation is delegated to chesscore.Board.
    """

    def __init__(self, session_id: str) -> None:
        self._session_id = _text(session_id, "session id")
        self._events: list[RemoteSessionEvent] = []
        self._event_ids: set[str] = set()
        self._state = RemoteSessionState(session_id=self._session_id)

    @property
    def state(self) -> RemoteSessionState:
        return self._state

    @property
    def events(self) -> tuple[RemoteSessionEvent, ...]:
        return tuple(self._events)

    def append(self, event: RemoteSessionEvent) -> bool:
        if not isinstance(event, RemoteSessionEvent):
            raise RemoteSessionError("append requires RemoteSessionEvent")
        if event.session_id != self._session_id:
            raise RemoteSessionError("event belongs to a different session")
        if event.event_id in self._event_ids:
            return False
        expected = len(self._events) + 1
        if event.sequence != expected:
            raise RemoteSessionError(f"expected sequence {expected}, got {event.sequence}")
        if len(self._events) >= MAX_REMOTE_EVENTS:
            raise RemoteSessionError("remote session event limit exceeded")
        new_state = _apply_event(self._state, event)
        self._events.append(event)
        self._event_ids.add(event.event_id)
        self._state = new_state
        return True

    def extend(self, events: Iterable[RemoteSessionEvent]) -> None:
        pending = tuple(events)
        clone = RemoteSessionLog(self._session_id)
        for existing in self._events:
            clone.append(existing)
        for event in pending:
            clone.append(event)
        self._events = list(clone._events)
        self._event_ids = set(clone._event_ids)
        self._state = clone._state

    def to_snapshot(self) -> dict[str, Any]:
        records = [event.to_record() for event in self._events]
        state = _state_record(self._state)
        body = {
            "version": REMOTE_SESSION_VERSION,
            "session_id": self._session_id,
            "events": records,
            "state": state,
        }
        body["digest"] = _digest_without_digest(body)
        return body

    def to_json(self) -> str:
        text = json.dumps(self.to_snapshot(), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        if len(text.encode("utf-8")) > MAX_REMOTE_SNAPSHOT_BYTES:
            raise RemoteSessionError("remote session snapshot exceeds size limit")
        return text

    @classmethod
    def from_snapshot(cls, snapshot: Mapping[str, Any]) -> "RemoteSessionLog":
        data = _mapping(snapshot, "remote session snapshot")
        _exact_keys(data, {"version", "session_id", "events", "state", "digest"}, "remote session snapshot")
        _version(data["version"])
        supplied_digest = _text(data["digest"], "snapshot digest")
        if supplied_digest != _digest_without_digest(data):
            raise RemoteSessionError("remote session snapshot digest mismatch")
        session_id = _text(data["session_id"], "session id")
        raw_events = data["events"]
        if not isinstance(raw_events, list):
            raise RemoteSessionError("events must be a list")
        if len(raw_events) > MAX_REMOTE_EVENTS:
            raise RemoteSessionError("remote session event limit exceeded")
        log = cls(session_id)
        for raw in raw_events:
            log.append(RemoteSessionEvent.from_record(raw))
        expected_state = _state_from_record(data["state"])
        if expected_state != log.state:
            raise RemoteSessionError("snapshot state does not match deterministic event replay")
        return log

    @classmethod
    def from_json(cls, text: str) -> "RemoteSessionLog":
        if not isinstance(text, str):
            raise RemoteSessionError("snapshot JSON must be text")
        if len(text.encode("utf-8")) > MAX_REMOTE_SNAPSHOT_BYTES:
            raise RemoteSessionError("remote session snapshot exceeds size limit")
        try:
            data = json.loads(text, object_pairs_hook=_reject_duplicate_pairs, parse_constant=_reject_constant)
        except (json.JSONDecodeError, RemoteSessionError) as exc:
            if isinstance(exc, RemoteSessionError):
                raise
            raise RemoteSessionError("invalid remote session JSON") from exc
        return cls.from_snapshot(data)


def _apply_event(state: RemoteSessionState, event: RemoteSessionEvent) -> RemoteSessionState:
    kwargs = {
        "session_id": state.session_id,
        "last_sequence": event.sequence,
        "position_fen": state.position_fen,
        "pointer_square": state.pointer_square,
        "annotations": state.annotations,
        "last_answer": state.last_answer,
        "active_student_id": state.active_student_id,
        "spectator": state.spectator,
        "demo": state.demo,
    }
    payload = event.payload
    if event.kind is RemoteEventKind.POSITION:
        kwargs["position_fen"] = payload["fen"]
    elif event.kind is RemoteEventKind.POINTER:
        kwargs["pointer_square"] = payload["square"]
    elif event.kind is RemoteEventKind.HIGHLIGHT:
        annotation = RemoteAnnotation(payload["square"], payload["tag"])
        if annotation not in state.annotations:
            kwargs["annotations"] = state.annotations + (annotation,)
    elif event.kind is RemoteEventKind.CLEAR_ANNOTATIONS:
        kwargs["annotations"] = ()
    elif event.kind is RemoteEventKind.STUDENT_ANSWER:
        kwargs["last_answer"] = StudentAnswer(
            payload["student_id"], payload["answer_type"], payload["value"]
        )
    elif event.kind is RemoteEventKind.ACTIVE_STUDENT:
        kwargs["active_student_id"] = payload["student_id"]
    elif event.kind is RemoteEventKind.SPECTATOR:
        kwargs["spectator"] = payload["enabled"]
    elif event.kind is RemoteEventKind.DEMO:
        kwargs["demo"] = payload["enabled"]
    return RemoteSessionState(**kwargs)


def _canonical_payload(kind: RemoteEventKind, payload: object) -> dict[str, Any]:
    data = _mapping(payload, "event payload")
    if kind is RemoteEventKind.POSITION:
        _exact_keys(data, {"fen"}, "position payload")
        return {"fen": _fen(data["fen"])}
    if kind is RemoteEventKind.POINTER:
        _exact_keys(data, {"square"}, "pointer payload")
        return {"square": _square(data["square"], "pointer square")}
    if kind is RemoteEventKind.HIGHLIGHT:
        _exact_keys(data, {"square", "tag"}, "highlight payload")
        return {
            "square": _square(data["square"], "highlight square"),
            "tag": _optional_text(data["tag"], "highlight tag"),
        }
    if kind is RemoteEventKind.CLEAR_ANNOTATIONS:
        _exact_keys(data, set(), "clear-annotations payload")
        return {}
    if kind is RemoteEventKind.STUDENT_ANSWER:
        _exact_keys(data, {"student_id", "answer_type", "value"}, "student-answer payload")
        return {
            "student_id": _text(data["student_id"], "student id"),
            "answer_type": _text(data["answer_type"], "answer type"),
            "value": _text(data["value"], "answer value"),
        }
    if kind is RemoteEventKind.ACTIVE_STUDENT:
        _exact_keys(data, {"student_id"}, "active-student payload")
        return {"student_id": _optional_text(data["student_id"], "student id")}
    if kind in {RemoteEventKind.SPECTATOR, RemoteEventKind.DEMO}:
        _exact_keys(data, {"enabled"}, f"{kind.value} payload")
        if type(data["enabled"]) is not bool:
            raise RemoteSessionError("enabled must be a boolean")
        return {"enabled": data["enabled"]}
    raise RemoteSessionError(f"unsupported remote event kind: {kind!r}")


def _state_record(state: RemoteSessionState) -> dict[str, Any]:
    return {
        "session_id": state.session_id,
        "last_sequence": state.last_sequence,
        "position_fen": state.position_fen,
        "pointer_square": state.pointer_square,
        "annotations": [{"square": item.square, "tag": item.tag} for item in state.annotations],
        "last_answer": None
        if state.last_answer is None
        else {
            "student_id": state.last_answer.student_id,
            "answer_type": state.last_answer.answer_type,
            "value": state.last_answer.value,
        },
        "active_student_id": state.active_student_id,
        "spectator": state.spectator,
        "demo": state.demo,
    }


def _state_from_record(value: object) -> RemoteSessionState:
    data = _mapping(value, "state record")
    _exact_keys(
        data,
        {
            "session_id",
            "last_sequence",
            "position_fen",
            "pointer_square",
            "annotations",
            "last_answer",
            "active_student_id",
            "spectator",
            "demo",
        },
        "state record",
    )
    raw_annotations = data["annotations"]
    if not isinstance(raw_annotations, list):
        raise RemoteSessionError("annotations must be a list")
    annotations: list[RemoteAnnotation] = []
    for raw in raw_annotations:
        item = _mapping(raw, "annotation record")
        _exact_keys(item, {"square", "tag"}, "annotation record")
        annotations.append(RemoteAnnotation(item["square"], item["tag"]))
    raw_answer = data["last_answer"]
    answer = None
    if raw_answer is not None:
        item = _mapping(raw_answer, "answer record")
        _exact_keys(item, {"student_id", "answer_type", "value"}, "answer record")
        answer = StudentAnswer(item["student_id"], item["answer_type"], item["value"])
    return RemoteSessionState(
        session_id=data["session_id"],
        last_sequence=data["last_sequence"],
        position_fen=data["position_fen"],
        pointer_square=data["pointer_square"],
        annotations=tuple(annotations),
        last_answer=answer,
        active_student_id=data["active_student_id"],
        spectator=data["spectator"],
        demo=data["demo"],
    )


def _fen(value: object) -> str:
    if not isinstance(value, str) or not value.strip():
        raise RemoteSessionError("position FEN must be non-empty text")
    try:
        return Board(value).fen()
    except (TypeError, ValueError) as exc:
        raise RemoteSessionError(f"invalid canonical position FEN: {exc}") from exc


def _square(value: object, label: str) -> str:
    if not isinstance(value, str):
        raise RemoteSessionError(f"{label} must be canonical square text")
    try:
        square = normalize_square(value)
    except ValueError as exc:
        raise RemoteSessionError(str(exc)) from exc
    if value != square:
        raise RemoteSessionError(f"{label} must use canonical lowercase algebraic form")
    return square


def _text(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise RemoteSessionError(f"{label} must be non-empty text")
    if len(value) > MAX_TEXT:
        raise RemoteSessionError(f"{label} exceeds length limit")
    return value


def _optional_text(value: object | None, label: str) -> str | None:
    if value is None:
        return None
    return _text(value, label)


def _positive_int(value: object, label: str) -> int:
    if type(value) is not int or value < 1:
        raise RemoteSessionError(f"{label} must be a positive integer")
    return value


def _version(value: object) -> int:
    if type(value) is not int or value != REMOTE_SESSION_VERSION:
        raise RemoteSessionError(f"unsupported remote session version: {value!r}")
    return value


def _mapping(value: object, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise RemoteSessionError(f"{label} must be an object")
    if any(not isinstance(key, str) for key in value):
        raise RemoteSessionError(f"{label} keys must be text")
    return value


def _exact_keys(value: Mapping[str, Any], expected: set[str], label: str) -> None:
    actual = set(value)
    if actual != expected:
        missing = sorted(expected - actual)
        extra = sorted(actual - expected)
        raise RemoteSessionError(f"{label} schema mismatch; missing={missing}, extra={extra}")


def _digest_without_digest(value: Mapping[str, Any]) -> str:
    body = {key: _copy_json(item) for key, item in value.items() if key != "digest"}
    return hashlib.sha256(
        json.dumps(body, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _copy_json(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _copy_json(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_copy_json(item) for item in value]
    if isinstance(value, tuple):
        return [_copy_json(item) for item in value]
    return value


def _reject_duplicate_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise RemoteSessionError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _reject_constant(value: str) -> None:
    raise RemoteSessionError(f"non-finite JSON constant is not allowed: {value}")
