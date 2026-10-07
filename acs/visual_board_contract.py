from __future__ import annotations

"""Shared presentation-only contract for sighted chess-board surfaces.

The contract deliberately owns no Board/FEN/SAN/move-generation state. Product
surfaces project state from their canonical owners into this immutable model.
That makes visual preferences reusable without creating a second chess truth.
"""

from dataclasses import dataclass, replace
from enum import Enum


_FILES = "abcdefgh"
_RANKS = "12345678"
_ALL_SQUARES = frozenset(file_name + rank for rank in _RANKS for file_name in _FILES)
_ALLOWED_PIECES = frozenset("KQRBNPkqrbnp")


class BoardSurface(str, Enum):
    ORDINARY_PLAY = "ordinary_play"
    TEACHER = "teacher"
    ONLINE = "online"
    SPECTATOR = "spectator"


class BoardTheme(str, Enum):
    CLASSIC = "classic"
    HIGH_CONTRAST = "high_contrast"
    BLUE = "blue"


class PieceTheme(str, Enum):
    UNICODE = "unicode"
    LETTERS = "letters"


class BoardOrientation(str, Enum):
    WHITE = "white"
    BLACK = "black"


class CoordinateMode(str, Enum):
    OFF = "off"
    EDGES = "edges"
    EVERY_SQUARE = "every_square"


def _enum_value(enum_type: type[Enum], value: object, label: str):
    if isinstance(value, enum_type):
        return value
    if type(value) is not str:
        raise ValueError(f"{label} must be text")
    try:
        return enum_type(value)
    except ValueError as exc:
        raise ValueError(f"unsupported {label}") from exc


def _square(value: object, label: str = "square") -> str:
    if type(value) is not str or value not in _ALL_SQUARES:
        raise ValueError(f"{label} must be a canonical chess square")
    return value


@dataclass(frozen=True, slots=True)
class VisualBoardPreferences:
    board_theme: BoardTheme = BoardTheme.CLASSIC
    piece_theme: PieceTheme = PieceTheme.UNICODE
    orientation: BoardOrientation = BoardOrientation.WHITE
    coordinate_mode: CoordinateMode = CoordinateMode.EDGES
    scale_percent: int = 100
    show_last_move: bool = True

    def __post_init__(self) -> None:
        object.__setattr__(self, "board_theme", _enum_value(BoardTheme, self.board_theme, "board theme"))
        object.__setattr__(self, "piece_theme", _enum_value(PieceTheme, self.piece_theme, "piece theme"))
        object.__setattr__(self, "orientation", _enum_value(BoardOrientation, self.orientation, "board orientation"))
        object.__setattr__(self, "coordinate_mode", _enum_value(CoordinateMode, self.coordinate_mode, "coordinate mode"))
        if type(self.scale_percent) is not int or not 75 <= self.scale_percent <= 150:
            raise ValueError("scale_percent must be an exact integer in 75..150")
        if type(self.show_last_move) is not bool:
            raise ValueError("show_last_move must be boolean")

    def updated(self, field: object, value: object) -> "VisualBoardPreferences":
        if type(field) is not str:
            raise ValueError("visual preference field must be text")
        if field == "board_theme":
            return replace(self, board_theme=_enum_value(BoardTheme, value, "board theme"))
        if field == "piece_theme":
            return replace(self, piece_theme=_enum_value(PieceTheme, value, "piece theme"))
        if field == "orientation":
            return replace(self, orientation=_enum_value(BoardOrientation, value, "board orientation"))
        if field == "coordinate_mode":
            return replace(self, coordinate_mode=_enum_value(CoordinateMode, value, "coordinate mode"))
        if field == "scale_percent":
            if type(value) is not int:
                raise ValueError("scale_percent must be an exact integer")
            return replace(self, scale_percent=value)
        if field == "show_last_move":
            if type(value) is not bool:
                raise ValueError("show_last_move must be boolean")
            return replace(self, show_last_move=value)
        raise ValueError("unknown visual preference field")

    def as_dict(self) -> dict[str, object]:
        return {
            "boardTheme": self.board_theme.value,
            "pieceTheme": self.piece_theme.value,
            "orientation": self.orientation.value,
            "coordinateMode": self.coordinate_mode.value,
            "scalePercent": self.scale_percent,
            "showLastMove": self.show_last_move,
        }


@dataclass(frozen=True, slots=True)
class VisualBoardCell:
    square: str
    piece: str
    accessible_label: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "square", _square(self.square))
        if type(self.piece) is not str or (self.piece and self.piece not in _ALLOWED_PIECES):
            raise ValueError("piece must be an empty or canonical piece symbol")
        if type(self.accessible_label) is not str or not self.accessible_label or len(self.accessible_label) > 256:
            raise ValueError("accessible_label must be bounded non-empty text")


@dataclass(frozen=True, slots=True)
class VisualBoardSnapshot:
    """Immutable visual projection supplied entirely by canonical product owners."""

    surface: BoardSurface
    preferences: VisualBoardPreferences
    cells: tuple[VisualBoardCell, ...]
    selected_square: str | None = None
    last_move: tuple[str, str] | None = None
    legal_targets: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "surface", _enum_value(BoardSurface, self.surface, "board surface"))
        if not isinstance(self.preferences, VisualBoardPreferences):
            raise ValueError("preferences must be VisualBoardPreferences")
        if type(self.cells) is not tuple or len(self.cells) != 64:
            raise ValueError("visual board must contain exactly 64 cells")
        if any(not isinstance(cell, VisualBoardCell) for cell in self.cells):
            raise ValueError("visual board contains an invalid cell")
        squares = [cell.square for cell in self.cells]
        if len(set(squares)) != 64 or set(squares) != _ALL_SQUARES:
            raise ValueError("visual board must contain every canonical square once")
        if self.selected_square is not None:
            object.__setattr__(self, "selected_square", _square(self.selected_square, "selected_square"))
        if self.last_move is not None:
            if type(self.last_move) is not tuple or len(self.last_move) != 2:
                raise ValueError("last_move must contain exactly two squares")
            object.__setattr__(
                self,
                "last_move",
                (
                    _square(self.last_move[0], "last_move source"),
                    _square(self.last_move[1], "last_move target"),
                ),
            )
        if type(self.legal_targets) is not tuple:
            raise ValueError("legal_targets must be a tuple")
        normalized = tuple(_square(square, "legal target") for square in self.legal_targets)
        if len(set(normalized)) != len(normalized):
            raise ValueError("legal_targets must not contain duplicates")
        object.__setattr__(self, "legal_targets", normalized)

    def as_dict(self) -> dict[str, object]:
        return {
            "surface": self.surface.value,
            "preferences": self.preferences.as_dict(),
            "cells": [
                {"square": cell.square, "piece": cell.piece, "label": cell.accessible_label}
                for cell in self.cells
            ],
            "selectedSquare": self.selected_square,
            "lastMove": (
                {"from": self.last_move[0], "to": self.last_move[1]}
                if self.last_move is not None
                else None
            ),
            "legalTargets": list(self.legal_targets),
        }
