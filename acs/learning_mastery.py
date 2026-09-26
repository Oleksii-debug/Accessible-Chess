from __future__ import annotations

"""Local, deterministic learning-mastery progression for Accessible Chess.

This module consumes already-decided Training outcomes. It never parses moves,
judges chess correctness, opens content, or owns Training persistence. The model
is intentionally non-lossy: practice can add progress, but inactivity, mistakes,
hints, clock gaps, or mode changes never subtract earned mastery.
"""

from dataclasses import dataclass, replace
from datetime import date
from enum import Enum
import hashlib
import json
import re
from typing import Any, Mapping


MASTERY_SCHEMA_VERSION = 1
_MAX_WIRE_INTEGER = (1 << 53) - 1
_MAX_POINTS = 10_000_000_000
_MAX_COUNTER = 1_000_000_000
_MAX_BESTS = 4096
_CHILD_DAILY_CAP = 500
_ADULT_DAILY_CAP = 2000
_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_SNAPSHOT_FIELDS = frozenset(
    {
        "schema_version",
        "mode",
        "revision",
        "total_points",
        "completed_count",
        "perfect_completions",
        "current_streak",
        "best_streak",
        "last_practice_date",
        "daily_points_date",
        "daily_points",
        "last_event_id",
        "last_event_digest",
        "bests",
        "digest",
    }
)
_BEST_FIELDS = frozenset(
    {"activity_id", "accuracy_bps", "mistakes", "hints_used", "duration_seconds"}
)
_OUTCOME_FIELDS = frozenset(
    {
        "sequence",
        "event_id",
        "activity_id",
        "practice_date",
        "completed",
        "correct_steps",
        "total_steps",
        "mistakes",
        "hints_used",
        "duration_seconds",
    }
)


class LearningMode(str, Enum):
    CHILD = "child"
    ADULT = "adult"


class MasteryError(ValueError):
    """Raised for stale, corrupt, ambiguous, or out-of-policy mastery state."""


@dataclass(frozen=True, slots=True)
class TrainingOutcome:
    """Chess-neutral summary emitted after canonical Training evaluates practice."""

    sequence: int
    event_id: str
    activity_id: str
    practice_date: str
    completed: bool
    correct_steps: int
    total_steps: int
    mistakes: int = 0
    hints_used: int = 0
    duration_seconds: int = 0

    def __post_init__(self) -> None:
        _positive_int(self.sequence, "outcome sequence", maximum=_MAX_COUNTER)
        object.__setattr__(self, "event_id", _identifier(self.event_id, "event id"))
        object.__setattr__(
            self, "activity_id", _identifier(self.activity_id, "activity id")
        )
        object.__setattr__(
            self, "practice_date", _iso_date(self.practice_date, "practice date")
        )
        if type(self.completed) is not bool:
            raise MasteryError("outcome completed must be boolean")
        _positive_int(self.total_steps, "total steps", maximum=100_000)
        _nonnegative_int(self.correct_steps, "correct steps", maximum=self.total_steps)
        _nonnegative_int(self.mistakes, "mistakes", maximum=100_000)
        _nonnegative_int(self.hints_used, "hints used", maximum=100_000)
        _nonnegative_int(self.duration_seconds, "duration seconds", maximum=86_400)
        if self.completed and self.correct_steps != self.total_steps:
            raise MasteryError("completed outcome must have all steps correct")

    @property
    def digest(self) -> str:
        return _digest(self.to_record())

    def to_record(self) -> dict[str, object]:
        return {
            "sequence": self.sequence,
            "event_id": self.event_id,
            "activity_id": self.activity_id,
            "practice_date": self.practice_date,
            "completed": self.completed,
            "correct_steps": self.correct_steps,
            "total_steps": self.total_steps,
            "mistakes": self.mistakes,
            "hints_used": self.hints_used,
            "duration_seconds": self.duration_seconds,
        }

    @classmethod
    def from_record(cls, value: Mapping[str, Any]) -> "TrainingOutcome":
        data = _mapping(value, "training outcome")
        if frozenset(data) != _OUTCOME_FIELDS:
            raise MasteryError("training outcome schema mismatch")
        return cls(**{key: data[key] for key in _OUTCOME_FIELDS})


