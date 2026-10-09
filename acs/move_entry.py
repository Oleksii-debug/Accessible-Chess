from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import re

from .keybindings import ActionRegistry, BindingContext
from .position_editor import (
    MAX_COORDINATE_POSITION_CHARS,
    PositionState,
    parse_piece_coordinate_position,
)

MAX_MOVE_ENTRY_CHARS = MAX_COORDINATE_POSITION_CHARS


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


_POSITION_HEADER_RE = re.compile(r"(?is)^\s*[WB]\s*:")


def parse_move_entry(
    text: str,
    registry: ActionRegistry | None = None,
    *,
    position_turn: str = "w",
) -> MoveEntryIntent:
    """Classify move-entry text without mutating chess state.

    Canonical W:/B: position syntax has precedence over user-remappable
    one-letter aliases. This prevents aliases such as w and b from ever
    corrupting position data. Non-command text is returned as chess move input
    for the chess rules service to validate/execute.
    """

    if type(text) is not str:
        raise ValueError("move entry text must be text")
    if len(text) > MAX_MOVE_ENTRY_CHARS:
        raise ValueError("move entry text is too long")
    raw = text
    stripped = raw.strip()
    if not stripped:
        return MoveEntryIntent(MoveEntryKind.EMPTY, raw)

    if _POSITION_HEADER_RE.match(stripped):
        return MoveEntryIntent(
            MoveEntryKind.POSITION,
            raw,
            position=parse_piece_coordinate_position(stripped, turn=position_turn),
        )

    actions = ActionRegistry() if registry is None else registry
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
