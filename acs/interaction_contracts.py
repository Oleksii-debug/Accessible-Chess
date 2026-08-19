from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import ClassVar, Mapping, NoReturn, TypeAlias

from .squares import normalize_square


CONTRACT_VERSION = 1


class ContractErrorCode(str, Enum):
    INVALID_FIELD = "invalid_field"
    UNSUPPORTED_POSITION_EDITOR_OPERATION = "unsupported_position_editor_operation"
    INVALID_POSITION_EDITOR_FIELDS = "invalid_position_editor_fields"


class ContractValidationError(ValueError):
    """Raised when an interaction payload is ambiguous or unsupported."""

    def __init__(
        self,
        message: str,
        *,
        code: ContractErrorCode = ContractErrorCode.INVALID_FIELD,
    ) -> None:
        super().__init__(message)
        self.code = ContractErrorCode(code)


class CommandFamily(str, Enum):
    MOVE = "move"
    TEACHER_POINTER = "teacher_pointer"
    POSITION_EDITOR = "position_editor"
    ANNOTATION = "annotation"
    STUDENT_HOVER = "student_hover"
    STUDENT_SELECTION = "student_selection"


class AnnotationOperation(str, Enum):
    SET_HIGHLIGHT = "set_highlight"
    ADD_ARROW = "add_arrow"
    CLEAR = "clear"


class PositionEditorOperation(str, Enum):
    """Bounded v1 mutations understood by every position-editor adapter."""

    CLEAR = "clear"
    PLACE_PIECE = "place_piece"
    REMOVE_PIECE = "remove_piece"
    SET_TURN = "set_turn"
    SET_CASTLING = "set_castling"
    SET_EN_PASSANT = "set_en_passant"
    SET_HALFMOVE_CLOCK = "set_halfmove_clock"
    SET_FULLMOVE_NUMBER = "set_fullmove_number"
    LOAD_FEN = "load_fen"


class EngineVisibilityPolicy(str, Enum):
    VISIBLE_TO_TEACHER = "visible_to_teacher"
    VISIBLE_TO_STUDENT = "visible_to_student"
    HIDDEN = "hidden"


class BoardPermissionState(str, Enum):
    LOCKED = "locked"
    SELECT_ONLY = "select_only"
    MOVE_ALLOWED = "move_allowed"


def _validate_version(version: int) -> None:
    if type(version) is not int or version != CONTRACT_VERSION:
        raise ContractValidationError(
            f"unsupported interaction contract version: {version!r}"
        )


def _required_text(value: object, label: str) -> str:
    if not isinstance(value, str):
        raise ContractValidationError(f"{label} must be a string")
    if not value.strip():
        raise ContractValidationError(f"{label} must not be empty")
    return value


def _optional_text(value: object | None, label: str) -> str | None:
    if value is None:
        return None
    return _required_text(value, label)


def _optional_square(value: str | int | None) -> str | None:
    if value is None:
        return None
    try:
        return normalize_square(value)
    except ValueError as exc:
        raise ContractValidationError(str(exc)) from exc


def _required_square(value: str | int | None, label: str = "square") -> str:
    square = _optional_square(value)
    if square is None:
        raise ContractValidationError(f"{label} must not be empty")
    return square


def _payload_square(
    value: object,
    label: str = "square",
    *,
    optional: bool = False,
) -> str | None:
    """Require the JSON v1 square representation without constructor coercion.

    Domain constructors accept integer square indexes for in-process callers,
    but the published adapter schema uses canonical algebraic strings only.
    Deserializers therefore reject integers instead of silently widening the
    language-neutral wire contract.
    """

    if value is None and optional:
        return None
    if not isinstance(value, str):
        suffix = " or null" if optional else ""
        raise ContractValidationError(f"{label} must be a square string{suffix}")
    square = _required_square(value, label)
    if value != square:
        raise ContractValidationError(
            f"{label} must use canonical lowercase algebraic form"
        )
    return square


