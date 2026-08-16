from __future__ import annotations

import random
from dataclasses import dataclass, field
from enum import Enum
from typing import Mapping, Sequence


class LessonItemKind(str, Enum):
    WARM_UP = "warm_up"
    EXPLANATION = "explanation"
    POSITION = "position"
    EXERCISE = "exercise"
    MINI_GAME = "mini_game"
    PAIR_PLAY = "pair_play"
    REVIEW = "review"
    RECAP = "recap"
    BREAK = "break"


class AssignmentTarget(str, Enum):
    ALL = "all"
    PARTICIPANTS = "participants"
    GROUP = "group"


class PairingMode(str, Enum):
    SEQUENTIAL = "sequential"
    RANDOM = "random"


@dataclass(frozen=True)
class LessonPosition:
    position_id: str
    title: str
    fen: str
    prompt: str = ""
    teacher_notes: str = ""
    tags: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        position_id = _stable_id(self.position_id, "position_id")
        title = str(self.title).strip()
        fen = str(self.fen)
        if not title:
            raise ValueError("lesson position title must not be empty")
        if not fen.strip():
            raise ValueError("lesson position FEN must not be empty")
        tags = tuple(_stable_id(tag, "tag") for tag in self.tags)
        object.__setattr__(self, "position_id", position_id)
        object.__setattr__(self, "title", title)
        object.__setattr__(self, "fen", fen)
        object.__setattr__(self, "prompt", str(self.prompt).strip())
        object.__setattr__(self, "teacher_notes", str(self.teacher_notes).strip())
        object.__setattr__(self, "tags", tags)


@dataclass(frozen=True)
class PositionAssignment:
    assignment_id: str
    position_id: str
    target: AssignmentTarget = AssignmentTarget.ALL
    participant_ids: tuple[str, ...] = ()
    group_id: str | None = None

    def __post_init__(self) -> None:
        assignment_id = _stable_id(self.assignment_id, "assignment_id")
        position_id = _stable_id(self.position_id, "position_id")
        participants = tuple(_nonempty(value, "participant_id") for value in self.participant_ids)
        if len(set(participants)) != len(participants):
            raise ValueError("position assignment contains duplicate participant IDs")
        group_id = _nonempty(self.group_id, "group_id") if self.group_id is not None else None
        if self.target is AssignmentTarget.ALL:
            if participants or group_id is not None:
                raise ValueError("all-target assignment cannot contain participant/group target")
        elif self.target is AssignmentTarget.PARTICIPANTS:
            if not participants or group_id is not None:
                raise ValueError("participant-target assignment requires participant_ids only")
        elif self.target is AssignmentTarget.GROUP:
            if group_id is None or participants:
                raise ValueError("group-target assignment requires group_id only")
        object.__setattr__(self, "assignment_id", assignment_id)
        object.__setattr__(self, "position_id", position_id)
        object.__setattr__(self, "participant_ids", participants)
        object.__setattr__(self, "group_id", group_id)


@dataclass(frozen=True)
class LessonItem:
    item_id: str
    kind: LessonItemKind
    title: str
    duration_minutes: int
    position_id: str | None = None
    notes: str = ""

    def __post_init__(self) -> None:
        item_id = _stable_id(self.item_id, "item_id")
        title = str(self.title).strip()
        if not title:
            raise ValueError("lesson item title must not be empty")
        if isinstance(self.duration_minutes, bool) or int(self.duration_minutes) <= 0:
            raise ValueError("lesson item duration_minutes must be positive")
        position_id = _stable_id(self.position_id, "position_id") if self.position_id is not None else None
        if self.kind is LessonItemKind.POSITION and position_id is None:
            raise ValueError("position lesson item requires position_id")
        object.__setattr__(self, "item_id", item_id)
        object.__setattr__(self, "title", title)
        object.__setattr__(self, "duration_minutes", int(self.duration_minutes))
        object.__setattr__(self, "position_id", position_id)
        object.__setattr__(self, "notes", str(self.notes).strip())


