from __future__ import annotations

"""Extended Position Description parsing on the canonical position model.

EPD is an interchange grammar, not another chess-rules engine. Its first four
position fields are delegated to PositionState.from_fen. Unknown operation
operands remain opaque text; only hmvc/fmvn are interpreted because they map
directly to the canonical FEN counters.
"""

from dataclasses import dataclass
import re

from .input_limits import MAX_FEN_CHARS
from .position_editor import PositionState, PositionValidationError

MAX_EPD_CHARS = MAX_FEN_CHARS
MAX_EPD_OPERATIONS = 256
MAX_EPD_OPCODE_CHARS = 64

_OPCODE_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]*$")


class EpdParseError(ValueError):
    """Raised when one EPD record cannot be represented safely."""


@dataclass(frozen=True, slots=True)
class EpdOperation:
    opcode: str
    operand: str | None = None

    def __post_init__(self) -> None:
        if type(self.opcode) is not str:
            raise TypeError("EPD opcode must be text")
        if (
            not self.opcode
            or len(self.opcode) > MAX_EPD_OPCODE_CHARS
            or _OPCODE_RE.fullmatch(self.opcode) is None
        ):
            raise EpdParseError("invalid EPD opcode")
        if self.operand is not None and type(self.operand) is not str:
            raise TypeError("EPD operand must be text or None")
        if self.operand is not None:
            _validate_operand(self.operand)


@dataclass(frozen=True, slots=True)
class EpdRecord:
    position: PositionState
    operations: tuple[EpdOperation, ...] = ()

    def __post_init__(self) -> None:
        if type(self.position) is not PositionState:
            raise TypeError("EPD position must be a PositionState")
        if type(self.operations) is not tuple:
            raise TypeError("EPD operations must be an immutable tuple")
        if any(type(item) is not EpdOperation for item in self.operations):
            raise TypeError("EPD operations must contain EpdOperation values")
        if len(self.operations) > MAX_EPD_OPERATIONS:
            raise EpdParseError("EPD contains too many operations")

    def to_epd(self) -> str:
        return serialize_epd(self)


def looks_like_epd(text: object) -> bool:
    """Recognize EPD shape without reclassifying ordinary six-field FEN."""

    if type(text) is not str or len(text) > MAX_EPD_CHARS:
        return False
    stripped = text.strip()
    if not stripped:
        return False
    parts = stripped.split(maxsplit=4)
    if len(parts) < 4 or parts[0].count("/") != 7:
        return False
    if len(parts) == 4:
        return True
    tail = parts[4].lstrip()
    if not tail:
        return False
    # A normal FEN has numeric halfmove/fullmove fields after the same first
    # four fields. EPD operations begin with an opcode and end with semicolons.
    return (tail[0].isascii() and tail[0].isalpha()) or ";" in tail


def parse_epd(text: str) -> EpdRecord:
    """Parse one bounded EPD record through the canonical position authority."""

    if type(text) is not str:
        raise EpdParseError("EPD must be text")
    if len(text) > MAX_EPD_CHARS:
        raise EpdParseError("EPD is too long")
    if "\n" in text or "\r" in text or "\x00" in text:
        raise EpdParseError("EPD must contain exactly one text record")

    stripped = text.strip()
    if not stripped:
        raise EpdParseError("EPD must not be blank")
    parts = stripped.split(maxsplit=4)
    if len(parts) < 4:
        raise EpdParseError("EPD must contain at least four position fields")

    board, turn, castling, en_passant = parts[:4]
    operations = _parse_operations(parts[4] if len(parts) == 5 else "")

    halfmove = 0
    fullmove = 1
    seen: set[str] = set()
    for operation in operations:
        if operation.opcode not in {"hmvc", "fmvn"}:
            continue
        if operation.opcode in seen:
            raise EpdParseError(f"duplicate EPD {operation.opcode} operation")
        seen.add(operation.opcode)
        value = _parse_counter(operation)
        if operation.opcode == "hmvc":
            halfmove = value
        else:
            if value < 1:
                raise EpdParseError("EPD fmvn must be at least 1")
            fullmove = value

    try:
        position = PositionState.from_fen(
            f"{board} {turn} {castling} {en_passant} {halfmove} {fullmove}"
        )
    except (PositionValidationError, ValueError) as exc:
        raise EpdParseError("invalid EPD position fields") from exc

    return EpdRecord(position=position, operations=operations)


