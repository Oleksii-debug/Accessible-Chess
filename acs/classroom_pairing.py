from __future__ import annotations

"""Provider-neutral classroom pair-play orchestration.

This module composes the canonical :mod:`acs.teaching_session` lesson/student/start
position authority into stable pair-play launch references.  It never owns a Board,
moves, clocks, transport, or game-session runtime.  A downstream game-session owner
receives the immutable `game_session_id`, colors, time control and canonical start
FEN from this plan.
"""

from dataclasses import dataclass, fields, replace
from enum import Enum
import hashlib
import json
import random
import re
from typing import Any, Callable, Mapping

from .classroom_domain import ClassroomSnapshot
from .teaching_session import LessonSession, validate_lesson_session_scope


PAIRING_PLAN_VERSION = 1
MAX_PAIRINGS = 1_000
MAX_PAIRING_JSON_BYTES = 1_000_000
MAX_BASE_SECONDS = 24 * 60 * 60
MAX_INCREMENT_SECONDS = 60 * 60
MAX_WIRE_INTEGER = (1 << 53) - 1
_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_DIGEST_RE = re.compile(r"^[0-9a-f]{64}$")


class ClassroomPairingError(ValueError):
    """Stable fail-closed error for classroom pair-play plans."""


class PairingMode(str, Enum):
    SEQUENTIAL = "sequential"
    RANDOM = "random"


@dataclass(frozen=True)
class ClassroomPairing:
    pairing_id: str
    game_session_id: str
    white_student_id: str
    black_student_id: str
    base_seconds: int = 0
    increment_seconds: int = 0

    def __post_init__(self) -> None:
        _id(self.pairing_id, "pairing id")
        _id(self.game_session_id, "game session id")
        white = _id(self.white_student_id, "white student id")
        black = _id(self.black_student_id, "black student id")
        if white == black:
            raise ClassroomPairingError("pairing students must be distinct")
        _time(self.base_seconds, MAX_BASE_SECONDS, "base seconds")
        _time(self.increment_seconds, MAX_INCREMENT_SECONDS, "increment seconds")


