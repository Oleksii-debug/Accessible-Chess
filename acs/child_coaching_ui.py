from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any, Iterable, Mapping, Sequence

from .keybindings import ActionRegistry, BindingContext
from .lesson_plan import (
    AssignmentTarget,
    LessonItem,
    LessonItemKind,
    LessonPlan,
    PairingMode,
    PairingService,
    PositionAssignment,
)
from .teaching_actions import build_teaching_action_registry
from .teaching_controls import normalize_square, spoken_square


@dataclass(frozen=True)
class LessonTemplateBlock:
    block_id: str
    kind: LessonItemKind
    title: str
    duration_minutes: int
    notation_required: bool = False

    def __post_init__(self) -> None:
        if not str(self.block_id).strip() or not str(self.title).strip():
            raise ValueError("template block requires id and title")
        if isinstance(self.duration_minutes, bool) or int(self.duration_minutes) <= 0:
            raise ValueError("template block duration must be positive")
        object.__setattr__(self, "duration_minutes", int(self.duration_minutes))


@dataclass(frozen=True)
class LessonTemplate:
    template_id: str
    title: str
    age_band: str
    blocks: tuple[LessonTemplateBlock, ...]

    @property
    def planned_minutes(self) -> int:
        return sum(block.duration_minutes for block in self.blocks)


@dataclass(frozen=True)
class NoNotationTask:
    task_id: str
    title: str
    response_mode: str
    mutates_board: bool


PRESCHOOL_TEMPLATE = LessonTemplate(
    "preschool",
    "Дошкільнята 4–6 років",
    "4-6",
    (
        LessonTemplateBlock("hello", LessonItemKind.WARM_UP, "Привітання і готовність", 3),
        LessonTemplateBlock("recognition", LessonItemKind.EXPLANATION, "Знайди фігуру або поле", 5),
        LessonTemplateBlock("movement", LessonItemKind.MINI_GAME, "Гра на рух фігури", 6),
        LessonTemplateBlock("response", LessonItemKind.EXERCISE, "Покажи відповідь на дошці", 5),
        LessonTemplateBlock("break", LessonItemKind.BREAK, "Коротка руханка", 4),
        LessonTemplateBlock("play", LessonItemKind.PAIR_PLAY, "Проста гра з тренером", 7),
        LessonTemplateBlock("recap", LessonItemKind.RECAP, "Що запам'ятали", 3),
    ),
)

YOUNG_BEGINNER_TEMPLATE = LessonTemplate(
    "young-beginner",
    "Молодший початківець 7–8 років",
    "7-8",
    (
        LessonTemplateBlock("warmup", LessonItemKind.WARM_UP, "Коротке повторення", 5),
        LessonTemplateBlock("concept", LessonItemKind.EXPLANATION, "Одна нова тема", 10),
        LessonTemplateBlock("demo", LessonItemKind.POSITION, "Показ на демонстраційній дошці", 8),
        LessonTemplateBlock("response", LessonItemKind.EXERCISE, "Відповіді учня", 8),
        LessonTemplateBlock("minigame", LessonItemKind.MINI_GAME, "Мінігра або вправа", 10),
        LessonTemplateBlock("play", LessonItemKind.PAIR_PLAY, "Гра під наглядом", 12),
        LessonTemplateBlock("recap", LessonItemKind.RECAP, "Підсумок і завдання", 5),
    ),
)

SCHOOL_AGE_TEMPLATE = LessonTemplate(
    "school-age",
    "Шкільний початківець 9–10 років",
    "9-10",
    (
        LessonTemplateBlock("recap", LessonItemKind.RECAP, "Повторення", 6),
        LessonTemplateBlock("concept", LessonItemKind.EXPLANATION, "Нова тема", 10),
        LessonTemplateBlock("calculation", LessonItemKind.EXERCISE, "Розрахунок або тактика", 12),
        LessonTemplateBlock("position", LessonItemKind.POSITION, "Робота з позицією", 10),
        LessonTemplateBlock("play", LessonItemKind.PAIR_PLAY, "Практична партія", 15),
        LessonTemplateBlock("review", LessonItemKind.REVIEW, "Розбір гри", 8),
        LessonTemplateBlock("homework", LessonItemKind.RECAP, "Підсумок і наступне завдання", 4),
    ),
)

