from __future__ import annotations

"""Age-adaptive child-coaching templates over the canonical teaching session.

This module owns lesson-template metadata only. It deliberately does not own a
Board, chess rules, classroom transport, pair-play, or durable classroom state.
Executable lesson sessions are materialized through acs.teaching_session.
"""

from dataclasses import dataclass, replace
from enum import Enum
import hashlib
import json
import re
from typing import Mapping

from .interaction_contracts import EngineVisibilityPolicy
from .teaching_session import (
    LessonSession,
    TeachingActivity,
    TeachingInputKind,
    TeachingPositionSource,
    TeachingSessionError,
    TeachingStep,
    default_policy,
)

CHILD_COACHING_TEMPLATE_VERSION = 1
MAX_TEMPLATE_BLOCKS = 64
MAX_TEMPLATE_JSON_BYTES = 512_000
MAX_BLOCK_MINUTES = 90
MAX_TOTAL_MINUTES = 180
MAX_TITLE = 160
MAX_PROMPT = 2048
MAX_NOTE = 4096
_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_DIGEST_RE = re.compile(r"^[0-9a-f]{64}$")
_MAX_WIRE_INTEGER = (1 << 53) - 1


class ChildCoachingError(ValueError):
    """Stable validation failure for child-coaching contracts."""


class AgeBand(str, Enum):
    PRESCHOOL_4_6 = "preschool_4_6"
    YOUNG_BEGINNER_7_8 = "young_beginner_7_8"
    SCHOOL_AGE_9_10 = "school_age_9_10"
    STRONG_CHILD = "strong_child"


class LessonLevel(str, Enum):
    BEGINNER = "beginner"
    DEVELOPING = "developing"
    ADVANCED = "advanced"


class LessonBlockKind(str, Enum):
    READINESS = "readiness"
    WARM_UP = "warm_up"
    RECAP = "recap"
    CONCEPT = "concept"
    DEMONSTRATION = "demonstration"
    POINTER_TASK = "pointer_task"
    GUIDED_RESPONSE = "guided_response"
    EXERCISE = "exercise"
    MINI_GAME = "mini_game"
    SUPERVISED_GAME = "supervised_game"
    ATTENTION_BREAK = "attention_break"
    REVIEW = "review"
    HOMEWORK = "homework"


@dataclass(frozen=True, slots=True)
class LessonBlock:
    block_id: str
    kind: LessonBlockKind
    title: str
    minutes: int
    activity: TeachingActivity
    prompt: str
    notation_required: bool = False
    teacher_note: str | None = None
    target_square: str | None = None
    target_piece: str | None = None
    solution_text: str | None = None
    student_engine_visible: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "block_id", _identifier(self.block_id, "lesson block id"))
        object.__setattr__(self, "kind", _enum(self.kind, LessonBlockKind, "lesson block kind"))
        object.__setattr__(self, "title", _text(self.title, "lesson block title", MAX_TITLE))
        if type(self.minutes) is not int or not 1 <= self.minutes <= MAX_BLOCK_MINUTES:
            raise ChildCoachingError(
                f"lesson block minutes must be an integer from 1 to {MAX_BLOCK_MINUTES}"
            )
        object.__setattr__(
            self, "activity", _enum(self.activity, TeachingActivity, "teaching activity")
        )
        object.__setattr__(self, "prompt", _text(self.prompt, "student prompt", MAX_PROMPT))
        if type(self.notation_required) is not bool:
            raise ChildCoachingError("notation_required must be boolean")
        object.__setattr__(
            self,
            "teacher_note",
            _optional_text(self.teacher_note, "teacher-only note", MAX_NOTE),
        )
        if type(self.student_engine_visible) is not bool:
            raise ChildCoachingError("student_engine_visible must be boolean")
        # TeachingStep stays authoritative for activity/target/policy shape.
        step = self.to_teaching_step()
        if (
            self.kind is LessonBlockKind.POINTER_TASK
            and step.policy.input_kind is not TeachingInputKind.SELECTION
        ):
            raise ChildCoachingError(
                "pointer task must remain selection-only and cannot mutate board state"
            )

    def to_teaching_step(self) -> TeachingStep:
        visibility = (
            EngineVisibilityPolicy.VISIBLE_TO_STUDENT
            if self.student_engine_visible
            else EngineVisibilityPolicy.HIDDEN
        )
        try:
            return TeachingStep(
                step_id=self.block_id,
                activity=self.activity,
                prompt=self.prompt,
                policy=default_policy(self.activity, engine_visibility=visibility),
                target_square=self.target_square,
                target_piece=self.target_piece,
                solution_text=self.solution_text,
            )
        except TeachingSessionError as exc:
            raise ChildCoachingError(
                "lesson block is incompatible with the canonical teaching-session contract"
            ) from exc

    def to_record(self) -> dict[str, object]:
        return {
            "block_id": self.block_id,
            "kind": self.kind.value,
            "title": self.title,
            "minutes": self.minutes,
            "activity": self.activity.value,
            "prompt": self.prompt,
            "notation_required": self.notation_required,
            "teacher_note": self.teacher_note,
            "target_square": self.target_square,
            "target_piece": self.target_piece,
            "solution_text": self.solution_text,
            "student_engine_visible": self.student_engine_visible,
        }

    @classmethod
    def from_record(cls, value: Mapping[str, object]) -> "LessonBlock":
        data = _mapping(value, "lesson block")
        _exact_keys(
            data,
            {
                "block_id", "kind", "title", "minutes", "activity", "prompt",
                "notation_required", "teacher_note", "target_square", "target_piece",
                "solution_text", "student_engine_visible",
            },
            "lesson block",
        )
        return cls(
            block_id=data["block_id"],
            kind=data["kind"],
            title=data["title"],
            minutes=data["minutes"],
            activity=data["activity"],
            prompt=data["prompt"],
            notation_required=data["notation_required"],
            teacher_note=data["teacher_note"],
            target_square=data["target_square"],
            target_piece=data["target_piece"],
            solution_text=data["solution_text"],
            student_engine_visible=data["student_engine_visible"],
        )