@dataclass(frozen=True)
class PairingBatch:
    batch_id: str
    lesson_session_id: str
    lesson_session_digest: str
    start_fen: str
    mode: PairingMode
    pairings: tuple[ClassroomPairing, ...]
    unpaired_student_ids: tuple[str, ...] = ()
    version: int = PAIRING_PLAN_VERSION

    def __post_init__(self) -> None:
        _version(self.version)
        _id(self.batch_id, "pairing batch id")
        _id(self.lesson_session_id, "lesson session id")
        _digest_text(self.lesson_session_digest, "lesson session digest")
        if type(self.start_fen) is not str or not self.start_fen.strip() or self.start_fen != self.start_fen.strip():
            raise ClassroomPairingError("pairing start FEN must be exact non-empty text")
        mode = _enum(self.mode, PairingMode, "pairing mode")
        object.__setattr__(self, "mode", mode)
        if type(self.pairings) is not tuple or len(self.pairings) > MAX_PAIRINGS:
            raise ClassroomPairingError("pairings must be a bounded tuple")
        if any(type(item) is not ClassroomPairing for item in self.pairings):
            raise ClassroomPairingError("pairings contain invalid record type")
        unpaired = _id_tuple(self.unpaired_student_ids, "unpaired student ids")
        object.__setattr__(self, "unpaired_student_ids", unpaired)

        pairing_ids = tuple(item.pairing_id for item in self.pairings)
        game_ids = tuple(item.game_session_id for item in self.pairings)
        if len(set(pairing_ids)) != len(pairing_ids):
            raise ClassroomPairingError("pairing ids must be unique")
        if len(set(game_ids)) != len(game_ids):
            raise ClassroomPairingError("game session ids must be unique")

        students = [
            student_id
            for item in self.pairings
            for student_id in (item.white_student_id, item.black_student_id)
        ]
        students.extend(unpaired)
        if len(set(students)) != len(students):
            raise ClassroomPairingError("a student may appear only once in a pairing batch")

    @property
    def digest(self) -> str:
        return _digest(self._body())

    def _body(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "batch_id": self.batch_id,
            "lesson_session_id": self.lesson_session_id,
            "lesson_session_digest": self.lesson_session_digest,
            "start_fen": self.start_fen,
            "mode": self.mode.value,
            "pairings": [_encode_record(item) for item in self.pairings],
            "unpaired_student_ids": list(self.unpaired_student_ids),
        }

    def to_record(self) -> dict[str, Any]:
        body = self._body()
        body["digest"] = _digest(body)
        return body

    def to_json(self) -> str:
        text = _canonical_json(self.to_record())
        if len(text.encode("utf-8")) > MAX_PAIRING_JSON_BYTES:
            raise ClassroomPairingError("pairing batch JSON exceeds size limit")
        return text

    @classmethod
    def from_record(cls, value: Mapping[str, Any]) -> "PairingBatch":
        data = _mapping(value, "pairing batch")
        expected = {
            "version", "batch_id", "lesson_session_id", "lesson_session_digest",
            "start_fen", "mode", "pairings", "unpaired_student_ids", "digest",
        }
        _exact_keys(data, expected, "pairing batch")
        _version(data["version"])
        supplied = _digest_text(data["digest"], "pairing batch digest")
        body = {key: data[key] for key in expected if key != "digest"}
        if _digest(body) != supplied:
            raise ClassroomPairingError("pairing batch digest mismatch")

        raw_pairings = data["pairings"]
        if type(raw_pairings) is not list or len(raw_pairings) > MAX_PAIRINGS:
            raise ClassroomPairingError("pairings must be a bounded JSON array")
        pairing_fields = {field.name for field in fields(ClassroomPairing)}
        pairings = []
        for raw in raw_pairings:
            item = _mapping(raw, "ClassroomPairing record")
            _exact_keys(item, pairing_fields, "ClassroomPairing record")
            pairings.append(ClassroomPairing(**dict(item)))

        raw_unpaired = data["unpaired_student_ids"]
        if type(raw_unpaired) is not list:
            raise ClassroomPairingError("unpaired student ids must be a JSON array")
        return cls(
            batch_id=data["batch_id"],
            lesson_session_id=data["lesson_session_id"],
            lesson_session_digest=data["lesson_session_digest"],
            start_fen=data["start_fen"],
            mode=data["mode"],
            pairings=tuple(pairings),
            unpaired_student_ids=tuple(raw_unpaired),
            version=data["version"],
        )

    @classmethod
    def from_json(cls, text: str) -> "PairingBatch":
        if type(text) is not str:
            raise ClassroomPairingError("pairing batch JSON must be exact text")
        try:
            encoded = text.encode("utf-8")
        except UnicodeEncodeError as exc:
            raise ClassroomPairingError("pairing batch JSON contains invalid Unicode") from exc
        if len(encoded) > MAX_PAIRING_JSON_BYTES:
            raise ClassroomPairingError("pairing batch JSON exceeds size limit")
        try:
            raw = json.loads(
                text,
                object_pairs_hook=_reject_duplicate_pairs,
                parse_constant=_reject_constant,
                parse_int=_parse_wire_integer,
            )
        except json.JSONDecodeError as exc:
            raise ClassroomPairingError("invalid pairing batch JSON") from exc
        except RecursionError as exc:
            raise ClassroomPairingError("pairing batch JSON exceeds nesting limit") from exc
        return cls.from_record(raw)


Shuffle = Callable[[list[str]], None]


