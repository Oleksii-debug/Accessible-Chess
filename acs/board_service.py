from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping


FILES = "abcdefgh"
RANKS = "12345678"
PIECE_VALUES = {"P": 1, "N": 3, "B": 3, "R": 5, "Q": 9, "K": 0}


def square_name(index: int) -> str:
    if not 0 <= index < 64:
        raise ValueError("square index must be in 0..63")
    return FILES[index % 8] + RANKS[index // 8]


def parse_square(value: str | int) -> int:
    if isinstance(value, int):
        if not 0 <= value < 64:
            raise ValueError("square index must be in 0..63")
        return value
    text = str(value).strip().lower()
    if len(text) != 2 or text[0] not in FILES or text[1] not in RANKS:
        raise ValueError(f"invalid square: {value!r}")
    return (int(text[1]) - 1) * 8 + FILES.index(text[0])


def piece_color(piece: str | None) -> str | None:
    if not piece:
        return None
    return "w" if piece.isupper() else "b"


@dataclass(frozen=True)
class MoveView:
    frm: int
    to: int
    san: str | None = None
    is_capture: bool = False


@dataclass(frozen=True)
class BoardSnapshot:
    pieces: tuple[str | None, ...]
    turn: str
    legal_moves: tuple[MoveView, ...] = ()
    attacks: Mapping[int, tuple[int, ...]] = field(default_factory=dict)
    last_move: MoveView | None = None
    last_captured_piece: str | None = None

    def __post_init__(self) -> None:
        if len(self.pieces) != 64:
            raise ValueError("pieces must contain exactly 64 squares")
        if self.turn not in {"w", "b"}:
            raise ValueError("turn must be 'w' or 'b'")


@dataclass(frozen=True)
class EngineSnapshot:
    evaluation: str | None = None
    best_move: str | None = None


@dataclass(frozen=True)
class ClockSnapshot:
    my_clock: str | None = None
    opponent_clock: str | None = None


@dataclass(frozen=True)
class SquareView:
    square: str
    piece: str | None


@dataclass(frozen=True)
class MaterialView:
    white: Mapping[str, int]
    black: Mapping[str, int]
    white_points: int
    black_points: int

    @property
    def balance(self) -> int:
        return self.white_points - self.black_points


class BoardCommandService:
    """Presentation-neutral data source for accessible board commands.

    It deliberately owns no keyboard bindings and no speech strings. UI layers
    resolve action IDs through ActionRegistry, then call this service.
    """

    def __init__(
        self,
        board: BoardSnapshot,
        *,
        engine: EngineSnapshot | None = None,
        clocks: ClockSnapshot | None = None,
    ) -> None:
        self.board = board
        self.engine = engine or EngineSnapshot()
        self.clocks = clocks or ClockSnapshot()

    def current(self, square: str | int) -> SquareView:
        idx = parse_square(square)
        return SquareView(square_name(idx), self.board.pieces[idx])

    def last_move(self) -> MoveView | None:
        return self.board.last_move

    def last_captured(self) -> str | None:
        return self.board.last_captured_piece

    def legal_moves(self, square: str | int) -> tuple[MoveView, ...]:
        idx = parse_square(square)
        return tuple(move for move in self.board.legal_moves if move.frm == idx)

    def captures(self, square: str | int) -> tuple[MoveView, ...]:
        return tuple(move for move in self.legal_moves(square) if move.is_capture)

    def surroundings(self, square: str | int) -> tuple[SquareView, ...]:
        idx = parse_square(square)
        file_no, rank_no = idx % 8, idx // 8
        result: list[SquareView] = []
        for dr in (-1, 0, 1):
            for df in (-1, 0, 1):
                if not (df or dr):
                    continue
                nf, nr = file_no + df, rank_no + dr
                if 0 <= nf < 8 and 0 <= nr < 8:
                    target = nr * 8 + nf
                    result.append(SquareView(square_name(target), self.board.pieces[target]))
        return tuple(result)

    def all_controllers(self, square: str | int) -> tuple[SquareView, ...]:
        idx = parse_square(square)
        origins = self.board.attacks.get(idx, ())
        return tuple(SquareView(square_name(origin), self.board.pieces[origin]) for origin in origins)

    def attackers(self, square: str | int) -> tuple[SquareView, ...]:
        idx = parse_square(square)
        occupant_color = piece_color(self.board.pieces[idx])
        if occupant_color is None:
            return self.all_controllers(idx)
        return tuple(
            item for item in self.all_controllers(idx)
            if piece_color(item.piece) not in {None, occupant_color}
        )

    def defenders(self, square: str | int) -> tuple[SquareView, ...]:
        idx = parse_square(square)
        occupant_color = piece_color(self.board.pieces[idx])
        target_color = occupant_color or self.board.turn
        return tuple(
            item for item in self.all_controllers(idx)
            if piece_color(item.piece) == target_color
        )

    def material(self) -> MaterialView:
        white = {piece: 0 for piece in PIECE_VALUES}
        black = {piece: 0 for piece in PIECE_VALUES}
        for piece in self.board.pieces:
            if not piece:
                continue
            kind = piece.upper()
            if kind not in PIECE_VALUES:
                continue
            (white if piece.isupper() else black)[kind] += 1
        white_points = sum(white[p] * PIECE_VALUES[p] for p in PIECE_VALUES)
        black_points = sum(black[p] * PIECE_VALUES[p] for p in PIECE_VALUES)
        return MaterialView(white, black, white_points, black_points)

    def evaluation(self) -> str | None:
        return self.engine.evaluation

    def best_move(self) -> str | None:
        return self.engine.best_move

    def my_clock(self) -> str | None:
        return self.clocks.my_clock

    def opponent_clock(self) -> str | None:
        return self.clocks.opponent_clock

    def cycle_piece(
        self,
        piece_type: str,
        current_square: str | int,
        *,
        direction: int = 1,
        color: str | None = None,
    ) -> SquareView | None:
        kind = str(piece_type).strip().upper()
        if kind not in PIECE_VALUES:
            raise ValueError(f"unknown piece type: {piece_type!r}")
        if direction not in {-1, 1}:
            raise ValueError("direction must be -1 or 1")
        target_color = color or self.board.turn
        if target_color not in {"w", "b"}:
            raise ValueError("color must be 'w' or 'b'")

        matches = [
            i for i, piece in enumerate(self.board.pieces)
            if piece and piece.upper() == kind and piece_color(piece) == target_color
        ]
        if not matches:
            return None

        current = parse_square(current_square)
        ordered = sorted(matches)
        if direction == 1:
            candidates = [idx for idx in ordered if idx > current]
            target = candidates[0] if candidates else ordered[0]
        else:
            candidates = [idx for idx in reversed(ordered) if idx < current]
            target = candidates[0] if candidates else ordered[-1]
        return SquareView(square_name(target), self.board.pieces[target])

    def rank(self, rank: int) -> tuple[SquareView, ...]:
        if not 1 <= int(rank) <= 8:
            raise ValueError("rank must be in 1..8")
        base = (int(rank) - 1) * 8
        return tuple(SquareView(square_name(base + file_no), self.board.pieces[base + file_no]) for file_no in range(8))

    def file(self, file_name: str) -> tuple[SquareView, ...]:
        text = str(file_name).strip().lower()
        if text not in FILES:
            raise ValueError("file must be a..h")
        file_no = FILES.index(text)
        return tuple(SquareView(square_name(rank_no * 8 + file_no), self.board.pieces[rank_no * 8 + file_no]) for rank_no in range(8))