@dataclass(frozen=True, slots=True)
class LessonTemplate:
    template_id: str
    title: str
    age_band: AgeBand
    level: LessonLevel
    blocks: tuple[LessonBlock, ...]
    custom: bool = False
    version: int = CHILD_COACHING_TEMPLATE_VERSION

    def __post_init__(self) -> None:
        if type(self.version) is not int or self.version != CHILD_COACHING_TEMPLATE_VERSION:
            raise ChildCoachingError(
                f"unsupported child-coaching template version: {self.version!r}"
            )
        object.__setattr__(self, "template_id", _identifier(self.template_id, "lesson template id"))
        object.__setattr__(self, "title", _text(self.title, "lesson template title", MAX_TITLE))
        object.__setattr__(self, "age_band", _enum(self.age_band, AgeBand, "age band"))
        object.__setattr__(self, "level", _enum(self.level, LessonLevel, "lesson level"))
        if type(self.custom) is not bool:
            raise ChildCoachingError("custom must be boolean")
        if (
            type(self.blocks) is not tuple
            or not self.blocks
            or len(self.blocks) > MAX_TEMPLATE_BLOCKS
            or any(type(block) is not LessonBlock for block in self.blocks)
        ):
            raise ChildCoachingError(
                f"lesson template requires 1..{MAX_TEMPLATE_BLOCKS} LessonBlock records"
            )
        block_ids = tuple(block.block_id for block in self.blocks)
        if len(set(block_ids)) != len(block_ids):
            raise ChildCoachingError("lesson template block ids must be unique")
        if self.total_minutes > MAX_TOTAL_MINUTES:
            raise ChildCoachingError(
                f"lesson template duration must not exceed {MAX_TOTAL_MINUTES} minutes"
            )

    @property
    def total_minutes(self) -> int:
        return sum(block.minutes for block in self.blocks)

    @property
    def no_notation_required(self) -> bool:
        return not any(block.notation_required for block in self.blocks)

    @property
    def digest(self) -> str:
        return _digest(_template_body(self))

    def to_record(self) -> dict[str, object]:
        body = _template_body(self)
        body["digest"] = _digest(body)
        return body

    @classmethod
    def from_record(cls, value: Mapping[str, object]) -> "LessonTemplate":
        data = _mapping(value, "lesson template")
        _exact_keys(
            data,
            {"version", "template_id", "title", "age_band", "level", "blocks", "custom", "digest"},
            "lesson template",
        )
        raw_blocks = data["blocks"]
        if type(raw_blocks) is not list or not raw_blocks or len(raw_blocks) > MAX_TEMPLATE_BLOCKS:
            raise ChildCoachingError("lesson template blocks must be a bounded non-empty array")
        supplied = _digest_text(data["digest"], "lesson template digest")
        template = cls(
            template_id=data["template_id"],
            title=data["title"],
            age_band=data["age_band"],
            level=data["level"],
            blocks=tuple(LessonBlock.from_record(item) for item in raw_blocks),
            custom=data["custom"],
            version=data["version"],
        )
        if template.digest != supplied:
            raise ChildCoachingError("lesson template digest mismatch")
        return template

    def to_json(self) -> str:
        return _bounded_json(self.to_record())

    @classmethod
    def from_json(cls, text: str) -> "LessonTemplate":
        return cls.from_record(_parse_json(text))

    def replace_block(self, block_id: str, replacement: LessonBlock) -> "LessonTemplate":
        block_id = _identifier(block_id, "lesson block id")
        if type(replacement) is not LessonBlock:
            raise TypeError("replacement must be LessonBlock")
        if replacement.block_id != block_id:
            raise ChildCoachingError("replacement block id must remain stable")
        found = False
        blocks: list[LessonBlock] = []
        for block in self.blocks:
            if block.block_id == block_id:
                blocks.append(replacement)
                found = True
            else:
                blocks.append(block)
        if not found:
            raise ChildCoachingError("lesson template block does not exist")
        return replace(self, blocks=tuple(blocks), custom=True)

    def append_block(self, block: LessonBlock) -> "LessonTemplate":
        if type(block) is not LessonBlock:
            raise TypeError("block must be LessonBlock")
        if any(item.block_id == block.block_id for item in self.blocks):
            raise ChildCoachingError("lesson template block id already exists")
        return replace(self, blocks=self.blocks + (block,), custom=True)

    def remove_block(self, block_id: str) -> "LessonTemplate":
        block_id = _identifier(block_id, "lesson block id")
        remaining = tuple(block for block in self.blocks if block.block_id != block_id)
        if len(remaining) == len(self.blocks):
            raise ChildCoachingError("lesson template block does not exist")
        if not remaining:
            raise ChildCoachingError("lesson template cannot remove its final block")
        return replace(self, blocks=remaining, custom=True)