def plan_pairings(
    lesson_session: LessonSession,
    classroom: ClassroomSnapshot,
    *,
    batch_id: str,
    game_session_ids: tuple[str, ...],
    student_ids: tuple[str, ...] | None = None,
    mode: PairingMode | str = PairingMode.SEQUENTIAL,
    base_seconds: int = 0,
    increment_seconds: int = 0,
    shuffle: Shuffle | None = None,
) -> PairingBatch:
    """Create one stable pair-play launch plan without creating game state."""

    if type(lesson_session) is not LessonSession:
        raise ClassroomPairingError("pairing plan requires canonical LessonSession")
    if type(classroom) is not ClassroomSnapshot:
        raise ClassroomPairingError("pairing plan requires canonical ClassroomSnapshot")
    try:
        validate_lesson_session_scope(lesson_session, classroom)
    except Exception as exc:
        raise ClassroomPairingError("lesson session is outside current classroom scope") from exc

    batch_id = _id(batch_id, "pairing batch id")
    mode = _enum(mode, PairingMode, "pairing mode")
    _time(base_seconds, MAX_BASE_SECONDS, "base seconds")
    _time(increment_seconds, MAX_INCREMENT_SECONDS, "increment seconds")

    selected = lesson_session.student_ids if student_ids is None else _id_tuple(student_ids, "pairing student ids")
    allowed = frozenset(lesson_session.student_ids)
    if any(student_id not in allowed for student_id in selected):
        raise ClassroomPairingError("pairing student is outside lesson session")
    active = {
        item.student_id
        for item in classroom.students
        if not item.deleted
    }
    if any(student_id not in active for student_id in selected):
        raise ClassroomPairingError("pairing student is unavailable")

    ordered = list(selected)
    if mode is PairingMode.RANDOM:
        if shuffle is None:
            random.SystemRandom().shuffle(ordered)
        else:
            if not callable(shuffle):
                raise ClassroomPairingError("shuffle must be callable")
            before = tuple(ordered)
            shuffle(ordered)
            if sorted(ordered) != sorted(before) or len(ordered) != len(before):
                raise ClassroomPairingError("shuffle must preserve the exact student set")

    pair_count = len(ordered) // 2
    if type(game_session_ids) is not tuple or len(game_session_ids) != pair_count:
        raise ClassroomPairingError("game_session_ids must match the number of pairs")
    checked_game_ids = tuple(_id(item, "game session id") for item in game_session_ids)
    if len(set(checked_game_ids)) != len(checked_game_ids):
        raise ClassroomPairingError("game session ids must be unique")

    pairings = []
    for index in range(pair_count):
        white = ordered[index * 2]
        black = ordered[index * 2 + 1]
        pairings.append(
            ClassroomPairing(
                pairing_id=_pairing_id(batch_id, index),
                game_session_id=checked_game_ids[index],
                white_student_id=white,
                black_student_id=black,
                base_seconds=base_seconds,
                increment_seconds=increment_seconds,
            )
        )
    unpaired = tuple(ordered[pair_count * 2 :])
    return PairingBatch(
        batch_id=batch_id,
        lesson_session_id=lesson_session.session_id,
        lesson_session_digest=lesson_session.digest,
        start_fen=lesson_session.source.fen,
        mode=mode,
        pairings=tuple(pairings),
        unpaired_student_ids=unpaired,
    )


def override_pairing(
    batch: PairingBatch,
    *,
    pairing_id: str,
    white_student_id: str,
    black_student_id: str,
    base_seconds: int | None = None,
    increment_seconds: int | None = None,
) -> PairingBatch:
    """Swap colors and/or time control without changing stable game identity."""

    if type(batch) is not PairingBatch:
        raise ClassroomPairingError("override requires PairingBatch")
    pairing_id = _id(pairing_id, "pairing id")
    existing = next((item for item in batch.pairings if item.pairing_id == pairing_id), None)
    if existing is None:
        raise ClassroomPairingError("unknown pairing id")
    white = _id(white_student_id, "white student id")
    black = _id(black_student_id, "black student id")
    if {white, black} != {existing.white_student_id, existing.black_student_id}:
        raise ClassroomPairingError("pairing override cannot change participant membership")
    resolved_base = existing.base_seconds if base_seconds is None else base_seconds
    resolved_increment = existing.increment_seconds if increment_seconds is None else increment_seconds
    replacement = ClassroomPairing(
        pairing_id=existing.pairing_id,
        game_session_id=existing.game_session_id,
        white_student_id=white,
        black_student_id=black,
        base_seconds=resolved_base,
        increment_seconds=resolved_increment,
    )
    return replace(
        batch,
        pairings=tuple(replacement if item.pairing_id == pairing_id else item for item in batch.pairings),
    )