def _sequence(value: int | None) -> int | None:
    if value is None:
        return None
    if type(value) is not int or value < 0:
        raise ContractValidationError("sequence must be a non-negative integer")
    return value


_POSITION_EDITOR_PIECES = frozenset("PNBRQKpnbrqk")
_CANONICAL_CASTLING_VALUES = frozenset(
    {
        "-",
        "K",
        "Q",
        "KQ",
        "k",
        "Kk",
        "Qk",
        "KQk",
        "q",
        "Kq",
        "Qq",
        "KQq",
        "kq",
        "Kkq",
        "Qkq",
        "KQkq",
    }
)


def _position_editor_fields(
    operation: object,
    square: object,
    piece: object,
    value: object,
) -> tuple[PositionEditorOperation, str | None, str | None, str | None]:
    """Validate the complete discriminated v1 position-editor command."""

    try:
        bounded_operation = PositionEditorOperation(operation)
    except (TypeError, ValueError) as exc:
        raise ContractValidationError(
            f"unsupported position editor operation: {operation!r}",
            code=ContractErrorCode.UNSUPPORTED_POSITION_EDITOR_OPERATION,
        ) from exc

    def reject(message: str) -> NoReturn:
        raise ContractValidationError(
            message,
            code=ContractErrorCode.INVALID_POSITION_EDITOR_FIELDS,
        )

    if bounded_operation is PositionEditorOperation.CLEAR:
        if square is not None or piece is not None or value is not None:
            reject("clear must not include square, piece, or value")
        return bounded_operation, None, None, None

    if bounded_operation is PositionEditorOperation.PLACE_PIECE:
        try:
            normalized_square = _required_square(square)
        except ContractValidationError as exc:
            reject(str(exc))
        if not isinstance(piece, str) or piece not in _POSITION_EDITOR_PIECES:
            reject("place_piece requires one canonical chess piece symbol")
        if value is not None:
            reject("place_piece must not include value")
        return bounded_operation, normalized_square, piece, None

    if bounded_operation is PositionEditorOperation.REMOVE_PIECE:
        try:
            normalized_square = _required_square(square)
        except ContractValidationError as exc:
            reject(str(exc))
        if piece is not None or value is not None:
            reject("remove_piece requires a square only")
        return bounded_operation, normalized_square, None, None

    if square is not None or piece is not None:
        reject(f"{bounded_operation.value} must not include square or piece")

    if bounded_operation is PositionEditorOperation.SET_TURN:
        if not isinstance(value, str) or value not in {"w", "b"}:
            reject("set_turn value must be 'w' or 'b'")
        return bounded_operation, None, None, value

    if bounded_operation is PositionEditorOperation.SET_CASTLING:
        if not isinstance(value, str) or value not in _CANONICAL_CASTLING_VALUES:
            reject("set_castling value must be canonical KQkq rights or '-'")
        return bounded_operation, None, None, value

    if bounded_operation is PositionEditorOperation.SET_EN_PASSANT:
        if value == "-":
            return bounded_operation, None, None, value
        if not isinstance(value, str):
            reject("set_en_passant value must be '-' or a canonical rank-3/rank-6 square")
        try:
            normalized_value = _required_square(value, "en-passant square")
        except ContractValidationError as exc:
            reject(str(exc))
        if value != normalized_value or normalized_value[1] not in {"3", "6"}:
            reject("set_en_passant value must be '-' or a canonical rank-3/rank-6 square")
        return bounded_operation, None, None, normalized_value

    if bounded_operation is PositionEditorOperation.SET_HALFMOVE_CLOCK:
        if (
            not isinstance(value, str)
            or not value.isascii()
            or not value.isdigit()
            or (len(value) > 1 and value.startswith("0"))
        ):
            reject("set_halfmove_clock value must be canonical non-negative decimal text")
        return bounded_operation, None, None, value

    if bounded_operation is PositionEditorOperation.SET_FULLMOVE_NUMBER:
        if (
            not isinstance(value, str)
            or not value.isascii()
            or not value.isdigit()
            or value.startswith("0")
        ):
            reject("set_fullmove_number value must be canonical positive decimal text")
        return bounded_operation, None, None, value

    if not isinstance(value, str) or not value.strip():
        reject("load_fen value must be a non-empty FEN string")
    return bounded_operation, None, None, value