def compile_lesson_session(
    template: LessonTemplate,
    *,
    session_id: str,
    lesson_id: str,
    source: TeachingPositionSource,
    student_ids: tuple[str, ...] = (),
    cohort_id: str | None = None,
    require_no_notation: bool = False,
) -> LessonSession:
    """Materialize a reusable template through the canonical session authority."""

    if type(template) is not LessonTemplate:
        raise TypeError("template must be LessonTemplate")
    if type(require_no_notation) is not bool:
        raise TypeError("require_no_notation must be boolean")
    if require_no_notation and not template.no_notation_required:
        raise ChildCoachingError("lesson template requires notation")
    if type(source) is not TeachingPositionSource:
        raise TypeError("source must be TeachingPositionSource")
    try:
        return LessonSession(
            session_id=session_id,
            lesson_id=lesson_id,
            source=source,
            steps=tuple(block.to_teaching_step() for block in template.blocks),
            student_ids=student_ids,
            cohort_id=cohort_id,
        )
    except TeachingSessionError as exc:
        raise ChildCoachingError(
            "lesson template could not be materialized as a canonical teaching session"
        ) from exc


def copy_as_custom(
    template: LessonTemplate, *, template_id: str, title: str | None = None
) -> LessonTemplate:
    if type(template) is not LessonTemplate:
        raise TypeError("template must be LessonTemplate")
    return LessonTemplate(
        template_id=template_id,
        title=template.title if title is None else title,
        age_band=template.age_band,
        level=template.level,
        blocks=template.blocks,
        custom=True,
    )