@dataclass(frozen=True)
class LessonPlan:
    lesson_id: str
    title: str
    age_band: str
    level: str
    items: tuple[LessonItem, ...]
    positions: tuple[LessonPosition, ...] = ()
    assignments: tuple[PositionAssignment, ...] = ()

    def __post_init__(self) -> None:
        lesson_id = _stable_id(self.lesson_id, "lesson_id")
        title = str(self.title).strip()
        if not title or not self.items:
            raise ValueError("lesson plan requires title and at least one item")
        position_ids = [position.position_id for position in self.positions]
        if len(position_ids) != len(set(position_ids)):
            raise ValueError("lesson plan contains duplicate position IDs")
        item_ids = [item.item_id for item in self.items]
        if len(item_ids) != len(set(item_ids)):
            raise ValueError("lesson plan contains duplicate item IDs")
        assignment_ids = [assignment.assignment_id for assignment in self.assignments]
        if len(assignment_ids) != len(set(assignment_ids)):
            raise ValueError("lesson plan contains duplicate assignment IDs")
        known_positions = set(position_ids)
        for item in self.items:
            if item.position_id is not None and item.position_id not in known_positions:
                raise ValueError(f"lesson item references unknown position: {item.position_id}")
        for assignment in self.assignments:
            if assignment.position_id not in known_positions:
                raise ValueError(f"assignment references unknown position: {assignment.position_id}")
        object.__setattr__(self, "lesson_id", lesson_id)
        object.__setattr__(self, "title", title)
        object.__setattr__(self, "age_band", str(self.age_band).strip())
        object.__setattr__(self, "level", str(self.level).strip())

    @property
    def planned_minutes(self) -> int:
        return sum(item.duration_minutes for item in self.items)

    def position_map(self) -> Mapping[str, LessonPosition]:
        return {position.position_id: position for position in self.positions}


@dataclass(frozen=True)
class ClassroomPairing:
    pairing_id: str
    white_participant_id: str
    black_participant_id: str
    base_seconds: int
    increment_seconds: int = 0
    start_fen: str | None = None

    def __post_init__(self) -> None:
        pairing_id = _stable_id(self.pairing_id, "pairing_id")
        white = _nonempty(self.white_participant_id, "white participant")
        black = _nonempty(self.black_participant_id, "black participant")
        if white == black:
            raise ValueError("pairing participants must be different")
        if isinstance(self.base_seconds, bool) or int(self.base_seconds) < 0:
            raise ValueError("base_seconds must be non-negative")
        if isinstance(self.increment_seconds, bool) or int(self.increment_seconds) < 0:
            raise ValueError("increment_seconds must be non-negative")
        start_fen = None
        if self.start_fen is not None:
            start_fen = " ".join(str(self.start_fen).strip().split())
            if not start_fen:
                raise ValueError("start_fen cannot be blank")
        object.__setattr__(self, "pairing_id", pairing_id)
        object.__setattr__(self, "white_participant_id", white)
        object.__setattr__(self, "black_participant_id", black)
        object.__setattr__(self, "base_seconds", int(self.base_seconds))
        object.__setattr__(self, "increment_seconds", int(self.increment_seconds))
        object.__setattr__(self, "start_fen", start_fen)


@dataclass(frozen=True)
class PairingPlan:
    pairings: tuple[ClassroomPairing, ...]
    unpaired_participant_ids: tuple[str, ...] = ()


class PairingService:
    def create(
        self,
        participant_ids: Sequence[str],
        *,
        mode: PairingMode = PairingMode.SEQUENTIAL,
        base_seconds: int = 600,
        increment_seconds: int = 0,
        random_seed: int | None = None,
        start_fen: str | None = None,
    ) -> PairingPlan:
        ids = [_nonempty(value, "participant_id") for value in participant_ids]
        if len(ids) != len(set(ids)):
            raise ValueError("pairing input contains duplicate participant IDs")
        if mode is PairingMode.RANDOM:
            rng = random.Random(random_seed)
            rng.shuffle(ids)
        pairings: list[ClassroomPairing] = []
        for index in range(0, len(ids) - 1, 2):
            pairings.append(
                ClassroomPairing(
                    f"pair-{index // 2 + 1}",
                    ids[index],
                    ids[index + 1],
                    base_seconds,
                    increment_seconds,
                    start_fen,
                )
            )
        unpaired = tuple(ids[-1:]) if len(ids) % 2 else ()
        return PairingPlan(tuple(pairings), unpaired)


def _stable_id(value: object, field_name: str) -> str:
    text = str(value).strip().lower()
    allowed = "abcdefghijklmnopqrstuvwxyz0123456789._-"
    if not text or any(ch not in allowed for ch in text):
        raise ValueError(f"{field_name} must be a stable lowercase id")
    return text


def _nonempty(value: object, field_name: str) -> str:
    text = str(value).strip()
    if not text:
        raise ValueError(f"{field_name} must not be empty")
    return text
