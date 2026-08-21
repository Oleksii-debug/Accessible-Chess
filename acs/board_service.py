from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from types import MappingProxyType

from .squares import FILES, parse_square, square_name


PIECE_VALUES = {"P": 1, "N": 3, "B": 3, "R": 5, "Q": 9, "K": 0}
PIECE_SYMBOLS = frozenset("PNBRQKpnbrqk")


def _validate_piece(piece: str | None, *, field_name: str) -> None:
    if piece is not None and (
        not isinstance(piece, str) or piece not in PIECE_SYMBOLS
    ):
        raise TypeError(f"{field_name} must be a canonical piece symbol or None")


def _validate_optional_text(value: str | None, *, field_name: str) -> None:
    if value is None:
        return
    if (
        not isinstance(value, str)
        or not value.strip()
        or "\n" in value
        or "\r" in value
    ):
        raise TypeError(f"{field_name} must be non-empty single-line text or None")


def piece_color(piece: str | None) -> str | None:
    _validate_piece(piece, field_name="piece")
    if piece is None:
        return None
    return "w" if piece.isupper() else "b"


@dataclass(frozen=True)
class MoveView:
    frm: int
    to: int
    san: str | None = None
    is_capture: bool = False

    def __post_init__(self) -> None:
        for field_name, value in (("frm", self.frm), ("to", self.to)):
            if type(value) is not int or not 0 <= value < 64:
                raise ValueError(f"{field_name} must be an integer in 0..63")
        if self.frm == self.to:
            raise ValueError("move endpoints must be distinct")
        _validate_optional_text(self.san, field_name="san")
        if not isinstance(self.is_capture, bool):
            raise TypeError("is_capture must be boolean")


@dataclass(frozen=True)
class BoardSnapshot:
    pieces: tuple[str | None, ...]
    turn: str
    legal_moves: tuple[MoveView, ...] = ()
    attacks: Mapping[int, tuple[int, ...]] = field(default_factory=dict)
    last_move: MoveView | None = None
    last_captured_piece: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.pieces, tuple) or len(self.pieces) != 64:
            raise ValueError("pieces must contain exactly 64 squares")
        for piece in self.pieces:
            _validate_piece(piece, field_name="pieces entry")
        if not isinstance(self.turn, str) or self.turn not in {"w", "b"}:
            raise ValueError("turn must be 'w' or 'b'")
        if (
            not isinstance(self.legal_moves, tuple)
            or any(not isinstance(move, MoveView) for move in self.legal_moves)
        ):
            raise TypeError("legal_moves must be a tuple of MoveView")
        if not isinstance(self.attacks, Mapping):
            raise TypeError("attacks must be a mapping")
        detached_attacks: dict[int, tuple[int, ...]] = {}
        for target, origins in self.attacks.items():
            if type(target) is not int or not 0 <= target < 64:
                raise ValueError("attack targets must be integers in 0..63")
            if (
                not isinstance(origins, tuple)
                or any(type(origin) is not int or not 0 <= origin < 64 for origin in origins)
            ):
                raise TypeError("attack origins must be tuples of integers in 0..63")
            if target in origins or len(set(origins)) != len(origins):
                raise ValueError("attack origins must be distinct and exclude the target")
            detached_attacks[target] = tuple(origins)
        if self.last_move is not None and not isinstance(self.last_move, MoveView):
            raise TypeError("last_move must be MoveView or None")
        _validate_piece(self.last_captured_piece, field_name="last_captured_piece")
        object.__setattr__(self, "attacks", MappingProxyType(detached_attacks))


@dataclass(frozen=True)
class EngineSnapshot:
    evaluation: str | None = None
    best_move: str | None = None

    def __post_init__(self) -> None:
        _validate_optional_text(self.evaluation, field_name="evaluation")
        _validate_optional_text(self.best_move, field_name="best_move")


