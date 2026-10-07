from __future__ import annotations

"""Shared presentation-only visual-board contract for every product surface.

The contract intentionally carries no FEN, move list, piece array, clock, engine
state, or other chess truth. Consumers combine it with their existing canonical
board projection. This keeps ordinary play, Teacher, Online, and Spectator on one
visual vocabulary without creating a second chess-state owner.
"""

from dataclasses import dataclass
from enum import Enum
from typing import Mapping

from .squares import normalize_square


VISUAL_BOARD_CONTRACT_VERSION = 1
_FORBIDDEN_VISUAL_KEYS = frozenset({
    "fen", "position", "position_fen", "board", "pieces", "moves",
    "move_history", "history", "turn", "legal_moves",
})


class VisualBoardConsumer(str, Enum):
    PLAY = "play"
    TEACHER = "teacher"
    ONLINE = "online"
    SPECTATOR = "spectator"


def _square(value: object, *, optional: bool = False) -> str | None:
    if value is None and optional:
        return None
    if type(value) is not str or value != value.strip():
        raise ValueError("visual-board square must be canonical text")
    try:
        canonical = normalize_square(value)
    except ValueError as exc:
        raise ValueError("visual-board square is invalid") from exc
    if canonical != value:
        raise ValueError("visual-board square must use lowercase algebraic text")
    return canonical


@dataclass(frozen=True, slots=True)
class VisualBoardPresentation:
    selected_square: str | None = None
    legal_squares: tuple[str, ...] = ()
    last_move: tuple[str, str] | None = None

    def __post_init__(self) -> None:
        selected = _square(self.selected_square, optional=True)
        if not isinstance(self.legal_squares, tuple):
            raise TypeError("legal_squares must be a tuple")
        legal = tuple(_square(item) for item in self.legal_squares)
        if len(legal) > 64 or len(set(legal)) != len(legal):
            raise ValueError("legal_squares must be unique and bounded")
        last = self.last_move
        if last is not None:
            if not isinstance(last, tuple) or len(last) != 2:
                raise TypeError("last_move must be a two-square tuple or None")
            start = _square(last[0])
            end = _square(last[1])
            if start == end:
                raise ValueError("last_move endpoints must differ")
            last = (start, end)
        object.__setattr__(self, "selected_square", selected)
        object.__setattr__(self, "legal_squares", legal)
        object.__setattr__(self, "last_move", last)

    def as_dict(self) -> dict[str, object]:
        return {
            "selected_square": self.selected_square,
            "legal_squares": list(self.legal_squares),
            "last_move": (
                None
                if self.last_move is None
                else {"from": self.last_move[0], "to": self.last_move[1]}
            ),
        }


@dataclass(frozen=True, slots=True)
class VisualBoardContract:
    consumer: VisualBoardConsumer
    visual: Mapping[str, object]
    presentation: VisualBoardPresentation = VisualBoardPresentation()
    version: int = VISUAL_BOARD_CONTRACT_VERSION

    def __post_init__(self) -> None:
        if type(self.version) is not int or self.version != VISUAL_BOARD_CONTRACT_VERSION:
            raise ValueError("unsupported visual-board contract version")
        if not isinstance(self.consumer, VisualBoardConsumer):
            raise TypeError("consumer must be VisualBoardConsumer")
        if not isinstance(self.visual, Mapping) or any(type(k) is not str for k in self.visual):
            raise TypeError("visual snapshot must be an object")
        if _FORBIDDEN_VISUAL_KEYS.intersection(self.visual):
            raise ValueError("visual snapshot must not contain chess truth")
        if not isinstance(self.presentation, VisualBoardPresentation):
            raise TypeError("presentation must be VisualBoardPresentation")

    def as_dict(self) -> dict[str, object]:
        # VisualBoardWebViewState already returns detached JSON-safe values.
        return {
            "version": self.version,
            "consumer": self.consumer.value,
            "visual": dict(self.visual),
            "presentation": self.presentation.as_dict(),
        }


def build_visual_board_contract(
    consumer: VisualBoardConsumer | str,
    visual: Mapping[str, object],
    *,
    selected_square: str | None = None,
    legal_squares: tuple[str, ...] = (),
    last_move: tuple[str, str] | None = None,
) -> dict[str, object]:
    try:
        target = consumer if isinstance(consumer, VisualBoardConsumer) else VisualBoardConsumer(consumer)
    except (TypeError, ValueError) as exc:
        raise ValueError("unsupported visual-board consumer") from exc
    return VisualBoardContract(
        target,
        visual,
        VisualBoardPresentation(
            selected_square=selected_square,
            legal_squares=legal_squares,
            last_move=last_move,
        ),
    ).as_dict()