@dataclass(frozen=True)
class MoveCommand:
    """Text explicitly routed from Move Input, not inferred from another mode."""

    raw_text: str
    version: int = CONTRACT_VERSION
    family: ClassVar[CommandFamily] = CommandFamily.MOVE

    def __post_init__(self) -> None:
        _validate_version(self.version)
        object.__setattr__(self, "raw_text", _required_text(self.raw_text, "move text"))


@dataclass(frozen=True)
class TeacherPointerCommand:
    """Presentation-only pointer target; consumers must not mutate Position."""

    square: str
    version: int = CONTRACT_VERSION
    family: ClassVar[CommandFamily] = CommandFamily.TEACHER_POINTER

    def __post_init__(self) -> None:
        _validate_version(self.version)
        object.__setattr__(self, "square", _required_square(self.square))


@dataclass(frozen=True)
class PositionEditorCommand:
    """Explicit position-editor operation, separate from chess moves."""

    operation: PositionEditorOperation
    square: str | None = None
    piece: str | None = None
    value: str | None = None
    version: int = CONTRACT_VERSION
    family: ClassVar[CommandFamily] = CommandFamily.POSITION_EDITOR

    def __post_init__(self) -> None:
        _validate_version(self.version)
        operation, square, piece, value = _position_editor_fields(
            self.operation,
            self.square,
            self.piece,
            self.value,
        )
        object.__setattr__(self, "operation", operation)
        object.__setattr__(self, "square", square)
        object.__setattr__(self, "piece", piece)
        object.__setattr__(self, "value", value)


def validate_position_editor_authority(command: PositionEditorCommand) -> None:
    """Revalidate semantic authority at the router boundary.

    Normal construction already validates commands. Revalidation prevents a
    stale, forged, or non-canonical in-process object from gaining mutation
    authority merely because it has the right Python class.
    """

    if not isinstance(command, PositionEditorCommand):
        raise ContractValidationError(
            "position editor authority requires PositionEditorCommand",
            code=ContractErrorCode.INVALID_POSITION_EDITOR_FIELDS,
        )
    _position_editor_fields(
        command.operation,
        command.square,
        command.piece,
        command.value,
    )


@dataclass(frozen=True)
class AnnotationCommand:
    """Presentation annotation command with no chess-position payload."""

    operation: AnnotationOperation
    start_square: str | None = None
    end_square: str | None = None
    tag: str | None = None
    version: int = CONTRACT_VERSION
    family: ClassVar[CommandFamily] = CommandFamily.ANNOTATION

    def __post_init__(self) -> None:
        _validate_version(self.version)
        try:
            operation = AnnotationOperation(self.operation)
        except (TypeError, ValueError) as exc:
            raise ContractValidationError(f"unsupported annotation operation: {self.operation!r}") from exc
        start = _optional_square(self.start_square)
        end = _optional_square(self.end_square)
        tag = _optional_text(self.tag, "annotation tag")
        if operation is AnnotationOperation.SET_HIGHLIGHT and (start is None or end is not None):
            raise ContractValidationError("set_highlight requires one start square and no end square")
        if operation is AnnotationOperation.ADD_ARROW:
            if start is None or end is None:
                raise ContractValidationError("add_arrow requires start and end squares")
            if start == end:
                raise ContractValidationError("arrow start and end squares must differ")
        if operation is AnnotationOperation.CLEAR and (start is not None or end is not None):
            raise ContractValidationError("clear must not include squares")
        object.__setattr__(self, "operation", operation)
        object.__setattr__(self, "start_square", start)
        object.__setattr__(self, "end_square", end)
        object.__setattr__(self, "tag", tag)