@dataclass(frozen=True)
class ClockSnapshot:
    my_clock: str | None = None
    opponent_clock: str | None = None

    def __post_init__(self) -> None:
        _validate_optional_text(self.my_clock, field_name="my_clock")
        _validate_optional_text(self.opponent_clock, field_name="opponent_clock")


@dataclass(frozen=True)
class SquareView:
    square: str
    piece: str | None

    def __post_init__(self) -> None:
        if not isinstance(self.square, str) or square_name(parse_square(self.square)) != self.square:
            raise ValueError("square must be canonical lowercase algebraic text")
        _validate_piece(self.piece, field_name="piece")


@dataclass(frozen=True)
class MaterialView:
    white: Mapping[str, int]
    black: Mapping[str, int]
    white_points: int
    black_points: int

    def __post_init__(self) -> None:
        detached: list[dict[str, int]] = []
        for field_name, values in (("white", self.white), ("black", self.black)):
            if not isinstance(values, Mapping) or set(values) != set(PIECE_VALUES):
                raise ValueError(f"{field_name} material must contain every canonical piece")
            copied: dict[str, int] = {}
            for piece, count in values.items():
                if piece not in PIECE_VALUES or type(count) is not int or count < 0:
                    raise TypeError(
                        f"{field_name} material counts must be non-negative integers"
                    )
                copied[piece] = count
            detached.append(copied)
        for field_name, points in (
            ("white_points", self.white_points),
            ("black_points", self.black_points),
        ):
            if type(points) is not int or points < 0:
                raise TypeError(
                    f"{field_name} must be a non-negative integer")
        expected_white = sum(detached[0][piece] * value for piece, value in PIECE_VALUES.items())
        expected_black = sum(detached[1][piece] * value for piece, value in PIECE_VALUES.items())
        if self.white_points != expected_white or self.black_points != expected_black:
            raise ValueError("material point totals must match piece counts")
        object.__setattr__(self, "white", MappingProxyType(detached[0]))
        object.__setattr__(self, "black", MappingProxyType(detached[1]))

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
        if not isinstance(board, BoardSnapshot):
            raise TypeError("board must be BoardSnapshot")
        if engine is not None and not isinstance(engine, EngineSnapshot):
            raise TypeError("engine must be EngineSnapshot or None")
        if clocks is not None and not isinstance(clocks, ClockSnapshot):
            raise TypeError("clocks must be ClockSnapshot or None")
        self.board = board
        self.engine = EngineSnapshot() if engine is None else engine
        self.clocks = ClockSnapshot() if clocks is None else clocks

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
        reference_color = occupant_color or self.board.turn
        target_color = "b" if reference_color == "w" else "w"
        return tuple(
            item for item in self.all_controllers(idx)
            if piece_color(item.piece) == target_color
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
        if not isinstance(piece_type, str):
            raise TypeError("piece_type must be text")
        kind = piece_type.strip().upper()
        if kind not in PIECE_VALUES:
            raise ValueError(f"unknown piece type: {piece_type!r}")
        if type(direction) is not int or direction not in {-1, 1}:
            raise ValueError("direction must be -1 or 1")
        if color is not None and not isinstance(color, str):
            raise TypeError("color must be text or None")
        target_color = self.board.turn if color is None else color
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
        if type(rank) is not int or not 1 <= rank <= 8:
            raise ValueError("rank must be in 1..8")
        base = (rank - 1) * 8
        return tuple(SquareView(square_name(base + file_no), self.board.pieces[base + file_no]) for file_no in range(8))

    def file(self, file_name: str) -> tuple[SquareView, ...]:
        if not isinstance(file_name, str):
            raise TypeError("file must be text")
        text = file_name.strip().lower()
        if text not in FILES:
            raise ValueError("file must be a..h")
        file_no = FILES.index(text)
        return tuple(SquareView(square_name(rank_no * 8 + file_no), self.board.pieces[rank_no * 8 + file_no]) for rank_no in range(8))
