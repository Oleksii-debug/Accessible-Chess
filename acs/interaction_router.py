from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Mapping

from .interaction_contracts import (
    CONTRACT_VERSION,
    AnnotationCommand,
    BoardPermissionState,
    ContractValidationError,
    InteractionMessage,
    MoveCommand,
    PositionEditorCommand,
    StudentHoverEvent,
    StudentSelectionEvent,
    TeacherPointerCommand,
    interaction_from_payload,
    interaction_to_payload,
    validate_position_editor_authority,
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


def _validate_routing_version(version: object) -> int:
    if type(version) is not int or version != CONTRACT_VERSION:
        raise ContractValidationError(
            f"unsupported routing contract version: {version!r}"
        )
    return version


def _exact_payload(payload: Mapping[str, object], keys: set[str]) -> None:
    actual = set(payload)
    if actual != keys:
        missing = sorted(keys - actual)
        unknown = sorted(actual - keys)
        raise ContractValidationError(
            f"routing payload keys mismatch; missing={missing}, unknown={unknown}"
        )


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
class InteractionRequest:
    """One versioned request for the canonical interaction router."""

    source: InputSource
    message: InteractionMessage
    policy: InteractionPolicy = InteractionPolicy()
    version: int = CONTRACT_VERSION

    def __post_init__(self) -> None:
        _validate_routing_version(self.version)
        try:
            object.__setattr__(self, "source", InputSource(self.source))
        except (TypeError, ValueError) as exc:
            raise ContractValidationError(
                f"unsupported input source: {self.source!r}"
            ) from exc
        if not isinstance(
            self.message,
            (
                MoveCommand,
                TeacherPointerCommand,
                PositionEditorCommand,
                AnnotationCommand,
                StudentHoverEvent,
                StudentSelectionEvent,
            ),
        ):
            raise ContractValidationError("request message is not an interaction contract")
        if not isinstance(self.policy, InteractionPolicy):
            raise ContractValidationError("request policy must be InteractionPolicy")


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
        if not isinstance(self.reason, str):
            raise ContractValidationError("routing reason must be a string")
        if not self.reason.strip():
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
    if policy is None:
        policy = InteractionPolicy()
    elif not isinstance(policy, InteractionPolicy):
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
            try:
                validate_position_editor_authority(message)
            except ContractValidationError as exc:
                return RoutingDecision(
                    False,
                    InteractionEffect.NONE,
                    f"position editor rejected: {exc.code.value}",
                )
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


def evaluate_request(request: InteractionRequest) -> RoutingDecision:
    if not isinstance(request, InteractionRequest):
        raise ContractValidationError("request must be InteractionRequest")
    return evaluate_interaction(request.message, request.source, request.policy)


def routing_request_to_payload(request: InteractionRequest) -> dict[str, object]:
    if not isinstance(request, InteractionRequest):
        raise ContractValidationError("request must be InteractionRequest")
    return {
        "version": request.version,
        "kind": "request",
        "source": request.source.value,
        "policy": {"board_permission": request.policy.board_permission.value},
        "message": interaction_to_payload(request.message),
    }


def routing_request_from_payload(payload: Mapping[str, object]) -> InteractionRequest:
    if not isinstance(payload, Mapping):
        raise ContractValidationError("routing request payload must be an object")
    _exact_payload(payload, {"version", "kind", "source", "policy", "message"})
    version = _validate_routing_version(payload["version"])
    if payload["kind"] != "request":
        raise ContractValidationError("routing request kind must be 'request'")
    policy_payload = payload["policy"]
    if not isinstance(policy_payload, Mapping):
        raise ContractValidationError("routing policy must be an object")
    _exact_payload(policy_payload, {"board_permission"})
    try:
        source = InputSource(payload["source"])
    except (TypeError, ValueError) as exc:
        raise ContractValidationError(
            f"unsupported input source: {payload['source']!r}"
        ) from exc
    return InteractionRequest(
        source=source,
        message=interaction_from_payload(payload["message"]),
        policy=InteractionPolicy(policy_payload["board_permission"]),
        version=version,
    )


def routing_decision_to_payload(decision: RoutingDecision) -> dict[str, object]:
    if not isinstance(decision, RoutingDecision):
        raise ContractValidationError("decision must be RoutingDecision")
    return {
        "version": CONTRACT_VERSION,
        "kind": "decision",
        "accepted": decision.accepted,
        "effect": decision.effect.value,
        "reason": decision.reason,
    }


def routing_decision_from_payload(payload: Mapping[str, object]) -> RoutingDecision:
    if not isinstance(payload, Mapping):
        raise ContractValidationError("routing decision payload must be an object")
    _exact_payload(payload, {"version", "kind", "accepted", "effect", "reason"})
    _validate_routing_version(payload["version"])
    if payload["kind"] != "decision":
        raise ContractValidationError("routing decision kind must be 'decision'")
    return RoutingDecision(
        accepted=payload["accepted"],
        effect=payload["effect"],
        reason=payload["reason"],
    )


def _family_mismatch(source: InputSource, message: object) -> RoutingDecision:
    family = getattr(message, "family", None)
    family_name = getattr(family, "value", type(message).__name__)
    return RoutingDecision(
        False,
        InteractionEffect.NONE,
        f"{family_name} is not valid for {source.value}",
    )