def assert_pairing_scope(
    batch: PairingBatch,
    lesson_session: LessonSession,
    classroom: ClassroomSnapshot,
) -> None:
    """Validate a deserialized/reconnected plan against live canonical authorities."""

    if type(batch) is not PairingBatch:
        raise ClassroomPairingError("scope check requires PairingBatch")
    if type(lesson_session) is not LessonSession or type(classroom) is not ClassroomSnapshot:
        raise ClassroomPairingError("scope check requires canonical lesson and classroom")
    try:
        validate_lesson_session_scope(lesson_session, classroom)
    except Exception as exc:
        raise ClassroomPairingError("lesson session is outside current classroom scope") from exc
    if (
        batch.lesson_session_id != lesson_session.session_id
        or batch.lesson_session_digest != lesson_session.digest
        or batch.start_fen != lesson_session.source.fen
    ):
        raise ClassroomPairingError("pairing batch does not match the lesson session")

    allowed = frozenset(lesson_session.student_ids)
    active = {item.student_id for item in classroom.students if not item.deleted}
    for student_id in (
        *(student for item in batch.pairings for student in (item.white_student_id, item.black_student_id)),
        *batch.unpaired_student_ids,
    ):
        if student_id not in allowed or student_id not in active:
            raise ClassroomPairingError("pairing batch references unavailable lesson student")


def _pairing_id(batch_id: str, index: int) -> str:
    digest = hashlib.sha256(f"{batch_id}:{index}".encode("utf-8")).hexdigest()[:24]
    return f"pair-{digest}"


def _time(value: object, maximum: int, label: str) -> int:
    if type(value) is not int or not 0 <= value <= maximum:
        raise ClassroomPairingError(f"{label} must be an integer from 0 to {maximum}")
    return value


def _id(value: object, label: str) -> str:
    if type(value) is not str or _ID_RE.fullmatch(value) is None:
        raise ClassroomPairingError(f"{label} must be a canonical opaque identifier")
    return value


def _id_tuple(value: object, label: str) -> tuple[str, ...]:
    if type(value) is not tuple or len(value) > MAX_PAIRINGS * 2 + 1:
        raise ClassroomPairingError(f"{label} must be a bounded tuple")
    checked = tuple(_id(item, label) for item in value)
    if len(set(checked)) != len(checked):
        raise ClassroomPairingError(f"{label} contains duplicate identifiers")
    return checked


def _enum(value: object, enum_type, label: str):
    if type(value) is enum_type:
        return value
    if type(value) is not str:
        raise ClassroomPairingError(f"{label} is invalid")
    try:
        return enum_type(value)
    except ValueError as exc:
        raise ClassroomPairingError(f"unsupported {label}: {value!r}") from exc


def _version(value: object) -> int:
    if type(value) is not int or value != PAIRING_PLAN_VERSION:
        raise ClassroomPairingError(f"unsupported pairing plan version: {value!r}")
    return value


def _digest_text(value: object, label: str) -> str:
    if type(value) is not str or _DIGEST_RE.fullmatch(value) is None:
        raise ClassroomPairingError(f"{label} must be lowercase SHA-256 hex")
    return value


def _encode_record(item: ClassroomPairing) -> dict[str, Any]:
    return {field.name: getattr(item, field.name) for field in fields(item)}


def _mapping(value: object, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or any(type(key) is not str for key in value):
        raise ClassroomPairingError(f"{label} must be an exact-key object")
    return value


def _exact_keys(value: Mapping[str, Any], expected: set[str], label: str) -> None:
    actual = set(value)
    if actual != expected:
        raise ClassroomPairingError(
            f"{label} schema mismatch; missing={sorted(expected-actual)}, extra={sorted(actual-expected)}"
        )


def _canonical_json(value: object) -> str:
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    except (TypeError, ValueError, RecursionError) as exc:
        raise ClassroomPairingError("pairing batch cannot be serialized canonically") from exc


def _digest(value: object) -> str:
    text = _canonical_json(value)
    try:
        encoded = text.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise ClassroomPairingError("pairing batch contains invalid Unicode") from exc
    return hashlib.sha256(encoded).hexdigest()


def _parse_wire_integer(value: str) -> int:
    digits = value[1:] if value.startswith("-") else value
    if not digits or len(digits) > 16:
        raise ClassroomPairingError("pairing JSON integer exceeds exact wire bounds")
    parsed = int(value, 10)
    if not -MAX_WIRE_INTEGER <= parsed <= MAX_WIRE_INTEGER:
        raise ClassroomPairingError("pairing JSON integer exceeds exact wire bounds")
    return parsed


def _reject_duplicate_pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ClassroomPairingError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _reject_constant(value):
    raise ClassroomPairingError(f"non-finite JSON constant is not allowed: {value}")
