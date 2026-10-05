from __future__ import annotations

"""Deterministic group-lesson rotation scheduling for child coaching.

Rotation owns only teaching-flow order. Pair creation, clocks, colors, game
sessions, chess state and deployment remain external authorities.
"""

from dataclasses import dataclass, replace
from enum import Enum
import hashlib
import json
import re
from typing import Mapping

from .teaching_session import LessonSession

ROTATION_VERSION = 1
MAX_ROTATION_ROUNDS = 64
MAX_ROTATION_TARGETS = 2000
MAX_ROTATION_JSON_BYTES = 512_000
MAX_ROTATION_MINUTES = 90
MAX_TOTAL_ROTATION_MINUTES = 240
_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_DIGEST_RE = re.compile(r"^[0-9a-f]{64}$")
_MAX_WIRE_INTEGER = (1 << 53) - 1


class ChildCoachingRotationError(ValueError):
    """Stable validation failure for rotation contracts."""


class RotationActivity(str, Enum):
    DEMONSTRATION = "demonstration"
    TASK_WORK = "task_work"
    PAIR_PLAY = "pair_play"
    ATTENTION_BREAK = "attention_break"
    REVIEW = "review"


class RotationTarget(str, Enum):
    ALL = "all"
    GROUP = "group"
    SELECTED = "selected"


class RotationPhase(str, Enum):
    PLANNED = "planned"
    ACTIVE = "active"
    COMPLETED = "completed"


@dataclass(frozen=True, slots=True)
class RotationRound:
    round_id: str
    activity: RotationActivity
    title: str
    minutes: int
    target: RotationTarget = RotationTarget.ALL
    target_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "round_id", _identifier(self.round_id, "rotation round id"))
        object.__setattr__(
            self,
            "activity",
            _enum(self.activity, RotationActivity, "rotation activity"),
        )
        object.__setattr__(self, "title", _text(self.title, "rotation round title", 160))
        if type(self.minutes) is not int or not 1 <= self.minutes <= MAX_ROTATION_MINUTES:
            raise ChildCoachingRotationError(
                f"rotation minutes must be an integer from 1 to {MAX_ROTATION_MINUTES}"
            )
        object.__setattr__(
            self,
            "target",
            _enum(self.target, RotationTarget, "rotation target"),
        )
        if type(self.target_ids) is not tuple or len(self.target_ids) > MAX_ROTATION_TARGETS:
            raise ChildCoachingRotationError("rotation target_ids must be a bounded tuple")
        targets = tuple(
            _identifier(item, "rotation target id")
            for item in self.target_ids
        )
        if len(set(targets)) != len(targets):
            raise ChildCoachingRotationError("rotation target ids must be unique")
        if self.target is RotationTarget.ALL and targets:
            raise ChildCoachingRotationError("all-student rotation must not list target ids")
        if self.target is not RotationTarget.ALL and not targets:
            raise ChildCoachingRotationError("scoped rotation requires target ids")
        object.__setattr__(self, "target_ids", targets)

    def to_record(self) -> dict[str, object]:
        return {
            "round_id": self.round_id,
            "activity": self.activity.value,
            "title": self.title,
            "minutes": self.minutes,
            "target": self.target.value,
            "target_ids": list(self.target_ids),
        }

    @classmethod
    def from_record(cls, value: Mapping[str, object]) -> "RotationRound":
        data = _mapping(value, "rotation round")
        _exact_keys(
            data,
            {"round_id", "activity", "title", "minutes", "target", "target_ids"},
            "rotation round",
        )
        raw_targets = data["target_ids"]
        if type(raw_targets) is not list:
            raise ChildCoachingRotationError("rotation target_ids must be an array")
        return cls(
            round_id=data["round_id"],
            activity=data["activity"],
            title=data["title"],
            minutes=data["minutes"],
            target=data["target"],
            target_ids=tuple(raw_targets),
        )


