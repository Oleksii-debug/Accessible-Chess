from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from .interaction_contracts import (
    AnnotationCommand,
    BoardPermissionState,
    ContractValidationError,
    InteractionMessage,
    MoveCommand,
    PositionEditorCommand,
    StudentHoverEvent,
    StudentSelectionEvent,
    TeacherPointerCommand,
)


class InputSource(str, Enum):
    MOVE_INPUT = "move_input"
    TEACHER_POINTER_EDITOR = "teacher_pointer_editor"
    POSITION_EDITOR = "position_editor"
    ANNOTATION_EDITOR = "annotation_editor"
    STUDENT_SURFACE = "student_surface"


class InteractionEffect(str, Enum):
    NONE = "none"
    CHESS_MOVE = "chess_move"
    POSITION_EDIT = "position_edit"
    PRESENTATION = "presentation"
    OBSERVATION = "observation"


@dataclass(frozen=True)
class InteractionPolicy:
    board_permission: BoardPermissionState = BoardPermissionState.LOCKED

    def __post_init__(self) -> None:
        try:
            object.__setattr__(self, "board_permission", BoardPermissionState(self.board_permission))
        except (TypeError, ValueError) as exc:
            raise ContractValidationError(
                f"unsupported board permission: {self.board_permission!r}"
            ) from exc


@dataclass(frozen=True)
class RoutingDecision:
    accepted: bool
    effect: InteractionEffect
    reason: str

    def __post_init__(self) -> None:
        if type(self.accepted) is not bool:
            raise ContractValidationError("accepted must be boolean")
        try:
            object.__setattr__(self, "effect", InteractionEffect(self.effect))
        except (TypeError, ValueError) as exc:
            raise ContractValidationError(f"unsupported interaction effect: {self.effect!r}") from exc
        if not str(self.reason).strip():
            raise ContractValidationError("routing reason must not be empty")
        if not self.accepted and self.effect is not InteractionEffect.NONE:
            raise ContractValidationError("rejected interactions must have effect=none")

    @property
    def can_mutate_position(self) -> bool:
        return self.accepted and self.effect in {
            InteractionEffect.CHESS_MOVE,
            InteractionEffect.POSITION_EDIT,
        }

    @property
    def can_create_move(self) -> bool:
        return self.accepted and self.effect is InteractionEffect.CHESS_MOVE


def route_text_command(source: InputSource, text: str) -> MoveCommand | TeacherPointerCommand:
    """Route text only after the active input source is already known.

    A coordinate such as ``e4`` therefore cannot be guessed into the wrong
    family. Structured editor, annotation, and student input use their explicit
    DTO constructors instead of this text-only helper.
    """

    try:
        source = InputSource(source)
    except (TypeError, ValueError) as exc:
        raise ContractValidationError(f"unsupported input source: {source!r}") from exc
    if source is InputSource.MOVE_INPUT:
        return MoveCommand(text)
    if source is InputSource.TEACHER_POINTER_EDITOR:
        return TeacherPointerCommand(text)
    raise ContractValidationError(f"text-only routing is not valid for {source.value}")


def evaluate_interaction(
    message: InteractionMessage,
    source: InputSource,
    policy: InteractionPolicy | None = None,
) -> RoutingDecision:
    """Classify one explicit message without executing chess or UI behavior."""

    try:
        source = InputSource(source)
    except (TypeError, ValueError):
        return RoutingDecision(False, InteractionEffect.NONE, "unsupported input source")
    policy = policy or InteractionPolicy()
    if not isinstance(policy, InteractionPolicy):
        raise ContractValidationError("policy must be InteractionPolicy")

    if source is InputSource.MOVE_INPUT:
        if isinstance(message, MoveCommand):
            return RoutingDecision(True, InteractionEffect.CHESS_MOVE, "explicit move input")
        return _family_mismatch(source, message)

    if source is InputSource.TEACHER_POINTER_EDITOR:
        if isinstance(message, TeacherPointerCommand):
            return RoutingDecision(True, InteractionEffect.PRESENTATION, "explicit teacher pointer")
        return _family_mismatch(source, message)

    if source is InputSource.POSITION_EDITOR:
        if isinstance(message, PositionEditorCommand):
            return RoutingDecision(True, InteractionEffect.POSITION_EDIT, "explicit position edit")
        return _family_mismatch(source, message)

    if source is InputSource.ANNOTATION_EDITOR:
        if isinstance(message, AnnotationCommand):
            return RoutingDecision(True, InteractionEffect.PRESENTATION, "explicit annotation")
        return _family_mismatch(source, message)

    if isinstance(message, (StudentHoverEvent, StudentSelectionEvent)):
        return RoutingDecision(True, InteractionEffect.OBSERVATION, "student event remains non-mutating")
    if isinstance(message, MoveCommand):
        if policy.board_permission is BoardPermissionState.MOVE_ALLOWED:
            return RoutingDecision(True, InteractionEffect.CHESS_MOVE, "explicit student move permitted")
        return RoutingDecision(False, InteractionEffect.NONE, "student move is not permitted")
    return _family_mismatch(source, message)


def _family_mismatch(source: InputSource, message: object) -> RoutingDecision:
    family = getattr(message, "family", None)
    family_name = getattr(family, "value", type(message).__name__)
    return RoutingDecision(
        False,
        InteractionEffect.NONE,
        f"{family_name} is not valid for {source.value}",
    )