@dataclass(frozen=True, slots=True)
class ActivityBest:
    activity_id: str
    accuracy_bps: int
    mistakes: int
    hints_used: int
    duration_seconds: int

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "activity_id", _identifier(self.activity_id, "activity id")
        )
        _nonnegative_int(self.accuracy_bps, "accuracy", maximum=10_000)
        _nonnegative_int(self.mistakes, "mistakes", maximum=100_000)
        _nonnegative_int(self.hints_used, "hints used", maximum=100_000)
        _nonnegative_int(self.duration_seconds, "duration seconds", maximum=86_400)

    def to_record(self) -> dict[str, object]:
        return {
            "activity_id": self.activity_id,
            "accuracy_bps": self.accuracy_bps,
            "mistakes": self.mistakes,
            "hints_used": self.hints_used,
            "duration_seconds": self.duration_seconds,
        }

    @classmethod
    def from_record(cls, value: Mapping[str, Any]) -> "ActivityBest":
        data = _mapping(value, "activity best")
        if frozenset(data) != _BEST_FIELDS:
            raise MasteryError("activity best schema mismatch")
        return cls(**{key: data[key] for key in _BEST_FIELDS})


@dataclass(frozen=True, slots=True)
class MasteryState:
    mode: LearningMode
    revision: int = 0
    total_points: int = 0
    completed_count: int = 0
    perfect_completions: int = 0
    current_streak: int = 0
    best_streak: int = 0
    last_practice_date: str | None = None
    daily_points_date: str | None = None
    daily_points: int = 0
    last_event_id: str | None = None
    last_event_digest: str | None = None
    bests: tuple[ActivityBest, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.mode, LearningMode):
            raise MasteryError("mastery mode must be LearningMode")
        _nonnegative_int(self.revision, "revision", maximum=_MAX_COUNTER)
        _nonnegative_int(self.total_points, "total points", maximum=_MAX_POINTS)
        _nonnegative_int(self.completed_count, "completed count", maximum=_MAX_COUNTER)
        _nonnegative_int(
            self.perfect_completions, "perfect completions", maximum=_MAX_COUNTER
        )
        _nonnegative_int(self.current_streak, "current streak", maximum=_MAX_COUNTER)
        _nonnegative_int(self.best_streak, "best streak", maximum=_MAX_COUNTER)
        if self.current_streak > self.best_streak:
            raise MasteryError("current streak must not exceed best streak")
        if self.last_practice_date is not None:
            object.__setattr__(
                self,
                "last_practice_date",
                _iso_date(self.last_practice_date, "last practice date"),
            )
        if self.daily_points_date is not None:
            object.__setattr__(
                self,
                "daily_points_date",
                _iso_date(self.daily_points_date, "daily points date"),
            )
        _nonnegative_int(self.daily_points, "daily points", maximum=_ADULT_DAILY_CAP)
        if self.daily_points > _ADULT_DAILY_CAP:
            raise MasteryError("daily points exceed global cap-accounting limit")
        if (self.daily_points_date is None) != (self.daily_points == 0):
            raise MasteryError("daily points date/value are inconsistent")
        if self.daily_points_date is not None and self.last_practice_date is not None:
            if self.daily_points_date != self.last_practice_date:
                raise MasteryError("daily points must describe the last practice date")
        if self.revision == 0:
            if self.last_event_id is not None or self.last_event_digest is not None:
                raise MasteryError("empty mastery state must not contain event identity")
        else:
            if self.last_event_id is None or self.last_event_digest is None:
                raise MasteryError("nonempty mastery state requires last event identity")
            object.__setattr__(
                self, "last_event_id", _identifier(self.last_event_id, "last event id")
            )
            if not _is_sha256(self.last_event_digest):
                raise MasteryError("last event digest must be lowercase SHA-256")
        if type(self.bests) is not tuple or len(self.bests) > _MAX_BESTS:
            raise MasteryError("activity bests must be a bounded tuple")
        if any(type(item) is not ActivityBest for item in self.bests):
            raise MasteryError("activity bests contain invalid record type")
        ids = tuple(item.activity_id for item in self.bests)
        if ids != tuple(sorted(ids)) or len(ids) != len(set(ids)):
            raise MasteryError("activity bests must be unique and sorted")

    @classmethod
    def empty(cls, mode: LearningMode = LearningMode.ADULT) -> "MasteryState":
        return cls(mode=mode)

    @property
    def level(self) -> int:
        return min(100, 1 + self.total_points // 500)

    @property
    def achievements(self) -> tuple[str, ...]:
        values: list[str] = []
        if self.completed_count >= 1:
            values.append("first_completion")
        if self.best_streak >= 7:
            values.append("practice_streak_7")
        if self.total_points >= 1_000:
            values.append("mastery_1000")
        if self.perfect_completions >= 10:
            values.append("perfect_10")
        return tuple(values)

    def to_record(self) -> dict[str, object]:
        body = self._body()
        body["digest"] = _digest(body)
        return body

    def _body(self) -> dict[str, object]:
        return {
            "schema_version": MASTERY_SCHEMA_VERSION,
            "mode": self.mode.value,
            "revision": self.revision,
            "total_points": self.total_points,
            "completed_count": self.completed_count,
            "perfect_completions": self.perfect_completions,
            "current_streak": self.current_streak,
            "best_streak": self.best_streak,
            "last_practice_date": self.last_practice_date,
            "daily_points_date": self.daily_points_date,
            "daily_points": self.daily_points,
            "last_event_id": self.last_event_id,
            "last_event_digest": self.last_event_digest,
            "bests": [item.to_record() for item in self.bests],
        }

    def to_json(self) -> str:
        return _canonical_json(self.to_record())

    @classmethod
    def from_record(cls, value: Mapping[str, Any]) -> "MasteryState":
        data = _mapping(value, "mastery snapshot")
        if frozenset(data) != _SNAPSHOT_FIELDS:
            raise MasteryError("mastery snapshot schema mismatch")
        supplied_digest = data["digest"]
        if not _is_sha256(supplied_digest):
            raise MasteryError("mastery snapshot digest is invalid")
        body = {key: data[key] for key in data if key != "digest"}
        if _digest(body) != supplied_digest:
            raise MasteryError("mastery snapshot digest mismatch")
        if type(data["schema_version"]) is not int or data["schema_version"] != MASTERY_SCHEMA_VERSION:
            raise MasteryError("unsupported mastery snapshot version")
        try:
            mode = LearningMode(data["mode"])
        except (TypeError, ValueError) as exc:
            raise MasteryError("invalid mastery mode") from exc
        raw_bests = data["bests"]
        if type(raw_bests) is not list or len(raw_bests) > _MAX_BESTS:
            raise MasteryError("mastery bests must be a bounded array")
        return cls(
            mode=mode,
            revision=data["revision"],
            total_points=data["total_points"],
            completed_count=data["completed_count"],
            perfect_completions=data["perfect_completions"],
            current_streak=data["current_streak"],
            best_streak=data["best_streak"],
            last_practice_date=data["last_practice_date"],
            daily_points_date=data["daily_points_date"],
            daily_points=data["daily_points"],
            last_event_id=data["last_event_id"],
            last_event_digest=data["last_event_digest"],
            bests=tuple(ActivityBest.from_record(item) for item in raw_bests),
        )

    @classmethod
    def from_json(cls, text: str) -> "MasteryState":
        if type(text) is not str:
            raise MasteryError("mastery snapshot JSON must be text")
        if len(text.encode("utf-8")) > 2_000_000:
            raise MasteryError("mastery snapshot exceeds size limit")
        try:
            raw = json.loads(
                text,
                object_pairs_hook=_reject_duplicate_pairs,
                parse_constant=_reject_constant,
                parse_int=_parse_wire_integer,
            )
        except (json.JSONDecodeError, RecursionError) as exc:
            raise MasteryError("invalid mastery snapshot JSON") from exc
        return cls.from_record(raw)


@dataclass(frozen=True, slots=True)
class MasteryUpdate:
    state: MasteryState
    earned_points: int
    capped_points: int
    new_achievements: tuple[str, ...]
    personal_best_improved: bool
    duplicate_retry: bool = False


def record_training_outcome(state: MasteryState, outcome: TrainingOutcome) -> MasteryUpdate:
    """Apply one canonical Training outcome with bounded crash-retry idempotence.

    Sequence is strictly monotonic. Retrying the exact most-recent event returns
    the same state and awards zero additional points. Older/gapped/reused events
    fail closed rather than creating duplicate rewards.
    """

    if type(state) is not MasteryState or type(outcome) is not TrainingOutcome:
        raise MasteryError("mastery update requires canonical state and outcome")

    if outcome.sequence == state.revision:
        if (
            state.last_event_id == outcome.event_id
            and state.last_event_digest == outcome.digest
        ):
            return MasteryUpdate(state, 0, 0, (), False, duplicate_retry=True)
        raise MasteryError("mastery sequence was reused with different event content")
    if outcome.sequence != state.revision + 1:
        raise MasteryError("mastery outcome sequence is stale or has a gap")

    practice_day = date.fromisoformat(outcome.practice_date)
    if state.last_practice_date is not None:
        previous_day = date.fromisoformat(state.last_practice_date)
        if practice_day < previous_day:
            raise MasteryError("mastery outcomes must be applied chronologically")

    if state.last_practice_date is None:
        current_streak = 1
    else:
        previous_day = date.fromisoformat(state.last_practice_date)
        delta = (practice_day - previous_day).days
        if delta == 0:
            current_streak = state.current_streak
        elif delta == 1:
            current_streak = state.current_streak + 1
        else:
            current_streak = 1
    best_streak = max(state.best_streak, current_streak)

    if state.daily_points_date == outcome.practice_date:
        daily_points = state.daily_points
    else:
        daily_points = 0
    raw_points = _raw_points(outcome)
    remaining = max(0, _daily_cap(state.mode) - daily_points)
    earned = min(raw_points, remaining)
    capped = raw_points - earned

    candidate_best = _best_from_outcome(outcome)
    bests, improved = _update_best(state.bests, candidate_best, mode=state.mode)
    completed_count = state.completed_count + int(outcome.completed)
    perfect = outcome.completed and outcome.mistakes == 0 and outcome.hints_used == 0
    perfect_completions = state.perfect_completions + int(perfect)

    before_achievements = set(state.achievements)
    updated = MasteryState(
        mode=state.mode,
        revision=outcome.sequence,
        total_points=state.total_points + earned,
        completed_count=completed_count,
        perfect_completions=perfect_completions,
        current_streak=current_streak,
        best_streak=best_streak,
        last_practice_date=outcome.practice_date,
        daily_points_date=outcome.practice_date if daily_points + earned else None,
        daily_points=daily_points + earned,
        last_event_id=outcome.event_id,
        last_event_digest=outcome.digest,
        bests=bests,
    )
    new_achievements = tuple(
        value for value in updated.achievements if value not in before_achievements
    )
    return MasteryUpdate(updated, earned, capped, new_achievements, improved)


def change_learning_mode(state: MasteryState, mode: LearningMode) -> MasteryState:
    """Change presentation/reward policy without deleting already-earned progress."""

    if type(state) is not MasteryState or not isinstance(mode, LearningMode):
        raise MasteryError("mode change requires canonical state and LearningMode")
    if state.mode is mode:
        return state
    # Preserve the same daily accounting window across mode changes. If a user
    # switches from adult to child after earning more than the child cap, the
    # child policy simply awards no more points that day; switching modes cannot
    # reset or bypass either cap. No already-earned mastery is removed.
    return replace(state, mode=mode)


def _raw_points(outcome: TrainingOutcome) -> int:
    # Transparent, mastery-first scoring: correct work earns credit; completion
    # and unaided accuracy add bonuses. Mistakes/hints never subtract prior or
    # newly earned base credit; they only mean the optional clean bonus is absent.
    points = outcome.correct_steps * 20
    if outcome.completed:
        points += 50
    if outcome.completed and outcome.mistakes == 0 and outcome.hints_used == 0:
        points += 20
    return points


def _best_from_outcome(outcome: TrainingOutcome) -> ActivityBest:
    accuracy = (outcome.correct_steps * 10_000) // outcome.total_steps
    return ActivityBest(
        activity_id=outcome.activity_id,
        accuracy_bps=accuracy,
        mistakes=outcome.mistakes,
        hints_used=outcome.hints_used,
        duration_seconds=outcome.duration_seconds,
    )


def _update_best(
    bests: tuple[ActivityBest, ...],
    candidate: ActivityBest,
    *,
    mode: LearningMode,
) -> tuple[tuple[ActivityBest, ...], bool]:
    existing = next((item for item in bests if item.activity_id == candidate.activity_id), None)
    if existing is not None and not _is_better(candidate, existing, mode=mode):
        return bests, False
    if existing is None and len(bests) >= _MAX_BESTS:
        raise MasteryError("activity best capacity is exhausted")
    replacement = tuple(item for item in bests if item.activity_id != candidate.activity_id)
    replacement += (candidate,)
    return tuple(sorted(replacement, key=lambda item: item.activity_id)), True


def _is_better(candidate: ActivityBest, existing: ActivityBest, *, mode: LearningMode) -> bool:
    candidate_key = (
        candidate.accuracy_bps,
        -candidate.mistakes,
        -candidate.hints_used,
    )
    existing_key = (
        existing.accuracy_bps,
        -existing.mistakes,
        -existing.hints_used,
    )
    if candidate_key != existing_key:
        return candidate_key > existing_key
    # Child mode deliberately does not reward speed as a tie-breaker.
    if mode is LearningMode.CHILD:
        return False
    if candidate.duration_seconds == 0:
        return False
    if existing.duration_seconds == 0:
        return True
    return candidate.duration_seconds < existing.duration_seconds


def _daily_cap(mode: LearningMode) -> int:
    return _CHILD_DAILY_CAP if mode is LearningMode.CHILD else _ADULT_DAILY_CAP


def _identifier(value: object, label: str) -> str:
    if type(value) is not str:
        raise MasteryError(f"{label} must be text")
    if not _ID_RE.fullmatch(value):
        raise MasteryError(f"{label} is invalid")
    return value


def _iso_date(value: object, label: str) -> str:
    if type(value) is not str:
        raise MasteryError(f"{label} must be ISO date text")
    try:
        parsed = date.fromisoformat(value)
    except ValueError as exc:
        raise MasteryError(f"{label} must be an ISO calendar date") from exc
    canonical = parsed.isoformat()
    if canonical != value:
        raise MasteryError(f"{label} must be canonical ISO date text")
    return canonical


def _positive_int(value: object, label: str, *, maximum: int) -> int:
    if type(value) is not int or not 1 <= value <= maximum:
        raise MasteryError(f"{label} is outside the allowed range")
    return value


def _nonnegative_int(value: object, label: str, *, maximum: int) -> int:
    if type(value) is not int or not 0 <= value <= maximum:
        raise MasteryError(f"{label} is outside the allowed range")
    return value


def _mapping(value: object, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise MasteryError(f"{label} must be an object")
    if any(type(key) is not str for key in value):
        raise MasteryError(f"{label} contains a non-text key")
    return value


def _canonical_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _digest(value: object) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _is_sha256(value: object) -> bool:
    return type(value) is str and bool(re.fullmatch(r"[0-9a-f]{64}", value))


def _reject_duplicate_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise MasteryError("mastery JSON contains duplicate keys")
        result[key] = value
    return result


def _reject_constant(value: str) -> None:
    raise MasteryError("mastery JSON contains a non-finite value")


def _parse_wire_integer(value: str) -> int:
    parsed = int(value)
    if not -_MAX_WIRE_INTEGER <= parsed <= _MAX_WIRE_INTEGER:
        raise MasteryError("mastery JSON integer exceeds safe wire range")
    return parsed


__all__ = [
    "ActivityBest",
    "LearningMode",
    "MasteryError",
    "MasteryState",
    "MasteryUpdate",
    "TrainingOutcome",
    "change_learning_mode",
    "record_training_outcome",
]