def serialize_epd(record: EpdRecord) -> str:
    """Serialize EPD deterministically without inventing unknown-op semantics."""

    if type(record) is not EpdRecord:
        raise TypeError("record must be an EpdRecord")
    fields = record.position.to_fen().split()
    if len(fields) != 6:
        raise EpdParseError("canonical position did not produce six FEN fields")

    rendered: list[str] = []
    seen_hmvc = False
    seen_fmvn = False
    for operation in record.operations:
        if operation.opcode == "hmvc":
            if seen_hmvc:
                raise EpdParseError("duplicate EPD hmvc operation")
            seen_hmvc = True
            rendered.append(f"hmvc {record.position.halfmove};")
        elif operation.opcode == "fmvn":
            if seen_fmvn:
                raise EpdParseError("duplicate EPD fmvn operation")
            seen_fmvn = True
            rendered.append(f"fmvn {record.position.fullmove};")
        elif operation.operand is None:
            rendered.append(f"{operation.opcode};")
        else:
            rendered.append(f"{operation.opcode} {operation.operand};")

    if record.position.halfmove != 0 and not seen_hmvc:
        rendered.append(f"hmvc {record.position.halfmove};")
    if record.position.fullmove != 1 and not seen_fmvn:
        rendered.append(f"fmvn {record.position.fullmove};")

    core = " ".join(fields[:4])
    return core if not rendered else core + " " + " ".join(rendered)


def _parse_operations(tail: str) -> tuple[EpdOperation, ...]:
    if not tail.strip():
        return ()

    segments: list[str] = []
    buffer: list[str] = []
    quoted = False
    escaped = False
    for character in tail:
        if escaped:
            buffer.append(character)
            escaped = False
            continue
        if quoted and character == "\\":
            buffer.append(character)
            escaped = True
            continue
        if character == '"':
            buffer.append(character)
            quoted = not quoted
            continue
        if character == ";" and not quoted:
            segment = "".join(buffer).strip()
            if not segment:
                raise EpdParseError("EPD operation must not be empty")
            segments.append(segment)
            if len(segments) > MAX_EPD_OPERATIONS:
                raise EpdParseError("EPD contains too many operations")
            buffer.clear()
            continue
        if ord(character) < 0x20 and character != "\t":
            raise EpdParseError("EPD contains an invalid control character")
        buffer.append(character)

    if quoted or escaped:
        raise EpdParseError("EPD contains an unterminated quoted operand")
    if "".join(buffer).strip():
        raise EpdParseError("each EPD operation must end with a semicolon")
    return tuple(_parse_operation(segment) for segment in segments)


def _parse_operation(segment: str) -> EpdOperation:
    parts = segment.split(maxsplit=1)
    operand = parts[1].strip() if len(parts) == 2 else None
    return EpdOperation(parts[0], None if operand == "" else operand)


def _parse_counter(operation: EpdOperation) -> int:
    operand = operation.operand
    if operand is None or not operand.isascii() or not operand.isdecimal():
        raise EpdParseError(
            f"EPD {operation.opcode} operand must be an unsigned ASCII decimal integer"
        )
    try:
        return int(operand)
    except ValueError as exc:
        raise EpdParseError(
            f"EPD {operation.opcode} operand is outside the supported integer range"
        ) from exc


def _validate_operand(operand: str) -> None:
    if "\n" in operand or "\r" in operand or "\x00" in operand:
        raise EpdParseError("EPD operand contains an invalid control character")

    quoted = False
    escaped = False
    for character in operand:
        if escaped:
            escaped = False
            continue
        if quoted and character == "\\":
            escaped = True
            continue
        if character == '"':
            quoted = not quoted
            continue
        if character == ";" and not quoted:
            raise EpdParseError("EPD operand contains an unquoted semicolon")
        if ord(character) < 0x20 and character != "\t":
            raise EpdParseError("EPD operand contains an invalid control character")
    if quoted or escaped:
        raise EpdParseError("EPD operand contains an unterminated quoted string")