def preset_templates() -> tuple[LessonTemplate, ...]:
    return (
        LessonTemplate(
            "preset-preschool-4-6", "Preschool playful chess",
            AgeBand.PRESCHOOL_4_6, LessonLevel.BEGINNER,
            (
                _block("ready", LessonBlockKind.READINESS, "Ready to play", 3, TeachingActivity.TEACHER_EXPLAINS, "Welcome. Check comfort, attention and readiness."),
                _block("warm", LessonBlockKind.WARM_UP, "Chess attention game", 5, TeachingActivity.STUDENT_RESPONDS, "Point to the square or piece the coach names."),
                _block("concept", LessonBlockKind.CONCEPT, "One new idea", 5, TeachingActivity.TEACHER_EXPLAINS, "Listen to one short chess idea."),
                _block("demo", LessonBlockKind.DEMONSTRATION, "Show it on the board", 5, TeachingActivity.TEACHER_EXPLAINS, "Follow the board demonstration."),
                _block("find", LessonBlockKind.POINTER_TASK, "Find it", 5, TeachingActivity.STUDENT_RESPONDS, "Point to the requested square or piece. No notation is required."),
                _block("break", LessonBlockKind.ATTENTION_BREAK, "Movement break", 2, TeachingActivity.TEACHER_EXPLAINS, "Take a short movement and attention reset."),
                _block("mini", LessonBlockKind.MINI_GAME, "Mini challenge", 5, TeachingActivity.STUDENT_RESPONDS, "Answer the mini challenge by pointing or choosing on the board."),
            ),
        ),
        LessonTemplate(
            "preset-young-beginner-7-8", "Young beginner lesson",
            AgeBand.YOUNG_BEGINNER_7_8, LessonLevel.BEGINNER,
            (
                _block("ready", LessonBlockKind.READINESS, "Readiness", 3, TeachingActivity.TEACHER_EXPLAINS, "Check readiness and today's goal."),
                _block("recap", LessonBlockKind.RECAP, "Quick recap", 5, TeachingActivity.STUDENT_RESPONDS, "Answer a short recap question on the board."),
                _block("concept", LessonBlockKind.CONCEPT, "Main concept", 10, TeachingActivity.TEACHER_EXPLAINS, "Learn one main chess concept."),
                _block("demo", LessonBlockKind.DEMONSTRATION, "Guided examples", 8, TeachingActivity.TEACHER_EXPLAINS, "Follow the guided examples on the board."),
                _block("response", LessonBlockKind.GUIDED_RESPONSE, "Your turn", 8, TeachingActivity.STUDENT_RESPONDS, "Point to or choose the best answer on the board."),
                _block("exercise", LessonBlockKind.EXERCISE, "Exercises", 8, TeachingActivity.STUDENT_RESPONDS, "Solve the exercise without needing to type notation."),
                _block("play", LessonBlockKind.SUPERVISED_GAME, "Supervised play", 6, TeachingActivity.STUDENT_RESPONDS, "Answer the supervised mini-game task on the board."),
                _block("review", LessonBlockKind.REVIEW, "Review", 2, TeachingActivity.TEACHER_EXPLAINS, "Review what was learned and the next task."),
            ),
        ),
        LessonTemplate(
            "preset-school-age-9-10", "School-age beginner lesson",
            AgeBand.SCHOOL_AGE_9_10, LessonLevel.DEVELOPING,
            (
                _block("ready", LessonBlockKind.READINESS, "Goal and readiness", 5, TeachingActivity.TEACHER_EXPLAINS, "Set the lesson goal and check readiness."),
                _block("recap", LessonBlockKind.RECAP, "Previous lesson recap", 5, TeachingActivity.STUDENT_RESPONDS, "Answer the previous-lesson recap on the board."),
                _block("concept", LessonBlockKind.CONCEPT, "Concept", 10, TeachingActivity.TEACHER_EXPLAINS, "Study the main concept."),
                _block("demo", LessonBlockKind.DEMONSTRATION, "Demonstration", 8, TeachingActivity.TEACHER_EXPLAINS, "Follow the demonstration sequence."),
                _block("guided", LessonBlockKind.GUIDED_RESPONSE, "Guided calculation", 10, TeachingActivity.STUDENT_RESPONDS, "Choose the best continuation or square."),
                _block("exercise", LessonBlockKind.EXERCISE, "Independent exercise", 10, TeachingActivity.STUDENT_RESPONDS, "Solve the position using the board controls."),
                _block("play", LessonBlockKind.SUPERVISED_GAME, "Applied play", 7, TeachingActivity.MAKE_MOVE, "Play the applied position using board move controls."),
                _block("review", LessonBlockKind.REVIEW, "Game review", 5, TeachingActivity.TEACHER_EXPLAINS, "Review decisions, progress and the next task."),
            ),
        ),
        LessonTemplate(
            "preset-strong-child", "Strong child calculation session",
            AgeBand.STRONG_CHILD, LessonLevel.ADVANCED,
            (
                _block("recap", LessonBlockKind.RECAP, "Warm calculation", 10, TeachingActivity.STUDENT_RESPONDS, "Solve a short warm-up position."),
                _block("concept", LessonBlockKind.CONCEPT, "Strategic theme", 15, TeachingActivity.TEACHER_EXPLAINS, "Study the session theme and candidate moves."),
                _block("demo", LessonBlockKind.DEMONSTRATION, "Deep example", 15, TeachingActivity.TEACHER_EXPLAINS, "Follow the deeper demonstration."),
                _block("exercise", LessonBlockKind.EXERCISE, "Calculation set", 20, TeachingActivity.STUDENT_RESPONDS, "Calculate and choose the best continuation."),
                _block("play", LessonBlockKind.SUPERVISED_GAME, "Applied play", 15, TeachingActivity.MAKE_MOVE, "Play the position using board move controls."),
                _block("review", LessonBlockKind.REVIEW, "Review and next work", 10, TeachingActivity.TEACHER_EXPLAINS, "Review calculation quality and set the next task."),
            ),
        ),
    )