@dataclass(frozen=True)
class StudentHoverEvent:
    """Non-mutating reverse-channel observation from a student surface."""

    square: str
    piece: str | None = None
    student_id: str | None = None
    sequence: int | None = None
    version: int = CONTRACT_VERSION
    family: ClassVar[CommandFamily] = CommandFamily.STUDENT_HOVER

    def __post_init__(self) -> None:
        _validate_version(self.version)
        object.__setattr__(self, "square", _required_square(self.square))
        object.__setattr__(self, "piece", _optional_text(self.piece, "piece"))
        object.__setattr__(self, "student_id", _optional_text(self.student_id, "student id"))
        object.__setattr__(self, "sequence", _sequence(self.sequence))


@dataclass(frozen=True)
class StudentSelectionEvent:
    """Student selection/answer event; it is not a MoveCommand."""

    square: str
    piece: str | None = None
    student_id: str | None = None
    sequence: int | None = None
    version: int = CONTRACT_VERSION
    family: ClassVar[CommandFamily] = CommandFamily.STUDENT_SELECTION

    def __post_init__(self) -> None:
        _validate_version(self.version)
        object.__setattr__(self, "square", _required_square(self.square))
        object.__setattr__(self, "piece", _optional_text(self.piece, "piece"))
        object.__setattr__(self, "student_id", _optional_text(self.student_id, "student id"))
        object.__setattr__(self, "sequence", _sequence(self.sequence))


InteractionMessage: TypeAlias = (
    MoveCommand
    | TeacherPointerCommand
    | PositionEditorCommand
    | AnnotationCommand
    | StudentHoverEvent
    | StudentSelectionEvent
)
StudentPointerEvent: TypeAlias = StudentHoverEvent | StudentSelectionEvent


@dataclass(frozen=True)
class SquareHighlight:
    square: str
    purpose: str = "custom"

    def __post_init__(self) -> None:
        object.__setattr__(self, "square", _required_square(self.square))
        object.__setattr__(self, "purpose", _required_text(self.purpose, "highlight purpose"))


@dataclass(frozen=True)
class VisualArrow:
    start_square: str
    end_square: str
    purpose: str = "custom"

    def __post_init__(self) -> None:
        start = _required_square(self.start_square, "arrow start square")
        end = _required_square(self.end_square, "arrow end square")
        if start == end:
            raise ContractValidationError("arrow start and end squares must differ")
        object.__setattr__(self, "start_square", start)
        object.__setattr__(self, "end_square", end)
        object.__setattr__(self, "purpose", _required_text(self.purpose, "arrow purpose"))


@dataclass(frozen=True)
class TeacherPointerState:
    square: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "square", _optional_square(self.square))


@dataclass(frozen=True)
class PresentationState:
    """Presentation/session state that deliberately excludes chess Position."""

    pointer: TeacherPointerState = TeacherPointerState()
    highlights: tuple[SquareHighlight, ...] = ()
    arrows: tuple[VisualArrow, ...] = ()
    coordinate_labels_visible: bool = True
    student_pointer_history: tuple[StudentPointerEvent, ...] = ()
    active_student_id: str | None = None
    engine_visibility: EngineVisibilityPolicy = EngineVisibilityPolicy.HIDDEN
    board_permission: BoardPermissionState = BoardPermissionState.LOCKED
    version: int = CONTRACT_VERSION

    def __post_init__(self) -> None:
        _validate_version(self.version)
        if not isinstance(self.pointer, TeacherPointerState):
            raise ContractValidationError("pointer must be TeacherPointerState")
        try:
            highlights = tuple(self.highlights)
            arrows = tuple(self.arrows)
            history = tuple(self.student_pointer_history)
        except TypeError as exc:
            raise ContractValidationError("presentation collections must be iterable") from exc
        if any(not isinstance(item, SquareHighlight) for item in highlights):
            raise ContractValidationError("highlights must contain SquareHighlight values")
        if any(not isinstance(item, VisualArrow) for item in arrows):
            raise ContractValidationError("arrows must contain VisualArrow values")
        if type(self.coordinate_labels_visible) is not bool:
            raise ContractValidationError("coordinate_labels_visible must be boolean")
        if any(not isinstance(item, (StudentHoverEvent, StudentSelectionEvent)) for item in history):
            raise ContractValidationError("student_pointer_history contains an unsupported event")
        object.__setattr__(self, "highlights", highlights)
        object.__setattr__(self, "arrows", arrows)
        object.__setattr__(self, "student_pointer_history", history)
        object.__setattr__(self, "active_student_id", _optional_text(self.active_student_id, "active student id"))
        try:
            object.__setattr__(self, "engine_visibility", EngineVisibilityPolicy(self.engine_visibility))
            object.__setattr__(self, "board_permission", BoardPermissionState(self.board_permission))
        except (TypeError, ValueError) as exc:
            raise ContractValidationError("unsupported presentation policy") from exc