@dataclass(frozen=True, slots=True)
class RotationPlan:
    rotation_id: str
    lesson_session_id: str
    lesson_plan_digest: str
    rounds: tuple[RotationRound, ...]
    version: int = ROTATION_VERSION

    def __post_init__(self) -> None:
        _version(self.version)
        object.__setattr__(
            self,
            "rotation_id",
            _identifier(self.rotation_id, "rotation id"),
        )
        object.__setattr__(
            self,
            "lesson_session_id",
            _identifier(self.lesson_session_id, "lesson session id"),
        )
        object.__setattr__(
            self,
            "lesson_plan_digest",
            _digest_text(self.lesson_plan_digest, "lesson plan digest"),
        )
        if (
            type(self.rounds) is not tuple
            or not self.rounds
            or len(self.rounds) > MAX_ROTATION_ROUNDS
            or any(type(item) is not RotationRound for item in self.rounds)
        ):
            raise ChildCoachingRotationError(
                f"rotation plan requires 1..{MAX_ROTATION_ROUNDS} rounds"
            )
        ids = tuple(item.round_id for item in self.rounds)
        if len(set(ids)) != len(ids):
            raise ChildCoachingRotationError("rotation round ids must be unique")
        if self.total_minutes > MAX_TOTAL_ROTATION_MINUTES:
            raise ChildCoachingRotationError(
                f"rotation plan exceeds {MAX_TOTAL_ROTATION_MINUTES} minutes"
            )

    @property
    def total_minutes(self) -> int:
        return sum(item.minutes for item in self.rounds)

    @property
    def digest(self) -> str:
        return _digest(_plan_body(self))

    def to_record(self) -> dict[str, object]:
        body = _plan_body(self)
        body["digest"] = _digest(body)
        return body

    def to_json(self) -> str:
        return _bounded_json(self.to_record())

    @classmethod
    def from_record(cls, value: Mapping[str, object]) -> "RotationPlan":
        data = _mapping(value, "rotation plan")
        _exact_keys(
            data,
            {
                "version", "rotation_id", "lesson_session_id",
                "lesson_plan_digest", "rounds", "digest",
            },
            "rotation plan",
        )
        supplied = _digest_text(data["digest"], "rotation plan digest")
        raw_rounds = data["rounds"]
        if (
            type(raw_rounds) is not list
            or not raw_rounds
            or len(raw_rounds) > MAX_ROTATION_ROUNDS
        ):
            raise ChildCoachingRotationError("rotation rounds must be a bounded non-empty array")
        plan = cls(
            rotation_id=data["rotation_id"],
            lesson_session_id=data["lesson_session_id"],
            lesson_plan_digest=data["lesson_plan_digest"],
            rounds=tuple(RotationRound.from_record(item) for item in raw_rounds),
            version=data["version"],
        )
        if plan.digest != supplied:
            raise ChildCoachingRotationError("rotation plan digest mismatch")
        return plan

    @classmethod
    def from_json(cls, text: str) -> "RotationPlan":
        return cls.from_record(_parse_json(text, "rotation plan"))


@dataclass(frozen=True, slots=True)
class RotationState:
    rotation_id: str
    plan_digest: str
    phase: RotationPhase = RotationPhase.PLANNED
    round_index: int = 0
    pair_play_batch_ref: str | None = None
    revision: int = 0
    version: int = ROTATION_VERSION

    def __post_init__(self) -> None:
        _version(self.version)
        object.__setattr__(
            self,
            "rotation_id",
            _identifier(self.rotation_id, "rotation id"),
        )
        object.__setattr__(
            self,
            "plan_digest",
            _digest_text(self.plan_digest, "rotation plan digest"),
        )
        object.__setattr__(self, "phase", _enum(self.phase, RotationPhase, "rotation phase"))
        if (
            type(self.round_index) is not int
            or not 0 <= self.round_index < MAX_ROTATION_ROUNDS
        ):
            raise ChildCoachingRotationError(
                "rotation round_index must be a bounded non-negative integer"
            )
        if type(self.revision) is not int or self.revision < 0:
            raise ChildCoachingRotationError("rotation revision must be a non-negative integer")
        ref = self.pair_play_batch_ref
        if ref is not None:
            ref = _identifier(ref, "pair-play batch reference")
        object.__setattr__(self, "pair_play_batch_ref", ref)
        if self.phase is RotationPhase.PLANNED:
            if self.revision != 0 or self.round_index != 0 or ref is not None:
                raise ChildCoachingRotationError(
                    "planned rotation must be pristine at round zero"
                )
        elif self.revision < 1:
            raise ChildCoachingRotationError(
                "active/completed rotation must have a positive revision"
            )
        if self.phase is RotationPhase.COMPLETED and ref is not None:
            raise ChildCoachingRotationError("completed rotation cannot retain pair-play reference")

    @property
    def digest(self) -> str:
        return _digest(_state_body(self))

    def to_record(self) -> dict[str, object]:
        body = _state_body(self)
        body["digest"] = _digest(body)
        return body

    def to_json(self) -> str:
        return _bounded_json(self.to_record())

    @classmethod
    def from_record(cls, value: Mapping[str, object]) -> "RotationState":
        data = _mapping(value, "rotation state")
        _exact_keys(
            data,
            {
                "version", "rotation_id", "plan_digest", "phase",
                "round_index", "pair_play_batch_ref", "revision", "digest",
            },
            "rotation state",
        )
        supplied = _digest_text(data["digest"], "rotation state digest")
        state = cls(
            rotation_id=data["rotation_id"],
            plan_digest=data["plan_digest"],
            phase=data["phase"],
            round_index=data["round_index"],
            pair_play_batch_ref=data["pair_play_batch_ref"],
            revision=data["revision"],
            version=data["version"],
        )
        if state.digest != supplied:
            raise ChildCoachingRotationError("rotation state digest mismatch")
        return state

    @classmethod
    def from_json(cls, text: str) -> "RotationState":
        return cls.from_record(_parse_json(text, "rotation state"))