def ensure_preset_templates(templates: tuple[LessonTemplate, ...]) -> tuple[LessonTemplate, ...]:
    if type(templates) is not tuple or any(type(item) is not LessonTemplate for item in templates):
        raise TypeError("templates must be a tuple of LessonTemplate")
    ids = [item.template_id for item in templates]
    if len(set(ids)) != len(ids):
        raise ChildCoachingError("template ids must be unique")
    existing = set(ids)
    return templates + tuple(preset for preset in preset_templates() if preset.template_id not in existing)


def _block(block_id, kind, title, minutes, activity, prompt) -> LessonBlock:
    return LessonBlock(
        block_id=block_id,
        kind=kind,
        title=title,
        minutes=minutes,
        activity=activity,
        prompt=prompt,
        notation_required=False,
        student_engine_visible=False,
    )


def _template_body(template: LessonTemplate) -> dict[str, object]:
    return {
        "version": template.version,
        "template_id": template.template_id,
        "title": template.title,
        "age_band": template.age_band.value,
        "level": template.level.value,
        "blocks": [block.to_record() for block in template.blocks],
        "custom": template.custom,
    }


def _digest(payload: Mapping[str, object]) -> str:
    data = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(data).hexdigest()


def _bounded_json(payload: Mapping[str, object]) -> str:
    try:
        text = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        size = len(text.encode("utf-8"))
    except (TypeError, ValueError, UnicodeEncodeError, RecursionError) as exc:
        raise ChildCoachingError("lesson template cannot be serialized") from exc
    if size > MAX_TEMPLATE_JSON_BYTES:
        raise ChildCoachingError("lesson template JSON exceeds size limit")
    return text


def _parse_json(text: object) -> Mapping[str, object]:
    if type(text) is not str:
        raise ChildCoachingError("lesson template JSON must be text")
    try:
        data = text.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise ChildCoachingError("lesson template JSON is not valid UTF-8 text") from exc
    if len(data) > MAX_TEMPLATE_JSON_BYTES:
        raise ChildCoachingError("lesson template JSON exceeds size limit")
    try:
        value = json.loads(
            text,
            object_pairs_hook=_reject_duplicate_pairs,
            parse_constant=_reject_constant,
            parse_int=_parse_wire_integer,
        )
    except ChildCoachingError:
        raise
    except (json.JSONDecodeError, UnicodeError, RecursionError, ValueError) as exc:
        raise ChildCoachingError("invalid lesson template JSON") from exc
    return _mapping(value, "lesson template")


def _reject_duplicate_pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ChildCoachingError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _reject_constant(value):
    raise ChildCoachingError(f"non-finite JSON constant is not allowed: {value}")


def _parse_wire_integer(value: str) -> int:
    digits = value[1:] if value.startswith("-") else value
    if not digits or len(digits) > 16:
        raise ChildCoachingError("JSON integer exceeds exact wire bounds")
    parsed = int(value, 10)
    if not -_MAX_WIRE_INTEGER <= parsed <= _MAX_WIRE_INTEGER:
        raise ChildCoachingError("JSON integer exceeds exact wire bounds")
    return parsed


def _mapping(value: object, label: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise ChildCoachingError(f"{label} must be an object")
    return value


def _exact_keys(data: Mapping[str, object], expected: set[str], label: str) -> None:
    if set(data) != expected:
        raise ChildCoachingError(f"{label} fields are not canonical")


def _identifier(value: object, label: str) -> str:
    if type(value) is not str or _ID_RE.fullmatch(value) is None:
        raise ChildCoachingError(f"{label} must be a bounded portable identifier")
    return value


def _text(value: object, label: str, limit: int) -> str:
    if type(value) is not str:
        raise ChildCoachingError(f"{label} must be text")
    normalized = value.strip()
    if not normalized or len(normalized) > limit or "\x00" in normalized:
        raise ChildCoachingError(f"{label} is empty or exceeds its limit")
    return normalized


def _optional_text(value: object, label: str, limit: int) -> str | None:
    if value is None:
        return None
    return _text(value, label, limit)


def _enum(value: object, cls, label: str):
    try:
        return value if isinstance(value, cls) else cls(value)
    except (TypeError, ValueError) as exc:
        raise ChildCoachingError(f"invalid {label}") from exc


def _digest_text(value: object, label: str) -> str:
    if type(value) is not str or _DIGEST_RE.fullmatch(value) is None:
        raise ChildCoachingError(f"{label} must be a lowercase SHA-256 digest")
    return value