def interaction_to_payload(message: InteractionMessage) -> dict[str, object]:
    """Serialize one discriminated, versioned interaction message."""

    if isinstance(message, MoveCommand):
        return {"version": message.version, "family": message.family.value, "raw_text": message.raw_text}
    if isinstance(message, TeacherPointerCommand):
        return {"version": message.version, "family": message.family.value, "square": message.square}
    if isinstance(message, PositionEditorCommand):
        return {
            "version": message.version,
            "family": message.family.value,
            "operation": message.operation.value,
            "square": message.square,
            "piece": message.piece,
            "value": message.value,
        }
    if isinstance(message, AnnotationCommand):
        return {
            "version": message.version,
            "family": message.family.value,
            "operation": message.operation.value,
            "start_square": message.start_square,
            "end_square": message.end_square,
            "tag": message.tag,
        }
    if isinstance(message, (StudentHoverEvent, StudentSelectionEvent)):
        return {
            "version": message.version,
            "family": message.family.value,
            "square": message.square,
            "piece": message.piece,
            "student_id": message.student_id,
            "sequence": message.sequence,
        }
    raise ContractValidationError(f"unsupported interaction message: {type(message).__name__}")


def _exact_payload(payload: Mapping[str, object], keys: set[str]) -> None:
    actual = set(payload)
    if actual != keys:
        missing = sorted(keys - actual)
        unknown = sorted(actual - keys)
        raise ContractValidationError(f"payload keys mismatch; missing={missing}, unknown={unknown}")


def interaction_from_payload(payload: Mapping[str, object]) -> InteractionMessage:
    """Deserialize v1 without guessing families or silently ignoring fields."""

    if not isinstance(payload, Mapping):
        raise ContractValidationError("interaction payload must be a mapping")
    try:
        family = CommandFamily(payload.get("family"))
    except (TypeError, ValueError) as exc:
        raise ContractValidationError(f"unsupported command family: {payload.get('family')!r}") from exc
    version = payload.get("version")
    _validate_version(version)

    if family is CommandFamily.MOVE:
        _exact_payload(payload, {"version", "family", "raw_text"})
        return MoveCommand(payload["raw_text"], version=version)
    if family is CommandFamily.TEACHER_POINTER:
        _exact_payload(payload, {"version", "family", "square"})
        return TeacherPointerCommand(_payload_square(payload["square"]), version=version)
    if family is CommandFamily.POSITION_EDITOR:
        _exact_payload(payload, {"version", "family", "operation", "square", "piece", "value"})
        return PositionEditorCommand(
            payload["operation"],
            square=_payload_square(payload["square"], optional=True),
            piece=payload["piece"],
            value=payload["value"], version=version,
        )
    if family is CommandFamily.ANNOTATION:
        _exact_payload(payload, {"version", "family", "operation", "start_square", "end_square", "tag"})
        return AnnotationCommand(
            payload["operation"],
            start_square=_payload_square(payload["start_square"], "start square", optional=True),
            end_square=_payload_square(payload["end_square"], "end square", optional=True),
            tag=payload["tag"], version=version,
        )
    event_keys = {"version", "family", "square", "piece", "student_id", "sequence"}
    _exact_payload(payload, event_keys)
    event_type = StudentHoverEvent if family is CommandFamily.STUDENT_HOVER else StudentSelectionEvent
    return event_type(
        _payload_square(payload["square"]),
        piece=payload["piece"], student_id=payload["student_id"],
        sequence=payload["sequence"], version=version,
    )