def build_rotation_plan(
    lesson: LessonSession,
    *,
    rotation_id: str,
    rounds: tuple[RotationRound, ...],
) -> RotationPlan:
    if type(lesson) is not LessonSession:
        raise TypeError("lesson must be canonical LessonSession")
    plan = RotationPlan(
        rotation_id=rotation_id,
        lesson_session_id=lesson.session_id,
        lesson_plan_digest=lesson.digest,
        rounds=rounds,
    )
    validate_rotation_scope(plan, lesson)
    return plan


def validate_rotation_scope(plan: RotationPlan, lesson: LessonSession) -> None:
    if type(plan) is not RotationPlan or type(lesson) is not LessonSession:
        raise TypeError("rotation scope requires RotationPlan and LessonSession")
    if plan.lesson_session_id != lesson.session_id or plan.lesson_plan_digest != lesson.digest:
        raise ChildCoachingRotationError("rotation plan is anchored to a different lesson session")
    students = set(lesson.student_ids)
    for item in plan.rounds:
        if item.target is RotationTarget.SELECTED:
            if any(target not in students for target in item.target_ids):
                raise ChildCoachingRotationError(
                    "rotation selected target is outside the lesson session"
                )


def start_rotation(plan: RotationPlan) -> RotationState:
    if type(plan) is not RotationPlan:
        raise TypeError("plan must be RotationPlan")
    return RotationState(
        rotation_id=plan.rotation_id,
        plan_digest=plan.digest,
        phase=RotationPhase.ACTIVE,
        round_index=0,
        revision=1,
    )


def current_round(plan: RotationPlan, state: RotationState) -> RotationRound:
    _match(plan, state)
    if state.phase is RotationPhase.COMPLETED:
        raise ChildCoachingRotationError("rotation is already completed")
    if state.round_index >= len(plan.rounds):
        raise ChildCoachingRotationError("rotation state round index is out of range")
    return plan.rounds[state.round_index]


def bind_pair_play_batch(
    plan: RotationPlan,
    state: RotationState,
    batch_ref: str,
    *,
    expected_revision: int,
) -> RotationState:
    item = current_round(plan, state)
    if state.phase is not RotationPhase.ACTIVE:
        raise ChildCoachingRotationError("rotation must be active")
    if item.activity is not RotationActivity.PAIR_PLAY:
        raise ChildCoachingRotationError("pair-play batch can only bind during pair-play rotation")
    ref = _identifier(batch_ref, "pair-play batch reference")
    if (
        state.pair_play_batch_ref == ref
        and type(expected_revision) is int
        and expected_revision in {state.revision, state.revision - 1}
    ):
        return state
    _expected_revision(state, expected_revision)
    if state.pair_play_batch_ref is not None:
        raise ChildCoachingRotationError("pair-play batch is already bound")
    return replace(
        state,
        pair_play_batch_ref=ref,
        revision=state.revision + 1,
    )


def advance_rotation(
    plan: RotationPlan,
    state: RotationState,
    *,
    expected_revision: int,
) -> RotationState:
    item = current_round(plan, state)
    _expected_revision(state, expected_revision)
    if state.phase is not RotationPhase.ACTIVE:
        raise ChildCoachingRotationError("rotation must be active")
    if item.activity is RotationActivity.PAIR_PLAY and state.pair_play_batch_ref is None:
        raise ChildCoachingRotationError(
            "pair-play round cannot advance before external pair-play batch is bound"
        )
    next_index = state.round_index + 1
    if next_index >= len(plan.rounds):
        return replace(
            state,
            phase=RotationPhase.COMPLETED,
            pair_play_batch_ref=None,
            revision=state.revision + 1,
        )
    return replace(
        state,
        round_index=next_index,
        pair_play_batch_ref=None,
        revision=state.revision + 1,
    )


def default_group_rotation(lesson: LessonSession, *, rotation_id: str) -> RotationPlan:
    """A conservative editable flow; pairing details remain external."""

    return build_rotation_plan(
        lesson,
        rotation_id=rotation_id,
        rounds=(
            RotationRound("demo", RotationActivity.DEMONSTRATION, "Demonstration", 10),
            RotationRound("task", RotationActivity.TASK_WORK, "Independent task", 15),
            RotationRound("pair", RotationActivity.PAIR_PLAY, "Pair play", 15),
            RotationRound("review", RotationActivity.REVIEW, "Review", 10),
        ),
    )