DEFAULT_LESSON_TEMPLATES: tuple[LessonTemplate, ...] = (
    PRESCHOOL_TEMPLATE,
    YOUNG_BEGINNER_TEMPLATE,
    SCHOOL_AGE_TEMPLATE,
)

NO_NOTATION_TASKS: tuple[NoNotationTask, ...] = (
    NoNotationTask("find-square", "Знайди поле", "pointer", False),
    NoNotationTask("find-piece", "Знайди фігуру", "pointer", False),
    NoNotationTask("show-moves", "Покажи, куди може піти фігура", "pointer", False),
    NoNotationTask("capture-target", "Знайди фігуру, яку можна взяти", "pointer", False),
    NoNotationTask("check-king", "Покажи, як оголосити шах", "pointer", False),
    NoNotationTask("mate-one", "Знайди мат в один хід", "choice_or_move", True),
)


class ChildCoachingPresentationState:
    """Accessible lesson/classroom presentation without a second chess authority.

    Prepared positions keep exact FEN supplied by the existing lesson contracts.
    This state selects and describes positions; a real board deployment is left to
    the application/session boundary. Pointer-only beginner answers never mutate
    chess state because no Board object exists in this presentation layer.
    """

    def __init__(
        self,
        *,
        action_registry: ActionRegistry | None = None,
        lesson: LessonPlan | None = None,
        participant_ids: Iterable[str] = (),
    ) -> None:
        self.actions = action_registry or build_teaching_action_registry()
        self._templates = {item.template_id: item for item in DEFAULT_LESSON_TEMPLATES}
        self._template = self._templates[PRESCHOOL_TEMPLATE.template_id]
        self._lesson = lesson
        self._position_index = 0
        self._participants = tuple(_unique_nonempty(participant_ids))
        self._pairing_service = PairingService()
        self._rotation_order = self._participants
        self._rotation_round = 0
        self._pairing_plan = None
        self._board_index = 0
        self._demonstration_mode = True
        self._assignment_sequence = 0

    def snapshot(self) -> dict[str, Any]:
        return {
            "templates": [self._template_view(item) for item in self._templates.values()],
            "template": self._template_view(self._template),
            "noNotationTasks": [self._task_view(item) for item in NO_NOTATION_TASKS],
            "prepared": self._prepared_view(),
            "rotation": self._rotation_view(),
            "actions": [
                {
                    "actionId": item.action_id,
                    "title": item.title,
                    "binding": self.actions.get_binding(item.action_id),
                }
                for item in self.actions.definitions()
                if item.action_id.startswith("teaching.")
            ],
        }

    def select_template(self, template_id: str) -> dict[str, Any]:
        try:
            self._template = self._templates[str(template_id).strip()]
        except KeyError as exc:
            raise ValueError("unknown lesson template") from exc
        return self._template_view(self._template)

    def edit_template_block(
        self,
        block_id: str,
        *,
        title: str | None = None,
        duration_minutes: int | None = None,
    ) -> dict[str, Any]:
        found = False
        blocks: list[LessonTemplateBlock] = []
        for block in self._template.blocks:
            if block.block_id != str(block_id).strip():
                blocks.append(block)
                continue
            found = True
            next_title = block.title if title is None else str(title).strip()
            if not next_title:
                raise ValueError("block title must not be empty")
            next_duration = block.duration_minutes if duration_minutes is None else int(duration_minutes)
            blocks.append(replace(block, title=next_title, duration_minutes=next_duration))
        if not found:
            raise ValueError("unknown template block")
        self._template = replace(self._template, blocks=tuple(blocks))
        return self._template_view(self._template)

    def set_lesson(self, lesson: LessonPlan | None) -> dict[str, Any]:
        self._lesson = lesson
        self._position_index = 0
        return self._prepared_view()

    def previous_position(self) -> dict[str, Any]:
        positions = self._positions()
        if positions:
            self._position_index = max(0, self._position_index - 1)
        return self._prepared_view()

    def next_position(self) -> dict[str, Any]:
        positions = self._positions()
        if positions:
            self._position_index = min(len(positions) - 1, self._position_index + 1)
        return self._prepared_view()

    def deploy_selected(
        self,
        target: str = AssignmentTarget.ALL.value,
        *,
        participant_ids: Sequence[str] = (),
        group_id: str | None = None,
    ) -> dict[str, Any]:
        positions = self._positions()
        if not positions:
            return {"ok": False, "accessibleText": "Немає підготовленої позиції для показу."}
        position = positions[self._position_index]
        target_kind = AssignmentTarget(str(target))
        self._assignment_sequence += 1
        assignment = PositionAssignment(
            assignment_id=f"ui-assignment-{self._assignment_sequence}",
            position_id=position.position_id,
            target=target_kind,
            participant_ids=tuple(participant_ids),
            group_id=group_id,
        )
        target_text = "усім учням"
        if target_kind is AssignmentTarget.GROUP:
            target_text = f"групі {assignment.group_id}"
        elif target_kind is AssignmentTarget.PARTICIPANTS:
            target_text = f"вибраним учням: {', '.join(assignment.participant_ids)}"
        return {
            "ok": True,
            "positionId": position.position_id,
            "title": position.title,
            "fen": position.fen,
            "assignmentId": assignment.assignment_id,
            "target": assignment.target.value,
            "participantIds": list(assignment.participant_ids),
            "groupId": assignment.group_id,
            "mutatesGameHere": False,
            "accessibleText": f"Позицію «{position.title}» підготовлено для показу {target_text}.",
        }

    def pointer_only_answer(self, display_name: str, square: str) -> dict[str, Any]:
        square = normalize_square(square)
        name = str(display_name).strip() or "Учень"
        return {
            "ok": True,
            "square": square,
            "boardMutation": False,
            "notationRequired": False,
            "accessibleText": f"{name}: {spoken_square(square)}.",
        }

    def start_rotation(
        self,
        participant_ids: Sequence[str],
        *,
        mode: str = PairingMode.SEQUENTIAL.value,
        base_seconds: int = 600,
        increment_seconds: int = 0,
        random_seed: int | None = None,
    ) -> dict[str, Any]:
        self._rotation_order = tuple(_unique_nonempty(participant_ids))
        self._rotation_round = 1
        self._board_index = 0
        self._demonstration_mode = False
        self._pairing_plan = self._pairing_service.create(
            self._rotation_order,
            mode=PairingMode(mode),
            base_seconds=int(base_seconds),
            increment_seconds=int(increment_seconds),
            random_seed=random_seed,
        )
        return self._rotation_view()

    def next_rotation_round(self) -> dict[str, Any]:
        if len(self._rotation_order) < 2:
            return self._rotation_view()
        first, rest = self._rotation_order[0], self._rotation_order[1:]
        self._rotation_order = (*rest, first)
        self._rotation_round = max(1, self._rotation_round + 1)
        self._board_index = 0
        self._demonstration_mode = False
        self._pairing_plan = self._pairing_service.create(self._rotation_order)
        return self._rotation_view()

    def previous_board(self) -> dict[str, Any]:
        pairings = self._pairings()
        if pairings:
            self._board_index = max(0, self._board_index - 1)
            self._demonstration_mode = False
        return self._rotation_view()

    def next_board(self) -> dict[str, Any]:
        pairings = self._pairings()
        if pairings:
            self._board_index = min(len(pairings) - 1, self._board_index + 1)
            self._demonstration_mode = False
        return self._rotation_view()

    def return_to_demonstration(self) -> dict[str, Any]:
        self._demonstration_mode = True
        return self._rotation_view()

    def dispatch(self, action_id: str, payload: Mapping[str, object] | None = None) -> dict[str, Any]:
        action_id = str(action_id).strip()
        definition = self.actions.definition(action_id)
        if not action_id.startswith("teaching.") or definition.context is not BindingContext.DOCUMENT:
            raise ValueError("action is not owned by the teaching presentation")
        data = dict(payload or {})
        handlers = {
            "teaching.lesson.previous_position": lambda: self.previous_position(),
            "teaching.lesson.next_position": lambda: self.next_position(),
            "teaching.lesson.deploy_position": lambda: self.deploy_selected(
                str(data.get("target", AssignmentTarget.ALL.value)),
                participant_ids=tuple(data.get("participant_ids", ()) or ()),
                group_id=data.get("group_id") if data.get("group_id") is None else str(data.get("group_id")),
            ),
            "teaching.rotation.previous_board": lambda: self.previous_board(),
            "teaching.rotation.next_board": lambda: self.next_board(),
            "teaching.rotation.next_round": lambda: self.next_rotation_round(),
            "teaching.rotation.return_demo": lambda: self.return_to_demonstration(),
        }
        handler = handlers.get(action_id)
        if handler is None:
            return {"ok": False, "missingContract": action_id, "accessibleText": "Ця дія ще потребує окремого вводу."}
        return handler()

    def dispatch_binding(self, binding: str, payload: Mapping[str, object] | None = None) -> dict[str, Any]:
        resolution = self.actions.resolve_binding(BindingContext.DOCUMENT, binding)
        if resolution is None or not resolution.action_id.startswith("teaching."):
            return {"ok": False, "accessibleText": "Для цієї клавіші немає дії уроку."}
        return self.dispatch(resolution.action_id, payload)

    def _positions(self):
        return () if self._lesson is None else self._lesson.positions

    def _pairings(self):
        return () if self._pairing_plan is None else self._pairing_plan.pairings

    def _prepared_view(self) -> dict[str, Any]:
        positions = self._positions()
        if not positions:
            return {
                "available": False,
                "index": 0,
                "count": 0,
                "position": None,
                "accessibleText": "Підготовлені позиції не завантажено.",
            }
        position = positions[self._position_index]
        return {
            "available": True,
            "index": self._position_index,
            "count": len(positions),
            "position": {
                "positionId": position.position_id,
                "title": position.title,
                "fen": position.fen,
                "prompt": position.prompt,
                "teacherNotes": position.teacher_notes,
                "tags": list(position.tags),
            },
            "accessibleText": f"Позиція {self._position_index + 1} з {len(positions)}: {position.title}.",
        }

    def _rotation_view(self) -> dict[str, Any]:
        pairings = self._pairings()
        current = pairings[self._board_index] if pairings else None
        return {
            "round": self._rotation_round,
            "demonstrationMode": self._demonstration_mode,
            "currentBoardIndex": self._board_index,
            "pairings": [
                {
                    "pairingId": pair.pairing_id,
                    "white": pair.white_participant_id,
                    "black": pair.black_participant_id,
                    "baseSeconds": pair.base_seconds,
                    "incrementSeconds": pair.increment_seconds,
                }
                for pair in pairings
            ],
            "unpaired": [] if self._pairing_plan is None else list(self._pairing_plan.unpaired_participant_ids),
            "accessibleText": (
                "Демонстраційний режим."
                if self._demonstration_mode
                else (
                    f"Раунд {self._rotation_round}. Дошка {self._board_index + 1} з {len(pairings)}: "
                    f"{current.white_participant_id} — білі, {current.black_participant_id} — чорні."
                    if current is not None
                    else "Немає активних пар."
                )
            ),
        }

    @staticmethod
    def _template_view(template: LessonTemplate) -> dict[str, Any]:
        return {
            "templateId": template.template_id,
            "title": template.title,
            "ageBand": template.age_band,
            "plannedMinutes": template.planned_minutes,
            "blocks": [
                {
                    "blockId": block.block_id,
                    "kind": block.kind.value,
                    "title": block.title,
                    "durationMinutes": block.duration_minutes,
                    "notationRequired": block.notation_required,
                }
                for block in template.blocks
            ],
        }

    @staticmethod
    def _task_view(task: NoNotationTask) -> dict[str, Any]:
        return {
            "taskId": task.task_id,
            "title": task.title,
            "responseMode": task.response_mode,
            "mutatesBoard": task.mutates_board,
            "notationRequired": False,
        }


def _unique_nonempty(values: Iterable[str]) -> list[str]:
    result: list[str] = []
    for value in values:
        item = str(value).strip()
        if not item:
            raise ValueError("participant id must not be empty")
        if item in result:
            raise ValueError("participant ids must be unique")
        result.append(item)
    return result