def presentation_state_to_payload(state: PresentationState) -> dict[str, object]:
    if not isinstance(state, PresentationState):
        raise ContractValidationError("state must be PresentationState")
    return {
        "version": state.version,
        "pointer_square": state.pointer.square,
        "highlights": [
            {"square": item.square, "purpose": item.purpose} for item in state.highlights
        ],
        "arrows": [
            {"start_square": item.start_square, "end_square": item.end_square, "purpose": item.purpose}
            for item in state.arrows
        ],
        "coordinate_labels_visible": state.coordinate_labels_visible,
        "student_pointer_history": [interaction_to_payload(item) for item in state.student_pointer_history],
        "active_student_id": state.active_student_id,
        "engine_visibility": state.engine_visibility.value,
        "board_permission": state.board_permission.value,
    }


def presentation_state_from_payload(payload: Mapping[str, object]) -> PresentationState:
    if not isinstance(payload, Mapping):
        raise ContractValidationError("presentation payload must be a mapping")
    keys = {
        "version", "pointer_square", "highlights", "arrows", "coordinate_labels_visible",
        "student_pointer_history", "active_student_id", "engine_visibility", "board_permission",
    }
    _exact_payload(payload, keys)
    _validate_version(payload["version"])
    highlights = payload["highlights"]
    arrows = payload["arrows"]
    history = payload["student_pointer_history"]
    if not isinstance(highlights, list) or not isinstance(arrows, list) or not isinstance(history, list):
        raise ContractValidationError("presentation collections must be JSON arrays")
    parsed_history = tuple(interaction_from_payload(item) for item in history)
    if any(not isinstance(item, (StudentHoverEvent, StudentSelectionEvent)) for item in parsed_history):
        raise ContractValidationError("student history may contain only hover/selection events")
    try:
        parsed_highlights = tuple(_highlight_from_payload(item) for item in highlights)
        parsed_arrows = tuple(_arrow_from_payload(item) for item in arrows)
    except (TypeError, ValueError) as exc:
        raise ContractValidationError(f"invalid presentation collection entry: {exc}") from exc
    return PresentationState(
        pointer=TeacherPointerState(
            _payload_square(payload["pointer_square"], "pointer square", optional=True)
        ),
        highlights=parsed_highlights,
        arrows=parsed_arrows,
        coordinate_labels_visible=payload["coordinate_labels_visible"],
        student_pointer_history=parsed_history,
        active_student_id=payload["active_student_id"],
        engine_visibility=payload["engine_visibility"],
        board_permission=payload["board_permission"],
        version=payload["version"],
    )


def _highlight_from_payload(payload: object) -> SquareHighlight:
    if not isinstance(payload, Mapping):
        raise ContractValidationError("highlight entry must be an object")
    _exact_payload(payload, {"square", "purpose"})
    return SquareHighlight(
        _payload_square(payload["square"], "highlight square"),
        _required_text(payload["purpose"], "highlight purpose"),
    )


def _arrow_from_payload(payload: object) -> VisualArrow:
    if not isinstance(payload, Mapping):
        raise ContractValidationError("arrow entry must be an object")
    _exact_payload(payload, {"start_square", "end_square", "purpose"})
    return VisualArrow(
        _payload_square(payload["start_square"], "arrow start square"),
        _payload_square(payload["end_square"], "arrow end square"),
        _required_text(payload["purpose"], "arrow purpose"),
    )