def _match(plan: RotationPlan, state: RotationState) -> None:
    if type(plan) is not RotationPlan or type(state) is not RotationState:
        raise TypeError("rotation operation requires RotationPlan and RotationState")
    if state.rotation_id != plan.rotation_id or state.plan_digest != plan.digest:
        raise ChildCoachingRotationError("rotation state does not match plan")


def _expected_revision(state: RotationState, expected: int) -> None:
    if type(expected) is not int or expected != state.revision:
        raise ChildCoachingRotationError("stale rotation revision")


def _plan_body(plan: RotationPlan) -> dict[str, object]:
    return {
        "version": plan.version,
        "rotation_id": plan.rotation_id,
        "lesson_session_id": plan.lesson_session_id,
        "lesson_plan_digest": plan.lesson_plan_digest,
        "rounds": [item.to_record() for item in plan.rounds],
    }


def _state_body(state: RotationState) -> dict[str, object]:
    return {
        "version": state.version,
        "rotation_id": state.rotation_id,
        "plan_digest": state.plan_digest,
        "phase": state.phase.value,
        "round_index": state.round_index,
        "pair_play_batch_ref": state.pair_play_batch_ref,
        "revision": state.revision,
    }


def _bounded_json(payload: Mapping[str, object]) -> str:
    try:
        text = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        data = text.encode("utf-8")
    except (TypeError, ValueError, UnicodeEncodeError, RecursionError) as exc:
        raise ChildCoachingRotationError("rotation contract cannot be serialized") from exc
    if len(data) > MAX_ROTATION_JSON_BYTES:
        raise ChildCoachingRotationError("rotation JSON exceeds size limit")
    return text


def _parse_json(text: object, label: str) -> Mapping[str, object]:
    if type(text) is not str:
        raise ChildCoachingRotationError(f"{label} JSON must be text")
    try:
        encoded = text.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise ChildCoachingRotationError(f"{label} JSON is invalid UTF-8 text") from exc
    if len(encoded) > MAX_ROTATION_JSON_BYTES:
        raise ChildCoachingRotationError("rotation JSON exceeds size limit")
    try:
        value = json.loads(
            text,
            object_pairs_hook=_reject_duplicate_pairs,
            parse_constant=_reject_constant,
            parse_int=_parse_wire_integer,
        )
    except ChildCoachingRotationError:
        raise
    except (json.JSONDecodeError, UnicodeError, RecursionError, ValueError) as exc:
        raise ChildCoachingRotationError(f"invalid {label} JSON") from exc
    return _mapping(value, label)


def _reject_duplicate_pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ChildCoachingRotationError(f"duplicate rotation JSON key: {key}")
        result[key] = value
    return result


def _reject_constant(value):
    raise ChildCoachingRotationError(f"non-finite rotation JSON constant: {value}")


def _parse_wire_integer(value: str) -> int:
    digits = value[1:] if value.startswith("-") else value
    if not digits or len(digits) > 16:
        raise ChildCoachingRotationError("rotation JSON integer exceeds exact wire bounds")
    parsed = int(value, 10)
    if not -_MAX_WIRE_INTEGER <= parsed <= _MAX_WIRE_INTEGER:
        raise ChildCoachingRotationError("rotation JSON integer exceeds exact wire bounds")
    return parsed


def _version(value: object) -> None:
    if type(value) is not int or value != ROTATION_VERSION:
        raise ChildCoachingRotationError(f"unsupported rotation version: {value!r}")


def _mapping(value: object, label: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise ChildCoachingRotationError(f"{label} must be an object")
    return value


def _exact_keys(data: Mapping[str, object], expected: set[str], label: str) -> None:
    if set(data) != expected:
        raise ChildCoachingRotationError(f"{label} fields are not canonical")


def _identifier(value: object, label: str) -> str:
    if type(value) is not str or _ID_RE.fullmatch(value) is None:
        raise ChildCoachingRotationError(f"{label} must be a bounded portable identifier")
    return value


def _digest_text(value: object, label: str) -> str:
    if type(value) is not str or _DIGEST_RE.fullmatch(value) is None:
        raise ChildCoachingRotationError(f"{label} must be a lowercase SHA-256 digest")
    return value


def _text(value: object, label: str, limit: int) -> str:
    if type(value) is not str:
        raise ChildCoachingRotationError(f"{label} must be text")
    normalized = value.strip()
    if not normalized or len(normalized) > limit or "\x00" in normalized:
        raise ChildCoachingRotationError(f"{label} is empty or exceeds its limit")
    try:
        normalized.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise ChildCoachingRotationError(
            f"{label} must be valid UTF-8 text"
        ) from exc
    return normalized


def _enum(value: object, cls, label: str):
    try:
        return value if isinstance(value, cls) else cls(value)
    except (TypeError, ValueError) as exc:
        raise ChildCoachingRotationError(f"invalid {label}") from exc


def _digest(payload: Mapping[str, object]) -> str:
    data = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(data).hexdigest()
