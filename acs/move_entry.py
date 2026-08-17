from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import re

from .keybindings import ActionRegistry, BindingContext
from .position_editor import PositionState, empty_position


class MoveEntryKind(str, Enum):
    EMPTY = "empty"
    ACTION = "action"
    CHESS_MOVE = "chess_move"
    POSITION = "position"


@dataclass(frozen=True)
class MoveEntryIntent:
    kind: MoveEntryKind
    raw_text: str
    action_id: str | None = None
    move_text: str | None = None
    position: PositionState | None = None


_POSITION_HEADER_RE = re.compile(r"(?is)^\s*W\s*:")
_POSITION_SECTIONS_RE = re.compile(
    r"(?is)^\s*W\s*:\s*(?P<white>.*?)\s*\bB\s*:\s*(?P<black>.*?)\s*$"
)


def parse_move_entry(
    text: str,
    registry: ActionRegistry | None = None,
    *,
    position_turn: str = "w",
) -> MoveEntryIntent:
    """Classify move-entry text without mutating chess state.

    Canonical ``W:/B:`` position syntax has precedence over user-remappable
    one-letter aliases. This prevents aliases such as ``w`` and ``b`` from ever
    corrupting position data. Non-command text is returned as chess move input
    for the chess rules service to validate/execute.
    """

    raw = str(text)
    stripped = raw.strip()
    if not stripped:
        return MoveEntryIntent(MoveEntryKind.EMPTY, raw)

    if _POSITION_HEADER_RE.match(stripped):
        return MoveEntryIntent(
            MoveEntryKind.POSITION,
            raw,
            position=parse_piece_coordinate_position(stripped, turn=position_turn),
        )

    actions = registry or ActionRegistry()
    resolution = actions.resolve_alias(BindingContext.MOVE_ENTRY, stripped)
    if resolution is not None:
        return MoveEntryIntent(
            MoveEntryKind.ACTION,
            raw,
            action_id=resolution.action_id,
        )

    return MoveEntryIntent(
        MoveEntryKind.CHESS_MOVE,
        raw,
        move_text=stripped,
    )


def parse_piece_coordinate_position(text: str, *, turn: str = "w") -> PositionState:
    """Parse canonical ``W:/B:`` piece-coordinate text into ``PositionState``.

    Example: ``W: K e1 Q d1 P e4 B: K e8 P e5``. Piece symbols are canonical
    chess data and are deliberately independent from command aliases.

    The typed position is an application command, not a partially-edited board:
    it must therefore satisfy the same playable structural contract that the
    canonical Board/FEN boundary will enforce.
    """

    if turn not in {"w", "b"}:
        raise ValueError("turn must be 'w' or 'b'")

    match = _POSITION_SECTIONS_RE.match(str(text))
    if match is None:
        raise ValueError("position text must contain W: and B: sections")

    position = empty_position(turn=turn)
    used: set[str] = set()
    position = _fill_section(position, match.group("white"), white=True, used=used)
    position = _fill_section(position, match.group("black"), white=False, used=used)

    white_kings = sum(piece == "K" for piece in position.pieces)
    black_kings = sum(piece == "k" for piece in position.pieces)
    if white_kings != 1 or black_kings != 1:
        raise ValueError("position text requires exactly one white and one black king")

    problems = position.validate_playable()
    if problems:
        raise ValueError("position text is not playable: " + "; ".join(problems))
    return position


def _fill_section(
    position: PositionState,
    chunk: str,
    *,
    white: bool,
    used: set[str],
) -> PositionState:
    tokens = chunk.replace(",", " ").split()
    if len(tokens) % 2:
        raise ValueError("each piece must be followed by a square, for example N f3")

    result = position
    for index in range(0, len(tokens), 2):
        piece = tokens[index].upper()
        square = tokens[index + 1].lower()
        if piece not in "KQRBNP":
            raise ValueError(f"unknown piece symbol: {tokens[index]}")
        if square in used:
            raise ValueError(f"square {square} is specified more than once")
        used.add(square)
        result = result.with_piece(square, piece if white else piece.lower())
    return result
